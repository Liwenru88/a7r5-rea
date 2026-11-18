"""私有选择仅由CreativeLook描述符恢复；原690及原厂选择路径保持独立。"""
import struct

import pytest
from unicorn import arm64_const as regs

from test_ap_ui_dynamic import Machine, modules  # noqa: F401


def _owner(raw):
    m=Machine(raw);m.registered()
    u,base,work=m.u,m.base,m.work
    menu,mode,native,preset=work+0x400,work+0x404,work+0x408,work+0x700
    calls=[]
    def result(cpu,value):cpu.reg_write(regs.UC_ARM64_REG_X0,value)
    def getter(address):return lambda cpu:result(cpu,address)
    def value(address):return struct.unpack('<I',u.mem_read(address,4))[0]
    m.services[base+0x28a87e8]=getter(menu)
    m.services[base+0x28bfdcc]=getter(mode)
    m.services[base+0x28ae4b0]=getter(native)
    m.services[base+0x17ffd84]=lambda cpu:result(cpu,0)
    # 完整原getter及初选匹配另有original-creative-current.json原指令收据。
    m.services[base+0x1c05f18]=lambda cpu:result(cpu,value(native))
    for name,index in (('select',0),('preview',1),('preview_menu',0)):
        def stock(cpu,name=name,index=index):
            selected=cpu.reg_read(getattr(regs,'UC_ARM64_REG_X'+str(index)))
            calls.append((name,selected))
            if name=='preview_menu':selected={0x84c:0,0x852:17,0x853:18}[selected]
            u.mem_write(native,struct.pack('<I',selected))
        m.services[m.symbols['af_stock_'+name]]=stock
    payload=bytearray(74);payload[8]=3;u.mem_write(preset,bytes(payload))
    def models(selected=0x15d9,restricted=0,native_selector=None):
        u.mem_write(menu,struct.pack('<I',selected));u.mem_write(mode,struct.pack('<I',restricted))
        if native_selector is not None:u.mem_write(native,struct.pack('<I',native_selector))
    models(native_selector=0)
    assert m.call('af_ap_research_enable',1)==0
    return m,models,calls,preset,native


@pytest.mark.parametrize('slot,menu,selector',[(1,0x858,10),(7,0x15d9,19),(20,0x15e6,32)])
def test_installed_private_choice_survives_menu_exit_without_writing_native_selector(modules,slot,menu,selector):
    m,models,calls,preset,native=_owner(modules)
    catalog=m.symbols['af_ap_catalog']
    assert m.call('af_install',catalog,slot,preset,0)==0
    before=bytes(m.u.mem_read(catalog,6888))
    models(menu);m.call('af_ap_select',selector)
    models(0x2b36)  # 原Main已清当前菜单；重新进入只读descriptor current。
    assert m.call('af_ap_current')==selector
    assert bytes(m.u.mem_read(native,4))==bytes(4) and not calls
    assert bytes(m.u.mem_read(catalog,6888))==before


@pytest.mark.parametrize('operation,menu,selector',[
    ('select',0x84c,0),('preview',0x852,17),('preview_menu',0x853,18)])
def test_factory_choice_clears_private_selection_even_if_native_value_is_unchanged(modules,operation,menu,selector):
    m,models,calls,preset,native=_owner(modules)
    assert m.call('af_install',m.symbols['af_ap_catalog'],7,preset,0)==0
    models();m.call('af_ap_select',19);assert m.call('af_ap_current')==19
    models(menu)
    arguments=(m.work,selector) if operation=='preview' else (menu if operation=='preview_menu' else selector,)
    m.call('af_ap_'+operation,*arguments)
    assert calls==[(operation,menu if operation=='preview_menu' else selector)]
    assert m.call('af_ap_current')==selector


@pytest.mark.parametrize('reason',['native-change','restricted','deleted'])
def test_invalidated_private_selection_does_not_reappear_when_old_conditions_return(modules,reason):
    m,models,calls,preset,native=_owner(modules)
    catalog=m.symbols['af_ap_catalog']
    assert m.call('af_install',catalog,7,preset,0)==0
    m.call('af_ap_select',19);assert m.call('af_ap_current')==19
    if reason=='native-change':models(0x2b36,native_selector=17)
    elif reason=='restricted':models(0x2b36,restricted=1)
    else:m.call('af_catalog_init',catalog)
    assert m.call('af_ap_current')==(17 if reason=='native-change' else 0)
    models(0x2b36,native_selector=0)
    if reason=='deleted':assert m.call('af_install',catalog,7,preset,0)==0
    assert m.call('af_ap_current')==0 and not calls


def test_invalid_route_never_creates_a_private_current_and_enable_restores_owned_descriptor(modules):
    m,models,calls,preset,native=_owner(modules)
    descriptor=m.base+0x5858b08;original=m.base+0x1c05f18
    assert m.call('af_install',m.symbols['af_ap_catalog'],7,preset,0)==0
    for menu,selector,restricted in ((0x15d9,20,0),(0x15e7,19,0),(0x15e6,32,0),(0x15d9,19,1)):
        models(menu,restricted);m.call('af_ap_select',selector)
        assert m.call('af_ap_current')==0
    models();m.call('af_ap_preview_menu',0x15da)
    assert m.call('af_ap_current')==0 and not calls
    m.call('af_ap_select',19);assert m.call('af_ap_current')==19
    # 外部拥有者改current指针时，拒绝启停且不部分恢复行数/行表。
    before=bytes(m.u.mem_read(descriptor,0xa0))
    m.u.mem_write(descriptor+0x78,struct.pack('<Q',original+4))
    foreign=bytes(m.u.mem_read(descriptor,0xa0))
    assert m.call('af_ap_research_enable',0)==-5
    assert bytes(m.u.mem_read(descriptor,0xa0))==foreign
    m.u.mem_write(descriptor,before)
    assert m.call('af_ap_research_enable',0)==0
    assert struct.unpack('<Q',m.u.mem_read(descriptor+0x78,8))[0]==original
    assert m.call('af_ap_current')==0
    assert m.call('af_ap_research_enable',1)==0
    assert struct.unpack('<Q',m.u.mem_read(descriptor+0x78,8))[0]==m.symbols['af_ap_current']
    assert m.call('af_ap_current')==0
