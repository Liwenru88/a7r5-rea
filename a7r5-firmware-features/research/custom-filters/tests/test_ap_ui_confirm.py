"""ENTER作用域＋专有close BL授权；原ENTER资格/排队的完整窗口另有独立收据。"""
import struct

import pytest
from unicorn import arm64_const as regs

from test_ap_ui_dynamic import Machine, modules  # noqa: F401


def _confirm_owner(raw, namespace='manage'):
    m=Machine(raw);m.registered();assert m.call('af_ap_research_enable',1)==0
    u,base,work=m.u,m.base,m.work
    controller,event,continuation=work+0x4000,work+0x5000,work+0x1800
    m.map(controller,0x1000);m.map(event,0x1000)
    menu_at,group_at=work+0x400,work+0x404
    routes={'manage':(0x15e7,0x15ea,'af_ap_manage_menu'),
            'targets':(0x15ec,0x15f5,'af_ap_targets'),
            'browser':(0x1620,0x1621,'af_ap_browser')}
    group,menu,prefix=routes[namespace]
    state={'permits':dict.fromkeys(routes,0),'actions':[],'closes':[],'stock':[],
           'disabled':0,'reach_close':True,'change_menu':False,'events':[]}
    def set_result(cpu,value):cpu.reg_write(regs.UC_ARM64_REG_X0,value&((1<<64)-1))
    def models(next_group=group,next_menu=menu,table=0x58da458):
        u.mem_write(controller,struct.pack('<Q',base+table))
        u.mem_write(group_at,struct.pack('<I',next_group));u.mem_write(menu_at,struct.pack('<I',next_menu))
    models();u.mem_write(event,b'ENTER-event')
    m.services[base+0x28a8720]=lambda cpu:set_result(cpu,group_at)
    m.services[base+0x28a87e8]=lambda cpu:set_result(cpu,menu_at)
    for name,(_,_,stem) in routes.items():
        def intent(cpu,name=name):
            value=cpu.reg_read(regs.UC_ARM64_REG_X0)
            state['permits'][name]=value;state['events'].append(('intent',name,value));set_result(cpu,0)
        def action(cpu,name=name):
            value=cpu.reg_read(regs.UC_ARM64_REG_X0)
            assert state['permits'][name]==value and value
            state['permits'][name]=0;state['actions'].append((name,value));state['disabled']=1
            state['events'].append(('action',name,value))
        m.services[m.symbols[stem+'_intent']]=intent
        m.services[m.symbols[stem+'_action']]=action
    def original_close(cpu):
        assert cpu.reg_read(regs.UC_ARM64_REG_X0)==controller
        state['closes'].append(controller);state['events'].append(('original-close',))
    m.services[base+0x21edb2c]=original_close
    def stock(cpu):
        actual=(cpu.reg_read(regs.UC_ARM64_REG_X0),cpu.reg_read(regs.UC_ARM64_REG_X1))
        assert actual==(controller,event)
        state['stock'].append(actual);state['events'].append(('stock-qualification',state['disabled']))
        assert state['disabled']==0 and not any(state['permits'].values())
        if not state['reach_close']:set_result(cpu,0x73);return
        if state['change_menu']:u.mem_write(menu_at,struct.pack('<I',menu+1))
        # 此显式服务续接只执行真实af_ap_confirm_close，不伪造stock返回或重入Machine.call。
        # 原ENTER完整资格/close BL时序已另由verify_enter_close.py执行。
        return_to=cpu.reg_read(regs.UC_ARM64_REG_LR)
        u.mem_write(continuation,struct.pack('<6I2Q',
            0x580000d0,0xd63f0200,0x52800e60,0x580000b0,0xd61f0200,0xd503201f,
            m.symbols['af_ap_confirm_close'],return_to))
        cpu.reg_write(regs.UC_ARM64_REG_LR,continuation)
    m.services[m.symbols['af_stock_confirm']]=stock
    return m,controller,event,models,state,menu


@pytest.mark.parametrize('namespace',['manage','targets','browser'])
def test_enter_authorizes_only_at_qualified_close_then_clears_before_async_leave(modules,namespace):
    m,controller,event,models,state,menu=_confirm_owner(modules,namespace)
    assert m.call('af_ap_confirm',controller,event)==0x73
    assert state['stock']==[(controller,event)] and state['actions']==[(namespace,menu)]
    assert state['closes']==[controller] and state['disabled']==1
    assert not any(state['permits'].values())
    assert state['events'].index(('stock-qualification',0))<state['events'].index(('action',namespace,menu))
    assert state['events'].index(('action',namespace,menu))<state['events'].index(('original-close',))
    # 随后的通用leave/同callee调用仍完整委派，却没有本次ENTER作用域，不可再提交。
    m.call('af_ap_confirm_close',controller)
    assert state['actions']==[(namespace,menu)] and state['closes']==[controller,controller]
    assert not any(state['permits'].values())


@pytest.mark.parametrize('case',['no-qualified-close','changed-menu','foreign-controller','foreign-group','ROOT-not-row'])
def test_unqualified_or_changed_enter_scope_never_authorizes_a_write(modules,case):
    m,controller,event,models,state,menu=_confirm_owner(modules)
    if case=='no-qualified-close':state['reach_close']=False
    elif case=='changed-menu':state['change_menu']=True
    elif case=='foreign-controller':models(table=0x58da720)
    elif case=='foreign-group':models(next_group=0x1e6)
    else:models(next_menu=0x15e7)
    assert m.call('af_ap_confirm',controller,event)==0x73
    assert state['stock']==[(controller,event)] and not state['actions']
    assert not any(state['permits'].values())
    assert len(state['closes'])==(case!='no-qualified-close')
