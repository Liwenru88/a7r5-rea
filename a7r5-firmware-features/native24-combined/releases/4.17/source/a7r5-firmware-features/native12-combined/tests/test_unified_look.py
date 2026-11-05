"""统一入口真实 AArch64 回放；事务服务替身与原生体边界显式区分。"""
import io
import os
from pathlib import Path
import struct
import pytest
from elftools.elf.elffile import ELFFile
import menu_font
import e4_menu_compat
import unified_look
from runtime_support import AP, BASELINE
from test_runtime_codec import codec  # noqa: F401
from test_runtime_ap_ui import names
from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as R


@pytest.fixture(scope='module')
def candidate(images,tmp_path_factory):
    if os.environ.get('A7R5_UNIFIED_TEST_ORIGINAL')=='1':
        # 仅回放冻结的修复前研究组件，不改变正式构建来源或校验门禁。
        old=unified_look.HERE/'verification/2026-11-02-unified-creative-look'
        raw=(old/'components/appFw.so').read_bytes()
        assert unified_look.sha(raw)=='5cd0f22949fc8134c59855ca91a5225722638bf9098fe3e1c74b61fdad603c43'
        import json
        receipt=json.loads((old/'build/unified-look-patch.json').read_text())
        return raw,receipt,None
    out=tmp_path_factory.mktemp('unified')
    font,_=menu_font.build(images[2],out/'font')
    event,_=e4_menu_compat.build(font.read_bytes(),out/'event')
    path,receipt=unified_look.build(event.read_bytes(),out/'unified',BASELINE/'work/import/module_audit.json')
    return path.read_bytes(),receipt,event.read_bytes()


def machine(candidate):
    raw,receipt,_=candidate;ap=AP(raw);ap.symbols.update(receipt['symbols'])
    state={'mid':0x1610,'mode':0,'mask':4095,'selected':0,'seq':0,'command':2,'fail':False,'native':0,'requests':[],'stock':[]}
    mid,mode=ap.DATA,ap.DATA+8
    def current(a):a.write(mid,struct.pack('<I',state['mid']));return mid
    def layout(a):a.write(mode,struct.pack('<I',state['mode']));return mode
    ap.stub(0x28a87e8,current);ap.stub(0x17ffd84,lambda a:0);ap.stub(0x28bfdcc,layout)
    ap.stub(0x1c05f18,lambda a:state['native'])
    ap.stub('r5_filter_selected',lambda a:state['selected'])
    ap.stub('r5_filter_available_mask',lambda a:state['mask'])
    ap.stub('r5_filter_pending',lambda a:0)
    ap.stub('r5_filter_command_state',lambda a:state['command'])
    ap.stub('r5_filter_command_sequence',lambda a:state['seq'])
    def request(a):
        n=a.arg(0);state['seq']+=1;state['requests'].append(n)
        state['command']=3 if state['fail'] else 2
        if not state['fail']:state['selected']=n
        return 0
    ap.stub('r5_filter_request',request)
    for name in ('select','preview','preview_menu'):
        ap.stub('n12_stock_'+name,lambda a,n=name:state['stock'].append((n,a.arg(0),a.arg(1))) or 0)
    return ap,state


def test_build_inverse_layout_registry_and_fn(candidate):
    raw,receipt,source=candidate
    reverse=bytearray(raw[:len(source)])
    for p in reversed(receipt['patches']):
        before=bytes.fromhex(p['before']);reverse[p['offset']:p['offset']+len(before)]=before
    assert bytes(reverse)==source and receipt['inverse_exact']
    elf=ELFFile(io.BytesIO(raw));loads=[s for s in elf.iter_segments() if s['p_type']=='PT_LOAD']
    assert elf['e_phnum']==10 and [s['p_flags'] for s in loads[-2:]]==[5,6]
    ap,state=machine(candidate);insert=[]
    ap.stub('r5_native_menu_insert',lambda a:insert.append(('menus',a.arg(1),a.arg(2))) or 0)
    ap.stub('r5_native_row_insert',lambda a:insert.append(('rows',a.arg(1),a.arg(2))) or 0)
    ap.call('r5_filter_menu_register',0,10,20);ap.call('r5_filter_rows_register',0,30,40)
    assert insert[:2]==[('menus',10,20),('rows',30,40)] and len(insert)==3
    assert insert[2][2]-insert[2][1]==12*16
    assert ap.words(unified_look.DESC+0x54,1)==(31,)
    rows=receipt['symbols']['n12_rows']
    assert ap.read(rows,19*128)==ap.read(0x3f4a280,19*128)
    assert [ap.words(rows+(19+i)*128,1)[0] for i in range(12)]==list(range(0x1610,0x161c))
    assert [ap.words(rows+(19+i)*128+0x34,1)[0] for i in range(12)]==list(range(19,31))
    assert ap.words(0x3e6f220,1)==(6,) and ap.read(0x3e6f3a4,64)==bytes(64)
    group=unified_look.GROUP
    assert ap.words(group+8,1)==(7,)
    assert [struct.unpack('<Q',ap.read(group+16+i*24,8))[0] for i in range(7)]==[0x1f1,0x1f2,0x1f3,0x1f4,0x1f5,0x1f6,0x1f9]
    assert ap.call('r5_filter_menu_normalize',0,0x635)==0x1f2


def test_rejects_unknown_complete_preimage_before_creating_output(candidate,tmp_path):
    with pytest.raises(ValueError,match='完整前像'):
        unified_look.build(candidate[2][:-1],tmp_path/'bad')
    assert not (tmp_path/'bad').exists()


@pytest.mark.parametrize('check',[
    'test_fl23_selection_ignores_old_saved_base_and_keeps_native_routes',
    'test_ntsc_branches_execute_to_original_continuations',
    'test_marker_registration_executes_original_range_validator',
    'test_sound_selector_keeps_non_type1_inhibit_and_callee_state',
])
def test_existing_local_behavior_on_actual_new_ap(candidate,images,check):
    import test_integration
    # 复用现有可执行判定，但 AP 必须是本轮新候选；CP 按原摘要保持。
    revised=(*images[:2],candidate[0],*images[3:])
    getattr(test_integration,check)(revised)


def test_rows_and_anchor_execute_at_nonzero_loader_base(candidate):
    raw,receipt,_=candidate;base=0x10000000;ap=AP(raw)
    ap.cpu.mem_map(base,0x9200000)
    elf=ELFFile(io.BytesIO(raw))
    for segment in elf.iter_segments():
        if segment['p_type']=='PT_LOAD':ap.write(base+segment['p_vaddr'],segment.data())
    for at,info,addend in struct.iter_unpack('<QQq',elf.get_section_by_name('.rela.dyn').data()):
        if info==1027:ap.write(base+at,struct.pack('<Q',base+addend))
    ap.symbols.update(receipt['symbols']);ap.symbols={k:v+base for k,v in ap.symbols.items()}
    inserted=[]
    ap.stub('r5_native_row_insert',lambda a:inserted.append((a.arg(1),a.arg(2))) or 0)
    ap.call('n12_register',0,30,40)
    rows=ap.symbols['n12_rows']
    assert ap.read(rows,19*128)==ap.read(base+0x3f4a280,19*128)
    assert inserted[0]==(30,40) and inserted[1][1]-inserted[1][0]==12*16
    assert struct.unpack('<Q',ap.read(base+unified_look.DESC+0x58,8))[0]==rows


def test_custom_commit_preview_exit_and_failed_exit_do_not_delegate_virtual_value(candidate):
    ap,state=machine(candidate)
    for n in range(1,13):
        state['mid']=0x160f+n
        ap.call(0x1c956c8,state['mid'])
        ap.call(0x1c6f208,18+n)
        ap.call(0x25966cc,0x123,18+n)
        assert state['selected']==n and ap.call('n12_current')==18+n
    assert state['requests']==list(range(1,13)) and state['stock']==[]
    state['mid']=0x84c;state['fail']=True
    ap.call(0x1c6f208,0)
    assert state['selected']==12 and not state['stock'] and ap.call('n12_current')==30
    state['fail']=False
    # 换到另一款后再回原厂，才重试已经失败的退出事务。
    state['mid']=0x1610;ap.call(0x1c6f208,19);state['mid']=0x852
    ap.call(0x1c6f208,17)
    assert state['selected']==0 and [v[:2] for v in state['stock']]==[('select',17)]
    assert ap.call('n12_current')==0
    before=list(state['stock']);ap.call(0x1c6f208,0xffffffff)
    assert state['stock']==before


def test_invalid_context_and_failed_apply_remain_previous_applied(candidate):
    ap,state=machine(candidate);state.update(selected=6,fail=True,mid=0x1616)
    ap.call(0x1c956c8,0x1616)
    assert state['selected']==6 and ap.call('n12_current')==24 and state['requests']==[7]
    ap.call(0x1c956c8,0x1616)
    assert state['requests']==[7]
    state.update(fail=False,mode=1)
    ap.call(0x1c6f208,25)
    assert state['requests']==[7] and not state['stock']
    state.update(mode=0,mid=0x84c)
    ap.call(0x1c6f208,25)
    assert state['requests']==[7] and not state['stock']


def test_names_are_production_bin_names_and_absent_bank_keeps_native_route(candidate,codec):
    ap,state=machine(candidate);names(ap,codec,4095)
    expected=['AS','CC','EBB','ET','NC','NH','PV','RA','VN','正片','负片','Portra400']
    for i,name in enumerate(expected):
        resource=ap.call(0x1bd1b88,0,0x1610+i)
        pointer=ap.call('r5_filter_menu_text',resource)
        assert resource==0x02ff4301+i and ap.string(pointer)==name
    state.update(mask=0,mid=0x1610)
    ap.call(0x1c956c8,0x1610)
    assert state['requests']==[] and state['stock']==[]
    state['mid']=0x84c;ap.call(0x1c6f208,0)
    assert [v[:2] for v in state['stock']]==[('select',0)]


def test_full_title_reports_application_state_and_all_custom_icons_use_new_resources(candidate,codec):
    ap,state=machine(candidate);names(ap,codec,4095)
    title=ap.call('n12_title_name',0x1610)
    assert ap.string(ap.call('r5_filter_menu_text',title))=='[未应用] ASTIA'
    # 无归属的后台事务不能给当前项目套上应用中／失败标签。
    for command,selected,prefix in ((1,0,'[未应用] '),(3,0,'[未应用] '),(2,1,'')):
        state.update(command=command,selected=selected)
        title=ap.call('n12_title_name',0x1610)
        assert ap.string(ap.call('r5_filter_menu_text',title))==prefix+'ASTIA'
    for menu in range(0x1610,0x161c):
        for i,address in enumerate((0x1bd18e8,0x1bd19e8)):assert ap.call(address,0,menu)==0x02001ea4+2*(menu-0x1610)+i


def test_late_worker_failure_cannot_be_resubmitted_by_value_refresh(candidate):
    ap,state=machine(candidate)
    def pending(a):
        state['requests'].append(a.arg(0));state['seq']+=1;state['command']=1;return 0
    ap.stub('r5_filter_request',pending);ap.stub('usleep',lambda a:0)
    ap.call(0x1c956c8,0x1610)
    assert state['requests']==[1] and state['selected']==0
    state['command']=3
    ap.call(0x1c956c8,0x1610);ap.call(0x1c6f208,19)
    assert state['requests']==[1] and state['selected']==0


def asynchronous_machine(candidate):
    """使用真实提交器／忙态／序列；只有worker终态和原UI服务是显式夹具。"""
    from test_runtime_ap_ui import local
    ap,state=machine(candidate)
    for name in ('r5_filter_request','r5_filter_pending','r5_filter_command_state','r5_filter_command_sequence','r5_filter_selected'):
        ap.stubs.pop(ap.symbols[name])
    with (BASELINE/'work/import/objects/r5_filter_runtime423.o').open('rb') as f:
        obj=ELFFile(f)
        fields={s.name:local(ap,'r5_filter_runtime423',obj.get_section(s['st_shndx']).name)+s['st_value']
                for s in obj.get_section_by_name('.symtab').iter_symbols()
                if s.name in ('applied','command_state','desired','handled','dirty')}
    manager,view,controller=[ap.DATA+n for n in (0x10000,0x20000,0x30000)]
    ap.write(manager+0x338,struct.pack('<Q',view));ap.write(view,struct.pack('<Q',0x58ca670))
    ap.write(controller+0x178,struct.pack('<I',0xd9));ap.write(controller+0x180,struct.pack('<Q',manager))
    ap.stub('n12_stock_refresh',lambda a:0);ap.stub('n12_stock_labels',lambda a:0)
    ap.stub('n12_stock_inhibited',lambda a:0)
    ap.stub('n12_stock_dispatch' if 'n12_stock_dispatch' in ap.symbols else 0x1a6d8cc,
            lambda a:state['stock'].append(('dispatch',a.arg(2))) or 17)
    state['sleeps']=0
    def sleep(a):state['sleeps']+=1;return 0
    ap.stub('usleep',sleep)
    ap.call('r5_filter_bank_ready',0x1234,0x5678,4095)
    def finish(selected,success=True):
        # CPU测试内放置终态，不代表CP/E4/文件链成功；保留真实提交序列。
        ap.write(fields['applied'],struct.pack('<I',selected))
        ap.write(fields['command_state'],struct.pack('<I',2 if success else 3))
        if success:
            ap.write(fields['handled'],ap.read(fields['desired'],8));ap.write(fields['dirty'],bytes(4))
        else:
            # 与原worker失败一致：desired回到旧应用值，handled／dirty不假装完成。
            serial=struct.unpack('<Q',ap.read(fields['desired'],8))[0]&0xffffffff00000000
            ap.write(fields['desired'],struct.pack('<Q',serial|selected))
    def choose(slot):
        state['mid']=0x160f+slot;ap.call(0x1c956c8,state['mid'])
    def poll():ap.call(0x1e97a24,manager)
    def desired():return struct.unpack('<Q',ap.read(fields['desired'],8))[0]&0xffffffff
    return ap,state,choose,poll,finish,desired,controller,view


@pytest.mark.parametrize('last',[1,3])
def test_rapid_latest_target_coalesces_without_busy_failure_or_UI_sleep(candidate,codec,last):
    ap,state,choose,poll,finish,desired,_,_=asynchronous_machine(candidate)
    names(ap,codec,4095)
    choose(1);choose(2);choose(3);choose(last)
    assert ap.words(ap.symbols['n12_last_status'],1)[0]!=3, '忙态被误记为失败'
    assert state['sleeps']==0, 'UI仍同步等待后台事务'
    assert ap.call('r5_filter_command_sequence')==1 and desired()==1
    title=ap.call('n12_title_name',state['mid'])
    assert ap.string(ap.call('r5_filter_menu_text',title))==(
        '[应用中] ASTIA' if last==1 else '[等待应用] ETERNA BLEACH BYPASS')
    assert ap.call('n12_current')==18+last and ap.call('r5_filter_selected')==0
    finish(1);poll()
    assert ap.call('r5_filter_command_sequence')==(1 if last==1 else 2)
    assert desired()==last
    if last==3:finish(3);poll()
    assert (ap.call('n12_title_name',state['mid'])-0x02ff4601)//16==0


def test_owned_failure_does_not_retry_same_row_or_poison_new_queued_target(candidate):
    ap,state,choose,poll,finish,desired,_,_=asynchronous_machine(candidate)
    choose(1);finish(0,False);poll();choose(1)
    assert ap.call('r5_filter_command_sequence')==1
    assert (ap.call('n12_title_name',0x1610)-0x02ff4601)//16==3
    choose(2);choose(3);finish(0,False);poll()
    assert ap.call('r5_filter_command_sequence')==3 and desired()==3
    finish(3);poll()
    assert (ap.call('n12_title_name',0x1612)-0x02ff4601)//16==0


def test_native_latest_target_waits_for_exit_before_delegating_current_menu(candidate):
    ap,state,choose,poll,finish,desired,_,_=asynchronous_machine(candidate)
    choose(1)
    state['mid']=0x852;ap.call(0x1c6f208,17)
    state['mid']=0x853;ap.call(0x1c6f208,18)
    assert not state['stock'] and desired()==1
    assert ap.call(0x2209580,0)==1
    finish(1);poll()
    assert desired()==0 and ap.call('r5_filter_command_sequence')==2 and not state['stock']
    finish(0);poll()
    assert [row[:2] for row in state['stock']]==[('preview_menu',0x853)]


@pytest.mark.parametrize('use_menu',[True,False])
def test_menu_cancels_unsubmitted_target_and_enter_waits_without_retaining_context(candidate,use_menu):
    ap,state,choose,poll,finish,desired,controller,view=asynchronous_machine(candidate)
    choose(1);choose(3)
    assert ap.call(0x1a6d8cc,controller,0,0x201000c)==1 and not state['stock']
    if use_menu:assert ap.call(0x1a6d8cc,controller,0,0x201000f)==17
    state['mid']=0x1f2;ap.write(view,struct.pack('<Q',0x58ca6c8));finish(1);poll()
    state['mid']=0x1612;ap.write(view,struct.pack('<Q',0x58ca670));poll()
    assert ap.call('r5_filter_command_sequence')==1 and desired()==1
    choose(3);finish(3);poll()
    assert ap.call(0x1a6d8cc,controller,0,0x201000c)==17


def test_busy_at_submit_boundary_keeps_last_target_instead_of_failure(candidate):
    ap,state,choose,poll,finish,desired,_,_=asynchronous_machine(candidate)
    def claimed_elsewhere(a):
        a.stubs.pop(a.symbols['r5_filter_request'])
        a.pending.append(('r5_filter_request',(0,)))
        return (1<<64)-1
    ap.stub('r5_filter_request',claimed_elsewhere)
    choose(3)
    assert ap.words(ap.symbols['n12_last_status'],1)==(4,)
    assert ap.call('r5_filter_command_sequence')==1 and desired()==0
    finish(0);poll()
    assert ap.call('r5_filter_command_sequence')==2 and desired()==3


def test_foreign_sequence_cannot_complete_current_target_and_invalid_bank_is_not_submitted(candidate):
    ap,state,choose,poll,finish,desired,_,_=asynchronous_machine(candidate)
    choose(1);finish(1)
    assert ap.call('r5_filter_request',7)==0
    choose(3);poll()
    assert (ap.call('n12_title_name',0x1612)-0x02ff4601)//16==4
    assert ap.call('r5_filter_command_sequence')==2 and desired()==7
    finish(7);poll()
    assert ap.call('r5_filter_command_sequence')==3 and desired()==3
    choose(4);state['mask']=4;finish(3);poll()
    assert ap.call('r5_filter_command_sequence')==3 and ap.call('r5_filter_selected')==3
    assert (ap.call('n12_title_name',0x1613)-0x02ff4601)//16==3


def test_nonbusy_rejection_is_owned_failure_and_other_D9_events_still_delegate(candidate):
    ap,state,choose,poll,_,_,controller,_=asynchronous_machine(candidate)
    attempts=[]
    ap.stub('r5_filter_request',lambda a:attempts.append(a.arg(0)) or (1<<64)-1)
    choose(1);poll();choose(1)
    assert attempts==[1] and (ap.call('n12_title_name',0x1610)-0x02ff4601)//16==3
    state['mid']=0x999
    assert ap.call(0x1a6d8cc,controller,0,0x201000c)==17
    state['mid']=0x1610
    assert ap.call(0x1a6d8cc,controller,0,0x20f0000)==17
    ap.write(controller+0x180,bytes(8))
    assert ap.call(0x1a6d8cc,controller,0,0x201000c)==17


def test_original_refresh_is_requested_only_for_current_creative_presenter_until_consumed(candidate):
    ap,state=machine(candidate);manager,view=ap.DATA+0x10000,ap.DATA+0x20000
    ap.write(manager+0x338,struct.pack('<Q',view));ap.write(view,struct.pack('<Q',0x58ca670))
    ap.stub('n12_stock_refresh',lambda a:0);ap.stub('n12_stock_labels',lambda a:0)
    assert ap.call(0x1e97a24,manager)==1
    ap.call(0x2208e34,view);assert ap.call(0x1e97a24,manager)==0
    state['command']=3
    assert ap.call(0x1e97a24,manager)==1
    ap.call(0x2208e34,view);assert ap.call(0x1e97a24,manager)==0
    state.update(command=2,selected=1)
    assert ap.call(0x1e97a24,manager)==1
    ap.write(view,struct.pack('<Q',0x58ca6c8));assert ap.call(0x1e97a24,manager)==0
    state['mid']=0x84c;ap.write(view,struct.pack('<Q',0x58ca670))
    assert ap.call(0x1e97a24,manager)==0


def test_status_only_refresh_preserves_list_but_mask_change_rebuilds_it(candidate):
    ap,state=machine(candidate);manager,view,mapping,listing=[ap.DATA+n for n in (0x10000,0x20000,0x30000,0x40000)]
    ap.write(manager+0x338,struct.pack('<Q',view));ap.write(view,struct.pack('<Q',0x58ca670))
    ap.write(view+0x48,struct.pack('<Q',mapping));ap.write(mapping+9*16,struct.pack('<IIQ',0x1c,0,listing))
    ap.stub('n12_stock_refresh',lambda a:0)
    def rebuild(a):
        a.write(listing+0x30,bytes(0xd28));a.write(listing+4,struct.pack('<I',123));return 0
    ap.stub('n12_stock_labels',rebuild)
    ap.call(0x2208e34,view)
    raw=bytearray((i*17)%256 for i in range(0xd28));struct.pack_into('<I',raw,0xd00,31);raw[0xd26]=1
    ap.write(listing+0x30,raw);state['command']=3
    assert ap.call(0x1e97a24,manager)==1
    ap.call(0x2208e34,view)
    assert ap.read(listing+0x30,len(raw))==raw and ap.words(listing+4,1)==(123,)
    state['mask']=4094
    assert ap.call(0x1e97a24,manager)==1
    ap.call(0x2208e34,view)
    assert ap.read(listing+0x30,len(raw))==bytes(len(raw))


def test_native_parameters_delegate_and_custom_parameters_cannot_write(candidate):
    ap,state=machine(candidate);calls=[]
    for name in ('parameter_init','base_cycle','parameter_value','parameter_disabled','parameter_default','base_available','inhibited','direct'):
        ap.stub('n12_stock_'+name,lambda a,n=name:calls.append(n) or 9)
    for i in range(8):ap.stub('n12_stock_step_'+str(i),lambda a,i=i:calls.append('step'+str(i)) or 0)
    for mid in (0x84c,0x852,0x853,0x858,0x85d):
        state['mid']=mid;before=len(calls)
        for address in (0x220a7ac,0x220ac74,0x220b620,0x220b51c,0x220b708,0x2209464,0x2209580,0x220933c):ap.call(address,ap.DATA+0x100,0)
        for i in range(8):ap.call(0x2209918+i*0x154,ap.DATA+0x100,1)
        assert len(calls)-before==16
    state['mid']=0x1610;before=len(calls)
    for address in (0x220ac74,0x220b620,0x220b51c,0x220b708,0x2209464,0x2209580,0x220933c):ap.call(address,ap.DATA+0x100,0)
    for i in range(8):ap.call(0x2209918+i*0x154,ap.DATA+0x100,1)
    assert len(calls)==before
    assert ap.call(0x220b51c,ap.DATA+0x100)==1


def test_original_registry_enumerates_and_navigates_unified_rows(candidate):
    """原注册树和行枚举执行真实代码；内存分配与页面资格明确为夹具。"""
    raw,receipt,_=candidate
    std_path=Path(os.environ.get('A7R5_NATIVE12_STD',unified_look.HERE/'verification/2026-11-02-unified-creative-look/inputs/libstdc++.so.6.0.22'))
    std_raw=std_path.read_bytes()
    assert unified_look.sha(std_raw)=='28f2d082aea5206c42ba15664f39e2eaf7febed8f6264305e7e16aa44c878389'
    ap,state=machine(candidate);elf=ELFFile(io.BytesIO(raw))
    for at,info,addend in struct.iter_unpack('<QQq',elf.get_section_by_name('.rela.dyn').data()):
        if info==1027:ap.write(at,struct.pack('<Q',addend))
    std=ELFFile(io.BytesIO(std_raw));ap.cpu.mem_map(0x10000000,0x200000)
    for s in std.iter_segments():
        if s['p_type']=='PT_LOAD':ap.write(0x10000000+s['p_vaddr'],s.data())
    library_calls={0x16d9f20:0xa6350,0x16d9c70:0xa6210,0x16da520:0xa6280,0x16dbc80:0xa6288,0x16dc870:0xa65e8}
    def library(cpu,at,size,data):
        if at in library_calls:cpu.reg_write(R.UC_ARM64_REG_PC,0x10000000+library_calls[at])
    ap.cpu.hook_add(UC_HOOK_CODE,library)
    heap=[ap.DATA+0x200000];allocations=[]
    def allocate(a):
        n=a.arg(0);assert n in (40,48) and heap[0]+n+32<ap.STOP+0x400000
        at=heap[0];heap[0]+=(n+47)&~15
        a.write(at-16,b'\xa5'*(n+32));allocations.append((at,n));return at
    ap.stub(0x16dc130,allocate)
    def initialize(at):
        ap.write(at,bytes(48));ap.write(at+0x10,struct.pack('<4Q',0,at+8,at+8,0))
    rows,aliases,parents,descriptors=ap.DATA+0x1000,ap.DATA+0x1100,ap.DATA+0x1200,ap.DATA+0x1300
    for at in (rows,aliases,parents,descriptors):initialize(at)
    ap.write(0x5915b80,struct.pack('<Q',rows))
    ap.call('r5_filter_rows_register',rows,0x5030590,0x5046300,count=10000000)
    assert struct.unpack('<Q',ap.read(rows+0x28,8))[0]==5603
    table=ap.DATA+0x10000
    def append(at,registry,data):
        ap.write(table,data);ap.call(at,registry,table,table+len(data),count=3000000)
    menus=list(range(0x84c,0x85f))+list(range(0x1610,0x161c))
    append(0x1c935e0,aliases,b''.join(struct.pack('<2I',k,k) for k in range(0x84c,0x85f)))
    ap.write(0x592f4c8,struct.pack('<Q',aliases))
    append(0x1c935e0,parents,ap.read(0x3e44de0,0x31a8))
    ap.write(0x593fbd8,struct.pack('<Q',parents))
    append(0x1c91e94,descriptors,struct.pack('<2Q',0x1f2,unified_look.DESC))
    ap.write(0x59611f8,struct.pack('<Q',descriptors))
    obj,vt=ap.DATA+0x2000,ap.DATA+0x3000
    ap.write(obj,struct.pack('<Q',vt));ap.write(0x591f9a8,struct.pack('<Q',vt-16))
    points={0x10:ap.DATA+0x9000,0x1a8:0x1bcfffc,0x790:0x1bd9f98,0x798:0x1bd9ffc,
            0x700:ap.DATA+0x9010,0x550:0x1bc7840,0x560:0x1bc785c,0x8c8:0x1bc78a4,
            0x328:ap.DATA+0x9020,0x8d0:ap.DATA+0x9030,0x210:ap.DATA+0x9040,
            0x278:0x1bca844,0x2b0:0x1bd0a34,0x2e0:0x1bcf3fc,0x258:ap.DATA+0x9050,
            0x250:ap.DATA+0x9060,0x750:0x1bd1ef8}
    for off,at in points.items():ap.write(vt+off,struct.pack('<Q',at))
    for at,result in ((0x9000,unified_look.DESC),(0x9010,1),(0x9020,0x1e6),(0x9030,0),(0x9040,1),(0x9050,0),(0x9060,0)):
        ap.stub(ap.DATA+at,lambda a,result=result:result)
    for at,result in ((0x1be12d0,1),(0x2e7d208,0),(0x2e7cee4,0)):
        ap.stub(at,lambda a,result=result:result)
    def copy(a):n=a.arg(2);assert n<=128;a.write(a.arg(0),a.read(a.arg(1),n));return a.arg(0)
    ap.stub(0x16d9770,copy)
    def clear(a):
        at,n=a.arg(0),a.arg(2)
        assert n==0x400 and ap.STACK<=at<ap.STACK+0x10000 and a.arg(1)==0
        a.write(at,bytes(n));return at
    ap.stub(0x16d95f0,clear)
    native=ap.DATA+0x9100;ap.write(native,struct.pack('<I',16));ap.stub(0x28ae4b0,lambda a:native)
    page=ap.DATA+0x9200;ap.write(page,struct.pack('<I',0x1e6));ap.stub(0x28a8720,lambda a:page)
    output=ap.DATA+0x14000
    count=ap.call(0x1bcf3fc,obj,0x1e6,output,31,count=500000)
    assert count==31 and list(ap.words(output,31))==menus
    for index,menu in enumerate(menus):
        state['mid']=menu
        for direction in (-1,1):
            try:ap.call(0x1bd7234,direction&0xffffffff,output,output+4,1,count=500000)
            except Exception as exc:
                raise AssertionError(f'menu={menu:#x} direction={direction} PC={ap.cpu.reg_read(R.UC_ARM64_REG_PC):#x} LR={ap.cpu.reg_read(R.UC_ARM64_REG_LR):#x}') from exc
            assert ap.words(output,1)==(menus[(index+direction)%len(menus)],)
    assert all(ap.read(at-16,16)==b'\xa5'*16 and ap.read(at+n,16)==b'\xa5'*16 for at,n in allocations)
