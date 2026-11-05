"""协议兼容确认与超时独立于成像；实际双端入口另由同包审计验证。"""
import ctypes as c
from pathlib import Path
import subprocess

NATIVE=Path(__file__).resolve().parents[1]/'native'


def test_hello_roundtrip_deadline_and_stale_input(tmp_path):
    output=tmp_path/'handshake.so'
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
        *[str(NATIVE/n) for n in ('af_slots.c','af_apply_wire.c','af_handshake.c')],'-o',str(output)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    api=c.CDLL(str(output))
    class State(c.Structure):
        _fields_=[('session',c.c_uint64),('deadline',c.c_uint64),('required',c.c_uint32),('state',c.c_uint32)]
    api.af_hs_begin.argtypes=[c.POINTER(State),c.c_uint64,c.c_uint32,c.c_uint64,c.c_uint64,c.c_void_p]
    api.af_hs_server.argtypes=[c.POINTER(State),c.c_void_p,c.c_size_t,c.c_uint32,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)]
    api.af_hs_client.argtypes=[c.POINTER(State),c.c_void_p,c.c_size_t,c.c_uint32,c.c_uint64]
    api.af_hs_poll.argtypes=[c.POINTER(State),c.c_uint64]
    client,server=State(),State();wire=c.create_string_buffer(128);reply=c.create_string_buffer(128);n=c.c_size_t(99)
    assert api.af_hs_begin(c.byref(client),43,0x1fff,100,50,wire)==0
    assert client.state==1 and client.deadline==150
    assert api.af_hs_server_init(c.byref(server),0x1fff)==0
    assert api.af_hs_server(c.byref(server),wire,128,0x80020002,reply,128,c.byref(n))==1 and n.value==128
    assert wire.raw[:128]==reply.raw[:128]
    assert api.af_hs_client(c.byref(client),reply,128,0x123,149)==0 and client.state==1
    assert api.af_hs_client(c.byref(client),reply,128,0x90030001,150)==1 and client.state==3
    assert api.af_hs_client(c.byref(client),reply,128,0x90030001,149)==1 and client.state==3
    fresh=State()
    assert api.af_hs_begin(c.byref(fresh),43,0x1fff,100,50,wire)==0
    assert api.af_hs_client(c.byref(fresh),reply,128,0x90030001,149)==1 and fresh.state==2
    assert api.af_hs_begin(c.byref(fresh),44,0x1fff,151,50,wire)==-4
    other=State()
    assert api.af_hs_begin(c.byref(other),44,0x1fff,100,50,wire)==0
    assert api.af_hs_server(c.byref(server),wire,128,0x80020002,reply,128,c.byref(n))==1 and n.value==0
    assert server.session==43
    corrupt=bytearray(wire.raw[:128]);corrupt[55]^=1
    assert api.af_hs_client(c.byref(other),bytes(corrupt),128,0x90030001,110)==1 and other.state==1
    short=State()
    assert api.af_hs_begin(c.byref(short),1,0x1fff,(1<<64)-1,1,wire)==-1 and short.state==0
    assert api.af_hs_begin(c.byref(short),45,0x1fff,100,10,wire)==0
    assert api.af_hs_poll(c.byref(short),109)==-4 and api.af_hs_poll(c.byref(short),110)==-5
