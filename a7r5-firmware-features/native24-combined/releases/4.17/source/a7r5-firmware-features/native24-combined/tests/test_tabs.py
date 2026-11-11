"""原厂／附加分组导航；UI属性发布为夹具，应用请求执行真实隔离入口。"""
import json
import struct

import pytest

from replay import BUILD, candidate
from test_unified_look import asynchronous_machine, machine


class Tabs:
    def __init__(self, mask=0xffffff, eligibility='n12_visible', runtime=None):
        self.ap, self.state = runtime if runtime is not None else machine(candidate)
        # 原运行时vtable的visible实际经过上游available包装器，不能只测新入口。
        audit=json.loads((BUILD/'work/import/module_audit.json').read_text())
        self.ap.symbols['r5_filter_row_available']=audit['symbols']['r5_filter_row_available']
        self.state.update(mid=0x84c, mask=mask, bank_crc=0x5678, unavailable_factory=set())
        self.calls = []
        self.eligibility = eligibility
        self.manager = self.ap.DATA + 0x10000
        self.view = self.ap.DATA + 0x12000
        self.controller = self.ap.DATA + 0x20000
        self.ap.write(self.manager + 0x338, struct.pack('<Q', self.view))
        self.ap.write(self.view, struct.pack('<Q', 0x58ca670))
        self.ap.write(self.controller + 0x178, struct.pack('<I', 0xd9))
        self.ap.write(self.controller + 0x180, struct.pack('<Q', self.manager))
        self.ap.stub('n12_stock_refresh', lambda a: 0)
        self.ap.stub('n12_stock_labels', lambda a: 0)
        self.ap.stub('n12_stock_visible', lambda a: 1)
        self.ap.stub('n12_stock_available', lambda a: 1)
        self.ap.stub('n12_stock_dispatch', self.dispatch)
        self.ap.stub('r5_filter_bank_crc', lambda a: self.state['bank_crc'])
        self.ap.stub(0x1bd5a80, lambda a: 1)
        self.ap.stub(0x1bd5ab0, lambda a: a.arg(0) not in self.state['unavailable_factory'])
        self.ap.stub(0x1bd6384, lambda a: 0x335)
        self.ap.stub(0x1bd7234, self.next_original)
        self.ap.stub(0x2207480, self.move)
        self.ap.call('n12_refresh', self.manager)

    def next_original(self, a):
        direction, first, second = a.arg(0), a.arg(1), a.arg(2)
        direction = direction if direction < 0x80000000 else direction - 0x100000000
        context = a.cpu.context_save()
        rows = [m for m in list(range(0x84c, 0x85f)) + list(range(0x1610, 0x1628))
                if a.call(self.eligibility, 0, m)]
        if rows:
            index = rows.index(self.state['mid'])
            target = rows[(index + direction) % len(rows)]
            a.write(first, struct.pack('<I', target))
            a.write(second, struct.pack('<I', 0x335))
        a.cpu.context_restore(context)
        return 1

    def move(self, a):
        controller, direction = a.arg(0), a.arg(1)
        assert controller == self.controller
        context = a.cpu.context_save()
        first, second = a.DATA + 0x30000, a.DATA + 0x30004
        a.call('n12_tabs_nextrow', direction, first, second, 1)
        self.state['mid'] = a.words(first, 1)[0]
        assert a.call('n12_tabs_state', 2) == int(self.state['mid'] >= 0x1610)
        a.call('n12_preview_menu', self.state['mid'])
        a.cpu.context_restore(context)
        return 0

    def dispatch(self, a):
        event = a.arg(2)
        self.calls.append(event)
        if event in (0x2010000, 0x2010003) and 'n12_tabs_nextrow' in a.symbols:
            context = a.cpu.context_save()
            controller = a.arg(0)
            a.call(0x2207480, controller, 0xffffffff if event == 0x2010000 else 1)
            a.cpu.context_restore(context)
        return 1

    def key(self, low):
        return self.ap.call('n12_dispatch', self.controller, 0, 0x2010000 | low)

    def value(self, field):
        return self.ap.call('n12_tabs_state', field)


def test_left_restores_each_groups_last_applied_row():
    t = Tabs()
    t.state.update(mid=0x84e, native=2)
    t.key(6)
    assert t.value(2) == 1 and t.state['mid'] == 0x1610
    assert t.state['requests'] == [1] and t.state['selected'] == 1
    for key in (7, 8):
        t.key(key)
    assert t.value(2) == 1 and t.state['requests'] == [1] and t.calls == []
    t.key(3)
    assert t.state['mid'] == 0x1611 and t.state['requests'] == [1, 2]
    t.key(6)
    assert t.value(2) == 0 and t.state['mid'] == 0x84e
    assert t.state['requests'] == [1, 2, 0]
    assert [entry[:2] for entry in t.state['stock']] == [('preview_menu', 0x84e)]
    t.key(0xf)
    assert t.value(0) == 0
    t.key(6)
    assert t.state['mid'] == 0x1611 and t.state['requests'] == [1, 2, 0, 2]
    t.key(9)
    assert t.calls[-1] == 0x2010009
    t.key(0xc)
    assert t.calls[-1] == 0x201000c


@pytest.mark.parametrize('invalidated', ['slot', 'bank', 'factory'])
def test_switch_falls_back_to_first_eligible_row(invalidated):
    t = Tabs()
    t.state.update(mid=0x84e, native=2)
    t.key(6)
    t.key(3)
    if invalidated == 'factory':
        t.state['unavailable_factory'].update((0x84e, 0x84c))
    t.key(6)
    if invalidated == 'factory':
        assert t.state['mid'] == 0x84d
        return
    if invalidated == 'slot':
        t.state['mask'] = 1 << 3
    else:
        t.state['bank_crc'] += 1
    t.key(6)
    assert t.state['requests'][-1] == (4 if invalidated == 'slot' else 1)


def test_failed_highlight_does_not_replace_last_applied_custom_row():
    t = Tabs()
    t.key(6)
    t.key(3)
    t.state['fail'] = True
    t.key(3)
    assert t.state['mid'] == 0x1612 and t.state['selected'] == 2
    t.state['fail'] = False
    t.key(6)
    t.key(6)
    assert t.state['mid'] == 0x1611 and t.state['selected'] == 2


def test_synchronous_native_index_query_during_tab_publication_uses_group_index():
    """执行原索引体，覆盖属性通知在导航函数返回前同步查询的边界。"""
    t = Tabs(mask=0xfff)
    t.ap.stub('r5_native_row_insert', lambda a: 0)
    t.ap.call('n12_register', 0, 0, 0)
    descriptor = t.ap.DATA + 0x40000
    t.ap.write(descriptor + 0x54, struct.pack('<I', 43))
    t.ap.write(descriptor + 0x58, struct.pack('<Q', t.ap.symbols['n12_rows']))

    def visible(a):
        menu = a.arg(0)
        context = a.cpu.context_save()
        result = a.call('n12_visible', 0, menu)
        a.cpu.context_restore(context)
        return result

    t.ap.stub(0x1bd5a80, visible)
    observed = []

    def publishing(a):
        # 原导航发布MID后同步通知订阅者；此时还未进入刷新／labels包装器。
        context = a.cpu.context_save()
        assert a.call('n12_current') == 19
        a.cpu.context_restore(context)
        result = t.move(a)
        context = a.cpu.context_save()
        index = a.call(0x1be1084, descriptor, t.state['mid'])
        a.cpu.context_restore(context)
        observed.append(index)
        return result

    t.ap.stub(0x2207480, publishing)
    t.key(6)
    assert observed == [0], '自定义首项的同步查询必须返回组内0，不能返回混合列表19'
    assert t.state['requests'] == [1], '原导航的同步预览只能被提交一次'
    assert t.ap.call('n12_visible', 0, 0x84c) == 1, '发布窗口结束后恢复全局资格'


@pytest.mark.parametrize('stay_custom', [False, True])
def test_rapid_group_switch_keeps_last_target_until_async_completion(stay_custom):
    ap, state, _, _, finish, desired, _, _ = asynchronous_machine(candidate)
    t = Tabs(runtime=(ap, state))
    t.state.update(mid=0x84e, native=2)
    t.key(6)
    assert desired() == 1 and t.value(8) == 1
    t.key(6)
    assert t.state['mid'] == 0x84e and t.value(8) == 1
    if stay_custom:
        t.key(6)
    finish(1)
    ap.call('n12_dispatch', t.controller, 0, 0x20f0001)
    if stay_custom:
        assert t.state['mid'] == 0x1610 and desired() == 1 and t.value(8) == 1
        assert not any(row[0] == 'preview_menu' for row in state['stock'])
    else:
        assert desired() == 0 and t.value(8) == 2

        def original_refresh(a):
            context = a.cpu.context_save()
            # 原厂属性已暂回 ST。退回事务完成后，刷新应保留记住的目标。
            state['native'] = 0
            assert a.call('n12_current') == 2
            a.cpu.context_restore(context)
            return 0

        ap.stub('n12_stock_refresh', original_refresh)
        finish(0)
        ap.call('n12_dispatch', t.controller, 0, 0x20f0001)
        assert t.state['mid'] == 0x84e and t.value(8) == 2
        assert [row[1] for row in state['stock'] if row[0] == 'preview_menu'] == [0x84e]


@pytest.mark.parametrize('success', [False, True])
def test_custom_completion_after_leaving_group_only_remembers_success(success):
    ap, state, _, _, finish, desired, _, _ = asynchronous_machine(candidate)
    t = Tabs(runtime=(ap, state))
    t.key(6)
    finish(1)
    t.key(3)
    assert desired() == 2
    t.key(6)
    finish(2 if success else 1, success)
    ap.call('n12_dispatch', t.controller, 0, 0x20f0001)
    assert desired() == 0
    finish(0)
    ap.call('n12_dispatch', t.controller, 0, 0x20f0001)
    t.key(6)
    assert desired() == (2 if success else 1)


@pytest.mark.parametrize('eligibility',['n12_visible','n12_available','r5_filter_row_available'])
def test_group_projection_keeps_global_rows_and_uses_valid_custom_slots(eligibility):
    t = Tabs(mask=(1 << 3) | (1 << 23),eligibility=eligibility)
    t.key(6)
    assert t.state['mid'] == 0x1613 and t.state['requests'] == [4]
    t.key(3)
    assert t.state['mid'] == 0x1627 and t.state['requests'] == [4, 24]
    assert t.ap.call('n12_visible', 0, 0x84c) == 1
    # 全局原注册树可见性不被当前Tab隐藏，分组只在原投影／导航窗口生效。
    t.key(3)
    assert t.state['mid'] == 0x1613
    t.key(6)
    assert t.state['mid'] == 0x84c


def test_empty_custom_group_never_previews_and_left_returns_to_factory():
    t = Tabs(mask=0)
    t.key(6)
    assert t.value(2) == 1
    for key in (0, 3, 9, 0xc):
        t.key(key)
    assert t.state['requests'] == [] and t.state['stock'] == [] and t.calls == []
    t.key(6)
    assert t.value(2) == 0 and t.state['mid'] == 0x84c


def test_menu_leaves_empty_group_without_selecting():
    t = Tabs(mask=0)
    t.key(6)
    t.key(0xf)
    assert t.state['mid'] == 0x84c and t.state['requests'] == []
    assert t.value(0) == 0


@pytest.mark.parametrize('entry', ['n12_refresh', 'n12_labels'])
def test_native_refresh_and_labels_keep_projected_focus_in_the_custom_group(entry):
    t = Tabs()
    t.key(6); t.key(3)
    assert t.state['mid'] == 0x1611 and t.state['requests'] == [1, 2]
    def reproject(a):
        # 原模型保存的是组内第二行；原刷新必须使用同组资格反查MID。
        context = a.cpu.context_save()
        rows = [m for m in list(range(0x84c, 0x85f)) + list(range(0x1610, 0x1628))
                if a.call('r5_filter_row_available', 0, m)]
        t.state['mid'] = rows[1]
        a.cpu.context_restore(context)
        return 0
    t.ap.stub('n12_stock_refresh' if entry == 'n12_refresh' else 'n12_stock_labels', reproject)
    t.ap.call(entry, t.manager if entry == 'n12_refresh' else t.view)
    assert t.state['mid'] == 0x1611, '原组内索引不能在未分组表中反查为PT'
    assert t.ap.call('n12_visible', 0, 0x84c) == 1, '刷新窗口结束后恢复全局资格'


@pytest.mark.parametrize('parameter_page', [False, True])
def test_parameter_page_and_unrelated_controller_do_not_consume_tab_keys(parameter_page):
    t = Tabs()
    if parameter_page:
        t.ap.write(t.view, struct.pack('<Q', 0x58ca720))
    else:
        t.ap.write(t.controller + 0x178, struct.pack('<I', 0x2d6))
    t.key(6)
    assert t.calls == [0x2010006]


def test_parameter_center_is_forwarded_through_native_parameter_entry():
    t = Tabs()
    t.key(6)
    t.key(9)
    assert t.calls == [0x2010009]
    t.ap.write(t.view, struct.pack('<Q', 0x58ca720))
    t.ap.write(t.controller + 0x178, struct.pack('<I', 0xda))
    parameter_calls = []
    t.ap.stub('n12_stock_parameter_dispatch', lambda a: parameter_calls.append(a.arg(2)) or 1)
    handler = struct.unpack('<Q', t.ap.read(0x58da6d8, 8))[0]
    assert t.ap.call(handler, t.controller, 0, 0x201000c) == 1
    assert parameter_calls == [0x201000c] and t.calls == [0x2010009]
