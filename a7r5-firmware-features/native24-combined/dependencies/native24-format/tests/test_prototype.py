"""独立文件构造、原／派生C交叉验证及真实目标CPU布局检查。"""
import ctypes as C
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import zlib

from elftools.elf.elffile import ELFFile
import pytest
from unicorn import Uc, UC_ARCH_ARM, UC_ARCH_ARM64, UC_MODE_THUMB, UC_MODE_ARM
from unicorn import arm_const as ARM, arm64_const as A64

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native24_prepare', HERE / 'prepare.py')
build = importlib.util.module_from_spec(spec)
spec.loader.exec_module(build)
ORIGINAL = build.UPSTREAM / 'filters/FUJ_12_v45/R5NATIVE.BIN'
NAMES = ('slots', 'AP_look', 'AP_set', 'CP_value', 'CP_bank', 'gamma', 'view', 'restore_entry',
         'allocation', 'values', 'gamma_first', 'off_table', 'views', 'opaque', 'diag',
         'transfer', 'grid_alignment', 'grid', 'gamma_extra', 'tail_alignment', 'grid_size')


class Look(C.Structure):
    _fields_ = [('short', C.c_char * 24), ('full', C.c_char * 64),
                ('cc1', C.c_int16 * 24), ('matrix', C.c_int16 * 288),
                ('gamma', C.c_uint32 * 129), ('grid', C.c_int8 * 1215), ('pad', C.c_uint8)]


def set_type(slots):
    class LookSet(C.Structure):
        _fields_ = [('mask', C.c_uint32), ('look', Look * slots)]
    return LookSet


def save(name, value):
    folder = os.environ.get('A7R5_NATIVE24_EVIDENCE')
    if folder:
        output = Path(folder)
        output.mkdir(parents=True, exist_ok=True)
        (output / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


@pytest.fixture(scope='module')
def libraries(tmp_path_factory):
    folder = os.environ.get('A7R5_NATIVE24_PROTOTYPE_BUILD')
    if folder:
        folder = Path(folder)
        receipt = json.loads((folder / 'build.json').read_text())
        assert receipt['prototype_sources'] == {p.name: build.sha(p) for p in (HERE / 'prepare.py', HERE / 'layout.c')}
        assert all(build.sha(folder / name) == digest for name, digest in receipt['outputs'].items())
    else:
        folder = tmp_path_factory.mktemp('native24') / 'build'
        build.prepare(folder)
    libs = {n: C.CDLL(str((folder / str(n) / 'prototype.dylib').resolve())) for n in (12, 24)}
    for lib in libs.values():
        lib.r5_decode_look_file.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p]
        lib.r5_encode_look_file.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
        lib.r5_encode_look_file.restype = C.c_size_t
        lib.prototype_exercise.argtypes = [C.c_void_p, C.c_size_t]
        lib.prototype_selection_encode.argtypes = [C.c_uint, C.c_void_p]
        lib.prototype_selection_decode.argtypes = [C.c_void_p, C.POINTER(C.c_uint)]
    return folder, libs


def checksummed(data):
    result = bytearray(data)
    struct.pack_into('<I', result, 112, 0)
    struct.pack_into('<I', result, 112, zlib.crc32(result))
    return bytes(result)


def file_for(slots, version=5):
    """测试13～24仅复制旧配方并标识测试名，非新增滤镜成品。"""
    original = ORIGINAL.read_bytes()
    records = []
    for slot in slots:
        at = 128 + ((slot - 1) % 12) * 2452
        record = bytearray(original[at:at + 2452])
        struct.pack_into('<I', record, 0, slot)
        if slot > 12:
            record[4:28] = f'TEST{slot}'.encode().ljust(24, b'\0')
            record[28:92] = f'测试槽{slot}'.encode().ljust(64, b'\0')
        records.append(record)
    header = bytearray(original[:128])
    header[:8] = b'R5CUST' + str(version).encode() + b'\0'
    struct.pack_into('<5I', header, 8, version, 128, 128 + len(slots) * 2452,
                     len(slots), sum(1 << (slot - 1) for slot in slots))
    return checksummed(header + b''.join(records))


@pytest.mark.parametrize('slots,expected', [(12, 522152), (24, 947000)])
def test_host_and_target_layouts_and_exact_slot_boundaries(libraries, slots, expected):
    folder, libs = libraries
    lib = libs[slots]
    constants = list((C.c_uint32 * len(NAMES)).in_dll(lib, 'prototype_layout_constants'))
    layout = dict(zip(NAMES, constants))
    assert layout['allocation'] == expected and layout['AP_set'] == 4 + slots * 2444
    assert layout['CP_bank'] == 64 + slots * 2392
    buffer = C.create_string_buffer(b'\xa5' * (expected + 32))
    pointer = C.addressof(buffer) + 16
    assert lib.prototype_exercise(pointer, expected - 1) == 0
    assert buffer.raw == b'\xa5' * (expected + 32) + b'\0'
    assert lib.prototype_exercise(pointer, expected) == slots
    host = C.string_at(pointer, expected)
    assert buffer.raw[:16] == buffer.raw[expected + 16:expected + 32] == b'\xa5' * 16
    for n in range(slots):
        at = 64 + n * 2392
        assert host[at:at + 2392] == bytes([n + 1]) * 2392
        gamma = layout['gamma_first'] if n == 0 else layout['gamma_extra'] + (n - 1) * 20028
        assert host[gamma:gamma + 20028] == bytes([n + 1]) * 20028
        packed = layout['grid'] + 8 + n * 8 * 405 * 4
        assert host[packed:packed + 12960] == struct.pack('<I', n + 1) * (8 * 405)
        view = layout['views'] + (n + 1) * 24
        assert struct.unpack_from('<2I', host, view + 8) == (n + 1, 0x04000000 + gamma)
    assert host[layout['opaque']:layout['diag']] == bytes(1044)
    assert host[layout['diag']:layout['grid']] == bytes(layout['grid'] - layout['diag'])
    restore = layout['grid'] + 8 + slots * 12960
    assert host[restore:layout['gamma_extra']] == bytes(layout['gamma_extra'] - restore)
    target_reports = {}
    for target in ('arm-none-eabi', 'aarch64-none-elf'):
        elf = ELFFile(io.BytesIO((folder / str(slots) / (target + '.o')).read_bytes()))
        symbols = elf.get_section_by_name('.symtab')
        symbol = symbols.get_symbol_by_name('prototype_layout_constants')[0]
        data = elf.get_section(symbol['st_shndx']).data()
        actual = struct.unpack_from('<' + 'I' * len(NAMES), data, symbol['st_value'])
        assert list(actual) == constants
        # 执行原型目标指令，不调用原固件，不伪造CP资源就绪。
        function = symbols.get_symbol_by_name('prototype_exercise')[0]
        text = elf.get_section(function['st_shndx'])
        assert not elf.get_section_by_name('.rel.text') and not elf.get_section_by_name('.rela.text')
        is_arm = target == 'arm-none-eabi'
        cpu = Uc(UC_ARCH_ARM if is_arm else UC_ARCH_ARM64, UC_MODE_THUMB if is_arm else UC_MODE_ARM)
        code, memory, stack, stop = 0x100000, 0x04000000, 0x08000000, 0x08100000
        cpu.mem_map(code, 0x10000)
        cpu.mem_write(code, text.data())
        # 原型view使用逻辑bank地址0x04000000，哨兵位于bank两侧。
        cpu.mem_map(memory - 4096, 4096 + ((expected + 16 + 4095) & ~4095))
        cpu.mem_write(memory - 16, b'\xa5' * (expected + 32))
        cpu.mem_map(stack, 0x10000)
        cpu.mem_map(stop, 4096)
        if is_arm:
            registers = (ARM.UC_ARM_REG_R0, ARM.UC_ARM_REG_R1, ARM.UC_ARM_REG_SP, ARM.UC_ARM_REG_LR, ARM.UC_ARM_REG_PC)
        else:
            registers = (A64.UC_ARM64_REG_X0, A64.UC_ARM64_REG_X1, A64.UC_ARM64_REG_SP, A64.UC_ARM64_REG_LR, A64.UC_ARM64_REG_PC)
        for register, value in zip(registers[:4], (memory, expected, stack + 0x8000, stop | int(is_arm))):
            cpu.reg_write(register, value)
        cpu.emu_start(code + function['st_value'], stop, count=20000000)
        assert cpu.reg_read(registers[4]) == stop and cpu.reg_read(registers[0]) == slots
        result = bytes(cpu.mem_read(memory - 16, expected + 32))
        assert result == b'\xa5' * 16 + host + b'\xa5' * 16
        for n in range(slots):
            view = memory + layout['views'] + (n + 1) * 24
            pointer = struct.unpack('<I', bytes(cpu.mem_read(view + 12, 4)))[0]
            assert bytes(cpu.mem_read(pointer, 20028)) == bytes([n + 1]) * 20028
        target_reports[target] = {'constants_match_host': True, 'execution_canaries': True,
                                  'view_Gamma_pointer_reads': slots,
                                  'memory_sha256': hashlib.sha256(result).hexdigest()}
    save(f'layout-{slots}', {'layout': layout, 'targets': target_reports,
                            'test_budget': 1048576, 'single_bank_fits_test_budget': expected <= 1048576,
                            'two_banks_fit_test_budget': 2 * expected <= 1048576,
                            'remaining_test_bytes': 1048576 - expected, 'real_heap_measured': False})


def test_original_twelve_recipe_bytes_survive_new_codec(libraries):
    _, libs = libraries
    raw = ORIGINAL.read_bytes()
    old, new = set_type(12)(), set_type(24)()
    assert libs[12].r5_decode_look_file(raw, len(raw), C.byref(old)) == 0
    C.memset(C.byref(new), 0xa5, C.sizeof(new))
    assert libs[24].r5_decode_look_file(raw, len(raw), C.byref(new)) == 0
    assert bytes(new)[:C.sizeof(old)] == bytes(old)
    assert bytes(new)[C.sizeof(old):] == bytes(12 * 2444)
    out = C.create_string_buffer(len(raw))
    assert libs[24].r5_encode_look_file(C.byref(new), out, len(raw)) == len(raw)
    assert out.raw == raw
    save('legacy-recipe', {'input_sha256': build.sha(ORIGINAL), 'bytes': len(raw),
                           'decoded_parameters_identical': True, 'reencoded_bytes_identical': True,
                           'extra_twelve_slots_zero': True})


@pytest.mark.parametrize('slots', [list(range(1, 25)), [1, 12, 13, 24]])
def test_candidate_full_and_sparse_files_cross_check_independent_constructor(libraries, slots):
    _, libs = libraries
    raw = file_for(slots)
    value = set_type(24)()
    assert libs[24].r5_decode_look_file(raw, len(raw), C.byref(value)) == 0
    assert value.mask == sum(1 << (slot - 1) for slot in slots)
    for i in range(24):
        if i + 1 not in slots:
            assert bytes(value.look[i]) == bytes(2444)
        elif i >= 12:
            assert value.look[i].full.decode() == f'测试槽{i + 1}'
    out = C.create_string_buffer(b'\xa5' * len(raw))
    assert libs[24].r5_encode_look_file(C.byref(value), out, len(raw) - 1) == 0
    assert out.raw == b'\xa5' * len(raw) + b'\0'
    assert libs[24].r5_encode_look_file(C.byref(value), out, len(raw)) == len(raw)
    assert out.raw[:len(raw)] == raw
    old = set_type(12)()
    C.memset(C.byref(old), 0xa5, C.sizeof(old))
    assert libs[12].r5_decode_look_file(raw, len(raw), C.byref(old)) == 2
    assert bytes(old) == b'\xa5' * C.sizeof(old)
    save(f'candidate-{len(slots)}-records', {'slots': slots, 'bytes': len(raw),
                                          'sha256': hashlib.sha256(raw).hexdigest(),
                                          'new_roundtrip': True, 'old_firmware_rejects': True,
                                          'synthetic_test_data_only': True})


@pytest.mark.parametrize('bad', ['legacy_high_slot', 'mixed_magic', 'slot25', 'duplicate', 'utf8', 'crc', 'mask25', 'reserved'])
def test_invalid_new_file_rejects_without_modifying_destination(libraries, bad):
    _, libs = libraries
    raw = bytearray(file_for(list(range(1, 25))))
    if bad == 'legacy_high_slot':
        raw = bytearray(file_for([13], version=4))
    elif bad == 'mixed_magic':
        raw[:8] = b'R5CUST4\0'
    elif bad == 'slot25':
        struct.pack_into('<I', raw, 128 + 23 * 2452, 25)
    elif bad == 'duplicate':
        struct.pack_into('<I', raw, 128 + 23 * 2452, 23)
    elif bad == 'utf8':
        raw[128 + 23 * 2452 + 28:128 + 23 * 2452 + 30] = b'\xc0\xaf'
    elif bad == 'mask25':
        struct.pack_into('<I', raw, 24, 0x1ffffff)
    elif bad == 'reserved':
        raw[116] = 1
    raw = bytearray(checksummed(raw))
    if bad == 'crc':
        raw[-7] ^= 1
    output = set_type(24)()
    C.memset(C.byref(output), 0xa5, C.sizeof(output))
    assert libs[24].r5_decode_look_file(bytes(raw), len(raw), C.byref(output)) == 2
    assert bytes(output) == b'\xa5' * C.sizeof(output)


def test_selected_sidecar_old_bytes_and_new_range_are_explicitly_distinct(libraries):
    _, libs = libraries
    observations = []
    for slot in range(25):
        out = C.create_string_buffer(24)
        assert libs[24].prototype_selection_encode(slot, out) == 1
        expected = (b'R5SEL4\0\0' if slot <= 12 else b'R5SEL5\0\0') + struct.pack('<4I', 1 if slot <= 12 else 2, slot, 0, 0)
        expected = expected[:20] + struct.pack('<I', zlib.crc32(expected))
        assert out.raw == expected
        decoded = C.c_uint(999)
        assert libs[24].prototype_selection_decode(out, C.byref(decoded)) == 0 and decoded.value == slot
        decoded.value = 999
        old_status = libs[12].prototype_selection_decode(out, C.byref(decoded))
        if slot <= 12:
            old = C.create_string_buffer(24)
            assert libs[12].prototype_selection_encode(slot, old) == 1
            assert old.raw == out.raw and old_status == 0 and decoded.value == slot
        else:
            assert old_status == -1 and decoded.value == 999
        observations.append({'slot': slot, 'hex': out.raw.hex(), 'old_accepted': slot <= 12})
    untouched = C.create_string_buffer(b'\xa5' * 24)
    assert libs[24].prototype_selection_encode(25, untouched) == 0
    assert untouched.raw == b'\xa5' * 24 + b'\0'
    for corrupt in (bytes(24), b'R5SEL4\0\0' + expected[8:], expected[:-1] + bytes([expected[-1] ^ 1])):
        decoded = C.c_uint(999)
        assert libs[24].prototype_selection_decode(corrupt, C.byref(decoded)) == -1 and decoded.value == 999
    save('selection-compatibility', {'observations': observations, 'invalid_preserves_output': True})


def test_source_transform_rejects_drift_before_uncontrolled_replacement():
    with pytest.raises(ValueError, match='前像次数'):
        build.codec24('unknown source')
