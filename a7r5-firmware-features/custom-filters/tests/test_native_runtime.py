"""一次启动、无消息超时与故障关闭；目标系统导入另由同包指令联验。"""
import ctypes as c
from pathlib import Path
import subprocess

import pytest

NATIVE=Path(__file__).resolve().parents[1]/'native'


class Hello(c.Structure):
    _fields_=[('session',c.c_uint64),('deadline',c.c_uint64),('required',c.c_uint32),('state',c.c_uint32)]


class Runtime(c.Structure):
    _fields_=[('hello',Hello),('last_now',c.c_uint64),('attempted',c.c_uint32),('fault',c.c_uint32)]


Value=c.CFUNCTYPE(c.c_int,c.POINTER(c.c_uint64))
Send=c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_size_t)
Receive=c.CFUNCTYPE(c.c_int,c.c_uint32,c.POINTER(c.c_void_p),c.c_int)


class Ports(c.Structure):
    _fields_=[('nonce',Value),('clock_ms',Value),('send',Send),('receive',Receive)]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    output=tmp_path_factory.mktemp('runtime')/'core.so'
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
        *[str(NATIVE/n) for n in ('af_slots.c','af_apply_wire.c','af_handshake.c','af_runtime.c')],
        '-o',str(output)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    lib=c.CDLL(str(output))
    lib.af_rt_start.argtypes=lib.af_rt_poll.argtypes=[c.POINTER(Runtime),c.POINTER(Ports)]
    lib.af_rt_next.argtypes=[c.POINTER(Runtime),c.POINTER(Ports),c.c_uint32,c.POINTER(c.c_void_p)]
    lib.af_rt_reply.argtypes=[c.POINTER(Runtime),c.POINTER(Ports),c.c_void_p,c.c_uint32,c.c_size_t]
    return lib


class Backend:
    def __init__(self):
        self.now=100;self.nonce_calls=0;self.sent=[];self.waits=[]
        self.nonce_error=self.clock_error=self.send_error=0
        self.receive_error=-1022;self.pointer=0;self.session=0x8899aabbccddeeff
        def nonce(out):
            self.nonce_calls+=1;out[0]=self.session;return self.nonce_error
        def clock(out):out[0]=self.now;return self.clock_error
        def send(p,n):self.sent.append(c.string_at(p,n));return self.send_error
        def receive(queue,out,wait):
            self.waits.append((queue,wait));out[0]=self.pointer;return self.receive_error
        self.ports=Ports(Value(nonce),Value(clock),Send(send),Receive(receive))


def test_task_start_once_empty_receive_deadline_and_late_reply(api):
    b=Backend();s=Runtime();out=c.c_void_p(0xdead)
    assert api.af_rt_next(c.byref(s),c.byref(b.ports),0x80020002,c.byref(out))==0
    assert out.value is None and b.nonce_calls==1 and len(b.sent)==1
    assert s.hello.session==b.session and s.hello.deadline==1100 and s.hello.state==1
    b.now=1099
    assert api.af_rt_next(c.byref(s),c.byref(b.ports),0x80020002,c.byref(out))==0
    assert b.waits[-1]==(0x80020002,1)
    b.now=1100
    assert api.af_rt_reply(c.byref(s),c.byref(b.ports),b.sent[0],0x90030001,128)==1
    assert s.hello.state==3 and api.af_rt_start(c.byref(s),c.byref(b.ports))==-4
    assert b.nonce_calls==1 and len(b.sent)==1


@pytest.mark.parametrize('failure,expected',[
    ('nonce_error',1),('zero_nonce',1),('clock_error',2),('overflow',2),('send_error',3)])
def test_start_failure_never_accepts_reply_or_restarts(api,failure,expected):
    b=Backend();s=Runtime()
    if failure=='zero_nonce':b.session=0
    elif failure=='overflow':b.now=(1<<64)-999
    else:setattr(b,failure,-1)
    assert api.af_rt_start(c.byref(s),c.byref(b.ports))==-1
    assert s.fault==expected and s.hello.state==3 and s.attempted==1
    assert api.af_rt_start(c.byref(s),c.byref(b.ports))==-4 and b.nonce_calls==1


def test_success_preserves_original_message_and_clock_rollback_disables_protocol(api):
    b=Backend();s=Runtime();out=c.c_void_p()
    assert api.af_rt_start(c.byref(s),c.byref(b.ports))==0
    assert api.af_rt_reply(c.byref(s),c.byref(b.ports),b.sent[0],0x90030001,128)==1
    assert s.hello.state==2
    b.pointer=0x12345678;b.receive_error=0
    assert api.af_rt_next(c.byref(s),c.byref(b.ports),0x80020002,c.byref(out))==1
    assert out.value==b.pointer and b.waits[-1][1]==-1
    b.now=99
    assert api.af_rt_poll(c.byref(s),c.byref(b.ports))==-1 and s.fault==2 and s.hello.state==3
    b.now=101
    assert api.af_rt_reply(c.byref(s),c.byref(b.ports),b.sent[0],0x90030001,128)==1
    assert s.hello.state==3


@pytest.mark.parametrize('missing_ports',[True,False])
def test_missing_clock_never_uses_previous_timestamp_for_reply(api,missing_ports):
    b=Backend();s=Runtime()
    assert api.af_rt_start(c.byref(s),c.byref(b.ports))==0
    invalid=Ports(b.ports.nonce,Value(),b.ports.send,b.ports.receive)
    ports=None if missing_ports else c.byref(invalid)
    assert api.af_rt_reply(c.byref(s),ports,b.sent[0],0x90030001,128)==1
    assert s.hello.state==3 and s.fault==2


@pytest.mark.parametrize('error,pointer',[(0,0),(-7,0),(-7,0x12345678)])
def test_receive_failure_keeps_nonempty_ownership_without_new_session(api,error,pointer):
    b=Backend();s=Runtime();out=c.c_void_p()
    b.receive_error=error;b.pointer=pointer
    assert api.af_rt_next(c.byref(s),c.byref(b.ports),0x80020002,c.byref(out))==bool(pointer)
    assert s.fault==4 and s.hello.state==3 and out.value==(pointer or None)
    assert b.nonce_calls==1 and len(b.sent)==1
