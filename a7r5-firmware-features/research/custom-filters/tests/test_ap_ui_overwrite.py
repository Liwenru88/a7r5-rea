"""原关闭后覆盖页的最小集成；原开屏/按键另由原窗口和完整Qt验收。"""
import struct
import pytest
from test_ap_ui_lifecycle import _owner
from test_ap_ui_dynamic import modules  # noqa: F401
from unicorn import arm64_const as regs


def _confirmation(raw):
    m,manager,catalog,models,state=_owner(raw)
    u,work=m.u,m.work
    # 本集成只替换原parent/locale服务；其原指令执行另有注册窗口证据。
    m.services[m.base+0x1bdb214]=lambda cpu:cpu.reg_write(regs.UC_ARM64_REG_X0,0x15ec)
    u.mem_write(work+0x420,bytes(4))
    m.services[m.base+0x28b0464]=lambda cpu:cpu.reg_write(regs.UC_ARM64_REG_X0,work+0x420)
    for slot,base,contrast in [(7,0,1),(20,1,-2)]:
        p=bytearray(74);p[0]=base;p[2]=contrast&255;p[8]=3
        u.mem_write(work+0x6100,bytes(p));assert m.call('af_install',catalog,slot,work+0x6100,0)==0
    state['catalog_before']=bytes(u.mem_read(catalog,6888))
    models(0x15e9,0x15e7,0xd4);assert m.call('af_ap_manage_ui_open',catalog,2,7)==0
    models(0x2b36,0x15e7);m.call('af_ap_refresh',manager)
    models(0x1600,0x15ec,0xd4);m.call('af_ap_refresh',manager)
    assert m.call('af_ap_manage_ui_state')==3
    assert m.call('af_ap_targets_intent',0x1600)==0;m.call('af_ap_targets_action',0x1600)
    assert m.call('af_ap_targets_result')==-24 and m.call('af_ap_targets_stage')==2
    assert m.call('af_ap_manage_take',m.symbols['af_ap_manager'],work+0x6000)==-2
    assert bytes(u.mem_read(catalog,6888))==state['catalog_before']
    # 第一次关闭／实际重开尚未发生时，即使重复ENTER也不能覆盖。
    assert m.call('af_ap_targets_intent',0x1600)==-4
    for _ in range(2):m.call('af_ap_refresh',manager)
    assert len(state['opens'])==1 and m.call('af_ap_targets_stage')==2
    models(0x2b36,0x15e7);m.call('af_ap_refresh',manager)
    assert len(state['opens'])==2 and m.call('af_ap_manage_ui_state')==2
    for _ in range(2):m.call('af_ap_refresh',manager)
    assert len(state['opens'])==2 and m.call('af_ap_targets_stage')==2
    # 原D4初始化已实际选中默认Cancel，才使二次确认READY。
    models(0x1601,0x15ec,0xd4);m.call('af_ap_refresh',manager)
    assert m.call('af_ap_manage_ui_state')==3 and m.call('af_ap_targets_stage')==3
    assert m.call('af_ap_targets_result')==-2
    return m,manager,catalog,models,state


@pytest.mark.parametrize('outcome',['confirm','menu-cancel','source-change','target-change'])
def test_overwrite_requires_second_ready_confirmation_and_preserves_snapshots(modules,outcome):
    m,manager,catalog,models,state=_confirmation(modules)
    owner=m.symbols['af_ap_manager'];u,work=m.u,m.work
    if outcome=='menu-cancel':
        # 不直接调用cancel：真实MENU回Main后的UI分支负责取消，并报告已取消。
        models(0x2b36,0x15e7);m.call('af_ap_refresh',manager)
        assert m.call('af_ap_targets_result')==-23 and m.call('af_ap_manage_ui_state')==4
    else:
        if outcome.endswith('change'):
            assert m.call('af_edit',catalog,7 if outcome=='source-change' else 20,0,4)==0
        before=bytes(u.mem_read(catalog,6888));models(0x1600,0x15ec,0xd4)
        assert m.call('af_ap_targets_intent',0x1600)==0;m.call('af_ap_targets_action',0x1600)
        assert bytes(u.mem_read(catalog,6888))==before
        if outcome=='confirm':
            assert m.call('af_ap_targets_result')==0
            job=work+0x6000;assert m.call('af_ap_manage_take',owner,job)==0
            ticket,op,source,target,overwrite=struct.unpack('<Q4I',u.mem_read(job,24))
            assert (ticket,op,source,target,overwrite)==(1,2,7,20,1)
            # 选择包／队列不代表持久化或Saved；此处尚未运行后端。
            return
        assert m.call('af_ap_targets_result')==-5
    assert m.call('af_ap_manage_take',owner,work+0x6000)==-2
    assert len(state['opens'])==(3 if outcome=='menu-cancel' else 2)
    assert state['scan']==state['read']==0


def _snapshot(u,catalog,slot):
    raw=bytes(u.mem_read(catalog+(slot-1)*344,344))
    revision=struct.unpack_from('<Q',raw,224)[0]
    return struct.pack('<QII',revision,raw[336],0)+raw[:222]+bytes(2)


def test_chosen_v2_rejects_legacy_packet_and_rechecks_whole_source_working_snapshot(modules):
    m,manager,catalog,models,state=_confirmation(modules)
    u,work=m.u,m.work;output=work+0x6000
    for generation in (1,2):
        u.mem_write(output,struct.pack('<Q4I',generation,2,7,20,0))
        assert m.call('af_ap_manage_ui_chosen',catalog,output)==-1
    packet=struct.pack('<IIQ4I',2,512,1,2,7,20,1)+_snapshot(u,catalog,7)+_snapshot(u,catalog,20)
    assert len(packet)==512;u.mem_write(output,packet)
    assert m.call('af_edit',catalog,7,0,4)==0
    assert m.call('af_ap_manage_ui_chosen',catalog,output)==-5
    assert m.call('af_ap_manage_take',m.symbols['af_ap_manager'],work+0x7000)==-2
