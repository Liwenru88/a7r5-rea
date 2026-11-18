"""最终AP与CP机器码之间的probe/transfer/inbound/名称发布完整回放。"""
import ctypes as C
import struct
import pytest
from runtime_support import AP,CP,decoded
from test_runtime_transport import codec


@pytest.mark.parametrize('mode',['valid','drop','duplicate','corrupt'])
def test_actual_ap_worker_messages_and_actual_cp_resource_receiver(images,codec,mode):
    ap,cp=AP(images[2]),CP(images[3]);cp.receiver_services()
    now={'ms':0,'length':0,'sent':[]}
    clock,sleep,ack=ap.DATA+0x10000,ap.DATA+0x11000,ap.DATA+0x12000
    def resolve(a):
        return {'clock_gettime':clock,'nanosleep':sleep}.get(a.string(a.arg(1)),0)
    def time(a):a.write(a.arg(1),struct.pack('<qq',now['ms']//1000,now['ms']%1000*1000000));return 0
    def pause(a):now['ms']+=100;return 0
    ap.stub('r5_stage411_dlsym',resolve);ap.stub(clock,time);ap.stub(sleep,pause)
    ap.stub('r5_osal_msg_size',lambda a:now['length'])
    ap.stub('r5_filter_service',lambda a:0)
    def native_send(a):
        packet=a.read(a.arg(1),a.arg(2));now['sent'].append(packet)
        reply=cp.consume(packet)
        if packet[0]==0xe7 and mode=='drop':return 0
        if reply:
            reply=bytearray(reply)
            if packet[0]==0xe7 and mode=='corrupt':reply[28]^=1
            a.write(ack,reply);now['length']=len(reply)
            a.pending.append(('r5_stage411_inbound',(ack,0x90030001)))
            if packet[0]==0xe7 and mode=='duplicate':a.pending.append(('r5_stage411_inbound',(ack,0x90030001)))
        return 0
    ap.stub('r5_native_ap_send',native_send)
    value=decoded(codec);ap.write(ap.DATA,bytes(value))
    digest=codec.r5_filter_compact_set_crc(C.byref(value))
    def run():
        assert ap.call('r5_session_new_transfer')==1
        ap.call('r5_stage411_probe_run',0xfff,digest)
        assert ap.call('r5_stage413_capacity_ready')==1
        ap.call('r5_stage413_transfer_run',ap.DATA)
        matched=ap.call('r5_stage421_transfer_matched')
        if matched:assert ap.call('r5_stage421_parameters_ready')==1
        return matched
    ap.call('r5_session_cold');assert ap.call('r5_session_prepare')==1
    assert run()==int(mode=='valid')
    if mode!='valid':
        assert ap.call('r5_filter_available_mask')&0xffffffff==0
        return
    assert ap.call('r5_filter_available_mask')&0xffffffff==0xfff and len(cp.heap_allocations)==1
    active=cp.words(0x1a39448,1)[0];snapshot=cp.read(active,522152)
    ap.call('r5_session_finish')
    for event in (0x920143,0x92015a):
        ap.write(ack,struct.pack('<I',event));ap.call('r5_stage421_power',ack)
    assert ap.call('r5_session_prepare')==1
    before=len(now['sent'])
    assert run()==1
    assert len(now['sent'])==before+2, '恢复只需probe和复用BEGIN'
    assert len(cp.heap_allocations)==1 and cp.read(active,522152)==snapshot
