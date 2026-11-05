"""原有界面保持与无需人工恢复的可观察回归；原厂UI/E4边界仍为夹具。"""
import struct

import pytest

from replay import Replay, recipe
from test_stability import FaultReplay, selected13


@pytest.mark.parametrize('mid', [0x84c, 0x84d, 0x84e, 0x852, 0x853])
def test_original_title_and_parameters_survive_unknown_backend(mid):
    r = selected13()
    r.armed = r.fail_forward = r.drop_rollback = True
    r.choose(24)
    r.service()
    assert r.ap.call('r5_filter_recovery_required') == 1
    r.mid = mid
    title = 0x2030001
    r.ap.stub(0x1bd5508, lambda a: title)
    assert r.ap.call('n12_title_name', mid) == title
    output, snapshot = r.ap.DATA + 0x78000, r.ap.DATA + 0x78100
    r.ap.write(snapshot + 0x20, struct.pack('<I', 0))
    r.ap.stub('n12_stock_display', lambda a: a.write(a.arg(1), b'ORIGINAL') or 0)
    r.ap.call('n12_display', 0, output, 0, snapshot)
    assert r.ap.read(output, 8) == b'ORIGINAL'
    r.ap.stub('n12_stock_parameter_value', lambda a: 7)
    assert r.ap.call('n12_parameter_value', 0) == 7
    writes = []
    r.ap.stub('n12_stock_step_0', lambda a: writes.append('write') or 0)
    r.ap.call('n12_step_0', 0, 1)
    assert writes == []
    r.record(f'background-original-{mid:x}')


def test_failed_switch_recovers_prior_selection_without_user_action():
    r = selected13()
    r.armed = r.fail_forward = r.drop_rollback = True
    r.choose(24)
    r.service()
    assert r.selected() == (13, 24, 13)
    r.fail_forward = r.drop_rollback = False
    r.ms += 1000
    for _ in range(3):
        r.service()
    assert r.selected() == (13, 13, 13)
    assert r.ap.call('r5_filter_recovery_required') == 0
    assert r.ap.call('r5_filter_pending') == 0
    assert r.ap.call('r5_filter_command_state') == 3
    assert 'R5RECOV.BIN' not in r.files
    r.record('background-auto-rollback')


def test_corrupt_journal_is_repaired_without_st_selection():
    r = FaultReplay(files={'R5NATIVE.BIN': recipe(), 'R5RECOV.BIN': bytes(24)})
    r.boot()
    assert r.selected() == (0, 0, 0)
    assert r.ap.call('r5_filter_recovery_required') == 0
    assert 'R5RECOV.BIN' not in r.files
    r.record('background-corrupt-journal')


class DelayedE4Replay(FaultReplay):
    block_native = False
    constructed = 0

    def refresh(self, ap):
        if not self.block_native:
            return super().refresh(ap)
        self.constructed += 1
        self.object = ap.DATA + 0x79000 + 16 * self.constructed
        ap.pending.append(('r5_filter_refresh_construct425', (self.object, ap.arg(0) + 16)))
        return 0


@pytest.mark.parametrize('native_last', [False, True])
def test_delayed_e4_background_recovery_keeps_only_last_ui_target(native_last):
    r = DelayedE4Replay()
    r.boot()
    r.choose(13)
    r.service()
    r.block_native = True
    r.choose(24)
    r.service()
    assert r.constructed == 1 and r.ap.call('r5_filter_native_inflight') == 1
    before = len(r.selection_packets())
    for slot in (14, 17, 23):
        r.choose(slot)
    if native_last:
        r.native_target(0x853)
    r.ms += 1000
    r.service()
    assert r.constructed == 1 and len(r.selection_packets()) == before
    r.ap.call('r5_filter_refresh_execute425', r.object + 0x1000)
    assert r.ap.call('r5_filter_native_inflight') == 1
    r.ap.call('r5_filter_refresh_execute425', r.object)
    r.block_native = False
    for _ in range(3):
        r.service()
    assert r.selected() == ((0, 0, 0) if native_last else (23, 23, 23))
    if native_last:
        assert r.native == 18
    assert 14 not in r.selection_packets() and 17 not in r.selection_packets()
    assert r.ap.call('r5_filter_recovery_required') == 0
    r.record('background-delayed-last-native' if native_last else 'background-delayed-last-custom')


def test_persistent_failure_ends_automatic_retries_without_false_success():
    r = selected13()
    r.fail_refresh = True
    r.choose(24)
    r.service()
    for _ in range(32):
        r.ms += 1000
        r.service()
    assert r.ap.call('r5_filter_recovering') == 0
    assert r.ap.call('r5_filter_recovery_required') == 1
    assert r.ap.call('r5_filter_command_state') == 5
    assert r.selected()[0] == 13 and 'R5RECOV.BIN' in r.files
    before = len(r.selection_packets())
    r.ms += 100000
    r.service()
    assert len(r.selection_packets()) == before
    r.record('background-bounded-failure')
