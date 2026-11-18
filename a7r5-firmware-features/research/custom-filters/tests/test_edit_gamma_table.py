"""完整Edit参数表重建；公开runtime逐字节对照，不是sRGB或机身ISP证明。"""
import base64
import bisect
import ctypes as c
import hashlib
import json
from pathlib import Path
import struct
import subprocess
import zlib

import pytest

HOME=Path(__file__).resolve().parents[1]
Progress=c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_uint32,c.c_uint32)


class Work(c.Structure):
    _fields_=[('table',c.c_uint16*65536)]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    target=tmp_path_factory.mktemp('edit-gamma-table')/'native.so'
    run=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror',
        '-ffp-contract=off','-shared','-fPIC',str(HOME/'native/af_edit_gamma_table.c'),
        '-o',str(target)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    result=c.CDLL(str(target))
    result.af_edit_gamma_table.argtypes=[c.c_void_p]*5+[Progress,c.c_void_p]
    result.af_edit_gamma_main_inverse.argtypes=[c.c_void_p,c.c_uint16,c.c_void_p,c.c_void_p,Progress,c.c_void_p]
    result.af_edit_gamma_secondary_inverse.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p,Progress,c.c_void_p]
    return result


def parameters():
    data=json.loads((HOME/'tests/fixtures/edit_gamma_axis_bridge.json').read_text())
    assert data['commit']=='8b563d46f800679abd3f215950cb541fc81da2a6'
    assert data['source_raw_sha256']=='986cbbf413a72d196e4ba64d2ca08503c66706338beed7267acd5c69fb2b1acc'
    axis=(c.c_uint32*128)(*data['edit_x']);curve=(c.c_uint32*128)(*data['edit_y'])
    # 公开static_tables.json中10025bea8:1025:<i4的完整数值与摘要。
    contrast=(c.c_int32*1025)(*[i*64 for i in range(1024)],65535)
    assert hashlib.sha256(struct.pack('<1025i',*contrast)).hexdigest()=='0de0274b973d87b2b3dfeefa116b228cca9f7efd29f0290719bf82d7abfac500'
    return axis,curve,contrast


def expected():
    data=json.loads((HOME/'tests/fixtures/edit_reference_context4.json').read_text())
    item=data['main_gamma'];raw=zlib.decompress(base64.b64decode(item['zlib_base64'],validate=True))
    assert len(raw)==131072 and hashlib.sha256(raw).hexdigest()==item['sha256']
    assert data['source_buffers'][0]['sha256']=='082d904742375cf85c04b181e79353a5864026c56e9a55ee25c3a8ee777bf60e'
    return raw


def inverse_data():
    data=json.loads((HOME/'tests/fixtures/edit_reference_context4.json').read_text())['chroma_tables']
    result={}
    for name in ('main_gamma','secondary_gamma','inverse_main','inverse_secondary'):
        item=data[name];raw=zlib.decompress(base64.b64decode(item['zlib_base64'],validate=True))
        assert len(raw)==item['bytes'] and hashlib.sha256(raw).hexdigest()==item['sha256']
        result[name]=raw
    return result


def test_all_65536_gamma_entries_equal_public_runtime_and_preserve_sources(api):
    axis,curve,contrast=parameters();inputs=bytes(axis),bytes(curve),bytes(contrast)
    work=Work();out=(c.c_uint16*65536)(*([0xa5a5]*65536))
    assert api.af_edit_gamma_table(axis,curve,contrast,c.byref(work),out,Progress(),None)==0
    assert bytes(out)==expected() and (bytes(axis),bytes(curve),bytes(contrast))==inputs
    assert max(curve)==261892 and max(curve)>131071
    assert out[32768]==0 and out[0]==((-out[65535])&65535)
    assert out[32767]==0 and out[32769]>0


def test_top_contrast_index_is_1023_and_negative_layout_is_explicit(api):
    axis,curve,contrast=parameters();curve[:]=[0]+[262143]*127
    work=Work();out=(c.c_uint16*65536)()
    assert api.af_edit_gamma_table(axis,curve,contrast,c.byref(work),out,Progress(),None)==0
    assert out[32768+8]==16368 and out[65535]==16368
    before=bytes(out);contrast[1024]=2147483647
    assert api.af_edit_gamma_table(axis,curve,contrast,c.byref(work),out,Progress(),None)==0
    assert bytes(out)==before
    assert list(out[:32768])==[((-out[65535-i])&65535) for i in range(32768)]


@pytest.mark.parametrize('cancel_at',(0,32768,65536))
def test_cancel_before_during_or_after_work_never_publishes(api,cancel_at):
    axis,curve,contrast=parameters();work=Work();out=(c.c_uint16*65536)(*([0xa5a5]*65536))
    before=bytes(out);calls=[]
    def progress(context,done,total):
        calls.append((done,total));return done==cancel_at
    callback=Progress(progress)
    assert api.af_edit_gamma_table(axis,curve,contrast,c.byref(work),out,callback,None)==-20
    assert calls[-1]==(cancel_at,65536) and bytes(out)==before


def test_invalid_late_parameter_or_buffer_alias_never_publishes(api):
    axis,curve,contrast=parameters();work=Work();out=(c.c_uint16*65536)(*([0xa5a5]*65536));before=bytes(out)
    curve[127]=262144
    assert api.af_edit_gamma_table(axis,curve,contrast,c.byref(work),out,Progress(),None)==-1 and bytes(out)==before
    curve[127]=261892;axis[127]=axis[126]
    assert api.af_edit_gamma_table(axis,curve,contrast,c.byref(work),out,Progress(),None)==-1 and bytes(out)==before
    axis,curve,contrast=parameters();contrast[1024]=-1
    assert api.af_edit_gamma_table(axis,curve,contrast,c.byref(work),out,Progress(),None)==-1 and bytes(out)==before
    contrast[1024]=65535
    assert api.af_edit_gamma_table(axis,curve,contrast,c.byref(work),c.byref(work),Progress(),None)==-1
    assert api.af_edit_gamma_table(c.byref(work),curve,contrast,c.byref(work),out,Progress(),None)==-1 and bytes(out)==before


@pytest.mark.parametrize('kind',('main','secondary'))
def test_entire_inverse_tables_equal_public_runtime(api,kind):
    data=inverse_data();source=(c.c_int16*65536).from_buffer_copy(data[kind+'_gamma'])
    expected_bytes=data['inverse_'+kind];output=(c.c_uint16*(len(expected_bytes)//2))()
    work=Work();before=bytes(source)
    if kind=='main':
        initial_zero=struct.unpack_from('<H',expected_bytes)[0]
        status=api.af_edit_gamma_main_inverse(source,initial_zero,c.byref(work),output,Progress(),None)
    else:
        status=api.af_edit_gamma_secondary_inverse(source,c.byref(work),output,Progress(),None)
    assert status==0 and bytes(output)==expected_bytes and bytes(source)==before


def test_inverse_strict_next_comparison_repeats_negative_indices_and_initial_zero(api):
    source=(c.c_int16*65536)(*([-999]*32768+[0,5,5,10]+[20]*32764))
    work=Work();output=(c.c_uint16*65536)();secondary=(c.c_uint16*16384)()
    assert api.af_edit_gamma_main_inverse(source,0x1234,c.byref(work),output,Progress(),None)==0
    assert output[0]==0x1234
    positive=list(source)[32769:]
    values=[bisect.bisect_left(positive,target) for target in range(32768)]
    assert list(output[32768:])==values
    assert list(output[1:32768])==[(-v)&65535 for v in values[1:][::-1]]
    assert [output[32768+i] for i in (0,5,6,10,11,20,21,32767)]==[0,0,2,2,3,3,32767,32767]
    assert api.af_edit_gamma_secondary_inverse(source,c.byref(work),secondary,Progress(),None)==0
    assert list(secondary)==values[:16384]


@pytest.mark.parametrize('kind,cancel_at',(('main',65536),('secondary',8192)))
def test_inverse_cancellation_and_invalid_input_leave_previous_output(api,kind,cancel_at):
    data=inverse_data();source=(c.c_int16*65536).from_buffer_copy(data[kind+'_gamma']);work=Work()
    length=65536 if kind=='main' else 16384;output=(c.c_uint16*length)(*([0xa5a5]*length));before=bytes(output)
    calls=[]
    def progress(context,done,total):calls.append((done,total));return done==cancel_at
    callback=Progress(progress)
    def call(cb):
        if kind=='main':return api.af_edit_gamma_main_inverse(source,0x1234,c.byref(work),output,cb,None)
        return api.af_edit_gamma_secondary_inverse(source,c.byref(work),output,cb,None)
    assert call(callback)==-20 and calls[-1][0]==cancel_at and bytes(output)==before
    source[65535]=-32768
    assert call(Progress())==-1 and bytes(output)==before
