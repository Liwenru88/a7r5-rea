"""显式普通目录的CUBE浏览/稳定读取，不接触真实SD。"""
import ctypes as c
import hashlib
import os
from pathlib import Path
import subprocess

import pytest

NATIVE=Path(__file__).resolve().parents[1]/'native'
Progress=c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_uint32,c.c_uint32)
class Entry(c.Structure):
    _fields_=[('name',c.c_char*128),('device',c.c_uint64),('inode',c.c_uint64),
              ('size',c.c_uint64),('mtime',c.c_int64),('nanoseconds',c.c_int64)]
class Listing(c.Structure):
    _fields_=[('generation',c.c_uint64),('device',c.c_uint64),('inode',c.c_uint64),
              ('count',c.c_uint32),('entries',Entry*64)]
class Source(c.Structure):
    _fields_=[('bytes',c.c_uint32),('sha256',c.c_ubyte*32)]
@pytest.fixture(scope='module')
def api(tmp_path_factory):
    out=tmp_path_factory.mktemp('media-build')/'media.so'
    r=subprocess.run(['clang','-shared','-fPIC','-std=c11','-O2','-Wall','-Wextra','-Werror',
        str(NATIVE/'af_media.c'),str(NATIVE/'af_sha256.c'),'-o',str(out)],capture_output=True,text=True)
    assert r.returncode==0,r.stderr
    lib=c.CDLL(str(out));lib.af_media_scan.argtypes=[c.c_int,c.c_uint64,c.c_void_p,c.c_void_p]
    lib.af_media_read.argtypes=[c.c_int,c.c_void_p,c.c_uint32,c.c_void_p,c.c_size_t,c.c_void_p,Progress,c.c_void_p]
    return lib

def scan(api,root,generation=1):
    work=Listing();out=Listing();fd=os.open(root,os.O_RDONLY)
    try:status=api.af_media_scan(fd,generation,c.byref(work),c.byref(out))
    finally:os.close(fd)
    return status,out

def test_browse_sorted_read_exact_bytes_and_removal_does_not_change_copy(api,tmp_path):
    raw=b'LUT_3D_SIZE 2\n'+b'0 0 0\n'*8
    (tmp_path/'z.CUBE').write_bytes(raw);(tmp_path/'a.a7FILTER').write_bytes(raw)
    (tmp_path/'note.txt').write_text('ignore')
    status,items=scan(api,tmp_path,8)
    assert status==0 and items.count==2 and items.generation==8
    assert [x.name for x in items.entries[:2]]==[b'a.a7FILTER',b'z.CUBE']
    fd=os.open(tmp_path,os.O_RDONLY);buffer=c.create_string_buffer(4096);source=Source()
    try:assert api.af_media_read(fd,c.byref(items),0,buffer,len(buffer),c.byref(source),Progress(),None)==0
    finally:os.close(fd)
    (tmp_path/'a.a7FILTER').unlink()
    assert buffer.raw[:source.bytes]==raw and bytes(source.sha256)==hashlib.sha256(raw).digest()

def test_replaced_file_and_cancellation_never_publish_source(api,tmp_path):
    p=tmp_path/'test.cube';p.write_bytes(b'x'*32000);status,items=scan(api,tmp_path)
    assert status==0
    fd=os.open(tmp_path,os.O_RDONLY);buffer=c.create_string_buffer(40000);source=Source(777);before=bytes(source)
    try:
        cb=Progress(lambda _,done,total:int(done>0))
        assert api.af_media_read(fd,c.byref(items),0,buffer,len(buffer),c.byref(source),cb,None)==-20
        assert bytes(source)==before
        p.unlink();p.write_bytes(b'changed')
        assert api.af_media_read(fd,c.byref(items),0,buffer,len(buffer),c.byref(source),Progress(),None)==-5
        assert bytes(source)==before
    finally:os.close(fd)

def test_link_and_over_limit_listing_do_not_publish_partial_results(api,tmp_path):
    (tmp_path/'bad.cube').symlink_to('/dev/null');work=Listing();out=Listing();c.memset(c.byref(out),0xa5,c.sizeof(out));before=bytes(out)
    fd=os.open(tmp_path,os.O_RDONLY)
    try:assert api.af_media_scan(fd,1,c.byref(work),c.byref(out))<0 and bytes(out)==before
    finally:os.close(fd)
    (tmp_path/'bad.cube').unlink()
    long=tmp_path/('a'*128+'.cube');long.write_bytes(b'x')
    assert scan(api,tmp_path)[0]==-1
    long.unlink()
    for i in range(65):(tmp_path/f'{i:02}.cube').write_bytes(b'x')
    status,_=scan(api,tmp_path)
    assert status==-9

def test_same_size_rewrite_with_preserved_timestamp_cannot_publish_mixed_bytes(api,tmp_path):
    p=tmp_path/'race.cube';p.write_bytes(b'A'*32768);stamp=p.stat();status,items=scan(api,tmp_path)
    assert status==0
    changed=False
    def replace(_,done,total):
        nonlocal changed
        if done==16384 and not changed:
            changed=True;p.write_bytes(b'B'*32768)
            os.utime(p,ns=(stamp.st_atime_ns,stamp.st_mtime_ns))
        return 0
    fd=os.open(tmp_path,os.O_RDONLY);buffer=c.create_string_buffer(40000);source=Source(777);before=bytes(source)
    try:assert api.af_media_read(fd,c.byref(items),0,buffer,len(buffer),c.byref(source),Progress(replace),None)==-5
    finally:os.close(fd)
    assert changed and bytes(source)==before

@pytest.mark.parametrize('mutate_at',[2,6])
def test_progress_mutation_after_verified_bytes_never_publishes(api,tmp_path,mutate_at):
    (tmp_path/'callback.cube').write_bytes(b'A'*4096)
    status,items=scan(api,tmp_path);assert status==0
    buffer=c.create_string_buffer(8192);source=Source(777);before=bytes(source)
    callbacks=0
    def mutate(_,done,total):
        nonlocal callbacks
        if done==total:
            callbacks+=1
            if callbacks==mutate_at:buffer[0]=b'B'
        return 0
    fd=os.open(tmp_path,os.O_RDONLY)
    try:assert api.af_media_read(fd,c.byref(items),0,buffer,len(buffer),c.byref(source),Progress(mutate),None)==-5
    finally:os.close(fd)
    assert callbacks>=mutate_at and bytes(source)==before
