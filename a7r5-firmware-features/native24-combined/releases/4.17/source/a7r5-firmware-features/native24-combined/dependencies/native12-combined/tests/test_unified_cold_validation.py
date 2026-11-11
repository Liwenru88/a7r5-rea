"""冷启动统一入口：真实双CPU协议和文件编解码，明确原E4执行替身。"""
import pytest

from test_unified_look import candidate  # noqa: F401
from unified_verification_support import UnifiedReplay, recipe


def test_boot_import_then_each_recipe_returns_to_native_st(candidate, images):
    replay = UnifiedReplay(candidate, images[3], cards={'A:/R5NATIVE.BIN': recipe()})
    replay.boot()
    assert replay.files['R5NATIVE.BIN'] == recipe()
    assert replay.ap.call('r5_filter_available_mask') & 0xffffffff == 0xfff
    assert replay.selected() == (0, 0, 0)
    for slot in range(1, 13):
        replay.choose(slot)
        replay.service()
        assert replay.selected() == (slot, slot, slot)
        assert replay.ap.call('n12_current') == 18 + slot
        record = recipe()[128 + (slot - 1) * 2452:128 + slot * 2452]
        full_name = record[28:92].split(b'\0', 1)[0].decode()
        assert replay.ap.string(replay.ap.call('r5_filter_full_name', slot)) == full_name
        title = replay.ap.call('n12_title_name', 0x160f + slot)
        assert replay.ap.string(replay.ap.call('r5_filter_menu_text', title)) == full_name
        before = len(replay.trace)
        replay.native_target(0x84c)
        assert not any(row[0].startswith('stock_') for row in replay.trace[before:])
        replay.service()
        assert replay.selected() == (0, 0, 0)
        assert [row for row in replay.trace if row[0].startswith('stock_')][-1] == ['stock_preview_menu', 0x84c]
        assert replay.native == replay.ap.call('n12_current') == 0
    assert not replay.handles
    replay.record('twelve-st-roundtrips')


@pytest.mark.parametrize('mid,selector', [(0x852, 17), (0x853, 18)])
def test_fl23_wait_for_real_exit_transaction_and_can_return_to_recipe(candidate, images, mid, selector):
    replay = UnifiedReplay(candidate, images[3], files={'R5NATIVE.BIN': recipe()})
    replay.boot()
    for slot in (1, 12):
        replay.choose(slot)
        replay.service()
        replay.native_target(mid)
        assert replay.selected()[0] == slot
        replay.service()
        assert replay.selected() == (0, 0, 0)
        assert [row for row in replay.trace if row[0].startswith('stock_')][-1] == ['stock_preview_menu', mid]
        assert replay.native == replay.ap.call('n12_current') == selector
    replay.choose(6)
    replay.service()
    assert replay.selected() == (6, 6, 6)
    replay.record(f'fl{selector - 15}-roundtrip')


def test_rapid_changes_during_actual_worker_keep_only_latest_and_failed_exit_does_not_apply_st(candidate, images):
    replay = UnifiedReplay(candidate, images[3], files={'R5NATIVE.BIN': recipe()})
    replay.boot()
    before = len(replay.selection_packets())
    replay.choose(1)

    def rotate():
        replay.on_refresh = None
        for slot in (2, 3, 11, 12):
            replay.choose(slot)
    replay.on_refresh = rotate
    replay.service()
    assert replay.selected() == (1, 1, 1)
    replay.service()
    assert replay.selected() == (12, 12, 12)
    assert replay.selection_packets()[before:] == [1, 1, 12, 12]
    replay.fail_refresh = True
    replay.native_target(0x84c)
    replay.service()
    assert replay.selected() == (12, 12, 12)
    assert replay.ap.call('r5_filter_command_state') == 3
    assert not any(row[0].startswith('stock_') for row in replay.trace)
    replay.fail_refresh = False
    replay.choose(6)
    replay.service()
    replay.native_target(0x84c)
    replay.service()
    assert replay.selected() == (0, 0, 0)
    assert [row for row in replay.trace if row[0].startswith('stock_')][-1] == ['stock_preview_menu', 0x84c]
    replay.record('rapid-and-failed-st-exit')


@pytest.mark.parametrize('slot,native', [(0, 0), (0, 1), (0, 17), (1, 0), (12, 0)])
def test_new_process_without_card_restores_persisted_selection_and_resume_ignores_sd(candidate, images, slot, native):
    first = UnifiedReplay(candidate, images[3], cards={'A:/R5NATIVE.BIN': recipe()}, native_selector=native)
    first.boot()
    if slot:
        first.choose(slot)
        first.service()
    assert first.selected() == (slot, slot, slot)
    first.record(f'restart-{slot}-native-{native}-before')
    # 新实例的全部AP/CP运行态均清零；仅传递上一次实际文件协议写出的字节。
    # 原厂0x690的开机输入仍为夹具，只验证自定义编号0不会主动把它强制改成ST。
    second = UnifiedReplay(candidate, images[3], files=first.files, native_selector=native)
    second.boot()
    assert second.selected() == (slot, slot, slot)
    assert second.files['R5NATIVE.BIN'] == recipe()
    assert second.ap.call('r5_filter_available_mask') & 0xffffffff == 0xfff
    assert not any(row[0] == 'card_open' for row in second.trace)
    assert not any(row == ['publish', 'R5NATIVE.BIN'] for row in second.trace)
    assert len(second.cp.heap_allocations) == 1
    if not slot:
        assert second.ap.call('n12_current') == native
        assert not any(row[0].startswith('stock_') for row in second.trace)
    # 恢复阶段即便出现零字节SD清空文件，也不能扫描／清除机内配方。
    second.cards = {'A:/R5NATIVE.BIN': b''}
    before = len(second.trace)
    event = second.ap.DATA + 0x7b000
    for value in (0x920143, 0x92015a):
        second.ap.write(event, value.to_bytes(4, 'little'))
        second.ap.call('r5_stage421_power', event)
    assert second.ap.call('r5_session_prepare') == 1
    assert second.ap.call('r5_session_cold_start') == 0
    second.ap.call('r5_stage411_child', second.ap.symbols['r5_stage411_state'], count=20000000)
    second.ap.call('r5_session_finish')
    assert second.selected() == (slot, slot, slot)
    assert second.files['R5NATIVE.BIN'] == recipe()
    assert len(second.cp.heap_allocations) == 1
    assert not any(row[0] == 'card_open' for row in second.trace[before:])
    assert not second.handles
    second.observe('resume')
    second.record(f'restart-{slot}-native-{native}-after-and-resume')
