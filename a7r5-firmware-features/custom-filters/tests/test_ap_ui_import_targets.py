"""已准备LUT模板到原D4目标确认的CPU接线；媒体/转换服务为显式边界。"""
import struct

import pytest
from unicorn import arm64_const as regs

from test_ap_ui_dynamic import modules  # noqa: F401
from test_ap_ui_lifecycle import _owner


def prepared_targets(raw, occupied=False):
    m, manager, catalog, models, state = _owner(raw, scan_result=0)
    u = m.u
    state.update(templates=0, finish=0, cancel=0)
    template = bytearray(176)
    struct.pack_into('<I', template, 0, 3)
    struct.pack_into('<IQ', template, 20, 0, 1)
    template[40] = 3  # initial.params[6]，完整纯参数ST基底。
    name = '暖光'.encode()
    struct.pack_into('<I', template, 16, len(name))
    template[106:106 + len(name)] = name
    state['template'] = template

    def result(cpu, value=0):
        cpu.reg_write(regs.UC_ARM64_REG_X0, value & ((1 << 64) - 1))

    def request(cpu):
        state['templates'] += 1
        u.mem_write(cpu.reg_read(regs.UC_ARM64_REG_X0), bytes(state['template']))
        result(cpu)

    def finish(cpu):
        state['finish'] += 1
        result(cpu)

    def cancel(cpu):
        state['cancel'] += 1
        result(cpu)

    u.mem_write(m.work + 0x424, bytes(4))
    m.services[m.base + 0x17ffd84] = lambda cpu: result(cpu)
    m.services[m.base + 0x28bfdcc] = lambda cpu: result(cpu, m.work + 0x424)
    m.services[m.symbols['af_ap_media_finish']] = finish
    m.services[m.symbols['af_ap_media_import_request']] = request
    m.services[m.symbols['af_ap_media_cancel']] = cancel
    m.services[m.symbols['af_ap_browser_result']] = lambda cpu: result(cpu)
    m.services[m.base + 0x1bdb214] = lambda cpu: result(cpu, 0x15ec)
    if occupied:
        preset = bytearray(74)
        preset[8] = 3
        if occupied == 'lut':
            preset[1], preset[10], preset[42] = 1, 0x11, 0x22
        u.mem_write(m.work + 0x6100, bytes(preset))
        assert m.call('af_install', catalog, 7, m.work + 0x6100, 0) == 0
    models(0x15ea, 0x15e7, 0xd4)
    assert m.call('af_ap_manage_ui_open', catalog, 3, 0) == 0
    models(0x2b36, 0x15e7)
    m.call('af_ap_refresh', manager)
    models(0x1663, 0x1620, 0xd4)
    m.call('af_ap_refresh', manager)
    assert m.call('af_ap_manage_ui_state') == 3
    models(0x2b36, 0x1620)
    m.call('af_ap_refresh', manager)
    assert state['finish'] == 1 and state['templates'] == 1
    assert state['opens'][-1] == (0x2ed, 0xd4, 0x15ec)
    models(0x15f3, 0x15ec, 0xd4)
    m.call('af_ap_refresh', manager)
    assert m.call('af_ap_manage_ui_state') == 3
    return m, manager, catalog, models, state


@pytest.mark.parametrize('case', ['accepted', 'cancelled', 'changed-template', 'overwrite-cancel', 'overwrite-lut', 'queued-parent-failed'])
def test_import_template_requires_same_selection_and_explicit_target_confirmation(modules, case):
    m, manager, catalog, models, state = prepared_targets(modules, occupied='lut' if case == 'overwrite-lut' else case == 'overwrite-cancel')
    owner = m.symbols['af_ap_manager']
    before = bytes(m.u.mem_read(catalog, 6888))
    assert m.call('af_ap_targets_available', 0x15ed) == 1  # 旧六可选，但后续必须显式确认替换。
    assert m.call('af_ap_manage_take', owner, m.work + 0x6400) == -2
    m.call('af_ap_targets_action', 0x15f3)
    assert m.call('af_ap_manage_take', owner, m.work + 0x6400) == -2
    if case == 'cancelled':
        assert m.call('af_ap_targets_cancel') == 0
        models(0x2b36, 0x15e7)
        m.call('af_ap_refresh', manager)
        assert state['cancel'] == 1
    else:
        if case == 'changed-template':
            state['template'][106:109] = b'New'
        assert m.call('af_ap_targets_intent', 0x15f3) == 0
        m.call('af_ap_targets_action', 0x15f3)
        if case in ('overwrite-cancel', 'overwrite-lut'):
            assert m.call('af_ap_targets_stage') == 2
            assert m.call('af_ap_targets_result') == -24
            models(0x2b36, 0x15e7)
            m.call('af_ap_refresh', manager)
            models(0x1601, 0x15ec, 0xd4)
            m.call('af_ap_refresh', manager)
            assert m.call('af_ap_targets_stage') == 3
            assert m.call('af_ap_targets_current') == m.call('af_ap_targets_name', 0x1601)
            confirm = 0x15f3 if case == 'overwrite-lut' else 0x1601
            models(confirm, 0x15ec, 0xd4)
            assert m.call('af_ap_targets_intent', confirm) == 0
            m.call('af_ap_targets_action', confirm)
        elif case == 'changed-template':
            assert m.call('af_ap_targets_result') == -5
        if case in ('accepted', 'overwrite-lut', 'queued-parent-failed'):
            assert m.call('af_ap_targets_result') == 0
            m.call('af_ap_targets_action', 0x15f3)
            if case == 'queued-parent-failed':
                state['screen_result'] = 0x4cf
                models(0x2b36, 0x15ec)
                m.call('af_ap_refresh', manager)
                assert m.call('af_ap_manage_ui_state') == 0
                assert not state['cancel'], '已确认并排队的导入仍拥有输入，不能因父页失败清掉'
            assert m.call('af_ap_manage_take', owner, m.work + 0x6400) == 0
            raw = bytes(m.u.mem_read(m.work + 0x6400 + 8, 176))
            expected = bytearray(state['template'])
            struct.pack_into('<I', expected, 8, 7)
            struct.pack_into('<I', expected, 12, int(case == 'overwrite-lut'))
            assert raw == expected
            assert state['templates'] == 2
    if case not in ('accepted', 'overwrite-lut', 'queued-parent-failed'):
        assert m.call('af_ap_manage_take', owner, m.work + 0x6400) == -2
    assert bytes(m.u.mem_read(catalog, 6888)) == before
