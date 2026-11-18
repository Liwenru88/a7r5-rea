"""用 AArch64 和 Thumb 机器码复验取景与编码请求的几何边界。"""

from pathlib import Path
import struct
import subprocess

from elftools.elf.elffile import ELFFile
import pytest
from unicorn import Uc, UC_ARCH_ARM, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn import arm_const as ARM, arm64_const as ARM64


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
CLANG = '/opt/homebrew/opt/llvm/bin/clang'
LLD = '/opt/homebrew/opt/lld/bin/ld.lld'
DATA = 0x03000000
STACK = DATA + 0x18000
STOP = DATA + 0x20000
GEOMETRY = struct.Struct('<6H')
RECT = struct.Struct('<4H')
CASES = (
    (4, (9504, 3352), (600, 211)),
    (5, (9504, 3512), (600, 221)),
    (6, (7920, 6336), (500, 400)),
    (7, (7392, 6336), (466, 400)),
    (8, (9504, 4976), (600, 314)),
    (9, (9504, 4048), (600, 255)),
)

ENCODE_SIZES = {
    (9504, 6336): tuple(size for _, size, _ in CASES),
    (6240, 4160): ((6240, 2200), (6240, 2304), (5200, 4160), (4848, 4160),
                   (6240, 3264), (6240, 2656)),
    (4752, 3168): ((4752, 1680), (4752, 1752), (3968, 3168), (3696, 3168),
                   (4752, 2488), (4752, 2024)),
}


@pytest.fixture(scope='module', params=['AP', 'CP'])
def machine(request, tmp_path_factory):
    thumb = request.param == 'CP'
    out = tmp_path_factory.mktemp(request.param) / 'geometry.elf'
    flags = ['--target=armv7a-none-eabi', '-mthumb'] if thumb else ['--target=aarch64-none-elf']
    subprocess.run([CLANG, *flags, '-Oz', '-ffreestanding', '-fno-builtin', '-nostdlib',
                    '-Wall', '-Wextra', '-Werror', '--ld-path='+LLD,
                    '-Wl,-Ttext=0x02000000', '-Wl,--entry=r5_aspect_crop',
                    '-Wl,--build-id=none', str(HERE/'geometry.c'), '-o', str(out)],
                   capture_output=True, check=True)
    cpu = Uc(UC_ARCH_ARM if thumb else UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.mem_map(0x02000000, 0x100000)
    cpu.mem_map(DATA, 0x30000)
    with out.open('rb') as handle:
        elf = ELFFile(handle)
        for section in elf.iter_sections():
            if section['sh_flags'] & 2 and section['sh_addr'] >= 0x02000000:
                cpu.mem_write(section['sh_addr'], section.data())
        symbols = {s.name: s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()}
    return cpu, symbols, thumb


def call(machine, name, *args):
    cpu, symbols, thumb = machine
    if thumb:
        registers = [ARM.UC_ARM_REG_R0, ARM.UC_ARM_REG_R1, ARM.UC_ARM_REG_R2, ARM.UC_ARM_REG_R3]
        sp, lr, pc = ARM.UC_ARM_REG_SP, ARM.UC_ARM_REG_LR, ARM.UC_ARM_REG_PC
        cpu.mem_write(STACK, struct.pack('<I', args[4]) if len(args) == 5 else bytes(4))
    else:
        registers = [getattr(ARM64, f'UC_ARM64_REG_X{i}') for i in range(5)]
        sp, lr, pc = ARM64.UC_ARM64_REG_SP, ARM64.UC_ARM64_REG_LR, ARM64.UC_ARM64_REG_PC
    for register, value in zip(registers, args):
        cpu.reg_write(register, value)
    cpu.reg_write(sp, STACK)
    cpu.reg_write(lr, STOP | int(thumb))
    cpu.emu_start(symbols[name], STOP, count=10000)
    assert cpu.reg_read(pc) == STOP and cpu.reg_read(sp) == STACK
    return cpu.reg_read(registers[0])


def test_six_ratios_share_centered_view_and_encoder_geometry(machine):
    cpu, _, _ = machine
    source = DATA
    result = DATA + 64
    full = GEOMETRY.pack(9600, 6344, 9504, 6336, 0, 0)
    for ratio, encoder_wh, view_wh in CASES:
        cpu.mem_write(source, full)
        assert call(machine, 'r5_aspect_crop', ratio, source, 0, 0, result) == 1
        cw, ch, w, h, x, y = GEOMETRY.unpack(cpu.mem_read(result, GEOMETRY.size))
        assert (cw, ch, w, h) == (9600, 6344, *encoder_wh)
        assert abs((2*x + w) - 9504) < 16
        assert 2*y + h == 6336 and not x % 8
        assert bytes(cpu.mem_read(source, GEOMETRY.size)) == full
        for portrait in (0, 1):
            vw, vh = (400, 600) if portrait else (600, 400)
            cpu.mem_write(source, RECT.pack(21, 13, vw, vh))
            assert call(machine, 'r5_aspect_viewport', ratio, source, portrait, result) == 1
            x, y, w, h = RECT.unpack(cpu.mem_read(result, RECT.size))
            assert (w, h) == (view_wh[::-1] if portrait else view_wh)
            assert abs(2*(x - 21) + w - vw) <= 1
            assert abs(2*(y - 13) + h - vh) <= 1


def test_in_place_auxiliary_crop_and_rejected_routes_leave_input_intact(machine):
    cpu, _, _ = machine
    source = DATA
    fixture = GEOMETRY.pack(1664, 1080, 1616, 1080, 0, 0)
    cpu.mem_write(source, fixture)
    for ratio, auxiliary, base in ((0, 1, 0), (3, 1, 0), (10, 1, 0), (9, 0, 0), (9, 1, 2)):
        assert call(machine, 'r5_aspect_crop', ratio, source, auxiliary, base, source) == 0
        assert bytes(cpu.mem_read(source, GEOMETRY.size)) == fixture
    assert call(machine, 'r5_aspect_crop', 9, source, 1, 0, source) == 1
    assert GEOMETRY.unpack(cpu.mem_read(source, GEOMETRY.size)) == (1664, 1080, 1616, 688, 0, 196)

    # 有效区域靠近画布右侧时，编码器对齐读取也必须留在画布内。
    outside = GEOMETRY.pack(384, 240, 336, 224, 41, 8)
    cpu.mem_write(source, outside)
    assert call(machine, 'r5_aspect_crop', 9, source, 0, 0, source) == 0
    assert bytes(cpu.mem_read(source, GEOMETRY.size)) == outside
