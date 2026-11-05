"""既有128B协议的显式原厂回退能力：旧peer拒绝新HELLO，不扩13消费者。"""
import ctypes as c
from pathlib import Path
import subprocess

ROOT=next(p for p in Path(__file__).resolve().parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
NATIVE=ROOT/'a7r5-firmware-features/custom-filters/native'
PROPOSAL=Path(__file__).resolve().parents[1]/'native'


class Preset(c.Structure):
    _fields_=[('base',c.c_uint8),('kind',c.c_uint8),('params',c.c_int8*8),('payload',c.c_uint8*32),('lut',c.c_uint8*32)]


class Packet(c.Structure):
    _fields_=[('operation',c.c_uint32),('required',c.c_uint32),('slot',c.c_uint32),('session',c.c_uint64),('version',c.c_uint64),('preset',Preset)]


class State(c.Structure):
    _fields_=[('session',c.c_uint64),('deadline',c.c_uint64),('required',c.c_uint32),('state',c.c_uint32)]


def test_old_new_peer_capability_and_factory_slot_are_fail_closed(tmp_path):
    libs=[]
    for old in (True,False):
        out=tmp_path/('old.so' if old else 'new.so')
        sources=[NATIVE/'af_slots.c',*[((NATIVE if old else PROPOSAL)/name) for name in ('af_apply_wire.c','af_handshake.c')]]
        cmd=['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC']
        if not old:cmd+=['-DAF_FACTORY_RESTORE406=1','-I'+str(PROPOSAL)]
        cmd+=['-I'+str(NATIVE),*map(str,sources),'-o',str(out)]
        built=subprocess.run(cmd,capture_output=True,text=True);assert built.returncode==0,built.stderr
        api=c.CDLL(str(out))
        api.af_hs_begin.argtypes=[c.POINTER(State),c.c_uint64,c.c_uint32,c.c_uint64,c.c_uint64,c.c_void_p]
        api.af_hs_server_init.argtypes=[c.POINTER(State),c.c_uint32]
        api.af_hs_server.argtypes=[c.POINTER(State),c.c_void_p,c.c_size_t,c.c_uint32,c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)]
        api.af_hs_poll.argtypes=[c.POINTER(State),c.c_uint64]
        api.af_apply_packet_encode.argtypes=[c.POINTER(Packet),c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)]
        api.af_apply_packet_decode.argtypes=[c.c_void_p,c.c_size_t,c.POINTER(Packet)]
        libs.append(api)
    old,new=libs;full=0x11fff;wire=c.create_string_buffer(128);reply=c.create_string_buffer(128);n=c.c_size_t()
    client,legacy=State(),State();assert new.af_hs_begin(c.byref(client),71,full,100,1000,wire)==0
    assert old.af_hs_server_init(c.byref(legacy),0x1fff)==0
    assert old.af_hs_server(c.byref(legacy),wire,128,0x80020002,reply,128,c.byref(n))==1 and n.value==0 and legacy.state==4
    assert new.af_hs_poll(c.byref(client),1100)==-5 and client.state==3
    current=State();assert new.af_hs_server_init(c.byref(current),full)==0
    assert new.af_hs_server(c.byref(current),wire,128,0x80020002,reply,128,c.byref(n))==1 and n.value==128 and current.state==5
    older=State();assert old.af_hs_begin(c.byref(older),72,0x1fff,100,1000,wire)==0
    untouched=State();assert new.af_hs_server_init(c.byref(untouched),full)==0
    assert new.af_hs_server(c.byref(untouched),wire,128,0x80020002,reply,128,c.byref(n))==1 and n.value==0 and untouched.state==4
    p=Packet(operation=2,required=full,slot=0,session=71,version=2)
    p.preset.base=18;p.preset.params[:]=[-3,4,-5,2,6,7,3,8]
    assert new.af_apply_packet_encode(c.byref(p),wire,128,c.byref(n))==0 and n.value==128
    parsed=Packet();assert new.af_apply_packet_decode(wire,128,c.byref(parsed))==0 and parsed.slot==0 and parsed.preset.base==18
    assert old.af_apply_packet_decode(wire,128,c.byref(parsed))==-1
    for required in (0x1fff,0x10000,0x20000|0x1fff):
        p.required=required;before=wire.raw
        assert new.af_apply_packet_encode(c.byref(p),wire,128,c.byref(n))==-1 and wire.raw==before
    p.slot=7;p.required=0x1fff
    assert new.af_apply_packet_encode(c.byref(p),wire,128,c.byref(n))==0
    assert old.af_apply_packet_decode(wire,128,c.byref(parsed))==0 and parsed.slot==7
