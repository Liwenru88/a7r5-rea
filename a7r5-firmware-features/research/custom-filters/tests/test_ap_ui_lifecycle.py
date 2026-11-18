"""原确认返回后的选择器状态机；复用动态模块，不把服务边界当实际GUI。

原3b2事务、wrapper转参、真实20B排队另有continuation29-route原指令收据。
此处隔离那些原AP服务，只验证新状态机何时允许调用、失败后是否可恢复。
"""
import io
import struct

import pytest
from elftools.elf.elffile import ELFFile
from unicorn import arm64_const as regs

from test_ap_ui_dynamic import Machine, modules  # noqa: F401


def _owner(raw, scan_result=-21):
    m=Machine(raw);m.registered();assert m.call('af_ap_research_enable',1)==0
    u,base,work=m.u,m.base,m.work
    manager,source=work+0x3000,work+0x5000
    m.map(manager,0x1000);m.map(source,128);m.map(work+0x6000,0x1000)
    menu,group,metadata=work+0x400,work+0x404,work+0x408
    state={'scan':0,'read':0,'screen_result':0xd4,'opens':[],'transactions':[]}
    def result(cpu,value):cpu.reg_write(regs.UC_ARM64_REG_X0,value&((1<<64)-1))
    def getter(address):return lambda cpu:result(cpu,address)
    m.services[base+0x28a87e8]=getter(menu)
    m.services[base+0x28a8720]=getter(group)
    m.services[base+0x28a8734]=getter(metadata)
    m.services[m.symbols['af_stock_refresh']]=lambda cpu:result(cpu,0)
    def lookup(cpu):
        root=cpu.reg_read(regs.UC_ARM64_REG_X0)
        assert root in (0x15e7,0x15ec,0x1620)
        result(cpu,state['screen_result'])
    m.services[base+0x1bd5720]=lookup
    def begin(cpu):
        u.mem_write(cpu.reg_read(regs.UC_ARM64_REG_X0),bytes(16))
        state['transactions'].append('begin')
    def assign(cpu):
        change=cpu.reg_read(regs.UC_ARM64_REG_X0)
        assert struct.unpack('<QQI',u.mem_read(change,20))==(group,metadata,0x3b2)
        value=cpu.reg_read(regs.UC_ARM64_REG_X1)
        assert value in (0x15e7,0x15ec,0x1620)
        u.mem_write(group,struct.pack('<I',value));state['transactions'].append(('3b2',value))
    def notify(cpu):
        change=cpu.reg_read(regs.UC_ARM64_REG_X0)
        assert struct.unpack('<I',u.mem_read(change+0x10,4))[0]==0x3b2
        state['transactions'].append('notify3b2')
    m.services[base+0x21d62a8]=begin;m.services[base+0x21f3ed8]=assign
    m.services[base+0x21d68d8]=notify
    m.services[base+0x21d62cc]=lambda cpu:state['transactions'].append('finish')
    def enqueue(cpu):
        assert cpu.reg_read(regs.UC_ARM64_REG_X0)==manager
        values=[struct.unpack('<I',u.mem_read(cpu.reg_read(getattr(regs,'UC_ARM64_REG_X'+str(i))),4))[0] for i in (1,2)]
        assert values==[0x2ed,0xd4]
        state['opens'].append((values[0],values[1],struct.unpack('<I',u.mem_read(group,4))[0]))
        # 原wrapper只排队，故明确不在此服务里模拟apply或改physical DS。
    m.services[base+0x1cdbb08]=enqueue
    def models(current_menu,current_group,physical=0x2ed,valid_manager=True):
        u.mem_write(menu,struct.pack('<I',current_menu));u.mem_write(group,struct.pack('<I',current_group))
        u.mem_write(manager,struct.pack('<Q',base+0x58d2fb8 if valid_manager else 0))
        u.mem_write(manager+0x3b8,struct.pack('<I',physical))
    # 浏览/目标模块保留真实bind/register/publish/begin；注册器是明确的空树服务。
    # 这里不复证原C++树，其原执行收据已独立保留。
    additional={0x28a87fc:0xf002b2a0,0x28a88ac:0xf002b2a0,0x28a88c0:0xf002b2a0,
                0x21edb44:0xa9be7bfd,0x21edb68:0xa9be7bfd,0x21f4130:0xa9bd7bfd,
                0x21f0864:0x39405001,0x21f0830:0x39405001,
                0x1bdb214:0xa9be7bfd,0x1bd6384:0xa9be7bfd}
    for offset,word in additional.items():m.map(base+offset,4);u.mem_write(base+offset,struct.pack('<I',word))
    for index,offset in enumerate((0x5915b80,0x59611f8,0x593fbd8,0x59430d0)):
        m.map(base+offset,8);u.mem_write(base+offset,struct.pack('<Q',work+0x1000+index*0x40))
    for offset in (0x1c91e94,0x1c91c40,0x1c935e0,0x1c938a8):m.services[base+offset]=lambda cpu:result(cpu,0)
    m.services[base+0x1bd906c]=lambda cpu:result(cpu,0)
    for address,size in ((0x5845f28,192),(0x3f52680,128),(0x3fe4a00,128)):m.map(base+address,size)
    u.mem_write(base+0x5845f28+0x20,struct.pack('<I',0xd4))
    u.mem_write(base+0x5845f28+0x54,struct.pack('<IQ',8,base+0x3f52680))
    catalog=m.symbols['af_ap_catalog'];binding=work+0x700
    u.mem_write(binding,struct.pack('<IIQ',1,16,base));assert m.call('af_ap_browser_bind',binding)==0
    assert m.call('af_ap_browser_register')==0 and m.call('af_ap_browser_enable',1)==0
    u.mem_write(binding,struct.pack('<IIQQQQ',2,40,base,catalog,catalog,m.symbols['af_ap_manage_ui_chosen']))
    assert m.call('af_ap_targets_bind',binding)==0
    assert m.call('af_ap_targets_register')==0 and m.call('af_ap_targets_enable',1)==0
    def scan(cpu):
        state['scan']+=1
        assert cpu.reg_read(regs.UC_ARM64_REG_X0)==7
        if not scan_result:
            generation=cpu.reg_read(regs.UC_ARM64_REG_X1);output=cpu.reg_read(regs.UC_ARM64_REG_X3)
            u.mem_write(output,struct.pack('<QQQI4x',generation,41,42,0))
        result(cpu,scan_result)
    def read(cpu):state['read']+=1;raise AssertionError('打开列表不得读取文件或伪造Imported')
    scan_at,read_at=work+0x1800,work+0x1808
    m.services[scan_at]=scan;m.services[read_at]=read
    u.mem_write(binding,struct.pack('<IIiIQQQQ',1,48,7,0,scan_at,read_at,source,128))
    assert m.call('af_ap_media_bind',binding)==0
    state['catalog_before']=bytes(u.mem_read(catalog,6888))
    return m,manager,catalog,models,state


def test_import_waits_for_original_close_and_actual_apply_before_returning_to_management(modules):
    m,manager,catalog,models,state=_owner(modules)
    models(0x15ea,0x1e6,0xd4)
    assert m.call('af_ap_manage_ui_open',catalog,3,0)==-5
    models(0x15ea,0x15e7,0xd4)
    assert m.call('af_ap_manage_ui_open',catalog+8,3,0)==-1
    assert m.call('af_ap_manage_ui_open',catalog,3,1)==-1
    assert m.call('af_ap_manage_ui_open',catalog,3,0)==0
    assert m.call('af_ap_manage_ui_state')==1 and state['scan']==0
    # 无效manager、仍在原D4、尚未完成close的Main，均不得扫描/排新页。
    for current,physical,valid in ((0x2b36,0x2ed,False),(0x2b36,0xd4,True),(0x15ea,0x2ed,True)):
        models(current,0x15e7,physical,valid);m.call('af_ap_refresh',manager)
        assert not state['opens'] and state['scan']==0
    models(0x2b36,0x15e7)
    m.call('af_ap_refresh',manager)
    # scan明确NOT_READY：只回管理D4，不产生Import任务或耐久成功。
    assert state['scan']==1 and state['read']==0
    assert state['opens']==[(0x2ed,0xd4,0x15e7)]
    assert m.call('af_ap_manage_ui_state')==4
    for _ in range(3):m.call('af_ap_refresh',manager)
    assert len(state['opens'])==1 and state['scan']==1 and m.call('af_ap_manage_ui_state')==4
    # 仅显式模拟原manager后续apply，才允许状态机认定回管理页完成。
    models(0x15e8,0x15e7,0xd4);m.call('af_ap_refresh',manager)
    assert m.call('af_ap_manage_ui_state')==0 and len(state['opens'])==1
    assert m.call('af_ap_manage_take',m.symbols['af_ap_manager'],m.work+0x6000)==-2
    assert bytes(m.u.mem_read(catalog,6888))==state['catalog_before']


@pytest.mark.parametrize('op', [3,4], ids=['import-list','create-target'])
def test_failed_original_open_releases_picker_and_allows_a_fresh_confirmation(modules,op):
    m,manager,catalog,models,state=_owner(modules,scan_result=0)
    models(0x15e7+op,0x15e7,0xd4)
    assert m.call('af_ap_manage_ui_open',catalog,op,0)==0
    # root查询失败，原开屏未排队；已激活的选择器必须清理，不能遗留BUSY。
    state['screen_result']=0x4cf;models(0x2b36,0x15e7)
    m.call('af_ap_refresh',manager)
    assert m.call('af_ap_manage_ui_state')==0 and m.call('af_ap_manage_ui_result')==-5
    assert not state['opens']
    if op==3:assert m.call('af_ap_media_phase')!=1, '失败打开遗留BROWSING，下一次prepare会BUSY'
    else:assert m.call('af_ap_targets_disabled')==1, '失败打开遗留active目标页，下一次begin会BUSY'
    # 即使DS查询已恢复，原close期间逻辑group被别处改走也必须拒绝并清理。
    state['screen_result']=0xd4;models(0x15e7+op,0x15e7,0xd4)
    assert m.call('af_ap_manage_ui_open',catalog,op,0)==0
    models(0x2b36,0x1e6);m.call('af_ap_refresh',manager)
    assert m.call('af_ap_manage_ui_state')==0 and m.call('af_ap_manage_ui_result')==-5
    assert not state['opens']
    if op==3:assert m.call('af_ap_media_phase')!=1
    else:assert m.call('af_ap_targets_disabled')==1
    state['screen_result']=0xd4;models(0x15e7+op,0x15e7,0xd4)
    assert m.call('af_ap_manage_ui_open',catalog,op,0)==0
    models(0x2b36,0x15e7);m.call('af_ap_refresh',manager)
    expected_root=0x1620 if op==3 else 0x15ec
    assert state['opens']==[(0x2ed,0xd4,expected_root)] and m.call('af_ap_manage_ui_state')==2
    assert m.call('af_ap_manage_take',m.symbols['af_ap_manager'],m.work+0x6000)==-2
    assert bytes(m.u.mem_read(catalog,6888))==state['catalog_before']


@pytest.mark.parametrize('op',[3,4],ids=['import-cancel','create-cancel'])
def test_picker_cancel_accepts_original_main_restored_management_group_without_resubmitting(modules,op):
    m,manager,catalog,models,state=_owner(modules,scan_result=0)
    models(0x15e7+op,0x15e7,0xd4)
    assert m.call('af_ap_manage_ui_open',catalog,op,0)==0
    models(0x2b36,0x15e7);m.call('af_ap_refresh',manager)
    picker=0x1620 if op==3 else 0x15ec
    assert state['opens']==[(0x2ed,0xd4,picker)] and m.call('af_ap_manage_ui_state')==2
    models(0x1663 if op==3 else 0x1601,picker,0xd4);m.call('af_ap_refresh',manager)
    assert m.call('af_ap_manage_ui_state')==3
    # 确认门禁另有独立测试；这里从选择器已接受Cancel后的状态开始，
    # 原Main初始化会恢复原管理父组，不保证保留刚关闭的picker组。
    assert m.call('af_ap_browser_cancel' if op==3 else 'af_ap_targets_cancel')==0
    models(0x2b36,0x15e7);m.call('af_ap_refresh',manager)
    assert m.call('af_ap_manage_ui_state')==4 and m.call('af_ap_manage_ui_result')==0
    assert state['opens']==[(0x2ed,0xd4,picker),(0x2ed,0xd4,0x15e7)]
    for _ in range(3):m.call('af_ap_refresh',manager)
    assert len(state['opens'])==2 and m.call('af_ap_manage_ui_state')==4
    models(0x15e8,0x15e7,0xd4);m.call('af_ap_refresh',manager)
    assert m.call('af_ap_manage_ui_state')==0
    assert m.call('af_ap_manage_take',m.symbols['af_ap_manager'],m.work+0x6000)==-2
    assert state['read']==0 and state['scan']==(op==3)
    assert bytes(m.u.mem_read(catalog,6888))==state['catalog_before']


@pytest.mark.parametrize('accepted',[True,False],ids=['new-save-queued','save-rejected'])
def test_save_returns_to_management_only_after_new_job_and_original_close(modules,accepted):
    m,manager,catalog,models,state=_owner(modules)
    u,base,work=m.u,m.base,m.work
    owner=m.symbols['af_ap_manager']
    size=next(symbol['st_size'] for symbol in ELFFile(io.BytesIO(modules)).get_section_by_name('.symtab').iter_symbols()
              if symbol.name=='af_ap_manager')
    initial=bytes(u.mem_read(owner,size))
    # 使用真实submit产生的QUEUED快照作为显式动作服务返回值。
    # 本测试验证UI生命周期，不以该内存快照冒充后端耐久回执或Saved。
    preset,request=work+0x6100,work+0x6200
    value=bytearray(74);value[8]=3;u.mem_write(preset,bytes(value))
    assert m.call('af_install',catalog,7,preset,0)==0
    u.mem_write(request,struct.pack('<IIII',1,7,7,0)+bytes(240))
    assert m.call('af_ap_manage_submit',owner,catalog,request)==0
    queued=bytes(u.mem_read(owner,size));u.mem_write(owner,initial)
    controller,event,continuation=work+0x8000,work+0x9000,work+0x1a00
    m.map(controller,0x2000);u.mem_write(controller,struct.pack('<Q',base+0x58da458))
    def result(cpu,value):cpu.reg_write(regs.UC_ARM64_REG_X0,value&((1<<64)-1))
    actions=[]
    def action(cpu):
        assert cpu.reg_read(regs.UC_ARM64_REG_X0)==0x15e8
        actions.append('save')
        if accepted:u.mem_write(owner,queued)
    m.services[m.symbols['af_ap_manage_menu_intent']]=lambda cpu:result(cpu,0)
    m.services[m.symbols['af_ap_manage_menu_action']]=action
    m.services[base+0x21edb2c]=lambda cpu:None
    def stock(cpu):
        assert (cpu.reg_read(regs.UC_ARM64_REG_X0),cpu.reg_read(regs.UC_ARM64_REG_X1))==(controller,event)
        return_to=cpu.reg_read(regs.UC_ARM64_REG_LR)
        u.mem_write(continuation,struct.pack('<6I2Q',
            0x580000d0,0xd63f0200,0x52800020,0x580000b0,0xd61f0200,0xd503201f,
            m.symbols['af_ap_confirm_close'],return_to))
        cpu.reg_write(regs.UC_ARM64_REG_LR,continuation)
    m.services[m.symbols['af_stock_confirm']]=stock
    models(0x15e8,0x15e7,0xd4)
    assert m.call('af_ap_confirm',controller,event)==1 and actions==['save']
    assert m.call('af_ap_manage_ui_state')==int(accepted)
    m.call('af_ap_refresh',manager);assert not state['opens']
    models(0x2b36,0x15e7);m.call('af_ap_refresh',manager)
    assert state['opens']==([(0x2ed,0xd4,0x15e7)] if accepted else [])
    assert m.call('af_ap_manage_ui_state')==(4 if accepted else 0)
    for _ in range(3):m.call('af_ap_refresh',manager)
    assert len(state['opens'])==int(accepted)
    models(0x15e8,0x15e7,0xd4);m.call('af_ap_refresh',manager)
    assert m.call('af_ap_manage_ui_state')==0
    assert bytes(u.mem_read(owner,size))==(queued if accepted else initial)
    assert state['scan']==state['read']==0
