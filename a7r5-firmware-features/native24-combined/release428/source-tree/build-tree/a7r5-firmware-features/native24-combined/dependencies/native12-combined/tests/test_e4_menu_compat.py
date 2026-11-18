"""实际AArch64的私有值刷新与原dispatch回归；外部原厂UI服务明确用替身。"""
import os
import struct
import pytest
from elftools.elf.elffile import ELFFile
import menu_font
import e4_menu_compat
from runtime_support import AP, BASELINE
from test_runtime_ap_ui import local


@pytest.fixture
def event_ap(images,tmp_path):
    font,_=menu_font.build(images[2],tmp_path/'font')
    patched,_=e4_menu_compat.build(font.read_bytes(),tmp_path/'event')
    # 只用于保留修复前的真实失败证据，不改变生产构建。
    return AP((font if os.environ.get('A7R5_E4_TEST_ORIGINAL')=='1' else patched).read_bytes())


def page(ap,active=1,owned=True):
    g=local(ap,'r5_filter_page425','.bss.g')
    controller,manager,mid=ap.DATA+0x1000,ap.DATA+0x2000,ap.DATA+0x3000
    ap.write(g,struct.pack('<8I',1,active,7,3,0,0,0,0))
    ap.write(g+32,struct.pack('<QQQ',controller if owned else 0,0,manager))
    ap.write(controller+0x178,struct.pack('<I',0xd9));ap.write(controller+0x180,struct.pack('<Q',manager))
    ap.write(mid,struct.pack('<I',0x635));ap.stub(0x28a8720,lambda a:mid)
    return g,controller


@pytest.mark.parametrize('event,active,owned,expected_calls',[
    (0x20f0001,1,True,0),(0x20f0001,0,True,0),
    (0x20f0001,1,False,1),(0x20f0000,1,True,1)])
def test_real_dispatch_consumes_private_value_refresh_only(event_ap,event,active,owned,expected_calls):
    ap=event_ap;_,controller=page(ap,active,owned);calls=[]
    ap.stub(0x1a6d8cc,lambda a:calls.append(a.arg(2)) or 17)
    result=ap.call(local(ap,'r5_filter_page425','.text.dispatch'),controller,0,event)
    assert calls==[event]*expected_calls
    assert result==(17 if expected_calls else 1)


def test_real_navigation_still_executes_original_dispatch_and_submits_once(event_ap):
    ap=event_ap;g,controller=page(ap);ui={'selected':7,'seq':0,'calls':[]}
    ap.stub('r5_filter_pending',lambda a:0);ap.stub('r5_filter_command_state',lambda a:2)
    ap.stub('r5_filter_available_mask',lambda a:4095)
    ap.stub('r5_filter_command_sequence',lambda a:ui['seq'])
    ap.stub('r5_filter_selected',lambda a:ui['selected'])
    def request(a):ui['selected']=a.arg(0);ui['seq']+=1;ui['calls'].append(a.arg(0));return 0
    ap.stub('r5_filter_request',request)
    assert ap.call(local(ap,'r5_filter_page425','.text.dispatch'),controller,0,0x2050000)==1
    assert ui['calls']==[8] and ap.words(g+8,1)==(8,)


def test_burst_navigation_and_delayed_value_notifications_keep_exact_pending_sequence(event_ap):
    """回放真实页面／提交器；worker完成和原厂通知路由是显式时序夹具。"""
    ap=event_ap;g,controller=page(ap)
    dispatch=local(ap,'r5_filter_page425','.text.dispatch')
    runtime='r5_filter_runtime423'
    with (BASELINE/'work/import/objects'/f'{runtime}.o').open('rb') as f:
        obj=ELFFile(f)
        fields={s.name:local(ap,runtime,obj.get_section(s['st_shndx']).name)+s['st_value']
                for s in obj.get_section_by_name('.symtab').iter_symbols()
                if s.name in ('applied','command_state')}
    def field(name,value):
        ap.write(fields[name],struct.pack('<I',value))
    ap.stub('r5_filter_available_mask',lambda a:4095)
    ap.call('r5_filter_bank_ready',0x1234,0x5678,4095)
    field('applied',7);field('command_state',2)
    ap.stub('usleep',lambda a:0)
    # 原厂回调最终进入原有菜单setter；此处只替代原厂路由，不替代提交器。
    def native_dispatch(a):
        assert a.arg(2)==0x20f0001
        a.pending.append(('r5_filter_menu_select',(ap.words(g+8,1)[0],)))
        return 1
    ap.stub(0x1a6d8cc,native_dispatch)
    ap.call(dispatch,controller,0,0x2050000)
    assert ap.words(g+8,3)==(8,4,1)
    assert ap.call('r5_filter_command_sequence')==1
    # 等待超过UI有界等待后仍在进行；快速按键不能插入第二个事务。
    for event in (0x2050000,0x2050000,0x2050001):
        ap.call(dispatch,controller,0,event)
    assert ap.words(g+8,3)==(8,4,1)
    assert ap.call('r5_filter_command_sequence')==1
    # 不证明IO成功：显式放置worker完成快照，只检查迟到通知与下次输入的交错。
    field('applied',8);field('command_state',2)
    for _ in range(3):ap.call(dispatch,controller,0,0x20f0001)
    ap.call(dispatch,controller,0,0x2050000)
    # 旧4.11被迟到通知偷开新序列后，在这里得到status=3；修复版继续申请9。
    assert ap.words(g+8,3)==(9,4,2), '迟到值通知改变了待处理序列，快速输入被误判为应用失败'
    assert ap.call('r5_filter_command_sequence')==2
