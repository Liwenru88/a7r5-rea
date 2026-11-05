"""精确参数坐标适配；不推断硬件Gamma插值或sRGB归一化。"""
import ctypes as c
import hashlib
import json
from pathlib import Path
import struct
import subprocess

import pytest
from test_native_gamma406 import source

HOME = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    path=tmp_path_factory.mktemp('edit-axis')/'bridge.so'
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
        str(HOME/'native/af_gamma406.c'),str(HOME/'native/af_edit_gamma_bridge.c'),'-o',str(path)],
        capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    lib=c.CDLL(str(path))
    lib.af_edit_gamma_bridge.argtypes=[c.c_void_p]*4
    lib.af_gamma406_axis.argtypes=[c.c_void_p]*2
    return lib


def parameters():
    data=json.loads((HOME/'tests/fixtures/edit_gamma_axis_bridge.json').read_text())
    return data,(c.c_uint32*128)(*data['edit_x']),(c.c_uint32*128)(*data['edit_y'])


def test_public_curve_preserves_18bit_common_nodes_and_cp_metadata(api):
    data,x,y=parameters();raw=bytes(source());record=c.create_string_buffer(raw)
    axis=(c.c_uint32*129)();assert api.af_gamma406_axis(record,axis)==0
    assert hashlib.sha256(bytes(axis)).hexdigest()==data['cp_axis_sha256']
    out=c.create_string_buffer(b'\xa5'*576,576)
    assert api.af_edit_gamma_bridge(x,y,record,out)==0
    actual=struct.unpack_from('<129I',out.raw)
    assert actual[:127]==tuple(y)[:127] and actual[128]==y[127]
    assert actual[127]==261892 and max(actual)>131071
    expected=bytearray(raw);struct.pack_into('<129I',expected,0,*actual)
    struct.pack_into('<I',expected,0x220,actual[-1])
    assert out.raw==expected and record.raw[:-1]==raw


def test_missing_node_has_explicit_linear_floor_and_failures_do_not_publish(api):
    _,x,y=parameters();record=c.create_string_buffer(bytes(source()))
    y[126]=240001;y[127]=262143
    # 先保证前段单调；末段并非原捕获，仅验证声明的重采样次序。
    for i in range(126):y[i]=i*1800
    out=c.create_string_buffer(b'\xa5'*576,576)
    assert api.af_edit_gamma_bridge(x,y,record,out)==0
    expected=240001+(262143-240001)*(61440*32-x[126])//(x[127]-x[126])
    assert struct.unpack_from('<I',out.raw,127*4)[0]==expected
    before=out.raw;x[80]+=1
    assert api.af_edit_gamma_bridge(x,y,record,out)==-1 and out.raw==before
    x[80]-=1;y[127]=262144
    assert api.af_edit_gamma_bridge(x,y,record,out)==-1 and out.raw==before
    assert api.af_edit_gamma_bridge(x,y,record,record)==-1
