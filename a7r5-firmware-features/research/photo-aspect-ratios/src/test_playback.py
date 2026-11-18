"""回放 A7R5 原生静态尺寸匹配和 JPEG 读侧元数据出口。"""

import io
import json
import os
from pathlib import Path
import runpy
import struct

from elftools.elf.elffile import ELFFile
import pytest
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn import arm64_const as R

from build_mpr import JPEG_EXIT, STOCK, build_mpr, digest
from test_ap import ap_image
from test_geometry import DATA, ENCODE_SIZES, ROOT, STACK, STOP


CUSTOM_SIZES = tuple(size for row in ENCODE_SIZES.values() for size in row)
NATIVE_SIZES = tuple(ENCODE_SIZES)
UNKNOWN_SIZE = (9504, 4049)


def machine(image, base):
    core = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    for segment in ELFFile(io.BytesIO(image)).iter_segments():
        if segment['p_type'] == 'PT_LOAD' and segment['p_flags'] & 1:
            start = segment['p_vaddr'] & ~0xfff
            end = (segment['p_vaddr'] + segment['p_memsz'] + 0xfff) & ~0xfff
            core.mem_map(base + start, end - start)
            core.mem_write(base + segment['p_vaddr'], segment.data())
    core.mem_map(DATA, 0x30000)
    return core


def test_native_still_matcher_accepts_generated_sizes_and_keeps_native_fallback(ap_image):
    base = 0x10000000
    core = machine(ap_image, base)
    table = DATA + 0x1000
    core.mem_write(table, b''.join(struct.pack('<HHI', *size, 0) for size in NATIVE_SIZES))
    # 原函数有 17 个入参，后九个走栈。
    core.mem_write(STACK, struct.pack('<9Q', *([table] * 9)))
    for kind, size, expected in (
        *((0, size, 1) for size in CUSTOM_SIZES + NATIVE_SIZES),
        (0, UNKNOWN_SIZE, 0),
        (1, CUSTOM_SIZES[0], 0),
    ):
        core.mem_write(DATA, struct.pack('<I', kind))
        core.mem_write(DATA + 0xf2, b'\x01\x00\x00')
        core.mem_write(DATA + 0xb80, b'\x01')
        core.mem_write(DATA + 0xb84, struct.pack('<II', *size))
        core.reg_write(R.UC_ARM64_REG_X0, DATA)
        for index in range(1, 8):
            core.reg_write(getattr(R, f'UC_ARM64_REG_X{index}'), table)
        core.reg_write(R.UC_ARM64_REG_SP, STACK)
        core.reg_write(R.UC_ARM64_REG_LR, STOP)
        core.emu_start(base + 0x2dbf3b0, STOP, count=512)
        assert core.reg_read(R.UC_ARM64_REG_PC) == STOP
        assert core.reg_read(R.UC_ARM64_REG_SP) == STACK
        assert core.reg_read(R.UC_ARM64_REG_X0) == expected, (kind, size)


@pytest.fixture(scope='module')
def mpr_images(tmp_path_factory):
    path = Path(os.environ.get('A7R5_ASPECT_STOCK_USR',
        ROOT/'a7r5-qemu/runs/verify-17-NqJEIq/baseline/inputs/nflasha15'))
    if not path.is_file():
        pytest.skip('需要锁定的原厂 USR 分区')
    ext2 = runpy.run_path(str(ROOT/'a7r5-dat-tool/a7r5dat/ext2read.py'))['Ext2'](path)
    try:
        raw = ext2.read_inode(ext2.walk('/lib/libmpr.so'))
    finally:
        ext2.mm.close()
        ext2.f.close()
    assert digest(raw) == STOCK
    if folder := os.environ.get('A7R5_ASPECT_CAPTURE'):
        folder = Path(folder)
        receipt = json.loads((folder / 'build.json').read_text())['MPR']
        patched = (folder / 'libmpr.so').read_bytes()
        assert digest(patched) == receipt['target_sha256']
    else:
        patched, receipt = build_mpr(raw, tmp_path_factory.mktemp('aspect-mpr'))
    reverse = bytearray(patched[:len(raw)])
    for row in receipt['patches']:
        offset, before = row['offset'], bytes.fromhex(row['before'])
        assert reverse[offset:offset+len(before)].hex() == row['after']
        reverse[offset:offset+len(before)] = before
    assert reverse == raw
    return raw, patched


def test_jpeg_read_exit_keeps_original_classification(mpr_images):
    base = 0x10000000
    original, patched = (machine(image, base) for image in mpr_images)
    meta = DATA + 0x1000

    def read_metadata(core, dimensions, *, valid=1, ratio=0, present=True):
        core.mem_write(DATA + 8, struct.pack('<Q', meta if present else 0))
        state = struct.pack('<B3xIIB3xI', valid, *dimensions, ratio, 3)
        core.mem_write(meta, state)
        core.mem_write(STACK, struct.pack('<QQ', 0, STOP) + bytes(0x30))
        core.reg_write(R.UC_ARM64_REG_X19, DATA)
        core.reg_write(R.UC_ARM64_REG_SP, STACK)
        core.emu_start(base + JPEG_EXIT, STOP, count=256)
        assert core.reg_read(R.UC_ARM64_REG_PC) == STOP
        assert core.reg_read(R.UC_ARM64_REG_SP) == STACK + 0x40
        assert core.reg_read(R.UC_ARM64_REG_X0) == 0
        assert core.mem_read(DATA + 0x3f0, 4) == struct.pack('<I', 2)
        return bytes(core.mem_read(meta, len(state)))

    for size in CUSTOM_SIZES:
        assert read_metadata(patched, size) == read_metadata(original, size)
    for size, options in ((UNKNOWN_SIZE, {}), (NATIVE_SIZES[0], {'ratio': 1}),
                          (CUSTOM_SIZES[0], {'valid': 0}), (CUSTOM_SIZES[0], {'ratio': 1}),
                          (CUSTOM_SIZES[0], {'present': False})):
        assert read_metadata(patched, size, **options) == read_metadata(original, size, **options)


def test_jpeg_native_writer_header_cache_and_exif_agree_for_all_six_ratios(mpr_images):
    from aspect_sizes import SIZES, FULL_SIZES, NATIVE_CLASSES
    from support_jpeg_writer import JpegWriter, geometry, GEN, OBJ

    original, patched = mpr_images
    for bias in (0, 0x10000000):
        for index, (id, width, height) in enumerate(SIZES):
            writer = JpegWriter(patched, bias)
            writer.prepare((width, height), FULL_SIZES[index % 3])
            before_header = writer.cache()
            assert writer.source_pointer == OBJ + 0x13c0
            assert writer.header() == 0
            assert writer.values() == (width, height)
            assert geometry(before_header) == (1, width, height, *NATIVE_CLASSES[id - 4])
            assert geometry(writer.native_meta()) == geometry(before_header)
            assert bytes(writer.u.mem_read(GEN, len(writer.source))) == writer.source
        for wh in ((9504, 6336), (9504, 4049)):
            old, new = JpegWriter(original, bias), JpegWriter(patched, bias)
            old.prepare(wh); new.prepare(wh)
            assert old.cache() == new.cache() and new.source_pointer == GEN
            assert old.header() == new.header() == 0
            assert old.native_header() == new.native_header()
