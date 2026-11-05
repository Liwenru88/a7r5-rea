"""合并AP的实际AArch64会话、菜单、Fn及私有页面；原厂UI服务显式替身。"""
import ctypes as C
import struct
import pytest
from runtime_support import AP, decoded
from test_runtime_transport import codec


def local(ap, filename, section):
    rows=[s for s in ap.audit['sections'] if s['object'].endswith('/'+filename+'.o') and s['name']==section]
    assert len(rows)==1
    return int(rows[0]['va'],16)


def test_actual_ap_session_power_epochs_reader_drain_and_cold_identity(images):
    ap=AP(images[2]);event=ap.DATA
    ap.stub('r5_stage411_dlsym',lambda a:a.DATA+0x1000)
    sleeps=[]
    ap.stub(ap.DATA+0x1000,lambda a:sleeps.append(1) or 0)
    def power(n):ap.write(event,struct.pack('<I',n));ap.call('r5_stage421_power',event)
    power(0x920143);power(0x92015a)
    ap.call('r5_session_cold')
    assert ap.call('r5_session_prepare')==1
    assert ap.call('r5_session_cold_start')==1 and ap.call('r5_session_epoch')==2
    assert ap.call('r5_session_admit')==1
    token=ap.call('r5_session_token',123)
    assert ap.call('r5_session_new_transfer')==0 and len(sleeps)==100
    assert ap.call('r5_session_admit')==0
    ap.call('r5_session_leave')
    assert ap.call('r5_session_new_transfer')==1
    assert ap.call('r5_session_token',123)!=token
    assert ap.call('r5_session_admit')==1
    power(0x920143)
    assert ap.call('r5_session_current')==0 and ap.call('r5_session_admit')==0
    power(0x92015a)
    assert ap.call('r5_session_prepare')==0
    ap.call('r5_session_leave')
    assert ap.call('r5_session_prepare')==1 and ap.call('r5_session_cold_start')==0
    assert ap.call('r5_session_epoch')==4
    assert ap.call('r5_session_prepare')==0


def names(ap,codec,mask):
    value=decoded(codec);value.mask=mask
    ap.write(ap.DATA,bytes(value))
    assert ap.call('r5_filter_names_publish',ap.DATA)==1


def test_actual_menu_registration_names_absence_parent_and_fn_preservation(images,codec):
    ap=AP(images[2]);names(ap,codec,0x805)
    insert=[]
    for function in ('r5_native_menu_insert','r5_native_row_insert'):
        ap.stub(function,lambda a:insert.append((a.arg(1),a.arg(2))) or 0)
    ap.call('r5_filter_menu_register',0,10,20)
    ap.call('r5_filter_rows_register',0,30,40)
    assert len(insert)==4 and insert[0]==(10,20) and insert[2]==(30,40)
    assert insert[1][1]-insert[1][0]==16 and insert[3][1]-insert[3][0]==13*16
    d=ap.symbols['r5_filter_menu_descriptor']
    assert ap.words(d+0x54,1)==(13,)
    assert ap.words(d+0x60,2)==(0x02002290,0x39fc)
    for n in range(13):
        assert ap.call('r5_filter_row_parent',0,0x1600+n)==0x635
        assert ap.call('r5_filter_row_available',0,0x1600+n)==int(n==0 or bool(0x805&(1<<(n-1))))
        assert ap.call('r5_filter_row_available_direct',0,0x1600+n)==int(n==0 or bool(0x805&(1<<(n-1))))
        pointer=ap.call('r5_filter_menu_text',0x02ff4300+n)
        assert bool(pointer)==(n in (0,1,3,12))
    ap.stub('r5_native_row_parent',lambda a:0x999)
    assert ap.call('r5_filter_row_parent',0,55)==0x999
    # Fn原生候选表：新增项沿用Creative Look所有20组still/movie/play标记。
    assert ap.words(0x3e6f218,3)==(21,0x0200604e,7)
    ids=[ap.words(0x3e6f224+64*i,1)[0] for i in range(7)]
    assert ids==[0x1f1,0x1f2,0x1f3,0x1f4,0x1f5,0x1f9,0x635]
    flags=ap.read(0x3e6f264+4,60)
    assert ap.read(0x3e6f3a4+4,60)==flags and all(flags[i]==0 for i in range(2,60,3))
    assert ap.call('r5_filter_menu_icon_query434',0,0x635)==0x02002290


@pytest.mark.parametrize('pool',[0x20000,0xb0000])
def test_actual_private_page_construction_navigation_retirement_and_lifecycle(images,codec,pool):
    ap=AP(images[2]);names(ap,codec,0x805)
    base=ap.DATA+0x10000;mid,manager,view,vt,mapping=base,base+0x100,base+0x1000,base+0x6000,base+0x7000
    ap.write(mid,struct.pack('<I',0x635))
    ap.stub(0x28a8720,lambda a:mid)
    ap.stub(0x28cc860,lambda a:mid)
    def construct(a):
        a.write(a.arg(0)+0x178,struct.pack('<I',a.arg(6)))
        a.write(a.arg(0)+0x180,struct.pack('<Q',a.arg(1)))
        return a.arg(0)
    ap.stub(0x1d2e2f0,construct)
    controller=ap.call('r5_filter_controller425',0,manager,0,0,0,0)
    assert controller
    assert ap.call('r5_filter_controller425',0,manager,0,0,0,0)==0
    ap.write(view,struct.pack('<Q',vt));ap.write(view+0x3ea0,struct.pack('<I',pool))
    for offset in (0x10,0x18,0x20,0x50,0x60):
        address=base+0xf000+offset
        ap.write(vt+offset,struct.pack('<Q',address));ap.stub(address,lambda a:0)
    ap.write(vt+0x30,struct.pack('<Q',base+0xff00));ap.stub(base+0xff00,lambda a:mapping)
    for n in range(34):
        kind=0x1c if n==9 and pool>=0xb0000 else 0x14 if n==15 or 22<=n<=28 else 2
        ap.write(mapping+n*16,struct.pack('<IIQ',kind,0,base+0x10000+n*0x1000))
    for address in (0x1b2ae4c,0x1bc3304):ap.stub(address,lambda a:0)
    presenter=ap.call('r5_filter_presenter425',0,view,0,0,0xd9,0)
    assert presenter
    g=local(ap,'r5_filter_page425','.bss.g')
    assert ap.words(g,8)[7]==int(pool>=0xb0000)
    assert ap.read(base+0x10000+11*0x1000+0x2c,1)==b'\1'
    ui={'selected':0,'seq':0,'calls':[]}
    ap.stub('r5_filter_selected',lambda a:ui['selected'])
    ap.stub('r5_filter_pending',lambda a:0)
    ap.stub('r5_filter_command_state',lambda a:2)
    ap.stub('r5_filter_command_sequence',lambda a:ui['seq'])
    def request(a):ui['selected']=a.arg(0);ui['seq']+=1;ui['calls'].append(a.arg(0));return 0
    ap.stub('r5_filter_request',request)
    dispatch=local(ap,'r5_filter_page425','.text.dispatch')
    for event,selected in ((0x2050000,1),(0x2050004,3),(0x2050000,12),(0x2050001,3)):
        assert ap.call(dispatch,controller,0,event)==1
        assert ap.words(g+8,1)[0]==ui['selected']==selected
    assert ui['calls']==[1,3,12,3]
    # 退休后私有输入被消费，原生生命周期消息仍转发。
    ap.call(local(ap,'r5_filter_page425','.text.exit_page'),controller,0)
    calls=list(ui['calls'])
    assert ap.call(dispatch,controller,0,0x2050000)==1 and ui['calls']==calls
    ap.stub(0x1a6d8cc,lambda a:999)
    assert ap.call(dispatch,controller,0,0x5001234)==999
    destroyed=[];ap.stub(0x22083ec,lambda a:destroyed.append(a.arg(0)) or 0)
    ap.call(local(ap,'r5_filter_page425','.text.controller_destroy'),controller)
    assert destroyed==[controller] and ap.words(g+32,2)==(0,0)
