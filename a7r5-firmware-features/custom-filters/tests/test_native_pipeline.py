"""同一C保存/调参/引用核心分别在AArch64和ARMv7机器码中执行。"""
import hashlib
import io
from pathlib import Path
import struct
import subprocess

import pytest

NATIVE = Path(__file__).resolve().parents[1] / 'native'
TESTS = Path(__file__).resolve().parent


@pytest.mark.parametrize('target,flags', [('aarch64-none-elf', []),
                                         ('armv7a-none-eabi', ['-mthumb'])])
def test_native_editor_storage_pipeline_on_target_instructions(tmp_path, target, flags):
    from elftools.elf.elffile import ELFFile
    from unicorn import Uc, UC_ARCH_ARM64, UC_ARCH_ARM, UC_MODE_THUMB
    from unicorn import arm64_const as a64, arm_const as arm
    sources = ['af_slots.c', 'af_record.c', 'af_sha256.c', 'af_document.c',
               'af_store.c', 'af_persist.c', 'af_ui.c', 'af_versions.c', 'af_cp406.c',
               'af_labels.c', 'af_labels_store.c']
    objects = []
    for source in [*[NATIVE / n for n in sources], TESTS / 'native_pipeline.c']:
        obj = tmp_path / (source.stem + '.o')
        result = subprocess.run(['clang', '--target=' + target, *flags,
                                 '-std=c11', '-O2', '-ffreestanding', '-fno-builtin',
                                 '-DAF_PIPELINE_TARGET=1',
                                 '-fno-stack-protector', '-Wall', '-Wextra', '-Werror',
                                 '-c', str(source), '-o', str(obj)], capture_output=True, text=True)
        assert result.returncode == 0, result.stderr
        objects.append(obj)
    program = tmp_path / 'pipeline.elf'
    result = subprocess.run(['/opt/homebrew/opt/lld/bin/ld.lld', '-Ttext=0x800000',
                             '--entry=af_pipeline_check', '--build-id=none',
                             *map(str, objects), '-o', str(program)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    elf = ELFFile(io.BytesIO(program.read_bytes()))
    machine = Uc(UC_ARCH_ARM64 if target.startswith('aarch64') else UC_ARCH_ARM,
                 0 if target.startswith('aarch64') else UC_MODE_THUMB)
    mapped = set()
    for segment in elf.iter_segments():
        if segment['p_type'] != 'PT_LOAD':
            continue
        start, end = segment['p_vaddr'], segment['p_vaddr'] + segment['p_memsz']
        header = 0x200000 if target.startswith('aarch64') else 0x10000
        assert (start == header and end <= header + 4096) or 0x700000 <= start <= end < 0x900000
        for page in range(start & ~4095, (end + 4095) & ~4095, 4096):
            if page not in mapped:
                machine.mem_map(page, 4096)
                mapped.add(page)
        machine.mem_write(start, segment.data())
    symbols = {s.name: int(s['st_value']) for s in elf.get_section_by_name('.symtab').iter_symbols()}
    machine.mem_map(0x1000000, 0x40000)
    stop = 0x103f000
    if target.startswith('aarch64'):
        machine.reg_write(a64.UC_ARM64_REG_SP, 0x103e000)
        machine.reg_write(a64.UC_ARM64_REG_LR, stop)
        pc, result_reg = a64.UC_ARM64_REG_PC, a64.UC_ARM64_REG_X0
    else:
        machine.reg_write(arm.UC_ARM_REG_C1_C0_2, 0xf << 20)
        machine.reg_write(arm.UC_ARM_REG_FPEXC, 1 << 30)
        machine.reg_write(arm.UC_ARM_REG_SP, 0x103e000)
        machine.reg_write(arm.UC_ARM_REG_LR, stop | 1)
        pc, result_reg = arm.UC_ARM_REG_PC, arm.UC_ARM_REG_R0
    machine.emu_start(symbols['af_pipeline_check'], stop, count=5000000)
    assert machine.reg_read(pc) == stop, '目标指令执行超出预算'
    assert machine.reg_read(result_reg) == 0, f'C闭环失败行号={machine.reg_read(result_reg)}'
    report = struct.unpack('<8I', machine.mem_read(symbols['af_pipeline_report'], 32))
    assert report[0] == 0x41375031 and report[2:] == (20, 20, 2, 2, 3, 1)
    assert report[1] > 500
    # 独立Python构造最终复制的纯参数文档，检查两种ABI的字节协议一致。
    header = bytearray(256)
    struct.pack_into('<4sHH', header, 0, b'AFD1', 1, 256)
    struct.pack_into('<I', header, 16, 4)
    initial = struct.pack('<BB8b64x', 18, 0, 0, 0, 0, 0, 0, 0, 3, 0)
    saved = struct.pack('<BB8b64x', 18, 0, 5, 9, -8, 7, 6, 5, 4, 3)
    header[88:162], header[162:236] = initial, saved
    struct.pack_into('<I', header, 236, 1)
    digest = hashlib.sha256(bytes(header) + b'copy').digest()
    assert bytes(machine.mem_read(symbols['af_pipeline_digest'], 32)) == digest
    prefix = bytearray((17*i+3) % 256 for i in range(0xe70))
    prefix[0xa40:0xa44] = (20).to_bytes(4, 'little')
    for field, value in zip((0xa44,0xa46,0xa45,0xa47,0xa48,0xd2e,0xd2f,0xd30),
                            (-9,9,-8,7,6,5,4,3)):
        prefix[field] = value & 255
    assert bytes(machine.mem_read(symbols['af_pipeline_cp_digest'], 32)) == hashlib.sha256(prefix).digest()
