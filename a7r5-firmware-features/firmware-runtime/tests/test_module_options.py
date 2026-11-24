"""对实际独立构建组件的可选能力执行定向回放。"""
import pytest

from replay import Replay, receipt, recipe
from test_tabs import Tabs


DISABLED = set(receipt.get('disabled_modules', ()))


def confirm_slot(replay, slot):
    replay.mid = 0x160f + slot
    replay.ap.call(0x1c6f208, 18 + slot)
    replay.service()


@pytest.mark.skipif('sd-import' not in DISABLED, reason='需要关闭冷启动导入的组件')
def test_import_off_reads_only_internal_library():
    data = recipe()
    absent = Replay(cards={'A:/R5NATIVE.BIN': data})
    absent.boot()
    assert absent.ap.call('r5_filter_available_mask') == 0
    assert 'R5NATIVE.BIN' not in absent.files
    assert not any(row[0] == 'card_open' for row in absent.trace)
    restored = Replay(files={'R5NATIVE.BIN': data}, cards={'A:/R5NATIVE.BIN': b'other'})
    restored.boot()
    assert restored.ap.call('r5_filter_available_mask') & 0xffffffff == 0xffffff
    assert not any(row[0] == 'card_open' for row in restored.trace)
    assert restored.files['R5NATIVE.BIN'] == data


@pytest.mark.skipif('preview' not in DISABLED, reason='需要关闭自动预览的组件')
def test_preview_off_applies_only_on_confirmation():
    ui = Tabs()
    ui.state['mid'] = 0x1610
    ui.ap.call('n12_preview', 0, 19)
    ui.ap.call('n12_preview_menu', 0x1610)
    assert ui.state['requests'] == []
    ui.state['mid'] = 0x84c
    ui.key(6)
    assert ui.state['mid'] == 0x1610 and ui.state['requests'] == []
    ui.key(3)
    assert ui.state['mid'] == 0x1611 and ui.state['requests'] == []
    ui.key(0xc)
    assert ui.state['requests'] == [2] and ui.state['selected'] == 2
    ui.key(6)
    assert ui.state['mid'] == 0x84c and ui.state['requests'] == [2]
    ui.key(0xc)
    assert ui.state['requests'] == [2, 0]
    assert ui.state['stock'][-1][:2] == ('preview_menu', 0x84c)


@pytest.mark.skipif('group-memory' not in DISABLED or 'preview' in DISABLED, reason='需要预览开启但组记忆关闭的组件')
def test_group_memory_off_always_previews_first_valid():
    ui = Tabs()
    ui.state.update(mid=0x84e, native=2, unavailable_factory={0x84c})
    ui.key(6)
    ui.key(3)
    assert ui.state['mid'] == 0x1611
    ui.key(6)
    assert ui.state['mid'] == 0x84d
    ui.key(6)
    assert ui.state['mid'] == 0x1610
    assert ui.state['requests'] == [1, 2, 0, 1]


@pytest.mark.skipif('tuning' not in DISABLED, reason='需要关闭八项调参的组件')
def test_tuning_off_preserves_saved_tune_and_factory_keys():
    ui = Tabs()
    ui.key(9)
    assert ui.calls[-1] == 0x2010009
    ui.key(6)
    ui.key(9)
    assert ui.calls.count(0x2010009) == 1
    r = Replay(files={'R5NATIVE.BIN': recipe(), 'R5TUNE.BIN': b'retain'})
    r.boot()
    confirm_slot(r, 13)
    assert r.selected()[:2] == (13, 13)
    assert r.selected()[2] == (None if 'selection-restore' in DISABLED else 13)
    assert r.files['R5TUNE.BIN'] == b'retain'
    assert not any(row[:2] == ['open', 'R5TUNE.BIN'] for row in r.trace)


@pytest.mark.skipif('selection-restore' not in DISABLED, reason='需要关闭跨开机选择恢复的组件')
def test_restore_off_keeps_selection_file_and_rolls_back_live_failure():
    # 旧选择以 R5SEL4 保存，关闭恢复时既不导入该选值也不覆盖文件。
    import struct
    import zlib
    selection = b'R5SEL4\0\0' + struct.pack('<III', 1, 12, 0)
    selection += struct.pack('<I', zlib.crc32(selection + bytes(4)))
    r = Replay(files={'R5NATIVE.BIN': recipe(), 'R5FILTER.BIN': selection})
    r.boot()
    assert r.selected() == (0, 0, 12)
    confirm_slot(r, 13)
    assert r.selected() == (13, 13, 12)
    r.fail_refresh = True
    confirm_slot(r, 14)
    assert r.selected() == (13, 13, 12)
    assert r.files['R5FILTER.BIN'] == selection
    assert not any(row[:2] == ['open', 'R5FILTER.BIN'] for row in r.trace)


@pytest.mark.skipif('selection-restore' not in DISABLED or 'tuning' in DISABLED,
                    reason='需要调参开启但选择恢复关闭的组件')
def test_tuning_persists_without_selection_persistence():
    from test_parameters import ParameterReplay, display_custom, edit_vector, parameters

    r = ParameterReplay(files={'R5NATIVE.BIN': recipe()})
    r.boot()
    values = (-3, 4, -5, 2, 6, 7, 4, 8)
    edit_vector(r, values)
    assert r.selected() == (13, 13, None)
    assert r.cp_values() == values and 'R5TUNE.BIN' in r.files
    restored = ParameterReplay(files=r.files)
    restored.boot()
    assert restored.selected() == (0, 0, None)
    display_custom(restored, 13)
    assert parameters(restored, 13) == values
