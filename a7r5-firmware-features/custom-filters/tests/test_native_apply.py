"""实际C整包/银行/帧屏障，及独立Python字节校验；不假冒CP回执。"""
import ctypes as c
import io
from pathlib import Path
import struct
import subprocess
import zlib

import pytest

HERE=Path(__file__).resolve().parent
NATIVE=HERE.parent/'native'


def test_native_transaction_contract_and_independent_wire_bytes(tmp_path):
    output=tmp_path/'apply.so'
    sources=[NATIVE/n for n in ('af_slots.c','af_apply.c','af_apply_wire.c','af_cp406_state.c')]
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-fPIC','-shared',
                           *map(str,sources),str(HERE/'native_apply.c'),'-o',str(output)],
                          capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    api=c.CDLL(str(output))
    line=api.af_apply_check()
    assert line==0,f'原生事务失败行号={line}'
    raw=bytes((c.c_uint8*128).in_dll(api,'af_apply_wire_result'))
    assert raw[:4]==b'A7P1' and struct.unpack_from('<HHI',raw,4)==(1,2,128)
    assert struct.unpack_from('<IQQI',raw,12)==(0x1fff,42,(1<<40)+1,20)
    assert raw[36:46]==struct.pack('<BB8b',17,0,-9,9,-8,7,-6,5,4,3)
    assert raw[48:80].hex()=='d15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9'
    assert raw[80:112].hex()=='18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97'
    assert raw[112:124]==b'\x01\0\0\0'+b'\0'*8
    assert struct.unpack_from('<I',raw,124)[0]==zlib.crc32(raw[:124])
    api.af_apply_packet_decode.argtypes=[c.c_void_p,c.c_size_t,c.c_void_p]
    # 两半32位累积仍须保留最高位；使用独立字节构造，不依赖被测编码器。
    for session,version in ((0xfedcba9876543210,0x81234567f0e1d2c3),((1<<64)-1,(1<<64)-1)):
        changed=bytearray(raw)
        struct.pack_into('<QQ',changed,16,session,version)
        struct.pack_into('<I',changed,124,zlib.crc32(changed[:124]))
        decoded=c.create_string_buffer(256)
        assert api.af_apply_packet_decode(bytes(changed),128,decoded)==0
        assert struct.unpack_from('<QQ',decoded.raw,16)==(session,version)
    for offset,value in ((4,2),(13,0x20),(46,1),(48,raw[48]^1),(32,21),(37,1),(44,0)):
        changed=bytearray(raw);changed[offset]=value
        struct.pack_into('<I',changed,124,zlib.crc32(changed[:124]))
        output=c.create_string_buffer(b'\xa5'*256)
        assert api.af_apply_packet_decode(bytes(changed),128,output)==-1
        assert output.raw[:256]==b'\xa5'*256


@pytest.mark.parametrize('target,flags',[('aarch64-none-elf',[]),('armv7a-none-eabi',['-mthumb'])])
def test_transaction_on_target_instructions(tmp_path,target,flags):
    from elftools.elf.elffile import ELFFile
    from unicorn import Uc,UC_ARCH_ARM64,UC_ARCH_ARM,UC_MODE_THUMB
    from unicorn import arm64_const as a64,arm_const as arm
    objects=[]
    for source in [*[NATIVE/n for n in ('af_slots.c','af_apply.c','af_apply_wire.c','af_cp406_state.c')],
                    HERE/'native_apply.c',HERE/'native_memory.c']:
        obj=tmp_path/(source.stem+'.o')
        result=subprocess.run(['clang','--target='+target,*flags,'-std=c11','-O2','-ffreestanding',
            '-fno-builtin','-fno-stack-protector','-Wall','-Wextra','-Werror','-c',str(source),'-o',str(obj)],
            capture_output=True,text=True)
        assert result.returncode==0,result.stderr
        objects.append(obj)
    binary=tmp_path/'apply.elf'
    result=subprocess.run(['/opt/homebrew/opt/lld/bin/ld.lld','-Ttext=0x800000',
        '--entry=af_apply_check','--build-id=none',*map(str,objects),'-o',str(binary)],
        capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    elf=ELFFile(io.BytesIO(binary.read_bytes()))
    is64=target.startswith('aarch64')
    cpu=Uc(UC_ARCH_ARM64 if is64 else UC_ARCH_ARM,0 if is64 else UC_MODE_THUMB)
    pages=set()
    for segment in elf.iter_segments():
        if segment['p_type']!='PT_LOAD':continue
        start,end=segment['p_vaddr'],segment['p_vaddr']+segment['p_memsz']
        header=0x200000 if is64 else 0x10000
        assert start==header and end<=header+4096 or 0x800000<=start<=end<0x900000
        for page in range(start&~4095,(end+4095)&~4095,4096):
            if page not in pages:cpu.mem_map(page,4096);pages.add(page)
        cpu.mem_write(start,segment.data())
    symbols={s.name:int(s['st_value']) for s in elf.get_section_by_name('.symtab').iter_symbols()}
    cpu.mem_map(0x1000000,0x40000);stop=0x103f000
    if is64:
        pc,ret=a64.UC_ARM64_REG_PC,a64.UC_ARM64_REG_X0
        cpu.reg_write(a64.UC_ARM64_REG_SP,0x103e000);cpu.reg_write(a64.UC_ARM64_REG_LR,stop)
    else:
        pc,ret=arm.UC_ARM_REG_PC,arm.UC_ARM_REG_R0
        cpu.reg_write(arm.UC_ARM_REG_C1_C0_2,0xf<<20);cpu.reg_write(arm.UC_ARM_REG_FPEXC,1<<30)
        cpu.reg_write(arm.UC_ARM_REG_SP,0x103e000);cpu.reg_write(arm.UC_ARM_REG_LR,stop|1)
    cpu.emu_start(symbols['af_apply_check'],stop,count=3000000)
    assert cpu.reg_read(pc)==stop and cpu.reg_read(ret)==0,f'目标事务失败行号={cpu.reg_read(ret)}'
    report=struct.unpack('<8I',cpu.mem_read(symbols['af_apply_report'],32))
    assert report[0]==0x41374131 and report[2:6]==(20,13,3,128)
    raw=bytes(cpu.mem_read(symbols['af_apply_wire_result'],128))
    assert struct.unpack_from('<Q',raw,24)[0]==(1<<40)+1
    assert struct.unpack_from('<I',raw,124)[0]==zlib.crc32(raw[:124])
