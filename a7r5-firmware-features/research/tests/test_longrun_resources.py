"""多库与长期播放回归；硬件服务边界明确使用夹具。"""
import importlib.util
import os
from pathlib import Path
import struct
import zlib

import pytest

FEATURES = Path(__file__).resolve().parents[1]
ROOT = FEATURES.parent
BUILD = Path(os.environ.get('A7R5_NATIVE24_BUILD',
    ROOT / 'a7r5-qemu/build/full419-repaired-20261111-v2-components'))


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def cp():
    support = load('longrun_actual_cp', FEATURES / 'firmware-runtime/dependencies/native12-combined/tests/runtime_support.py')
    folder = Path(os.environ.get('A7R5_LONGRUN_BUILD', BUILD))
    support.BASELINE = folder
    path = Path(os.environ.get('A7R5_LONGRUN_CP', folder / (
        'work/cp/cp423.NONINSTALLABLE.bin' if 'A7R5_LONGRUN_BUILD' in os.environ else 'cpapp-b.bin')))
    machine = support.CP(path.read_bytes())
    service = load('longrun_cp_services', FEATURES / 'firmware-runtime/tests/cp_services.py')
    service.receiver_services(machine, budget=16 * 947000)
    return machine


def test_multiple_retained_banks_have_disjoint_allocator_ranges(cp):
    first = cp.call(0x5ef69d, 947000)
    second = cp.call(0x5ef69d, 947000)
    assert first and second
    assert second >= first + 947000, '多库回放的分配区发生重叠，旧库不变断言无法成立'


def packet(op, token, mask, digest, slot=0, sequence=0, payload=b''):
    value = bytearray(struct.pack('<4B4s6I', 0xe7, 4, op, 0, b'R5N5',
                                 token, mask, slot, digest, sequence, 0) + payload)
    struct.pack_into('<I', value, 28, zlib.crc32(value))
    return bytes(value)


def test_rejected_unpublished_transfer_reuses_only_its_staging_bank(cp):
    probe = struct.pack('<4B6I', 0xe8, 2, 1, 32, 0x33503552, 77, 0, 0, 0, 0)
    assert cp.consume(probe + struct.pack('<I', zlib.crc32(probe)))
    crc = zlib.crc32(bytes(4))
    assert struct.unpack_from('<I', cp.consume(packet(1, 1, 0, crc)), 36)[0] == 0
    assert struct.unpack_from('<I', cp.consume(packet(3, 1, 0, crc, sequence=25)), 36)[0] == 0
    published = cp.words(0x1a39448, 1)[0]
    original = cp.read(published, 947000)
    for token in range(2, 5):
        ack = cp.consume(packet(1, token, 1, 0x12345678))
        assert struct.unpack_from('<I', ack, 36)[0] == 0
        ack = cp.consume(packet(2, token, 1, 0x12345678, slot=1, sequence=1, payload=bytes(2392)))
        assert struct.unpack_from('<I', ack, 36)[0] == 3
        assert cp.read(published, 947000) == original, '失败传输改写了已发布库'
    assert len(cp.heap_allocations) == 2, '未发布的失败暂存库被遗弃，持续消耗代次和堆'
    cp.consume(packet(1, 9, 1, 0xabcdef))
    staging = cp.words(0x1a39450, 1)[0]
    snapshot = cp.read(staging, 947000)
    ack = cp.consume(packet(2, 4, 1, 0x12345678, slot=1, sequence=1, payload=bytes(2392)))
    assert struct.unpack_from('<I', ack, 36)[0] != 0
    assert cp.read(staging, 947000) == snapshot, '迟到的旧会话 PUT 污染新暂存事务'


def compact(number):
    value = bytearray(2392)
    value[:len(str(number))] = str(number).encode()
    struct.pack_into('<I', value, 1172, 1)
    for index in range(129):
        struct.pack_into('<I', value, 656 + 4 * index, 1023 * index)
    return bytes(value)


def test_return_to_published_library_does_not_abandon_failed_staging(cp):
    probe = struct.pack('<4B6I', 0xe8, 2, 1, 32, 0x33503552, 77, 0, 0, 0, 0)
    cp.consume(probe + struct.pack('<I', zlib.crc32(probe)))
    digest = zlib.crc32(bytes(4))
    cp.consume(packet(1, 1, 0, digest))
    cp.consume(packet(3, 1, 0, digest, sequence=25))
    published = cp.words(0x1a39448, 1)[0]
    before = cp.read(published, 947000)
    for token in range(2, 5):
        cp.consume(packet(1, token, 1, 0x12345678))
        # 暂存尚在等待 PUT 时，AP 又恢复了当前已发布库。
        cp.consume(packet(1, token + 100, 0, digest))
        ack = cp.consume(packet(2, token, 1, 0x12345678, slot=1, sequence=1, payload=compact(token)))
        assert struct.unpack_from('<I', ack, 36)[0] != 0
        assert cp.read(published, 947000) == before
    assert len(cp.heap_allocations) == 2, '切回旧库时丢失了尚未发布的暂存缓冲'


def selection(sequence, slot, digest, token):
    raw = bytearray(struct.pack('<4B7I', 0xea, 2, 1, 32, 0x54463552,
                                sequence, slot, digest, token, 0, 0))
    struct.pack_into('<I', raw, 28, zlib.crc32(raw))
    return raw


def test_published_generations_are_retained_and_select_never_allocates(cp):
    probe = struct.pack('<4B6I', 0xe8, 2, 1, 32, 0x33503552, 77, 0, 0, 0, 0)
    cp.consume(probe + struct.pack('<I', zlib.crc32(probe)))
    retained = []
    for token in range(1, 17):
        value = compact(token)
        digest = zlib.crc32(struct.pack('<II', 1, 1) + value)
        for wire in (packet(1, token, 1, digest),
                     packet(2, token, 1, digest, slot=1, sequence=1, payload=value),
                     packet(3, token, 1, digest, sequence=25)):
            ack = cp.consume(wire)
            assert struct.unpack_from('<I', ack, 36)[0] == 0
        at = cp.words(0x1a39448, 1)[0]
        retained.append((at, cp.read(at, 947000)))
    assert len(cp.heap_allocations) == 16
    # 普通滤镜选择仅切不可变视图，不能消耗库的代次预算。
    for sequence in range(1, 2049):
        ack = cp.consume(selection(sequence, sequence & 1, digest, 16))
        assert struct.unpack_from('<I', ack, 24)[0] == 0
    assert len(cp.heap_allocations) == 16
    ack = cp.consume(packet(1, 17, 1, 0x12345678))
    assert struct.unpack_from('<I', ack, 36)[0] != 0
    assert all(cp.read(at, len(before)) == before for at, before in retained)
