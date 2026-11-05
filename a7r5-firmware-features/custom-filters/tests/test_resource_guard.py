"""汇编器独立核对保护字节，并在目标架构执行空、失败、正常指针路由。"""
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_LR, UC_ARM64_REG_PC

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from a7filters.resource_guard import STUB,FAILED,READY,stub_bytes


def test_guard_assembly_and_native_pointer_routes(tmp_path):
    compiler=shutil.which('clang')
    linker=shutil.which('ld.lld') or '/opt/homebrew/opt/lld/bin/ld.lld'
    assert compiler and Path(linker).is_file()
    source=Path(__file__).resolve().parents[1]/'native/af_resource_guard.S'
    object_path=tmp_path/'guard.o';executable=tmp_path/'guard.elf'
    subprocess.run([compiler,'--target=aarch64-none-elf','-c',str(source),'-o',str(object_path)],check=True,capture_output=True)
    subprocess.run([linker,'-m','aarch64elf','-Ttext='+hex(STUB),'--entry=af_resource_map_guard',
                    '--defsym=af_resource_map_failed='+hex(FAILED),'--defsym=af_resource_map_ready='+hex(READY),
                    '--build-id=none',str(object_path),'-o',str(executable)],check=True,capture_output=True)
    with executable.open('rb') as stream:
        elf=ELFFile(stream)
        assert elf['e_machine']=='EM_AARCH64' and elf.get_section_by_name('.text').data()==stub_bytes()
    cpu=Uc(UC_ARCH_ARM64,UC_MODE_ARM)
    cpu.mem_map(STUB,4096);cpu.mem_write(STUB,stub_bytes())
    cpu.mem_map(FAILED&~4095,4096)
    for address in (FAILED,READY):cpu.mem_write(address,struct.pack('<I',0xd65f03c0))
    outcomes=[]
    def observe(machine,address,size,data):
        if address in (FAILED,READY):outcomes.append(address)
    cpu.hook_add(UC_HOOK_CODE,observe)
    stop=0x9000f000
    for pointer,expected in ((0,FAILED),((1<<64)-1,FAILED),(0x93000000,READY)):
        outcomes.clear();cpu.reg_write(UC_ARM64_REG_X0,pointer);cpu.reg_write(UC_ARM64_REG_LR,stop)
        cpu.emu_start(STUB,stop,count=50)
        assert outcomes==[expected] and cpu.reg_read(UC_ARM64_REG_PC)==stop
        assert cpu.reg_read(UC_ARM64_REG_X0)==pointer
