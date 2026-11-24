"""独立版对照原厂组件、CP 启动映射和释放自定义滤镜后的原厂取值。"""
import hashlib
import json
import struct

import pytest
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM
from unicorn import arm_const as arm

from replay import BUILD, Replay, candidate, cp_raw, receipt, recipe

pytestmark = pytest.mark.skipif(receipt.get('profile') != 'native24-stock', reason='只验证原厂基底')


def test_original_ap_and_cp_are_the_only_patch_preimages():
    def reverse(raw, patches, length):
        result = bytearray(raw[:length])
        for row in reversed(patches):
            at = row['offset']
            before, after = (bytes.fromhex(row[key]) for key in ('before', 'after'))
            if at < length:
                width = min(length - at, len(before))
                assert result[at:at + width] == after[:width]
                result[at:at + width] = before[:width]
        return bytes(result)

    upstream = json.loads((BUILD / 'upstream-ap/ap_build.json').read_text())
    cp_build = json.loads((BUILD / 'work/cp/build.json').read_text())
    pins = json.loads((BUILD / 'work/dependencies/baseline_recipes.json').read_text())
    ap_source = reverse(candidate[2], upstream['patches'], pins['ap_baseline']['bytes'])
    cp_source = reverse(cp_raw, cp_build['patches'], pins['cp_baseline']['bytes'])
    for name, original in [('ap_baseline', ap_source), ('cp_baseline', cp_source)]:
        assert hashlib.sha256(original).hexdigest() == pins[name]['source_sha256']
    assert cp_raw[0x20128:0x20138] == cp_source[0x20128:0x20138]
    assert receipt['local_AP']['patches'] == receipt['local_CP']['patches'] == []

    # 原厂 AP 选择器、可见性和调参能力表均未带入 FL2／FL3 前置补丁。
    for row in pins['ap_baseline']['patches']:
        at = row['offset']
        before = bytes.fromhex(row['before'])
        assert candidate[0][at:at + len(before)] == before


def test_cp_original_startup_maps_runtime_pages_without_touching_native_gamma():
    base = 0x108000
    original = (BUILD / 'work/inputs/cp_baseline.bin').read_bytes()

    def boot(raw):
        cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        cpu.mem_map(0x100000, 0x1b00000)
        cpu.mem_write(base, raw)
        cpu.mem_map(0x3000000, 0x50000)
        cpu.mem_map(0x3e42000, 4096)
        cpu.reg_write(arm.UC_ARM_REG_SP, 0x3018000)
        cpu.emu_start(0x108398, 0x108728, count=5000000)
        assert cpu.reg_read(arm.UC_ARM_REG_PC) == 0x108728
        return cpu

    old, new = boot(original), boot(cp_raw)
    for at, size in [(0x110cfa8, 47 * 28), (0xdcc67c, 22 * 8), (0xdcc514, 58 * 8)]:
        assert old.mem_read(at, size) == new.mem_read(at, size)
    assert bytes(new.mem_read(0x1a39458, 32)) == bytes(32)
    root, = struct.unpack('<I', new.mem_read(0x108f1c, 4))
    for page in (0x1195000, 0x1196000):
        first, = struct.unpack('<I', new.mem_read(root + (page >> 20) * 4, 4))
        assert first & 3 == 1
        second, = struct.unpack('<I', new.mem_read((first & ~1023) + ((page >> 12) & 255) * 4, 4))
        assert second & 3 == 2 and second & ~4095 == page


def test_release_of_custom_view_preserves_factory_rows_and_delayed_ids():
    replay = Replay(cards={'A:/R5NATIVE.BIN': recipe()})
    replay.boot()
    replay.choose(24)
    replay.service()
    assert replay.selected() == (24, 24, 24)
    replay.native_target(0x84d)
    replay.service()
    assert replay.selected() == (0, 0, 0)
    cp = replay.cp
    view, = cp.words(0x1a39458, 1)
    table, route, normal = cp.words(view + 12, 3)
    assert (route, normal) == (0xdcc67c, 0xdcc514)
    assert cp.read(table, 47 * 28) == cp.read(0x110cfa8, 47 * 28)
    assert cp.read(table + 47 * 28, 4 * 28) == bytes(4 * 28)
    for index, wire in enumerate((0, 3, 2, 1, 16, 15, 19, 20, 17, 18, 5, 13)):
        still, movie = cp.words(route + wire * 8, 2)
        left, right = (cp.words(table + row * 28, 7) for row in (51 + index * 2, 52 + index * 2))
        first = cp.words(table + still * 28, 7)
        assert left == (first[0],) * 6 + first[6:]
        assert right == (0,) * 6 + cp.words(table + movie * 28 + 24, 1)
