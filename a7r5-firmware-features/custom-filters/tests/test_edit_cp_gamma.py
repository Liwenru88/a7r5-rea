"""固定ST/CP第6列到Edit的数值格式桥；不是sRGB或ISP应用证据。"""
import base64
import ctypes as c
import hashlib
import json
from pathlib import Path
import struct
import subprocess

import pytest

HOME=Path(__file__).resolve().parents[1]
Progress=c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_uint32,c.c_uint32)
RECORD_SHA='f4e9f31bce38b4c705721a501c7597705852e671bc39baf60b02dac8b88f95ac'
# 本包锁定CP的wire0/column6/0xdcca0c原576B记录；只作数值夹具，不是整固件。
RECORD_BASE64='AAAAABkEAAAxCAAASgwAAGMQAAB7FAAAlBgAAK0cAADGIAAA3iQAAPcoAAAQLQAAKDEAAEE1AABSOQAASj0AACpBAADzRAAAqEgAAEpMAADbTwAAW1MAAMxWAAAuWgAAgl0AAMpgAAAEZAAAM2cAAFZqAABvbQAAfHAAAIBzAAB5dgAAaXkAAFB8AAAtfwAAAoIAAM6EAACShwAATooAAAKNAACujwAAU5IAAPCUAACGlwAAFZoAAJ2cAAAenwAAmaEAAAykAAB6pgAA4agAAEKrAACdrQAA8q8AAEGyAACKtAAAzbYAAAu5AABDuwAAdr0AAKO/AADLwQAA7sMAAAzGAABQzgAAR9YAAPXdAABd5QAAhOwAAGvzAAAW+gAAiAABAMMGAQDJDAEAnhIBAEIYAQC4HQEAAiMBACIoAQAZLQEAfz8BANFPAQBcXgEAXWsBAAp3AQCQgQEAEosBALKTAQCLmwEAsqIBAD2pAQA9rwEAwLQBANO5AQCCvgEA1sIBANnGAQCSygEAB84BAEDRAQBB1AEAD9cBAK7ZAQAj3AEAmuABAIvkAQAK6AEAJ+sBAPDtAQBv8AEArfIBALT0AQCJ9gEAMvgBALX5AQAV+wEAV/wBAH39AQCL/gEAgv8BAIL/AQCC/wEAgv8BAIL/AQCC/wEAgv8BAIL/AQCC/wEAAAABAgMEBQQDBAQDAAAAAAAAAAAQAAEABgAAAIL/AQAAAAAAcGyYAXJsmAF0bJgBAAAAAAAAAAACAAAA'


class Output(c.Structure):
    _fields_=[('axis',c.c_uint32*128),('gamma_y',c.c_uint32*128)]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    target=tmp_path_factory.mktemp('edit-cp-gamma')/'native.so'
    run=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
        *[str(HOME/'native'/name) for name in ('af_edit_cp_gamma.c','af_gamma406.c','af_sha256.c')],
        '-o',str(target)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    lib=c.CDLL(str(target))
    lib.af_edit_cp_gamma.argtypes=[c.c_void_p,c.c_size_t,c.c_void_p,c.c_size_t,
                                   c.c_void_p,Progress,c.c_void_p]
    return lib


def parameters():
    raw=base64.b64decode(RECORD_BASE64,validate=True)
    assert len(raw)==576 and hashlib.sha256(raw).hexdigest()==RECORD_SHA
    data=json.loads((HOME/'tests/fixtures/edit_gamma_axis_bridge.json').read_text())
    assert data['source_raw_sha256']=='986cbbf413a72d196e4ba64d2ca08503c66706338beed7267acd5c69fb2b1acc'
    return raw,data,(c.c_uint32*129)(*struct.unpack_from('<129I',raw))


def missing_point(left,right):
    # 声明的纯参数往返：Edit线性向下取整，再(Y+1)//2回到CP整数。
    y=2*left+(2*(right-left)*4096)//8191
    return (y+1)//2


def synthetic_curve(data):
    axis=[x//32 for x in data['edit_x'][:127]]+[61440,data['edit_x'][-1]//32]
    values=[(x*100003)//65535 for x in axis]
    values[127]=missing_point(values[126],values[128])
    return (c.c_uint32*129)(*values)


def test_baseline_and_nonzero_representable_candidate_are_exact_and_self_contained(api):
    raw,data,curve=parameters();record=c.create_string_buffer(raw)
    for candidate in (curve,synthetic_curve(data)):
        guarded=c.create_string_buffer(b'\xa5'*(1024+32),1024+32)
        out=Output.from_buffer(guarded,16)
        before=bytes(candidate)
        assert api.af_edit_cp_gamma(record,576,candidate,129,c.byref(out),Progress(),None)==0
        assert list(out.axis)==data['edit_x']
        assert list(out.gamma_y)==[2*candidate[i] for i in range(127)]+[2*candidate[128]]
        if candidate is curve:assert list(out.gamma_y)==data['edit_y']
        assert guarded.raw[:16]==guarded.raw[-16:]==b'\xa5'*16
        assert bytes(candidate)==before and record.raw[:-1]==raw
    snapshot=bytes(out);candidate[100]+=1
    assert bytes(out)==snapshot


def test_missing_61440_has_explicit_rounding_and_independent_value_is_not_dropped(api):
    raw,data,_=parameters();record=c.create_string_buffer(raw)
    curve=synthetic_curve(data);curve[126]=120001;curve[128]=130947
    curve[127]=missing_point(curve[126],curve[128])
    assert curve[127]==125475
    out=Output();assert api.af_edit_cp_gamma(record,576,curve,129,c.byref(out),Progress(),None)==0
    before=bytes(out);curve[127]-=1
    assert api.af_edit_cp_gamma(record,576,curve,129,c.byref(out),Progress(),None)==-21
    assert bytes(out)==before
    curve[127]+=2
    assert api.af_edit_cp_gamma(record,576,curve,129,c.byref(out),Progress(),None)==-21
    assert bytes(out)==before


def test_invalid_source_shape_curve_and_alias_never_publish(api):
    raw,data,curve=parameters();record=c.create_string_buffer(raw)
    out=Output();c.memset(c.byref(out),0xa5,c.sizeof(out));before=bytes(out)
    for size,count in ((575,129),(577,129),(576,128),(576,130)):
        assert api.af_edit_cp_gamma(record,size,curve,count,c.byref(out),Progress(),None)==-1
        assert bytes(out)==before
    corrupt=bytearray(raw);corrupt[-1]^=1
    assert api.af_edit_cp_gamma(c.create_string_buffer(bytes(corrupt)),576,curve,129,c.byref(out),Progress(),None)==-1
    assert bytes(out)==before
    for index,value,expected in ((100,0,-1),(0,1,-1),(128,0,-1),(128,262144,-1),(128,131072,-21)):
        trial=(c.c_uint32*129)(*curve);trial[index]=value
        assert api.af_edit_cp_gamma(record,576,trial,129,c.byref(out),Progress(),None)==expected
        assert bytes(out)==before
    for source,candidate in ((None,curve),(record,None)):
        assert api.af_edit_cp_gamma(source,576,candidate,129,c.byref(out),Progress(),None)==-1
        assert bytes(out)==before
    assert api.af_edit_cp_gamma(record,576,curve,129,None,Progress(),None)==-1
    shared=c.create_string_buffer(b'\xa5'*1600,1600)
    c.memmove(shared,raw,576);saved=shared.raw
    assert api.af_edit_cp_gamma(shared,576,curve,129,shared,Progress(),None)==-1
    assert shared.raw==saved
    c.memmove(shared,bytes(curve),516);saved=shared.raw
    assert api.af_edit_cp_gamma(record,576,shared,129,c.byref(shared,512),Progress(),None)==-1
    assert shared.raw==saved
    assert api.af_edit_cp_gamma(record,576,c.byref(shared,1),129,c.byref(out),Progress(),None)==-1
    assert bytes(out)==before
    assert api.af_edit_cp_gamma(record,576,curve,129,c.byref(shared,1),Progress(),None)==-1
    assert shared.raw==saved


@pytest.mark.parametrize('cancel_at',(0,128))
def test_early_and_final_cancellation_preserve_output(api,cancel_at):
    raw,_,curve=parameters();record=c.create_string_buffer(raw)
    out=Output();c.memset(c.byref(out),0xa5,c.sizeof(out));before=bytes(out);calls=[]
    def progress(context,done,total):
        calls.append((done,total));return done==cancel_at
    callback=Progress(progress)
    assert api.af_edit_cp_gamma(record,576,curve,129,c.byref(out),callback,None)==-20
    assert calls[-1]==(cancel_at,128) and bytes(out)==before
