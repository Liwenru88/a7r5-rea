"""R5 原生 RAW 备选外观接口；不把指令回放当作实体 ARW 验收。"""
import importlib.util
import os
from pathlib import Path
import struct

import pytest
from unicorn import UC_HOOK_CODE
from unicorn import arm_const as A
from capstone import Cs, CS_ARCH_ARM, CS_MODE_THUMB

FEATURES = Path(__file__).resolve().parents[1]
ROOT = FEATURES.parent
BUILD = Path(os.environ.get('A7R5_NATIVE24_BUILD',
    ROOT / 'a7r5-qemu/build/full419-repaired-20261111-v2-components'))
CONFIG = 0x198780c
QUANTITY = 0xad9ff7
MAPPING = 0xada00f
GAMMA = 0xca0990


@pytest.fixture
def cp():
    path = FEATURES / 'native24-combined/dependencies/native12-combined/tests/runtime_support.py'
    spec = importlib.util.spec_from_file_location('raw_actual_cp', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.BASELINE = BUILD
    raw = Path(os.environ.get('A7R5_RAW_CP', BUILD / 'cpapp-b.bin')).read_bytes()
    machine = module.CP(raw)
    machine.fixture_raw = raw
    machine.write(CONFIG, bytes(256))
    machine.write(CONFIG + 3, b'\x0c')
    machine.write(CONFIG + 0x70, bytes(range(12)))
    return machine


def test_raw_quantity_accepts_native_twelve(cp):
    output = cp.DATA if hasattr(cp, 'DATA') else cp.PACKET
    assert cp.call(QUANTITY, output) == 0, '原生 RAW 数量接口仍只接受十款'
    assert cp.read(output, 1) == b'\x0c'


@pytest.mark.parametrize('value', [0, 9, 10, 11, 12])
def test_raw_mapping_uses_actual_count_and_preserves_unknown_output(cp, value):
    cp.write(cp.PACKET, struct.pack('<I', 0xa5a5a5a5))
    result = cp.call(MAPPING, value, cp.PACKET)
    assert result == (0 if value < 12 else -4)
    assert cp.words(cp.PACKET, 1) == ((value if value < 12 else 0xa5a5a5a5),)


def test_raw_alternative_gamma_rows_use_fl2_fl3_native_colors(cp):
    assert cp.words(GAMMA, 10) == (0, 1, 2, 3, 15, 16, 17, 18, 5, 13)
    assert cp.words(GAMMA + 40, 2) == (19, 20), '备选目录仍引用旧外观的 Gamma'


@pytest.mark.parametrize('group', range(8))
@pytest.mark.parametrize('index', [10, 11])
def test_all_native_raw_color_routes_use_fl2_fl3_instead_of_st(cp, group, index):
    if group < 6:
        gate = 0xbef228 + group * 32
        decoder = Cs(CS_ARCH_ARM, CS_MODE_THUMB)
        tail = next(decoder.disasm(cp.read(gate + 28, 4), gate + 28))
        assert tail.mnemonic == 'b.w'
        continuation = int(tail.op_str.removeprefix('#'), 16)
        incoming, outgoing = A.UC_ARM_REG_R1, A.UC_ARM_REG_R0
    else:
        gate, continuation = ((0xbef2e8, 0x2453b0), (0xbef30c, 0x245542))[group - 6]
        incoming = A.UC_ARM_REG_R0
        outgoing = A.UC_ARM_REG_R10 if group == 6 else A.UC_ARM_REG_R1
    cp.cpu.reg_write(incoming, index - 1)
    cp.cpu.emu_start(gate | 1, continuation, count=1000)
    assert cp.cpu.reg_read(A.UC_ARM_REG_PC) == continuation
    if group == 7:
        assert cp.read(cp.cpu.reg_read(outgoing), 4) == (b'FL2\0' if index == 10 else b'FL3\0')
    else:
        assert cp.cpu.reg_read(outgoing) == 54 + index - 10


def construct(cp, count, *, original=False):
    cp.write(CONFIG, bytes([0xa5]) * 256)
    cp.write(CONFIG + 3, bytes([count]))
    cp.write(CONFIG + 0x70, bytes(range(10)))
    before = cp.read(CONFIG, 256)

    def copy(cpu, at, size, context):
        if at != 0x5f51bc:
            return
        destination, source, length = (cpu.reg_read(r) for r in (A.UC_ARM_REG_R0, A.UC_ARM_REG_R1, A.UC_ARM_REG_R2))
        assert length <= 4096
        cp.write(destination, cp.read(source, length))
        cpu.reg_write(A.UC_ARM_REG_PC, cpu.reg_read(A.UC_ARM_REG_LR))

    cp.cpu.hook_add(UC_HOOK_CODE, copy)
    cp.cpu.reg_write(A.UC_ARM_REG_SP, cp.STACK + 0x8000)
    cp.cpu.reg_write(A.UC_ARM_REG_R0, cp.BANK)
    cp.cpu.reg_write(A.UC_ARM_REG_R1, 0)
    if original:
        cp.call(0xadd163, cp.BANK, 0)
    else:
        cp.cpu.emu_start(0xade855, 0xade858, count=1000000)
        assert cp.cpu.reg_read(A.UC_ARM_REG_PC) == 0xade858
    return before


def test_raw_native_constructor_adds_two_entries_without_changing_other_config(cp):
    before = construct(cp, 10)
    expected = bytearray(before)
    expected[3] = 12
    expected[0x7a:0x7c] = bytes((10, 11))
    assert cp.read(CONFIG, 256) == expected, '构造前没有发布十二款原生映射'
    # R5 是175个根字段，不能使用 M4 的169字段常量。
    assert struct.unpack('<H', cp.read(cp.BANK + 0x18, 2))[0] == 175
    assert struct.unpack('<I', cp.read(cp.BANK + 0x732, 4))[0] == 12


@pytest.mark.parametrize('count', [0, 10, 12, 13, 255])
def test_quantity_and_mapping_are_bounded_for_unknown_configuration(cp, count):
    cp.write(CONFIG + 3, bytes([count]))
    cp.write(cp.PACKET, b'\xa5' * 4)
    assert cp.call(QUANTITY, cp.PACKET) == (0 if count in (10, 12) else -4)
    assert cp.read(cp.PACKET, 1) == bytes([count])
    cp.write(cp.PACKET, b'\xa5' * 4)
    assert cp.call(MAPPING, 11, cp.PACKET) == (0 if count == 12 else -4)
    assert cp.words(cp.PACKET, 1)[0] == (11 if count == 12 else 0xa5a5a5a5)


def test_unknown_constructor_config_does_not_install_twelve_over_it(cp):
    before = construct(cp, 9)
    assert cp.read(CONFIG, 256) == before


def test_first_ten_raw_child_directories_match_original_native_constructor(cp):
    reference = type(cp)(cp.fixture_raw)
    construct(reference, 10, original=True)
    construct(cp, 10)
    assert cp.read(cp.BANK + 0x1162, 10 * 3110) == reference.read(reference.BANK + 0x1162, 10 * 3110)


def test_raw_patch_can_be_reversed_to_exact_source_and_guards_native_ranges(tmp_path):
    path = FEATURES / 'look-fl2-fl3/raw/native.py'
    spec = importlib.util.spec_from_file_location('raw_guard_test', path)
    patcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(patcher)
    source = Path(os.environ.get('A7R5_RAW_SOURCE_CP',
        ROOT / 'a7r5-qemu/build/full419-repaired-20261111-v2-components/cpapp-b.bin'))
    if not source.is_file():
        pytest.skip('设置 A7R5_RAW_SOURCE_CP 为原厂 4.00 或尚未加入 RAW 补丁的 CP')
    original = source.read_bytes()
    result, receipt = patcher.apply(original, tmp_path / 'good', source_sha256=patcher.digest(original))
    restored = bytearray(result)
    for row in reversed(receipt['patches']):
        before, after = bytes.fromhex(row['before']), bytes.fromhex(row['after'])
        assert restored[row['offset']:row['offset']+len(after)] == after
        restored[row['offset']:row['offset']+len(before)] = before
    assert restored == original
    mutated = bytearray(original)
    mutated[0xadd162 - patcher.BASE + 32] ^= 1
    with pytest.raises(ValueError, match='原生接口前像'):
        patcher.apply(mutated, tmp_path / 'bad', source_sha256=patcher.digest(mutated))
    assert not (tmp_path / 'bad').exists()
