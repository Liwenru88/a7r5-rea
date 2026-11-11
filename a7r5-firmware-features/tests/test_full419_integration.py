"""最终 DAT 的声音页、色彩、画幅状态及 AP 功能共存回归。"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import struct

import pytest
from unicorn import arm_const as R

FEATURES = Path(__file__).resolve().parents[1]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def final():
    if not os.environ.get('A7R5_FINAL_BUNDLE'):
        pytest.skip('需要本轮 4.19 全功能包及独立解包组件')
    bundle = Path(os.environ['A7R5_FINAL_BUNDLE'])
    readback = Path(os.environ['A7R5_FINAL_READBACK'])
    lock = json.loads((bundle / 'lock.json').read_text())
    assert json.loads((readback / 'manifest.json').read_text())['source'] == lock['dat']
    for name in ('usr/lib/appFw.so', 'cpapp-b.bin'):
        data = (readback / 'components' / name).read_bytes()
        assert hashlib.sha256(data).hexdigest() == lock['expected']['components'][name]['sha256']
    runtime = bundle / 'build-evidence/native24'
    support = load('full419_actual_support', FEATURES / 'native24-combined/dependencies/native12-combined/tests/runtime_support.py')
    support.BASELINE = runtime
    return bundle, readback, runtime, support


def test_actual_sound_page_keeps_original_root_and_rejects_corrupted_code_and_pte(final):
    bundle, readback, runtime, support = final
    raw = (readback / 'components/cpapp-b.bin').read_bytes()
    cp = support.CP(raw)
    cp.cpu.mem_map(0x3e42000, 4096)
    cp.cpu.reg_write(R.UC_ARM_REG_SP, cp.STACK + 0x8000)
    cp.cpu.emu_start(0x108398, 0x108728, count=5000000)
    assert cp.cpu.reg_read(R.UC_ARM_REG_PC) == 0x108728
    root, = struct.unpack('<I', cp.read(0x108f1c, 4))
    assert root == 0x1a3c000
    assert cp.read(0x1a3ad80, 512) == bytes(512)
    assert cp.read(0x1a3a000, 3456) == raw[0x11d4000-0x108000:0x11d4000-0x108000+3456]
    page = 0x1a3b000
    expected = raw[0x1198000-0x108000:0x1198000-0x108000+2240]
    assert cp.read(page, len(expected)) == expected
    cp.cpu.cpr_write(15, 0, 2, 0, 0, 0, False, root)
    assert cp.call('r5ss_cp_sound_page_error') == 0
    cp.write(page+2239, bytes([expected[-1] ^ 1]))
    assert cp.call('r5ss_cp_sound_page_error') != 0
    cp.write(page, expected)
    l1, = struct.unpack('<I', cp.read(root+(page>>20)*4, 4))
    at = (l1 & ~1023) + ((page>>12)&255)*4
    assert cp.read(at, 4) == struct.pack('<I', 0x1a3b63e)
    cp.write(at, bytes(4))
    assert cp.call('r5ss_cp_sound_page_error') != 0
    cp.write(at, struct.pack('<I', 0x1a3b63e))
    assert cp.call('r5ss_cp_sound_page_error') == 0


def test_final_sound_menu_relocations_and_crc_use_packaged_components(final, tmp_path):
    _, readback, runtime, support = final
    checks = load('full419_sound_checks', FEATURES / 'photo-electronic-shutter-sound/tests/test_bound_components.py')
    view = tmp_path / 'actual-components'
    view.mkdir()
    for name, relative in [('appFw.so', 'usr/lib/appFw.so'), ('cpapp-b.bin', 'cpapp-b.bin')]:
        shutil.copyfile(readback / 'components' / relative, view / name)
    (view / 'upstream-ap').mkdir()
    shutil.copyfile(runtime / 'upstream-ap/appFw.so', view / 'upstream-ap/appFw.so')
    record = json.loads((runtime / 'build.json').read_text())
    image = view, support, record
    checks.test_native_sound_menu_and_unified_registry(image)
    checks.test_relocations_keep_four_sound_peers_and_plt(image)
    checks.test_actual_cp_shared_crc_preserves_filter_protocol(image)


def test_final_ntsc_and_marker_native_behavior(final):
    _, readback, _, _ = final
    legacy = load('full419_ap_checks', FEATURES / 'native24-combined/dependencies/native12-combined/tests/test_integration.py')
    ap = (readback / 'components/usr/lib/appFw.so').read_bytes()
    cp = (readback / 'components/cpapp-b.bin').read_bytes()
    legacy.test_ntsc_branches_execute_to_original_continuations((None, None, ap, cp))
    legacy.test_marker_registration_executes_original_range_validator((None, None, ap, cp))


def test_final_templates_contain_r6_st_and_awb(final, monkeypatch):
    _, readback, _, _ = final
    checks = load('full419_template_checks', FEATURES / 'tests/test_phase1_replay.py')
    checks.test_all_12_templates_contain_both_selected_modules(readback, monkeypatch)
