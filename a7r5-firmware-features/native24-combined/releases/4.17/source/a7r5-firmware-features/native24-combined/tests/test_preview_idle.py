"""停手后由原生值通知推进最后目标，不靠下一次按键或外部轮询。"""
import struct
import pytest
from replay import candidate
from test_unified_look import asynchronous_machine


@pytest.mark.parametrize('event',[0x20f0000,0x20f0001])
def test_native_idle_notification_drains_last_target_and_requests_repaint(event):
    ap,state,choose,poll,finish,desired,controller,view=asynchronous_machine(candidate)
    ap.stub('n12_stock_dispatch', lambda a: 0)
    choose(1);choose(2);choose(3)
    finish(1)
    assert desired()==1
    result=ap.call('n12_dispatch',controller,0,event)
    assert desired()==3, '停止按键后，值通知必须推进最后目标'
    assert result==1, '状态变化必须通知原生UI重绘'
    finish(3)
    assert ap.call('n12_dispatch',controller,0,event)==1
    ap.call('n12_labels',view)
    sequence=ap.call('r5_filter_command_sequence')
    assert ap.call('n12_dispatch',controller,0,event)==0
    assert ap.call('r5_filter_command_sequence')==sequence


@pytest.mark.parametrize('event',[0x20f0000,0x20f0001])
def test_parameter_page_idle_notification_repaints_without_consuming_other_keys(event):
    ap,state,choose,poll,finish,desired,controller,view=asynchronous_machine(candidate)
    # 从原DA控制器vtable取得真实入口，不能直接调用D9包装器代替集成。
    handler=struct.unpack('<Q',ap.read(0x58da6d8,8))[0]
    assert handler==0x1a6df54
    instruction=struct.unpack('<I',ap.read(handler,4))[0]
    assert instruction&0xfc000000==0x14000000, '原DA事件入口尚未接入后台刷新'
    ap.stub('n12_stock_parameter_dispatch',lambda a:0)
    def wrong_controller(a):
        raise AssertionError('DA不能委派给D9原分派器')
    ap.stub('n12_stock_dispatch',wrong_controller)
    ap.write(view,struct.pack('<Q',0x58ca720))
    ap.write(controller+0x178,struct.pack('<I',0xda))
    choose(1);finish(1)
    assert ap.call(handler,controller,0,event)==1
    assert ap.call(handler,controller,0,event)==1
    ap.stub('n12_stock_parameter_labels',lambda a:0)
    ap.call(0x220c830,view)
    assert ap.call(handler,controller,0,event)==0
    assert ap.call(handler,controller,0,0x2010003)==0
