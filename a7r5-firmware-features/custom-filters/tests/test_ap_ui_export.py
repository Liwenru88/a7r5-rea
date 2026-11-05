"""导出原菜单至已保存快照的AArch64接线；原界面服务明确隔离，无文件/整机。"""
import struct

import pytest
from unicorn import arm64_const as regs

from test_ap_ui_dynamic import modules  # noqa: F401
from test_ap_ui_lifecycle import _owner
from test_ap_ui_confirm import _confirm_owner


def _export(raw):
    m, manager, catalog, models, state = _owner(raw)
    u, work, base = m.u, m.work, m.base
    state['selector'] = 19
    u.mem_write(work + 0x424, bytes(4))
    m.services[base + 0x28bfdcc] = lambda cpu: cpu.reg_write(regs.UC_ARM64_REG_X0, work + 0x424)
    m.services[base + 0x17ffd84] = lambda cpu: cpu.reg_write(regs.UC_ARM64_REG_X0, 0)
    m.services[base + 0x1c05f18] = lambda cpu: cpu.reg_write(regs.UC_ARM64_REG_X0, state['selector'])
    m.services[base + 0x1bdb214] = lambda cpu: cpu.reg_write(regs.UC_ARM64_REG_X0, 0x15ec)
    preset = bytearray(74)
    preset[8] = 3
    u.mem_write(work + 0x6100, bytes(preset))
    assert m.call('af_install', catalog, 7, work + 0x6100, 0) == 0
    assert m.call('af_edit', catalog, 7, 0, 4) == 0
    models(0x1604, 0x15e7, 0xd4)
    assert m.call('af_ap_manage_ui_open', catalog, 7, 0) == 0
    assert m.call('af_ap_targets_stage') == 2
    models(0x2b36, 0x15e7)
    m.call('af_ap_refresh', manager)
    assert state['opens'] == [(0x2ed, 0xd4, 0x15ec)]
    models(0x1601, 0x15ec, 0xd4)
    m.call('af_ap_refresh', manager)
    assert m.call('af_ap_targets_stage') == 3
    assert m.call('af_ap_manage_ui_state') == 3
    assert m.call('af_ap_targets_current') == m.call('af_ap_targets_name', 0x1601)
    return m, manager, catalog, models, state


@pytest.mark.parametrize('change', ['none', 'menu-cancel', 'before-chosen', 'before-pump', 'restricted-before-pump'])
def test_export_captures_saved_and_keeps_dirty_working_and_current_identity(modules, change):
    m, manager, catalog, models, state = _export(modules)
    u, work, owner = m.u, m.work, m.symbols['af_ap_manager']
    before = bytes(u.mem_read(catalog, 6888))
    job = work + 0x6400
    # 未到本页真正ENTER，原+88及焦点都不得生成请求。
    models(0x15f3, 0x15ec, 0xd4)
    m.call('af_ap_targets_action', 0x15f3)
    assert m.call('af_ap_manage_take', owner, job) == -2
    if change == 'menu-cancel':
        models(0x2b36, 0x15e7)
        m.call('af_ap_refresh', manager)
        assert m.call('af_ap_targets_result') == -23
        assert m.call('af_ap_manage_take', owner, job) == -2
        assert bytes(u.mem_read(catalog, 6888)) == before
        return
    if change == 'before-chosen':
        state['selector'] = 0
    assert m.call('af_ap_targets_intent', 0x15f3) == 0
    m.call('af_ap_targets_action', 0x15f3)
    m.call('af_ap_targets_action', 0x15f3)
    if change == 'before-chosen':
        assert m.call('af_ap_targets_result') != 0
        assert m.call('af_ap_manage_take', owner, job) == -2
    elif change in ('before-pump', 'restricted-before-pump'):
        if change == 'before-pump':
            state['selector'] = 0
        else:
            u.mem_write(work + 0x424, struct.pack('<I', 1))
        m.call('af_ap_refresh', manager)
        assert m.call('af_ap_manage_take', owner, job) == -2
        assert m.call('af_ap_manage_cancel', owner, 1) == -5
    else:
        assert m.call('af_ap_manage_take', owner, job) == 0
        assert struct.unpack('<Q4I', u.mem_read(job, 24)) == (1, 7, 7, 7, 0)
        request = bytes(u.mem_read(job + 8, 176))
        assert request[16:] == bytes(160)
        # 请求携带同槽完整快照；导出选择本身不把dirty工作值提交成saved。
        assert m.call('af_dirty', catalog, 7) == 1
    assert bytes(u.mem_read(catalog, 6888)) == before
    assert state['scan'] == state['read'] == 0


def test_export_row_reuses_original_enter_close_intent_without_a_new_hook(modules):
    m, controller, event, models, state, _ = _confirm_owner(modules)
    models(next_menu=0x1604)
    assert m.call('af_ap_confirm', controller, event) == 0x73
    assert state['actions'] == [('manage', 0x1604)]
    assert state['closes'] == [controller] and not any(state['permits'].values())
    m.call('af_ap_confirm_close', controller)
    assert state['actions'] == [('manage', 0x1604)]
