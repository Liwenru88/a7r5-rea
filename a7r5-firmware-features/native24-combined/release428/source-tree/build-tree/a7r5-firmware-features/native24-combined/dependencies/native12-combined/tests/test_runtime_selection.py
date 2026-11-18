"""真实AP选择状态机与CP机器码往返，失败与回退必须可观察。"""
import ctypes as C
from pathlib import Path
import struct
import pytest
from runtime_support import SOURCE, CP, decoded, library
from test_runtime_transport import codec, upload


@pytest.fixture
def selection(tmp_path, images, codec):
    cp, value = CP(images[3]), decoded(codec)
    assert upload(codec,cp,value)[0].phase == 4
    cp.write(0x1a39448,struct.pack('<II',cp.BANK,28768))
    cp.call('r5_filter423_accept',0x1234,1)
    # 原选择协议的编解码与文件侧实现同TU；本状态机层的文件服务是显式替身。
    protocol=tmp_path/'protocol.c'
    protocol.write_text('#define r5_filter_selection_load unused_load\n#define r5_filter_selection_save unused_save\n#include "r5_filter_selection423.c"\n')
    lib=library(tmp_path,'selection-linked',[Path(__file__).with_name('runtime_selection.c'),protocol])
    send=C.CFUNCTYPE(C.c_int,C.c_void_p,C.c_size_t)
    behavior={'mode':'valid','sent':[],'errors':[],'cp':cp}
    @send
    def native(p,n):
        try:
            data=C.string_at(p,n);behavior['sent'].append(data)
            if behavior['mode']=='send_fail': return -1
            if behavior['mode']=='drop': return 0
            cp=behavior['cp']
            cp.write(cp.PACKET,data)
            assert cp.call('r5_filter423_select',cp.PACKET,n,cp.ACK)==1
            ack=bytearray(cp.read(cp.ACK,32))
            if behavior['mode']=='corrupt': ack[28]^=1
            source=0x80020002 if behavior['mode']=='foreign' else 0x90030001
            lib.r5_filter_inbound(bytes(ack),C.c_uint32(source))
            return 0
        except Exception as e:
            behavior['errors'].append(e);return -1
    lib.test_bind.argtypes=[send];lib.test_bind(native)
    lib.r5_filter_bank_ready(C.c_uint32(0x1234),C.c_uint32(cp.words(cp.BANK+16,1)[0]),4095)
    lib.r5_filter_service()
    assert not behavior['errors']
    assert lib.r5_filter_selected()==0
    assert lib.r5_filter_pending()==0
    return lib,cp,behavior,native


def test_select_all_off_and_repeat_need_exact_execution_and_durability(selection):
    lib,cp,b,_=selection
    for n in [*range(1,13),0]:
        before=len(b['sent'])
        assert lib.r5_filter_request(n)==0
        assert lib.r5_filter_request(n)==-1
        lib.r5_filter_service()
        assert lib.r5_filter_command_state()==2
        assert lib.r5_filter_selected()==lib.test_stat(2)==n
        assert len(b['sent'])==before+2
        assert lib.r5_filter_request(n)==0
        lib.r5_filter_service()
        assert lib.r5_filter_command_state()==2 and len(b['sent'])==before+2
    assert not b['errors']


@pytest.mark.parametrize('failure',['send_fail','drop','corrupt','foreign','refresh','save','cancel'])
def test_failed_selection_never_reports_success_and_is_retryable(selection,failure):
    lib,cp,b,_=selection
    if failure in ('send_fail','drop','corrupt','foreign'): b['mode']=failure
    else: lib.test_fault({'refresh':1,'save':2,'cancel':4}[failure])
    if failure=='cancel': b['mode']='drop'
    assert lib.r5_filter_request(7)==0
    lib.r5_filter_service()
    assert lib.r5_filter_command_state()==3 and lib.r5_filter_selected()==0
    assert not b['errors']
    if failure=='save':
        # 首次CP选择成功但文件保存失败，必须尝试回退CP；AP仍不得宣称成功。
        assert cp.words(0x1a3945c+8,1)[0]==0
    if failure!='cancel':
        b['mode']='valid';lib.test_fault(0)
        assert lib.r5_filter_request(7)==0
        lib.r5_filter_service()
        assert lib.r5_filter_command_state()==2 and lib.r5_filter_selected()==7


def test_bank_reconciliation_missing_slots_and_reload_rejection(selection, images, codec):
    lib,cp,b,_=selection
    assert lib.r5_filter_request(12)==0;lib.r5_filter_service()
    cp,value=CP(images[3]),decoded(codec)
    value.mask=1
    assert upload(codec,cp,value)[0].phase==4
    cp.write(0x1a39448,struct.pack('<II',cp.BANK,28768))
    cp.call('r5_filter423_accept',0x1234,1)
    b['cp']=cp
    lib.r5_filter_bank_ready(0x1234,cp.words(cp.BANK+16,1)[0],1)
    lib.test_available(1)
    lib.r5_filter_service()
    assert lib.r5_filter_selected()==0
    assert lib.r5_filter_request(12)==-1
    assert lib.r5_filter_reload_request()==0
    lib.r5_filter_service()
    assert lib.r5_filter_command_state()==3
