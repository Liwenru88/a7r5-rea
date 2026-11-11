"""刷新查询不能提前消费尚未绘制的自定义参数。"""
import struct

from replay import candidate
from test_unified_look import asynchronous_machine


def test_parameter_dirty_lives_until_actual_labels_have_been_drawn():
    ap, state, choose, poll, finish, desired, controller, view = asynchronous_machine(candidate)
    ap.write(view, struct.pack('<Q', 0x58ca720))
    ap.write(controller + 0x178, struct.pack('<I', 0xda))
    manager = struct.unpack('<Q', ap.read(controller + 0x180, 8))[0]
    choose(1)
    finish(1)
    # 原心跳和页面管理器会分别查询；首次查询返回1不等于原呈现器已绘制。
    assert ap.call('n12_refresh', manager) == 1
    assert ap.call('n12_refresh', manager) == 1, '参数脏位被心跳查询提前消费，实际绘制将落后一键'
    ap.stub('n12_stock_parameter_labels', lambda a: 0)
    ap.call(0x220c830, view)
    assert ap.call('n12_refresh', manager) == 0


def test_failed_backend_is_visible_while_recovery_protects_pending_target():
    ap, state, choose, poll, finish, desired, controller, view = asynchronous_machine(candidate)
    choose(1)
    choose(2)
    ap.stub('r5_filter_command_state', lambda a: 5)
    ap.stub('r5_filter_recovering', lambda a: 1)
    assert ap.call('n12_refresh', struct.unpack('<Q', ap.read(controller + 0x180, 8))[0]) == 1
    title = ap.call('n12_title_name', state['mid'])
    assert (title - 0x02ff4601 - (state['mid'] - 0x1610)) // 32 == 3, '已失败不能长期显示等待切换'
    assert desired() == 1, '显示失败不能绕过恢复保护提交下一个目标'
