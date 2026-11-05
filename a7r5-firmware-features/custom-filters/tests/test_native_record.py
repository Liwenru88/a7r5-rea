"""用独立字节格式验证真实C记录核心；不调用任何机内存储接口。"""
import ctypes as c
from pathlib import Path
import shutil
import struct
import subprocess
import zlib

import pytest

NATIVE = Path(__file__).resolve().parents[1] / 'native'


class View(c.Structure):
    _fields_ = [('slot', c.c_uint32), ('generation', c.c_uint64),
                ('payload', c.c_void_p), ('bytes', c.c_size_t)]


class Choice(c.Structure):
    _fields_ = [('view', View), ('bank', c.c_uint32)]


@pytest.fixture(scope='module')
def lib(tmp_path_factory):
    compiler = shutil.which('clang') or shutil.which('cc')
    assert compiler, '需要编译真实C核心'
    output = tmp_path_factory.mktemp('af-record') / 'af_record.so'
    subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                    '-fPIC', '-shared', str(NATIVE/'af_record.c'), '-o', str(output)],
                   check=True, capture_output=True, text=True)
    api = c.CDLL(str(output))
    api.af_record_encode.argtypes = [c.c_uint32, c.c_uint64, c.c_void_p,
                                    c.c_size_t, c.c_size_t, c.c_void_p,
                                    c.c_size_t, c.POINTER(c.c_size_t)]
    api.af_record_decode.argtypes = [c.c_void_p, c.c_size_t, c.c_uint32,
                                    c.c_size_t, c.POINTER(View)]
    api.af_record_choose.argtypes = [c.c_void_p, c.c_size_t, c.c_void_p,
                                    c.c_size_t, c.c_uint32, c.c_size_t,
                                    c.POINTER(Choice)]
    api.af_record_plan_next.argtypes = [c.POINTER(Choice), c.POINTER(c.c_uint32),
                                       c.POINTER(c.c_uint64)]
    return api


def wire(payload=b'opaque-preset', slot=20, generation=42, version=1):
    header = bytearray(struct.pack('<4sHBBQIIII', b'A7F1', version, slot, 0,
                                  generation, len(payload), zlib.crc32(payload), 0, 0))
    struct.pack_into('<I', header, 24, zlib.crc32(header))
    return bytes(header) + payload


def test_encode_matches_independent_wire_format_and_decode_view(lib):
    payload = bytes(range(256)) + b'\x00\xff\x00'
    expected = wire(payload)
    output = c.create_string_buffer(len(expected) + 8)
    c.memset(output, 0xa5, len(output))
    written = c.c_size_t(77)
    assert lib.af_record_encode(20, 42, payload, len(payload), 1024,
                                output, len(expected), c.byref(written)) == 0
    assert written.value == len(expected)
    assert output.raw[:len(expected)] == expected
    assert output.raw[len(expected):] == b'\xa5' * 8
    view = View()
    assert lib.af_record_decode(output, written.value, 20, 1024, c.byref(view)) == 0
    assert (view.slot, view.generation, view.bytes) == (20, 42, len(payload))
    assert view.payload == c.addressof(output) + 32
    assert c.string_at(view.payload, view.bytes) == payload


@pytest.mark.parametrize('case', ['magic', 'header_crc', 'payload_crc', 'reserved',
                                 'truncated', 'trailing', 'slot', 'budget', 'zero_generation'])
def test_bad_record_does_not_publish_view(lib, case):
    raw = bytearray(wire())
    slot, budget = 20, 1024
    if case == 'magic': raw[0] ^= 1
    elif case == 'header_crc': raw[24] ^= 1
    elif case == 'payload_crc': raw[-1] ^= 1
    elif case == 'reserved':
        raw[28] = 1
        struct.pack_into('<I', raw, 24, 0)
        struct.pack_into('<I', raw, 24, zlib.crc32(raw[:32]))
    elif case == 'truncated': raw = raw[:-1]
    elif case == 'trailing': raw += b'\x00'
    elif case == 'slot': slot = 19
    elif case == 'budget': budget = 1
    elif case == 'zero_generation': raw = bytearray(wire(generation=0))
    output = View()
    c.memset(c.byref(output), 0xa5, c.sizeof(output))
    before = bytes(output)
    assert lib.af_record_decode(bytes(raw), len(raw), slot, budget, c.byref(output)) < 0
    assert bytes(output) == before


@pytest.mark.parametrize('slot,generation,budget,capacity',
                         [(0, 1, 1024, 128), (21, 1, 1024, 128),
                          (1, 0, 1024, 128), (1, 1, 2, 128), (1, 1, 1024, 33)])
def test_rejected_encode_changes_neither_buffer_nor_length(lib, slot, generation, budget, capacity):
    output = c.create_string_buffer(b'\xa5' * 128, 128)
    written = c.c_size_t(77)
    assert lib.af_record_encode(slot, generation, b'payload', 7, budget, output,
                                capacity, c.byref(written)) < 0
    assert output.raw == b'\xa5' * 128 and written.value == 77


def choose(lib, a, b, result):
    return lib.af_record_choose(a, len(a) if a else 0, b, len(b) if b else 0,
                                20, 1024, c.byref(result))


def test_recovery_selects_latest_valid_bank_and_plans_other_bank(lib):
    # 这些缓冲区必须活到视图消费结束，记录核心不拥有载荷内存。
    a = wire(generation=8)
    b = wire(payload=b'new complete record', generation=9)
    for first, second, bank, generation in ((a, b, 1, 9), (b, a, 0, 9),
                                            (a[:-1], b, 1, 9), (a, b[:-1], 0, 8),
                                            (None, b, 1, 9), (a, a, 0, 8)):
        selected = Choice()
        assert choose(lib, first, second, selected) == 0
        assert (selected.bank, selected.view.generation) == (bank, generation)
        next_bank, next_generation = c.c_uint32(77), c.c_uint64(88)
        assert lib.af_record_plan_next(c.byref(selected), c.byref(next_bank),
                                       c.byref(next_generation)) == 0
        assert (next_bank.value, next_generation.value) == (bank ^ 1, generation + 1)


@pytest.mark.parametrize('a,b,expected', [
    (wire(generation=2), wire(payload=b'different', generation=2), -4),
    (wire(), wire(version=2), -3), (wire(version=2), wire(), -3),
    (None, None, -1), (wire()[:-1], wire()[:-1], -1)])
def test_ambiguous_unsupported_or_both_bad_does_not_publish(lib, a, b, expected):
    selected = Choice()
    c.memset(c.byref(selected), 0xa5, c.sizeof(selected))
    before = bytes(selected)
    assert choose(lib, a, b, selected) == expected
    assert bytes(selected) == before


def test_generation_exhaustion_does_not_wrap_or_choose_write_target(lib):
    raw = wire(generation=0xffffffffffffffff)
    selected = Choice()
    assert choose(lib, raw, None, selected) == 0
    bank, generation = c.c_uint32(77), c.c_uint64(88)
    assert lib.af_record_plan_next(c.byref(selected), c.byref(bank), c.byref(generation)) == -5
    assert (bank.value, generation.value) == (77, 88)
