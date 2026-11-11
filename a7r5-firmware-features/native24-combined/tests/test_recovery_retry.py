"""恢复耗尽后的显式重试；不改变 E4 所有权、成像或文件事务。"""
import struct

import pytest

from test_stability import selected13
from test_background_interaction import DelayedE4Replay

CENTER = 0x201000c
IDLE = 0x20f0001


def exhausted():
    r = selected13()
    r.fail_refresh = True
    r.choose(24)
    r.service()
    for _ in range(32):
        r.ms += 1000
        r.service()
    assert r.ap.call('r5_filter_command_state') == 5
    assert not r.ap.call('r5_filter_recovering')
    assert 'R5RECOV.BIN' in r.files
    return r


def idle(r, count=4):
    for _ in range(count):
        r.ms += 1000
        r.service()
        r.ap.call('n12_dispatch', r.controller, 0, IDLE)


@pytest.mark.parametrize('layout', [0, 1, 2])
def test_center_retries_exhausted_recovery_before_confirming_same_group(layout):
    r = exhausted()
    r.fail_refresh = False
    r.ap.write(r.controller + 0x190, struct.pack('<I', layout))
    calls = []
    r.ap.stub('n12_stock_dispatch', lambda a: calls.append(a.arg(2)) or 0)
    r.ap.call('n12_dispatch', r.controller, 0, CENTER)
    assert CENTER not in calls and r.selected()[0] == 13
    idle(r)
    assert r.selected() == (24, 24, 24)
    assert calls.count(CENTER) == 1
    assert not r.ap.call('r5_filter_recovery_required')
    assert 'R5RECOV.BIN' not in r.files


def test_retry_keeps_last_target_and_cancels_old_confirmation():
    r = exhausted()
    r.fail_refresh = False
    calls = []
    r.ap.stub('n12_stock_dispatch', lambda a: calls.append(a.arg(2)) or 0)
    r.ap.call('n12_dispatch', r.controller, 0, CENTER)
    r.choose(17)
    idle(r)
    assert r.selected() == (17, 17, 17)
    assert CENTER not in calls


def test_retry_remains_bounded_and_keeps_journal_when_backend_is_still_broken():
    r = exhausted()
    r.ap.stub('n12_stock_dispatch', lambda a: 0)
    before = r.ap.call('r5_filter_command_sequence')
    r.ap.call('n12_dispatch', r.controller, 0, CENTER)
    after = r.ap.call('r5_filter_command_sequence')
    assert after == before + 1
    r.ap.call('n12_dispatch', r.controller, 0, CENTER)
    assert r.ap.call('r5_filter_command_sequence') == after
    idle(r, 33)
    assert r.ap.call('r5_filter_command_state') == 5
    assert not r.ap.call('r5_filter_recovering')
    assert 'R5RECOV.BIN' in r.files and r.selected()[0] == 13


def test_center_never_reuses_unfinished_native_object():
    r = DelayedE4Replay()
    r.boot()
    r.choose(13)
    r.service()
    r.block_native = True
    r.choose(24)
    r.service()
    assert r.ap.call('r5_filter_native_inflight')
    seq = r.ap.call('r5_filter_command_sequence')
    packets = len(r.selection_packets())
    r.ap.stub('n12_stock_dispatch', lambda a: 0)
    r.ms += 61000
    r.service()
    r.ap.call('n12_dispatch', r.controller, 0, CENTER)
    r.service()
    assert r.ap.call('r5_filter_command_sequence') == seq
    assert len(r.selection_packets()) == packets
    assert r.constructed == 1 and r.ap.call('r5_filter_native_inflight')


def test_leaving_during_retry_never_applies_or_confirms_a_retired_target():
    r = exhausted()
    r.fail_refresh = False
    calls = []
    r.ap.stub('n12_stock_dispatch', lambda a: calls.append(a.arg(2)) or 0)
    r.ap.call('n12_dispatch', r.controller, 0, CENTER)
    before = len(r.selection_packets())
    r.ap.call('n12_dispatch', r.controller, 0, 0x201000f)
    # 原菜单委派出口为夹具，显式移除退出后的呈现器。
    r.ap.write(r.manager + 0x338, bytes(8))
    idle(r)
    assert r.selected() == (13, 13, 13)
    assert 24 not in r.selection_packets()[before:] and CENTER not in calls


def test_parameter_center_retries_and_uses_parameter_confirmation_entry():
    r = exhausted()
    r.fail_refresh = False
    r.ap.write(r.view, struct.pack('<Q', 0x58ca720))
    r.ap.write(r.controller + 0x178, struct.pack('<I', 0xda))
    calls = []
    r.ap.stub('n12_stock_parameter_dispatch', lambda a: calls.append(a.arg(2)) or 0)
    r.ap.call('n12_parameter_dispatch', r.controller, 0, CENTER)
    assert CENTER not in calls
    for _ in range(4):
        r.service()
        r.ap.call('n12_parameter_dispatch', r.controller, 0, IDLE)
    assert r.selected() == (24, 24, 24) and calls.count(CENTER) == 1
