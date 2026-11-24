"""真实CP资源接收器的分配、复用、代际隔离和发送失败。"""
import ctypes as C
import struct
import zlib
import pytest
from runtime_support import CP, decoded
from test_runtime_transport import codec, upload


def probe(token=77):
    p=struct.pack('<4B6I',0xe8,1,1,32,0x32503552,token,0,0xfff,0,0)
    return p+struct.pack('<I',zlib.crc32(p))


def prepare(images,budget=1048576):
    cp=CP(images[3]);cp.receiver_services(budget)
    ack=cp.consume(probe())
    assert len(ack)==32 and struct.unpack_from('<I',ack,20)[0]==28768
    cp.receive=cp.consume
    return cp


def test_resume_reuses_sealed_bank_with_no_allocation_and_late_put_is_rejected(images,codec):
    cp=prepare(images);value=decoded(codec)
    assert upload(codec,cp,value)[0].phase==4
    active=cp.words(0x1a39448,1)[0]
    snapshot=cp.read(active,522152)
    assert cp.heap_allocations==[522152]
    state,acks=upload(codec,cp,value)
    assert state.phase==4 and len(acks)==1 and cp.heap_allocations==[522152]
    assert cp.read(active,522152)==snapshot
    late=bytearray(struct.pack('<4B7I',0xe7,3,2,0,0x584e3552,0x1234,0xfff,1,state.crc,1,0)+bytes(2392))
    struct.pack_into('<I',late,28,zlib.crc32(late))
    ack=cp.consume(bytes(late))
    assert struct.unpack_from('<I',ack,36)[0]==2
    assert cp.read(active,522152)==snapshot
    assert cp.consume(probe(),source=0x12345678) is None


def test_shared_heap_resource_failure_preserves_published_generations(images,codec):
    cp=prepare(images);value=decoded(codec)
    assert upload(codec,cp,value)[0].phase==4
    first=cp.words(0x1a39448,1)[0];saved=cp.read(first,522152)
    value.look[0].gamma[100]+=1
    assert upload(codec,cp,value)[0].phase==4
    second=cp.words(0x1a39448,1)[0]
    assert second!=first and cp.heap_used==2*522152
    value.look[0].gamma[100]+=1
    state,acks=upload(codec,cp,value)
    assert state.phase==5 and struct.unpack_from('<I',acks[-1],36)[0]==6
    assert cp.words(0x1a39448,1)[0]==second and cp.read(first,522152)==saved
    assert cp.words(0x1a39450+4,1)[0]==2


def test_receive_reply_failure_frees_message_without_reallocating_bank(images):
    cp=CP(images[3]);cp.receiver_services();cp.send_failure=True
    assert cp.consume(probe()) is not None
    assert cp.frees==1 and cp.heap_allocations==[522152]
    cp.consume(probe(88))
    assert cp.frees==2 and cp.heap_allocations==[522152]


def test_native_grid_restore_matches_original_builder_and_reuses_immutable_cache(images,codec):
    cp=CP(images[3]);value=decoded(codec)
    assert upload(codec,cp,value)[0].phase==4
    root,env,state,raw,w,out,work=0x3120000,0x3121000,0x3122000,0x3123000,0x3124000,0x3125000,0x3126000
    meta=0x3127000
    cp.write(raw,bytes((i%127 for i in range(1215))))
    cp.write(env+6,b'\1');cp.write(meta+11,b'\3')
    cp.write(w,struct.pack('<II',root,env))
    cp.write(out,struct.pack('<5I',0,0,state,work,meta))
    total=0
    for kind,transform,level in ((0,0,0),(0,1,8),(1,2,0),(1,2,1),(1,2,7),(1,2,8),(1,2,9),(2,0,3),(2,1,8),(2,2,7)):
        cp.write(root+0x2f,bytes([level]))
        cp.write(state+0x184,struct.pack('<IBB',raw,kind,transform))
        cp.call(0x231655,w,out)
        expected=cp.read(work+92,1620)
        packed=cp.call('r5_grid422_restore',cp.BANK,root,state)
        assert packed and cp.read(packed,1620)==expected
        snapshot=cp.read(packed,1620)
        assert cp.call('r5_grid422_restore',cp.BANK,root,state)==packed
        assert cp.read(packed,1620)==snapshot
        total=cp.words(cp.BANK+207880,1)[0]
    assert total<10, '>=8档应复用同一快照'
    # 填满31个已提交项后仍允许命中；新内容必须显式拒绝，不能覆盖旧项。
    old=cp.read(packed,1620)
    for i in range(40):
        cp.write(raw,bytes([i]))
        result=cp.call('r5_grid422_restore',cp.BANK,root,state)
        if not result:break
    assert not result and cp.words(cp.BANK+207880,1)[0]==31
    assert cp.read(packed,1620)==old
