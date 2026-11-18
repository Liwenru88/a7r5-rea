"""执行 A7R5 AVCAM 原始接收器和 JPEG 尺寸构造。"""

import json
import os
from pathlib import Path
import runpy
import struct

import pytest
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn import arm64_const as R

from build_avcam import SOURCE, apply_avcam, compile_avcam, digest
from test_geometry import CASES, DATA, GEOMETRY, ROOT, STACK, STOP


BASE = 0x1000000
PACKET = DATA
CONTEXT = DATA + 0x1000


@pytest.fixture(scope='module')
def stock_avcam():
    path = os.environ.get('A7R5_ASPECT_STOCK_AVCAM')
    if path:
        raw = Path(path).read_bytes()
    else:
        partition = Path(os.environ.get('A7R5_ASPECT_STOCK_AVCAM_PARTITION',
            ROOT/'a7r5-qemu/runs/verify-17-NqJEIq/dat/archive/0700_part_image/dev/nflasha3'))
        if not partition.is_file():
            pytest.skip('需要固定 A7R5 原厂 AVCAM 或其分区输入')
        fat = runpy.run_path(str(ROOT/'a7r5-dat-tool/a7r5dat/fat.py'))['FatImage']
        raw = fat(partition.read_bytes()).read('/AV-CAM.BIN')
    assert digest(raw) == SOURCE
    return raw


@pytest.fixture(scope='module')
def images(stock_avcam, tmp_path_factory):
    if folder := os.environ.get('A7R5_ASPECT_CAPTURE'):
        folder = Path(folder)
        proof = json.loads((folder / 'build.json').read_text())['AVCAM']
        result = (folder / 'AV-CAM.BIN').read_bytes()
        assert digest(result) == proof['target_sha256'] and digest(stock_avcam) == proof['source_sha256']
    else:
        result, proof = apply_avcam(stock_avcam, compile_avcam(tmp_path_factory.mktemp('aspect-avcam')))
    reverse = bytearray(result[:len(stock_avcam)])
    for row in proof['patches']:
        at, before = row['offset'], bytes.fromhex(row['before'])
        assert result[at:at + len(before)].hex() == row['after']
        reverse[at:at + len(before)] = before
    assert reverse == stock_avcam and len(result) >= len(stock_avcam)
    return stock_avcam, result


def machine(raw):
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.mem_map(BASE, 0x1000000)
    cpu.mem_write(BASE, raw)
    cpu.mem_map(DATA, 0x30000)
    return cpu


def native_format(cpu, aspect, formats, dimensions):
    data = bytearray(0x468)
    struct.pack_into('<I', data, 0, aspect)
    for at, kind, (width, height) in zip((0x1b0, 0x1bc), formats, dimensions):
        struct.pack_into('<IBBHH', data, at, kind, 0, 0, width, height)
    struct.pack_into('<I', data, 0x324, 9504)
    struct.pack_into('<I', data, 0x330, 6336)
    cpu.mem_write(PACKET, bytes(data))
    cpu.mem_write(CONTEXT, bytes(0x400))
    cpu.reg_write(R.UC_ARM64_REG_SP, STACK)
    cpu.reg_write(R.UC_ARM64_REG_X0, CONTEXT)
    cpu.reg_write(R.UC_ARM64_REG_X1, PACKET)
    cpu.emu_start(BASE+0x1f4088, BASE+0x1f4114, count=8000)
    assert cpu.reg_read(R.UC_ARM64_REG_PC) == BASE+0x1f4114
    return bytes(cpu.mem_read(CONTEXT, 0x400))


def test_avcam_jpeg_packet_sizes_update_only_the_jpeg_slot(images):
    stock, patched = map(machine, images)
    full = (9504, 6336)
    for formats in ((1, 2), (2, 1)):
        index = formats.index(1)
        jpeg = (0xa4, 0x224)[index]
        raw = (0x224, 0xa4)[index]
        control = native_format(stock, 2, formats, (full, full))
        assert native_format(patched, 2, formats, (full, full)) == control
        for _, wh, _ in CASES:
            dimensions = (wh, full) if index == 0 else (full, wh)
            changed = native_format(patched, 2, formats, dimensions)
            assert struct.unpack_from('<I', changed, jpeg+0x20)[0] == wh[0]
            assert struct.unpack_from('<I', changed, jpeg+0x2c)[0] == wh[1]
            assert changed[raw:raw+0x180] == control[raw:raw+0x180]
        assert native_format(patched, 1, formats, (full, full)) == native_format(stock, 1, formats, (full, full))
    assert native_format(patched, 2, (2, 4), (full, full)) == native_format(stock, 2, (2, 4), (full, full))


def test_repacked_native_size_setter_keeps_both_old_entry_points(images):
    stock, patched = map(machine, images)
    for formats in ((0, 0), (1, 2), (4, 1), (3, 4)):
        for start, arguments in ((0x1f4dbc, (6240, 4160)),
                                 (0x1f4dfc, (1, 6240, 4160)),
                                 (0x1f4dfc, (16, 6240, 4160))):
            results = []
            for cpu in (stock, patched):
                cpu.mem_write(CONTEXT, bytes([0xc5])*0x400)
                for at, kind in zip((0xa4, 0x224), formats):
                    cpu.mem_write(CONTEXT+at, struct.pack('<I', kind))
                cpu.reg_write(R.UC_ARM64_REG_SP, STACK)
                cpu.reg_write(R.UC_ARM64_REG_X30, STOP)
                for i, value in enumerate((CONTEXT, *arguments)):
                    cpu.reg_write(getattr(R, f'UC_ARM64_REG_X{i}'), value)
                cpu.emu_start(BASE+start, STOP, count=600)
                assert cpu.reg_read(R.UC_ARM64_REG_PC) == STOP
                assert cpu.reg_read(R.UC_ARM64_REG_SP) == STACK
                results.append(bytes(cpu.mem_read(CONTEXT, 0x400)))
            assert results[0] == results[1]


def test_heif_uses_cropped_scene_size_and_fits_thumbnail_only_for_custom(images):
    stock, patched = map(machine, images)
    main = CONTEXT + 0x3bc
    source = CONTEXT + 0x3c8

    def request(cpu, aspect, main_wh, source_wh, flag, start, stop):
        cpu.mem_write(STACK, bytes(0x200))
        cpu.mem_write(CONTEXT+0x80, struct.pack('<I', aspect))
        cpu.mem_write(CONTEXT+0x81c, struct.pack('<I', flag))
        cpu.mem_write(main, GEOMETRY.pack(9600, 6344, *main_wh, 0, 0))
        cpu.mem_write(source, GEOMETRY.pack(1664, 1080, *source_wh, 0, 0))
        cpu.reg_write(R.UC_ARM64_REG_SP, STACK)
        for i, value in ((8, 160), (9, 120), (20, CONTEXT), (22, CONTEXT), (23, source), (27, source)):
            cpu.reg_write(getattr(R, f'UC_ARM64_REG_X{i}'), value)
        cpu.emu_start(BASE+start, BASE+stop, count=700)
        assert cpu.reg_read(R.UC_ARM64_REG_PC) == BASE+stop
        return bytes(cpu.mem_read(STACK, 0x200))

    modes = ((0x2066b4, 0x206490), (0x20684c, 0x2068b4))
    for mode in modes:
        for aspect, width, height, flag in ((2, 9504, 6336, 1), (1, 8448, 6336, 1),
                                             (2, 9504, 4048, 0), (2, 0, 0, 1)):
            args = aspect, (width, height), (1616, 1080), flag, *mode
            assert request(patched, *args) == request(stock, *args)

    roi = (1616, 688)
    assert struct.unpack_from('<HH', request(patched, 2, (9504, 4048), roi, 1, *modes[0]), 0xd8) == roi
    result = request(patched, 2, (9504, 4048), roi, 1, *modes[1])
    assert struct.unpack_from('<4H', result, 0x144) == (0, 26, 160, 68)
    assert struct.unpack_from('<IH', result, 0x58) == (0x08000000, 0x800)
