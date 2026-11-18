"""公开Edit矩阵参数解码/代数表构造；不代表机身像素或任意校准构造器。"""
import base64
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


class Domain(c.Structure):
    _fields_=[('schema',c.c_uint32),('calibration_identity',c.c_uint8),
              ('output_gamut_mode',c.c_uint8),('trailing_padding',c.c_uint8*2)]


class Work(c.Structure):
    _fields_=[('config',c.c_uint8*552),('table',c.c_float*(1024*18))]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    target=tmp_path_factory.mktemp('edit-matrix-table')/'native.so'
    run=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror',
        '-ffp-contract=off','-shared','-fPIC',str(HOME/'native/af_edit_matrix_table.c'),
        '-o',str(target)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    result=c.CDLL(str(target));result.af_edit_matrix_table.argtypes=[c.c_void_p]*5+[Progress,c.c_void_p]
    return result


def source():
    d=json.loads((HOME/'tests/fixtures/edit_matrix_table_context4.json').read_text())
    assert d['commit']=='8b563d46f800679abd3f215950cb541fc81da2a6'
    p=c.create_string_buffer(bytes.fromhex(d['payload_hex']),276)
    config=bytes.fromhex(d['config_hex'])
    domain=Domain(1,1,3,(c.c_uint8*2)(*config[-2:]))
    return d,p,domain,config


def test_full_config_and_1024_sector_table_equal_published_runtime(api):
    d,p,domain,expected_config=source();before=bytes(p),bytes(domain)
    data=json.loads((HOME/'tests/fixtures/edit_reference_context4.json').read_text())['matrix_table']
    expected_table=zlib.decompress(base64.b64decode(data['zlib_base64'],validate=True))
    assert len(expected_table)==73728 and hashlib.sha256(expected_table).hexdigest()==d['table_sha256']
    cfg=(c.c_uint8*552)();table=(c.c_float*(1024*18))();work=Work()
    assert api.af_edit_matrix_table(p,c.byref(domain),c.byref(work),cfg,table,Progress(),None)==0
    assert bytes(cfg)==expected_config and bytes(table)==expected_table
    assert bytes(cfg[-2:])==b'\xff\xff' and (bytes(p),bytes(domain))==before


def test_coefficient_perturbation_interpolates_cyclic_sector_and_preserves_metadata(api):
    d,p,domain,base=source();raw=bytearray(p.raw);raw[24:216]=b'\0'*192
    domain.trailing_padding[:]=(0x12,0x34)
    # 六行×16扇区中第一项，半字交换后位于payload+26，数值为1/1024。
    struct.pack_into('<H',raw,26,4);payload=c.create_string_buffer(bytes(raw),276)
    cfg=(c.c_uint8*552)();table=(c.c_float*(1024*18))();work=Work()
    assert api.af_edit_matrix_table(payload,c.byref(domain),c.byref(work),cfg,table,Progress(),None)==0
    for sector,value in ((0,1/1024),(32,1/2048),(64,0),(960,0),(1023,63/65536)):
        row=list(table)[sector*18:sector*18+18]
        assert row[:3]==pytest.approx((1+value,-value,0),abs=1e-8)
        assert row[9:12]==pytest.approx((-value,value,0),abs=1e-8)
    assert bytes(cfg[:0x28])==base[:0x28] and bytes(cfg[0x1a8:-2])==base[0x1a8:-2]
    assert bytes(cfg[-2:])==b'\x12\x34'


def test_unmodeled_domain_bad_angle_and_alias_do_not_publish(api):
    _,p,domain,_=source();work=Work();cfg=(c.c_uint8*552)(*([0xa5]*552))
    table=(c.c_float*(1024*18)).from_buffer_copy(b'\x5a'*73728);before=bytes(cfg),bytes(table)
    for field,value in (('schema',0),('calibration_identity',0),('output_gamut_mode',2)):
        old=getattr(domain,field);setattr(domain,field,value)
        assert api.af_edit_matrix_table(p,c.byref(domain),c.byref(work),cfg,table,Progress(),None)==-1
        assert (bytes(cfg),bytes(table))==before;setattr(domain,field,old)
    raw=bytearray(p.raw);word=struct.unpack_from('<I',raw)[0];word=(word&~(1023<<11))|(64<<11)
    struct.pack_into('<I',raw,0,word);bad=c.create_string_buffer(bytes(raw),276)
    assert api.af_edit_matrix_table(bad,c.byref(domain),c.byref(work),cfg,table,Progress(),None)==-1
    assert (bytes(cfg),bytes(table))==before
    raw=bytearray(p.raw);struct.pack_into('<H',raw,63*4+2,0x2000)
    asymmetric=c.create_string_buffer(bytes(raw),276)
    assert api.af_edit_matrix_table(asymmetric,c.byref(domain),c.byref(work),cfg,table,Progress(),None)==-1
    assert (bytes(cfg),bytes(table))==before
    assert api.af_edit_matrix_table(p,c.byref(domain),c.byref(work),cfg,cfg,Progress(),None)==-1
    assert (bytes(cfg),bytes(table))==before


@pytest.mark.parametrize('cancel_at',(512,1024))
def test_cancel_during_or_after_table_keeps_both_published_outputs(api,cancel_at):
    _,p,domain,_=source();work=Work();cfg=(c.c_uint8*552)(*([0xa5]*552))
    table=(c.c_float*(1024*18)).from_buffer_copy(b'\x5a'*73728);before=bytes(cfg),bytes(table);calls=[]
    def progress(context,done,total):calls.append((done,total));return done==cancel_at
    callback=Progress(progress)
    assert api.af_edit_matrix_table(p,c.byref(domain),c.byref(work),cfg,table,callback,None)==-20
    assert calls[-1]==(cancel_at,1024) and (bytes(cfg),bytes(table))==before
