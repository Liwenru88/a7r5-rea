"""真实C传输软件契约；独立Python字节期待，不执行设备或目标指令。"""
import ctypes as c
import hashlib
from pathlib import Path
import struct
import subprocess
import zlib

import pytest

from joint_support import Recipe, seed
from test_native_slots import Preset

NATIVE=Path(__file__).resolve().parents[1]/'native'


class Asset(c.Structure):
    _fields_=[('base',c.c_uint32),('model_sha256',c.c_uint8*32),('recipe',Recipe),
              ('native_mode',c.c_uint32),('native_tone',c.c_int16*3),('native_seed',c.c_uint32*129),
              ('matrix_mode',c.c_uint32),('sector_matrix',c.c_int16*288)]


class Message(c.Structure):
    _fields_=[('session',c.c_uint64),('version',c.c_uint64),('slot',c.c_uint32),
              ('preset',Preset),('image',c.c_uint8*2483),('image_bytes',c.c_uint32)]


class Owned(c.Structure):
    _fields_=[('state',c.c_uint32),('references',c.c_uint32),('message',Message),('asset',Asset)]


class Lease(c.Structure):
    _fields_=[('session',c.c_uint64),('version',c.c_uint64),('lease',c.c_uint64),('bank',c.c_uint32)]


class Ack(c.Structure):
    _fields_=[('session',c.c_uint64),('version',c.c_uint64),('slot',c.c_uint32),
              ('status',c.c_int),('payload_sha256',c.c_uint8*32)]


def memory(n):
    return (c.c_uint64*((n+7)//8))()


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    target=tmp_path_factory.mktemp('recipe-transport')/'native.so'
    files=[NATIVE/name for name in ('af_recipe_transport.c','af_joint_asset.c','af_sha256.c','af_joint.c','af_slots.c')]
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
                           *map(str,files),'-o',str(target)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    lib=c.CDLL(str(target))
    for name in ('af_recipe_rx_bytes','af_recipe_tx_bytes','af_recipe_decode_work_bytes'):
        getattr(lib,name).restype=c.c_size_t
    lib.af_joint_asset_encode.argtypes=[c.POINTER(Asset),c.c_void_p,c.c_size_t,c.POINTER(c.c_size_t)]
    lib.af_recipe_tx_init.argtypes=[c.c_void_p,c.c_uint64,c.c_uint64,c.c_uint32,c.POINTER(Preset),c.c_void_p,c.c_size_t]
    lib.af_recipe_tx_frame.argtypes=[c.c_void_p,c.c_uint32,c.c_void_p,c.c_size_t]
    lib.af_recipe_tx_ack.argtypes=[c.c_void_p,c.c_void_p,c.c_size_t,c.POINTER(Ack)]
    lib.af_recipe_rx_init.argtypes=[c.c_void_p,c.c_uint64,c.c_uint32]
    lib.af_recipe_rx_frame.argtypes=[c.c_void_p,c.c_void_p,c.c_size_t]
    lib.af_recipe_rx_validate.argtypes=[c.c_void_p,c.c_void_p]
    lib.af_recipe_rx_rejection.argtypes=[c.c_void_p,c.c_void_p,c.c_size_t]
    for name in ('af_recipe_rx_take','af_recipe_rx_acquire'):
        getattr(lib,name).argtypes=[c.c_void_p,c.POINTER(Lease),c.POINTER(c.POINTER(Owned))]
    lib.af_recipe_rx_finish.argtypes=[c.c_void_p,c.POINTER(Lease),c.c_int,c.c_void_p,c.c_size_t]
    lib.af_recipe_rx_release.argtypes=[c.c_void_p,c.POINTER(Lease)]
    lib.af_recipe_rx_cancel.argtypes=[c.c_void_p]
    lib.af_recipe_ack_decode.argtypes=[c.c_void_p,c.c_size_t,c.POINTER(Ack)]
    return lib


def transaction(api,version=1,slot=7,session=0x1122334455667788):
    asset=Asset(base=17,recipe=seed());asset.model_sha256[:]=hashlib.sha256('研究模型'.encode()).digest()
    asset.recipe.matrix[:]=range(-9,9);asset.recipe.cc1[:]=range(-12,12)
    asset.recipe.grid[:]=[(i%128)-64 for i in range(1215)]
    raw=c.create_string_buffer(1943);written=c.c_size_t()
    assert api.af_joint_asset_encode(c.byref(asset),raw,1943,c.byref(written))==0 and written.value==1943
    preset=Preset(base=17,kind=1);preset.params[:]=[-1,2,-3,4,-5,6,3,8]
    preset.payload_sha256[:]=hashlib.sha256(raw.raw).digest();preset.lut_sha256[:]=hashlib.sha256(b'LUT').digest()
    tx=memory(api.af_recipe_tx_bytes())
    assert api.af_recipe_tx_init(tx,session,version,slot,c.byref(preset),raw,1943)==0
    frames=[]
    for i in range(28):
        frame=c.create_string_buffer(128)
        assert api.af_recipe_tx_frame(tx,i,frame,128)==0
        frames.append(frame.raw)
    return tx,frames,bytes(raw),preset


def receiver(api,session=0x1122334455667788):
    rx=memory(api.af_recipe_rx_bytes())
    assert api.af_recipe_rx_init(rx,session,1)==0
    return rx


def receive(api,rx,frame):
    return api.af_recipe_rx_frame(rx,c.create_string_buffer(frame),len(frame))


def ready(api,rx,frames):
    for frame in frames:assert receive(api,rx,frame)==0
    work=memory(api.af_recipe_decode_work_bytes())
    assert api.af_recipe_rx_validate(rx,work)==0
    lease=Lease();value=c.POINTER(Owned)()
    assert api.af_recipe_rx_take(rx,c.byref(lease),c.byref(value))==0
    return lease,value


def finish(api,rx,lease,status=0):
    out=c.create_string_buffer(b'\xa5'*128,128)
    assert api.af_recipe_rx_finish(rx,c.byref(lease),status,out,128)==0
    ack=Ack();assert api.af_recipe_ack_decode(out,128,c.byref(ack))==0
    return out.raw,ack


def edit(frame,at,value,fmt='I'):
    raw=bytearray(frame);struct.pack_into('<'+fmt,raw,at,value)
    struct.pack_into('<I',raw,124,zlib.crc32(raw[:124]))
    return bytes(raw)


def test_complete_wire_matches_independent_layout_and_waits_for_explicit_commit(api):
    tx,frames,raw,preset=transaction(api)
    assert len(frames)==28
    for i,frame in enumerate(frames):
        assert frame[:4]==b'A7R1' and frame[4]==1
        assert struct.unpack_from('<HIIQQ',frame,6)==(48,1943,7,0x1122334455667788,1)
        assert struct.unpack_from('<II',frame,40)==(1,0)
        assert struct.unpack_from('<I',frame,124)[0]==zlib.crc32(frame[:124])
        assert frame[5]==(1 if i==0 else 3 if i==27 else 2)
    assert frames[0][48:58]==bytes(preset)[:10]
    assert frames[0][60:92]==hashlib.sha256(raw).digest() and frames[0][92:124]==bytes(preset.lut_sha256)
    reassembled=b''.join(f[48:48+struct.unpack_from('<H',f,36)[0]] for f in frames[1:-1])
    assert reassembled==raw
    rx=receiver(api);ptr=c.POINTER(Owned)();lease=Lease()
    for frame in frames[:-1]:assert receive(api,rx,frame)==0
    assert api.af_recipe_rx_take(rx,c.byref(lease),c.byref(ptr))==-4
    assert api.af_recipe_rx_acquire(rx,c.byref(lease),c.byref(ptr))==-2
    assert receive(api,rx,frames[-1])==0
    assert api.af_recipe_rx_take(rx,c.byref(lease),c.byref(ptr))==-4
    work=memory(api.af_recipe_decode_work_bytes());assert api.af_recipe_rx_validate(rx,work)==0
    assert api.af_recipe_rx_take(rx,c.byref(lease),c.byref(ptr))==0
    assert ptr.contents.message.image_bytes==1943 and bytes(ptr.contents.message.image)[:1943]==raw and bytes(ptr.contents.message.preset)==bytes(preset)
    assert ptr.contents.asset.base==17 and ptr.contents.asset.recipe.matrix[0]==-9
    ackbytes,ack=finish(api,rx,lease)
    assert (ack.session,ack.version,ack.slot,ack.status)==(0x1122334455667788,1,7,0)
    assert ackbytes[5]==4 and bytes(ack.payload_sha256)==hashlib.sha256(raw).digest()
    assert api.af_recipe_tx_ack(tx,c.create_string_buffer(ackbytes),128,c.byref(ack))==0
    old=bytes(ack)
    for at,value,fmt in ((16,42,'Q'),(24,2,'Q'),(12,20,'I'),(48,ackbytes[48]^1,'B')):
        assert api.af_recipe_tx_ack(tx,c.create_string_buffer(edit(ackbytes,at,value,fmt)),128,c.byref(ack))==-5
        assert bytes(ack)==old
    assert api.af_recipe_ack_decode(c.create_string_buffer(edit(ackbytes,38,1,'h')),128,c.byref(ack))==-1
    assert bytes(ack)==old
    assert api.af_recipe_rx_release(rx,c.byref(lease))==0
    assert api.af_recipe_rx_finish(rx,c.byref(lease),0,c.create_string_buffer(128),128)==-5


@pytest.mark.parametrize('kind',['crc','offset','session','version','capability','padding'])
def test_rejected_frame_does_not_advance_or_publish(api,kind):
    tx,frames,raw,preset=transaction(api);rx=receiver(api)
    assert receive(api,rx,frames[0])==0
    frame=frames[1]
    if kind=='crc':frame=frame[:50]+bytes([frame[50]^1])+frame[51:]
    elif kind=='offset':frame=edit(frame,32,76)
    elif kind=='session':frame=edit(frame,16,9,'Q')
    elif kind=='version':frame=edit(frame,24,2,'Q')
    elif kind=='capability':frame=edit(frame,40,3)
    else:frame=edit(frame,44,1)
    before=bytes(rx)
    assert receive(api,rx,frame)<0 and bytes(rx)==before
    for frame in frames[1:]:assert receive(api,rx,frame)==0
    assert api.af_recipe_rx_validate(rx,memory(api.af_recipe_decode_work_bytes()))==0


def test_borrowed_generation_is_not_overwritten_and_failed_apply_keeps_old_active(api):
    rx=receiver(api);_,f1,raw,_=transaction(api,1)
    l1,p1=ready(api,rx,f1);finish(api,rx,l1)
    extra=Lease();extra_ptr=c.POINTER(Owned)()
    assert api.af_recipe_rx_acquire(rx,c.byref(extra),c.byref(extra_ptr))==0 and extra.lease!=l1.lease
    assert api.af_recipe_rx_release(rx,c.byref(extra))==0
    assert api.af_recipe_rx_release(rx,c.byref(extra))==-5
    snapshot=bytes(p1.contents)
    _,f2,_,_=transaction(api,2,20)
    l2,p2=ready(api,rx,f2);finish(api,rx,l2)
    assert bytes(p1.contents.message.image)[:1943]==raw and bytes(p1.contents.message)==snapshot[Owned.message.offset:Owned.message.offset+c.sizeof(Message)]
    _,f3,_,_=transaction(api,3)
    assert receive(api,rx,f3[0])==-7
    assert api.af_recipe_rx_release(rx,c.byref(l1))==0
    assert api.af_recipe_rx_release(rx,c.byref(l1))==-5
    l3,p3=ready(api,rx,f3);_,ack=finish(api,rx,l3,-6)
    assert ack.status==-6
    active=Lease();ptr=c.POINTER(Owned)()
    assert api.af_recipe_rx_acquire(rx,c.byref(active),c.byref(ptr))==0 and active.version==2
    assert api.af_recipe_rx_release(rx,c.byref(active))==0
    assert api.af_recipe_rx_release(rx,c.byref(l2))==0
    assert api.af_recipe_rx_release(rx,c.byref(l3))==0
    assert receive(api,rx,f3[0])==-5


def test_complete_payload_digest_and_native_identity_validation_are_transactional(api):
    _,frames,raw,preset=transaction(api);rx=receiver(api)
    damaged=bytearray(raw);damaged[32]^=1
    preset.payload_sha256[:]=hashlib.sha256(damaged).digest()
    tx=memory(api.af_recipe_tx_bytes())
    assert api.af_recipe_tx_init(tx,0x1122334455667788,1,7,c.byref(preset),c.create_string_buffer(bytes(damaged)),1943)==0
    for i in range(28):
        frame=c.create_string_buffer(128);assert api.af_recipe_tx_frame(tx,i,frame,128)==0
        assert receive(api,rx,frame.raw)==0
    result=api.af_recipe_rx_validate(rx,memory(api.af_recipe_decode_work_bytes()))
    assert result<0
    frame=c.create_string_buffer(128);ack=Ack()
    assert api.af_recipe_rx_rejection(rx,frame,128)==0
    assert api.af_recipe_ack_decode(frame,128,c.byref(ack))==0
    assert (ack.version,ack.slot,ack.status)==(1,7,result)
    assert bytes(ack.payload_sha256)==hashlib.sha256(damaged).digest()
    lease=Lease();ptr=c.POINTER(Owned)()
    assert api.af_recipe_rx_acquire(rx,c.byref(lease),c.byref(ptr))==-2
    assert receive(api,rx,frames[0])==-5


def test_cancel_capability_initialization_and_output_aliases_preserve_contract(api):
    rx=memory(api.af_recipe_rx_bytes())
    assert api.af_recipe_rx_init(rx,123,0)==-1
    assert api.af_recipe_rx_init(rx,123,5)==-1
    assert api.af_recipe_rx_init(rx,123,1)==0
    assert api.af_recipe_rx_init(rx,123,1)==-4
    _,frames,_,_=transaction(api,session=123)
    assert receive(api,rx,frames[0])==0
    assert api.af_recipe_rx_cancel(rx)==0 and receive(api,rx,frames[0])==-5
    _,frames,_,_=transaction(api,2,session=123)
    lease,ptr=ready(api,rx,frames)
    assert api.af_recipe_rx_cancel(rx)==-4
    old=bytes(rx)
    assert api.af_recipe_rx_finish(rx,c.byref(lease),0,rx,128)==-1 and bytes(rx)==old
    assert api.af_recipe_rx_release(rx,c.byref(lease))==-4
    finish(api,rx,lease);assert api.af_recipe_rx_release(rx,c.byref(lease))==0


def test_sector_asset_variable_length_and_capability_never_mix_transactions(api):
    asset=Asset(base=0,native_mode=1,matrix_mode=1)
    asset.model_sha256[:]=hashlib.sha256(b'sector-model').digest()
    asset.native_seed[:]=[i*512 for i in range(129)]
    asset.recipe.gamma[:]=asset.native_seed
    asset.sector_matrix[:]=[i%31-15 for i in range(288)]
    raw=c.create_string_buffer(2483);written=c.c_size_t()
    assert api.af_joint_asset_encode(c.byref(asset),raw,2483,c.byref(written))==0 and written.value==2483
    assert raw.raw[:5]==b'AJR3\x03'
    assert struct.unpack_from('<2I',raw.raw,8)==(2355,15)
    assert struct.unpack_from('<288h',raw.raw,128+516)==tuple(asset.sector_matrix)
    assert raw.raw[128+1140:]==bytes(asset.recipe.grid)
    # 新旧矩阵不能同时生效；非法值不能产生任何部分输出。
    for invalid in ('legacy', 'range'):
        if invalid=='legacy':asset.recipe.matrix[0]=1
        else:asset.sector_matrix[0]=1025
        before=raw.raw
        assert api.af_joint_asset_encode(c.byref(asset),raw,2483,c.byref(written))==-1 and raw.raw==before
        asset.recipe.matrix[0]=0;asset.sector_matrix[0]=-15
    preset=Preset(base=0,kind=1);preset.params[6]=3
    preset.payload_sha256[:]=hashlib.sha256(raw.raw).digest();preset.lut_sha256[0]=1
    tx=memory(api.af_recipe_tx_bytes())
    assert api.af_recipe_tx_init(tx,123,1,7,c.byref(preset),raw,2483)==0
    api.af_recipe_tx_frames.argtypes=[c.c_void_p]
    assert api.af_recipe_tx_frames(tx)==35
    frames=[]
    for ordinal in range(35):
        frame=c.create_string_buffer(128);assert api.af_recipe_tx_frame(tx,ordinal,frame,128)==0
        assert struct.unpack_from('<I',frame.raw,8)[0]==2483 and struct.unpack_from('<I',frame.raw,40)[0]==3
        frames.append(frame.raw)
    old_rx=receiver(api,123);before=bytes(old_rx)
    assert receive(api,old_rx,frames[0])==-30 and bytes(old_rx)==before
    rx=memory(api.af_recipe_rx_bytes());assert api.af_recipe_rx_init(rx,123,3)==0
    assert receive(api,rx,frames[0])==0
    # CRC有效但换成旧长度/能力的中间帧必须拒绝且不推进。
    mixed=edit(edit(frames[1],8,1943),40,1);before=bytes(rx)
    assert receive(api,rx,mixed)==-5 and bytes(rx)==before
    for frame in frames[1:]:assert receive(api,rx,frame)==0
    assert api.af_recipe_rx_validate(rx,memory(api.af_recipe_decode_work_bytes()))==0
    lease=Lease();value=c.POINTER(Owned)()
    assert api.af_recipe_rx_take(rx,c.byref(lease),c.byref(value))==0
    assert value.contents.message.image_bytes==2483 and value.contents.asset.matrix_mode==1
    assert list(value.contents.asset.sector_matrix)==list(asset.sector_matrix)
    ack,decoded=finish(api,rx,lease)
    assert api.af_recipe_tx_ack(tx,c.create_string_buffer(ack),128,c.byref(decoded))==0
    mixed=edit(edit(ack,8,1943),40,1)
    assert api.af_recipe_tx_ack(tx,c.create_string_buffer(mixed),128,c.byref(decoded))==-5
    assert api.af_recipe_rx_release(rx,c.byref(lease))==0
