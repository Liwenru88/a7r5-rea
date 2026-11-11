"""RAW 私有 TIFF 写入边界及原生 HEIF 分类入口的定向指令回放。"""
import struct

import pytest
from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as R

from aspect_sizes import SIZES, SCENES
from build_mpr import build_mpr
from test_playback import mpr_images, machine  # noqa: F401
from test_geometry import DATA, STACK, STOP


@pytest.fixture(scope='module')
def metadata(mpr_images, tmp_path_factory):
    original, patched = mpr_images
    image, receipt = build_mpr(original, tmp_path_factory.mktemp('mpr-tags'))
    assert image == patched
    return image, receipt


def test_raw_private_tiff_changes_only_preview_declarations_and_rejects_bad_tags(metadata):
    image, receipt = metadata
    base = 0x10000000
    cpu = machine(image, base)
    obj, cnv, geo, scene = (DATA + n for n in (0x1000, 0x2000, 0x3000, 0x4000))
    buffer = DATA + 0x8000
    tags = {id: (buffer + 0x100 + i * 32, buffer + 0x300 + i * 16, DATA + 0x5000 + i * 16)
            for i, id in enumerate((0xa002, 0xa003, 0xb02b, 0xb02c))}
    expected_scene = [0, 0]
    def pointer(at, value): cpu.mem_write(at, struct.pack('<Q', value))
    def word(at, value): cpu.mem_write(at, struct.pack('<I', value))
    def tag(core, *_):
        key = core.reg_read(R.UC_ARM64_REG_X1)
        core.reg_write(R.UC_ARM64_REG_X0, tags[key][2])
        core.reg_write(R.UC_ARM64_REG_PC, core.reg_read(R.UC_ARM64_REG_LR))
    def jpeg_parser(core, *_):
        # JPEG 解析服务为边界夹具；本测试核对私有 TIFF 的范围和写入原子性。
        area = core.reg_read(R.UC_ARM64_REG_X0)
        cpu.mem_write(area + 12, struct.pack('<III', *expected_scene, 3))
        core.reg_write(R.UC_ARM64_REG_X0, 0)
        core.reg_write(R.UC_ARM64_REG_PC, core.reg_read(R.UC_ARM64_REG_LR))
    cpu.hook_add(UC_HOOK_CODE, tag, begin=base + 0x26f050, end=base + 0x26f050)
    cpu.hook_add(UC_HOOK_CODE, jpeg_parser, begin=base + 0x274b44, end=base + 0x274b44)
    def run():
        for i, value in enumerate((obj, cnv, 0x1000)):
            cpu.reg_write(getattr(R, f'UC_ARM64_REG_X{i}'), value)
        cpu.reg_write(R.UC_ARM64_REG_SP, STACK)
        cpu.reg_write(R.UC_ARM64_REG_LR, STOP)
        cpu.emu_start(base + receipt['symbols']['aspect_mpr_raw_metadata'], STOP, count=2000)
        assert cpu.reg_read(R.UC_ARM64_REG_PC) == STOP
        return cpu.reg_read(R.UC_ARM64_REG_X0) & 0xffffffff
    pointer(obj + 8, buffer); pointer(cnv + 0xf8, buffer); word(cnv + 0xf0, 0x1000)
    pointer(cnv + 0xd0, geo); pointer(cnv + 0x1b8, scene); word(cnv + 0x1b0, 0x200)
    pointer(obj + 0x48, DATA + 0x6000); pointer(obj + 0x50, DATA + 0x6100)
    for id, w, h in SIZES:
        for broken in (False, True):
            cpu.mem_write(buffer, bytes([0x5a]) * 0x1000)
            cpu.mem_write(geo, struct.pack('<HHHH', w, 0, h, 0))
            expected_scene[:] = SCENES[id - 4]
            for key, (entry, value, ref) in tags.items():
                cpu.mem_write(entry, struct.pack('<HHII', key, 4, 1 if key < 0xb000 else 2, 0))
                cpu.mem_write(ref, struct.pack('<QQ', entry, value))
            if broken:
                cpu.mem_write(tags[0xb02c][0] + 2, struct.pack('<H', 3))
            before = bytes(cpu.mem_read(buffer, 0x1000))
            result = run()
            expected = bytearray(before)
            if not broken:
                for key, values in ((0xa002, (w,)), (0xa003, (h,)),
                                     (0xb02b, (h, w)), (0xb02c, SCENES[id - 4][::-1])):
                    offset = tags[key][1] - buffer
                    struct.pack_into('<' + 'I' * len(values), expected, offset, *values)
            assert result == (0xffffffff if broken else 0)
            assert bytes(cpu.mem_read(buffer, 0x1000)) == expected


def test_heif_ispe_classifies_all_custom_scene_sizes_and_retains_unknown_fallback(metadata):
    image, _ = metadata
    base = 0x10000000
    cpu = machine(image, base)
    for (w, h), destination in [(wh, 0x2671d0) for wh in SCENES] + [((256, 208), 0x267194),
                                                                  ((240, 208), 0x267194),
                                                                  ((1616, 689), 0x267180)]:
        cpu.mem_write(STACK + 0x60, struct.pack('<II', w, h))
        cpu.reg_write(R.UC_ARM64_REG_X29, STACK)
        cpu.emu_start(base + 0x26717c, base + destination, count=256)
        assert cpu.reg_read(R.UC_ARM64_REG_PC) == base + destination
