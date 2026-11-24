"""回放 24 槽、原厂成像模块及其与拍摄功能共存的组件。"""
import json
import os
from pathlib import Path
import struct

import pytest
from unicorn import Uc, UC_ARCH_ARM, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn import arm_const as arm, arm64_const as a64

import replay as runtime
from replay import Replay, candidate, cp_raw, receipt, recipe
from test_legacy_six import (BASE, CP_END, GAMMA_TABLE, MATERIALS, cp_color406, cp_gamma406, cp_machine,
                             digest, test_joint_matrix_and_chroma_match_historical_six as matrix_chroma,
                             test_native_grid_packs_six_and_checks_payload as grid_colors)
from test_runtime import assert_color


OPTIONS = receipt.get('color_modules', {})
FL23 = OPTIONS.get('fl23', False)
SIX = OPTIONS.get('factory_six', False)
pytestmark = pytest.mark.skipif(not OPTIONS, reason='需要阶段三色彩构建')


@pytest.fixture(autouse=True)
def capture_proof(monkeypatch):
    capture = os.environ.get('A7R5_COLOR_CAPTURE')
    readback = os.environ.get('A7R5_COLOR_READBACK')
    if not capture and not readback:
        return None
    assert capture and readback
    proof = json.loads((Path(capture) / 'build.json').read_text())
    components = Path(readback) / 'components'
    ap = (components / 'usr/lib/appFw.so').read_bytes()
    cp = (components / 'cpapp-b.bin').read_bytes()
    assert proof['color_modules'] == OPTIONS
    assert proof['AP']['source_sha256'] == digest(candidate[0])
    assert proof['CP_aspect']['source_sha256'] == digest(cp_raw)
    ap_sha = digest(ap)
    if optional := os.environ.get('A7R5_OPTIONAL_AP_READBACK'):
        assert Path(optional) == Path(readback)
        manifest = json.loads((Path(optional) / 'manifest.json').read_text())
        assert manifest['components']['usr/lib/appFw.so']['sha256'] == ap_sha
    else:
        assert proof['AP']['target_sha256'] == ap_sha
    assert proof['CP_sha256'] == digest(cp)
    final_ap = (ap, *candidate[1:])
    monkeypatch.setitem(globals(), 'candidate', final_ap)
    monkeypatch.setitem(globals(), 'cp_raw', cp)
    monkeypatch.setattr(runtime, 'candidate', final_ap)
    monkeypatch.setattr(runtime, 'cp_raw', cp)
    monkeypatch.setitem(runtime.namespace, 'AP_SHA', ap_sha)
    monkeypatch.setitem(runtime.namespace, 'CP_SHA', proof['CP_sha256'])
    return proof


@pytest.fixture(scope='module')
def stock():
    folder = os.environ.get('A7R5_PHASE3_STOCK')
    if not folder:
        pytest.fail('需要原厂 4.00 解包工作区')
    path = Path(folder) / 'components/cpapp-b.bin'
    raw = path.read_bytes()
    assert digest(raw) == '3269bf62426339791fcfbe8529698cd4accbe6c3d2ea61cd7c368a90ab7ee7c8'
    return raw


@pytest.fixture
def historical(stock, monkeypatch):
    source = json.loads((MATERIALS / 'recipes.json').read_text())['integrated'][1]
    before = bytearray(stock)
    for row in source['patches']:
        offset = row['offset']
        old, new = (bytes.fromhex(row[k]) for k in ('before', 'after'))
        assert before[offset:offset + len(old)] == old
        before[offset:offset + len(new)] = new
    old = bytes(before)
    assert digest(old) == source['after_sha256']
    allowed = {id(cp_raw): digest(cp_raw), id(old): digest(old)}
    monkeypatch.setattr(cp_machine, 'require_source',
                        lambda raw, _pin, _name: assert_identity(raw, allowed))
    return old


def assert_identity(raw, allowed):
    assert digest(raw) == allowed[id(raw)]


def test_shared_ap_selectors_do_not_enable_unselected_looks():
    code, output, stop = 0x3550354, 0x1000000, 0x1000010
    ap = candidate[0]
    core = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    core.mem_map(code & ~4095, 4096)
    core.mem_write(code, ap[code:code + 132])
    core.mem_map(output, 4096)
    bases = (0, 3, 2, 1, 16, 15, 17, 18, 5, 13) + ((19, 20) if FL23 else ())
    for selected in range(19):
        for base, ordinary in enumerate(bases):
            for reg, value in ((a64.UC_ARM64_REG_X0, selected), (a64.UC_ARM64_REG_X1, base),
                               (a64.UC_ARM64_REG_X2, output), (a64.UC_ARM64_REG_LR, stop)):
                core.reg_write(reg, value)
            core.emu_start(code, stop, count=60)
            expected = (249 + selected - 10 if SIX and 10 <= selected <= 15 else
                        255 if selected == 16 else selected + 2 if FL23 and selected >= 17 else ordinary)
            assert bytes(core.mem_read(output, 1)) == bytes([expected])


def test_native_startup_maps_only_required_pages(stock, capture_proof):
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.mem_map(0x100000, 0x1b00000)
    cpu.mem_write(BASE, cp_raw)
    cpu.mem_map(0x03000000, 0x50000)
    cpu.mem_map(0x3e42000, 4096)
    if capture_proof:
        cpu.mem_write(0x1a3ad80, b'\xcc' * 512)
    cpu.reg_write(arm.UC_ARM_REG_SP, 0x03018000)
    cpu.emu_start(0x108398, 0x108728, count=5000000)
    assert cpu.reg_read(arm.UC_ARM_REG_PC) == 0x108728
    root, = struct.unpack('<I', cpu.mem_read(0x108f1c, 4))
    legacy = list(range(0x119000, CP_END, 4096)) if SIX else []
    if capture_proof:
        legacy.append(0x118000)
        assert root == 0x1a3c000 and bytes(cpu.mem_read(0x1a3ad80, 512)) == bytes(512)
    for page in [*legacy, 0x1195000, 0x1196000]:
        first, = struct.unpack('<I', cpu.mem_read(root + (page >> 20) * 4, 4))
        assert first & 3 == 1
        pte, = struct.unpack('<I', cpu.mem_read((first & ~1023) + ((page >> 12) & 255) * 4, 4))
        assert pte & 3 == 2 and pte & ~4095 == page
    # 未启用的附加功能保留原厂指令。
    offsets = [] if receipt.get('sound_layout') else [0x377622]
    if not capture_proof:
        offsets += [0x33f322 - BASE, 0xadf128 - BASE, 0x473562 - BASE, 0xae78ae - BASE]
    for offset in offsets:
        assert cp_raw[offset:offset + 4] == stock[offset:offset + 4]
    if FL23:
        assert bytes(cpu.mem_read(0x1a3a000, 3456)) == cp_raw[0x11d4000 - BASE:0x11d4000 - BASE + 3456]


@pytest.mark.skipif(not SIX, reason='需要六款共存构建')
def test_factory_six_matrix_and_grid_equal_historical(historical):
    matrix_chroma((cp_raw, historical))
    grid_colors((cp_raw, historical))


@pytest.mark.skipif(not SIX, reason='需要六款共存构建')
def test_factory_gamma_remains_distinct_from_sd_gamma(historical):
    work = cp_machine.WORK
    for wire in range(249, 255):
        for column in (0, 6):
            old, old_row = cp_gamma406.setup(historical, wire, column)
            new, row = cp_gamma406.setup(cp_raw, wire, column)
            assert row == old_row + 24
            assert cp_gamma406.construct(old) == cp_gamma406.construct(new)
            view, table, curve = (work + n for n in (0x5000, 0x6000, 0x8000))
            new.put(view, struct.pack('<6I', 0x423f17e1, 0, 1, table, 0, 0))
            new.word(0x1a39458, view)
            source = new.word(GAMMA_TABLE + column * 4)
            native_curve = new.read(source, 576)
            new.put(curve, native_curve)
            new.word(table + 51 * 28 + column * 4, curve)
            assert cp_gamma406.construct(old) == cp_gamma406.construct(new)
            new.word(work + 0x2030, 51)
            assert cp_gamma406.construct(new)[1] == native_curve[:516]


@pytest.mark.skipif(not FL23, reason='需要 FL2／FL3 共存构建')
def test_fl23_matrix_and_gamma_match_the_417_runtime(monkeypatch):
    folder = os.environ.get('A7R5_PHASE3_417')
    if not folder:
        pytest.fail('需要 4.17 的独立解包工作区')
    reference = (Path(folder) / 'components/cpapp-b.bin').read_bytes()
    assert digest(reference) == '35eb911d27be4a8aab8a0a5fe9a8f028c16453d5ab79605fe36dbd199b833300'
    allowed = {id(cp_raw): digest(cp_raw), id(reference): digest(reference)}
    monkeypatch.setattr(cp_machine, 'require_source', lambda raw, _pin, _name: assert_identity(raw, allowed))
    start = 0x11d4000 - BASE
    assert cp_raw[start:start + 3456] == reference[start:start + 3456]
    # 原生 CC1 记录、Gamma 指针表及外观路由逐字节一致。
    for start, length in ((0xbef3ec - BASE, 192), (0x107e968 - BASE, 51 * 28), (0x107eefc - BASE, 22 * 8)):
        assert cp_raw[start:start + length] == reference[start:start + length]
    work = cp_machine.WORK
    for profile, wire in ((54, 19), (55, 20), (56, 19), (57, 20)):
        for sector in (0, 7, 15, 16):
            outputs = []
            for raw in (reference, cp_raw):
                cpu = cp_color406.setup(raw, wire)[0]
                at = 0x11d4000 - BASE
                cpu.put(0x1a3a000, raw[at:at + 3456])
                outputs.append(cp_color406._original(cpu, 0x71e41e,
                               (work + 0x4000, sector, work + 0x3000, profile), 54)[0])
            assert outputs[0] == outputs[1]


def test_shared_slots_apply_then_return_to_original_group(capture_proof):
    replay = Replay(cards={'A:/R5NATIVE.BIN': recipe()})
    replay.boot()
    assert replay.ap.call('r5_filter_available_mask') & 0xffffff == 0xffffff
    looks = [(0x84c, 0)]
    if SIX:
        looks += [(0x858 + slot, 10 + slot) for slot in range(6)]
    if FL23:
        looks += [(0x852, 17), (0x853, 18)]
    if capture_proof:
        replay.ap.stub(0x1c61d14, lambda _ap: 0)
        set_ratio = capture_proof['AP']['symbols']['r5_aspect_set']
        ratio_state = capture_proof['AP']['selection']
    for slot in range(1, 25):
        if capture_proof:
            ratio = 9 if slot % 2 else 0
            replay.ap.call(set_ratio, ratio)
        replay.choose(slot)
        replay.service()
        assert replay.selected() == (slot, slot, slot)
        assert_color(replay, slot)
        mid, selector = looks[(slot - 1) % len(looks)]
        replay.native_target(mid)
        replay.service()
        assert replay.selected() == (0, 0, 0) and replay.ap.call('n12_current') == selector
        if capture_proof:
            assert replay.ap.read(ratio_state, 1) == bytes([ratio])
    assert replay.files['R5NATIVE.BIN'] == recipe() and replay.cp.heap_allocations == [947000]
