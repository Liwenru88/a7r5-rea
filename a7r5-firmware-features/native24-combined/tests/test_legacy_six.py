"""在独立 CPU 上对照旧六款实际机器码，另外检查 SD 库与纵横比边界。"""

import json
import os
from pathlib import Path
import struct
import sys

import pytest
from unicorn import Uc, UC_ARCH_ARM, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn import arm_const as arm, arm64_const as arm64

HERE = Path(__file__).resolve().parents[1]
ROOT = HERE.parents[1]
sys.path[:0] = [str(HERE.parent / name) for name in ('look-factory-six/src', 'custom-filters')]
from build_legacy_six import BASE, CP_END, GAMMA_TABLE, TABLE_HOOKS, digest
from legacy_six import MATERIALS, load_recipes
from a7filters import cp_color406, cp_gamma406, cp_grid_route, cp_machine


@pytest.fixture(scope='module')
def inputs():
    out = os.environ.get('A7R5_LEGACY_SIX_BUILD')
    if not out:
        pytest.skip('需要六款合并构建目录')
    out = Path(out)
    receipt = json.loads((out / 'build.json').read_text())
    ap, cp = ((out / name).read_bytes() for name in ('appFw.so', 'cpapp-b.bin'))
    assert (digest(ap), digest(cp)) == tuple(receipt['components'][name] for name in ('appFw.so', 'cpapp-b.bin'))
    stock_path = Path(os.environ.get('A7R5_LEGACY_SIX_STOCK_CP',
        ROOT / 'a7r5-qemu/runs/verify-17-NqJEIq/baseline/inputs/cpapp-b.bin'))
    old = bytearray(stock_path.read_bytes())
    recipe = json.loads((MATERIALS / 'recipes.json').read_text())['integrated'][1]
    assert digest(old) == recipe['before_sha256']
    for row in recipe['patches']:
        at = row['offset']
        before, after = (bytes.fromhex(row[key]) for key in ('before', 'after'))
        assert old[at:at + len(before)] == before
        old[at:at + len(after)] = after
    assert digest(old) == recipe['after_sha256']
    return ap, cp, bytes(old), receipt


def test_factory_wire_and_existing_base_selection(inputs):
    ap, _, _, _ = inputs
    core = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    code, output, stop = 0x3550354, 0x1000000, 0x1000010
    core.mem_map(code & ~4095, 4096)
    core.mem_write(code, ap[code:code + 132])
    core.mem_map(output, 4096)
    stock = (0, 3, 2, 1, 16, 15, 17, 18, 5, 13, 19, 20)
    for selected in range(19):
        for base, ordinary in enumerate(stock):
            for reg, val in ((arm64.UC_ARM64_REG_X0, selected), (arm64.UC_ARM64_REG_X1, base),
                             (arm64.UC_ARM64_REG_X2, output), (arm64.UC_ARM64_REG_LR, stop)):
                core.reg_write(reg, val)
            core.emu_start(code, stop, count=60)
            want = 249 + selected - 10 if 10 <= selected <= 15 else {16: 255, 17: 19, 18: 20}.get(selected, ordinary)
            assert bytes(core.mem_read(output, 1)) == bytes([want])


@pytest.fixture
def verified_machine(inputs, monkeypatch):
    _, cp, old, _ = inputs
    allowed = {id(cp): digest(cp), id(old): digest(old)}

    def validate(raw, expected, name):
        assert digest(raw) == allowed[id(raw)]

    monkeypatch.setattr(cp_machine, 'require_source', validate)
    return cp, old


def test_joint_matrix_and_chroma_match_historical_six(verified_machine):
    cp, old = verified_machine
    w = cp_machine.WORK
    calls = [
        (0x71e41e, (w + 0x4000, 7, w + 0x3000, 0), 54),
        (0x71e670, (w + 0x5000, 0, w + 0x3000), 48),
        *((0x71e9c8, (w + 0x6000, 0, mode, w + 0x3000), 32) for mode in (0, 1)),
    ]
    for flag in (0, 1, 2):
        for marker in range(249, 255):
            machines = [cp_color406.setup(raw, marker, flag)[0] for raw in (old, cp)]
            for at, args, size in calls:
                outputs = [cp_color406._original(m, at, args, size)[0] for m in machines]
                assert outputs[0] == outputs[1], (flag, marker, hex(at))


def test_gamma_legacy_rows_and_sd_rows_remain_independent(verified_machine):
    cp, old = verified_machine
    for marker in (0, 3, *range(249, 255)):
        for column in (0, 6):
            a, old_row = cp_gamma406.setup(old, marker, column)
            b, new_row = cp_gamma406.setup(cp, marker, column)
            assert new_row == old_row + (24 if marker >= 249 else 0)
            assert cp_gamma406.construct(a) == cp_gamma406.construct(b)
            if marker < 249:
                continue
            # 设定独立 SD 曲线视图，重放私有行后仍按本次请求选择 Gamma。
            work = cp_machine.WORK
            view, table, route, curve = (work + i for i in (0x5000, 0x6000, 0x7000, 0x8000))
            b.put(view, struct.pack('<6I', 0x423f17e1, 0, 1, table, route, 0))
            b.word(0x1a39458, view)
            b.word(route, 51)
            source = b.word(0x107e968 + column * 4)
            native_curve = b.read(source, 576)
            b.put(curve, native_curve)
            b.word(table + 51 * 28 + column * 4, curve)
            assert cp_gamma406.construct(a) == cp_gamma406.construct(b)
            b.word(work + 0x2030, 51)
            _, y = cp_gamma406.construct(b)
            assert y == native_curve[:516]


def test_all_gamma_table_consumers_keep_stock_and_sd_routes(verified_machine):
    cp, _ = verified_machine
    m, _ = cp_gamma406.setup(cp, 0, 0)
    work = cp_machine.WORK
    view, table = work + 0x5000, work + 0x6000
    m.put(view, struct.pack('<6I', 0x423f17e1, 0, 1, table, 0, 0))
    m.word(0x1a39458, view)
    sources = ('r1', 'r6', 'r2', 'r2', 'lr', 'r0')
    destinations = ('r10', 'r10', 'r3', 'r3', 'r2', 'r1')
    for i, at in enumerate(TABLE_HOOKS):
        for row, wanted in ((74, table), (75, GAMMA_TABLE - 75 * 28), (86, GAMMA_TABLE - 75 * 28)):
            m.register('sp', cp_machine.STACK + 0xe000)
            m.register('lr', cp_machine.STOP | 1)
            flags = (m.register('cpsr') & 0x07ffffff) | 0xb8000000
            m.register('cpsr', flags)
            value = row * 7 if i in (2, 3, 5) else row
            if i == 1:
                value = work + 0x2000
                m.word(value + 0x30, row)
            m.register(sources[i], value)
            m.run(at, at + 4, preserve_state=True)
            assert m.register(destinations[i]) == wanted
            assert m.register(sources[i]) == value
            assert m.register('cpsr') & 0xf8000000 == flags & 0xf8000000


def test_native_grid_packs_six_and_checks_payload(verified_machine):
    cp, old = verified_machine
    for marker, (_, grid, _) in enumerate(load_recipes(), 249):
        a, pa = cp_grid_route.setup(old, marker)
        b, pb = cp_grid_route.setup(cp, marker)
        assert cp_grid_route.execute(a, pa) == cp_grid_route.execute(b, pb) == 405
        assert b.read(pb['out'], 1620) == a.read(pa['out'], 1620) == cp_grid_route.packed(cp, grid)
        assert cp_grid_route.execute(b, pb) == 0
    b, pb = cp_grid_route.setup(cp, 249)
    b.cpu.mem_write(0x11a008, bytes(4))
    assert cp_grid_route.execute(b, pb) == 0 and b.word(pb['grid_state'] + 0x184) == 0


def test_all_24_sd_slots_and_factory_six_share_the_final_pair(inputs, monkeypatch):
    from replay import BaseReplay, Replay, namespace, recipe, runtime_support
    from test_runtime import assert_color

    ap, cp, _, _ = inputs
    runtime = Path(os.environ.get('A7R5_LEGACY_SIX_RUNTIME', ROOT / 'a7r5-qemu/runs/verify-17-NqJEIq/runtime'))
    before = json.loads((runtime / 'build.json').read_text())
    assert digest((runtime / 'appFw.so').read_bytes()) == before['AP_sha256'] == (
        'eaf0b742745696f651dbe5ee75a813bb168ac41db81706743712ab8f6d0491bf')
    monkeypatch.setattr(runtime_support, 'BASELINE', runtime)
    monkeypatch.setitem(namespace, 'AP_SHA', digest(ap))
    monkeypatch.setitem(namespace, 'CP_SHA', digest(cp))
    replay = Replay.__new__(Replay)
    replay.fail_selection_rename = False
    BaseReplay.__init__(replay, (ap, before['unified']), cp, cards={'A:/R5NATIVE.BIN': recipe()})
    replay.boot()
    assert replay.ap.call('r5_filter_available_mask') & 0xffffff == 0xffffff
    for slot in range(1, 25):
        replay.choose(slot)
        replay.service()
        assert replay.selected() == (slot, slot, slot)
        assert_color(replay, slot)
        if slot <= 6:
            replay.native_target(0x857 + slot)
            replay.service()
            assert replay.selected() == (0, 0, 0)
            assert replay.ap.call('n12_current') == slot + 9
    assert replay.files['R5NATIVE.BIN'] == recipe()
    assert replay.cp.heap_allocations == [947000] and not replay.handles


def test_boot_preserves_page_root_and_maps_new_code(inputs, monkeypatch):
    _, cp, _, _ = inputs
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.mem_map(0x100000, 0x1b00000)
    cpu.mem_write(BASE, cp)
    cpu.mem_map(0x03000000, 0x50000)
    cpu.mem_map(0x3e42000, 4096)
    cpu.reg_write(arm.UC_ARM_REG_SP, 0x03018000)
    cpu.emu_start(0x108398, 0x108728, count=5000000)
    assert cpu.reg_read(arm.UC_ARM_REG_PC) == 0x108728
    assert bytes(cpu.mem_read(0x1a3ad80, 512)) == bytes(512)
    root = struct.unpack('<I', cpu.mem_read(0x108f1c, 4))[0]
    l1 = struct.unpack('<I', cpu.mem_read(root + 4, 4))[0]
    assert l1 & 3 == 1
    for page in range(0x118000, CP_END, 4096):
        l2 = struct.unpack('<I', cpu.mem_read((l1 & ~1023) + ((page >> 12) & 255) * 4, 4))[0]
        assert l2 & 3 == 2 and l2 & ~4095 == page
    monkeypatch.syspath_prepend(str(HERE / 'aspect'))
    from test_cp import POOL, TASK, bind, jpeg_geometry

    cpu.mem_write(POOL + 4, struct.pack('<I', 2))
    cpu.mem_write(POOL + 0x10, struct.pack('<II', TASK, 2 * 0x6688))
    bind(cpu, TASK, 0xe5, 47)
    assert jpeg_geometry(cpu, TASK) == (9504, 4048)


def test_all_name_banks_keep_aspect_labels(inputs):
    _, _, _, receipt = inputs
    names = receipt['names']
    out = Path(os.environ['A7R5_LEGACY_SIX_BUILD'])
    banks = sorted(out.glob('string_*.uxc'))
    assert len(banks) == 68
    for bank in banks:
        raw = bank.read_bytes()
        assert digest(raw) == receipt['components'][bank.name]
        count = struct.unpack_from('<I', raw, 12)[0] // 0x1001
        assert count == 3038
        base = 16 + 2 * count
        for tag, text in [(0xabd8 + i, n) for i, n in enumerate(names)] + [(0xab64, '1.91:1'), (0xab65, '2.35:1')]:
            at = base + 4 * struct.unpack_from('<H', raw, 16 + 2 * (tag - 0xa000))[0]
            assert struct.unpack_from('<I', raw, at)[0] == 0x1e000000 + tag
            assert raw[at + 4:].split(b'\0', 1)[0].decode() == text
