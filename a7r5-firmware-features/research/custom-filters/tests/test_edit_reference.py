"""公开Edit捕获向量核对整数像素算子；不证明相机或sRGB输入域。"""
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


class YGamma(c.Structure):
    _fields_=[('black_level',c.c_int16),('white_level',c.c_int16),
              ('pivot',c.c_int16),('gain',c.c_float)]


class Matrix(c.Structure):
    _fields_=[('table',c.c_void_p),('angles',c.c_void_p),('table_entries',c.c_size_t),
              ('angle_entries',c.c_size_t)]+[(name,c.c_uint16) for name in
              ('enabled','luma_smooth','chroma_smooth','scale_chroma','quadratic')]+[('thresholds',c.c_float*3)]


class Area(c.Structure):
    _fields_=[('coefficients',c.c_float*16),('selector',c.c_uint8)]


class Chroma(c.Structure):
    _fields_=[(name,c.c_int32) for name in ('high_cutoff','low_cutoff','high_slope','low_slope')]


class ChromaSource(c.Structure):
    _fields_=[('slopes',c.c_int16*3),('thresholds',c.c_int16*3),('low_slope',c.c_int16),
              ('low_threshold',c.c_int16),('gain_raw',c.c_int16),('exposure_300',c.c_int32)]


class ChromaTables(c.Structure):
    _fields_=[(name,c.c_void_p) for name in ('inverse_secondary','inverse_main','main_gamma','secondary_gamma')]+[
        (name,c.c_size_t) for name in ('inverse_secondary_entries','inverse_main_entries','main_entries','secondary_entries')]


def matrix_parameters(data):
    table=(c.c_float*(1024*18)).from_buffer_copy(unpack(data['matrix_table']))
    angles=(c.c_float*512).from_buffer_copy(unpack(data['matrix_angles']))
    p=data['matrix_parameters']
    result=Matrix(c.addressof(table),c.addressof(angles),len(table),len(angles),
        *(p[name] for name in ('enabled','luma_smooth','chroma_smooth','scale_chroma','quadratic')),
        (c.c_float*3)(*p['thresholds']))
    return result,table,angles


def chroma_parameters(data):
    s=data['chroma_source'];source=ChromaSource((c.c_int16*3)(*s['slopes']),
        (c.c_int16*3)(*s['thresholds']),s['low_slope'],s['low_threshold'],s['gain_raw'],s['exposure_300'])
    arrays=[u16(unpack(data['chroma_tables'][name])) for name in
            ('inverse_secondary','inverse_main','main_gamma','secondary_gamma')]
    tables=ChromaTables(*(c.addressof(a) for a in arrays),*(len(a) for a in arrays))
    return source,tables,arrays


def unpack(item):
    raw=zlib.decompress(base64.b64decode(item['zlib_base64'],validate=True))
    assert len(raw)==item['bytes'] and hashlib.sha256(raw).hexdigest()==item['sha256']
    return raw


def u16(raw):
    return (c.c_uint16*(len(raw)//2))(*struct.unpack('<'+'H'*(len(raw)//2),raw))


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    target=tmp_path_factory.mktemp('edit-ref')/'reference.so'
    run=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror',
        '-ffp-contract=off','-shared','-fPIC',str(HOME/'native/af_edit_reference.c'),
        '-o',str(target)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    result=c.CDLL(str(target))
    result.af_edit_ref_main_gamma.argtypes=[c.c_void_p,c.c_size_t,c.c_void_p,c.c_size_t,c.c_void_p]
    result.af_edit_ref_rgb_ycc.argtypes=[c.c_void_p,c.c_size_t,c.c_void_p,c.c_void_p,c.c_uint,c.c_void_p]
    result.af_edit_ref_y_gamma.argtypes=[c.c_void_p,c.c_size_t,c.c_void_p,c.c_void_p,c.c_size_t,c.c_void_p]
    result.af_edit_ref_ycc_rgb.argtypes=[c.c_void_p,c.c_size_t,c.c_void_p]
    result.af_edit_ref_matrix16.argtypes=[c.c_void_p,c.c_void_p,c.c_size_t,c.c_size_t,c.c_void_p]
    result.af_edit_ref_area.argtypes=[c.c_void_p,c.c_void_p,c.c_size_t,c.c_void_p]
    result.af_edit_ref_chroma_controls.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p]
    result.af_edit_ref_chroma.argtypes=[c.c_void_p,c.c_void_p,c.c_size_t,c.c_void_p]
    return result


@pytest.fixture(scope='module')
def fixture():
    data=json.loads((HOME/'tests/fixtures/edit_reference_context4.json').read_text())
    assert data['commit']=='8b563d46f800679abd3f215950cb541fc81da2a6' and data['context']==4
    assert data['capture_report_sha256']=='9e8ebb61859515ea5d473110209ceb71e4bd212eda8f43a4eb4cdd049b376e1e'
    assert len(data['source_buffers'])==46
    return data


@pytest.mark.parametrize('stage',('main-gamma','rgb-ycc','y-gamma','ycc-rgb','matrix16','area-comp','chroma-suppress'))
def test_seven_operators_equal_published_context4_actual_stage_outputs(api,fixture,stage):
    data=fixture['goldens'][stage];source=u16(unpack(data['input']))
    expected=unpack(data['output']);pixels=len(source)//3
    output=(c.c_uint16*len(source))(*([0xa5a5]*len(source)));before=bytes(source)
    assert pixels==1024
    if stage=='main-gamma':
        table=u16(unpack(fixture['main_gamma']))
        status=api.af_edit_ref_main_gamma(table,len(table),source,pixels,output)
    elif stage=='rgb-ycc':
        coefficients=(c.c_int16*8)(*fixture['cc1']);luma=(c.c_int16*3)(*fixture['luma'])
        status=api.af_edit_ref_rgb_ycc(source,pixels,coefficients,luma,fixture['keep_unclipped'],output)
    elif stage=='y-gamma':
        table=u16(unpack(fixture['y_gamma']));parameters=YGamma(**fixture['y_parameters'])
        status=api.af_edit_ref_y_gamma(table,len(table),c.byref(parameters),source,pixels,output)
    elif stage=='ycc-rgb':
        status=api.af_edit_ref_ycc_rgb(source,pixels,output)
    elif stage=='matrix16':
        parameters,table,angles=matrix_parameters(fixture)
        height,width=data['shape']
        status=api.af_edit_ref_matrix16(c.byref(parameters),source,width,height,output)
    elif stage=='area-comp':
        p=fixture['area_parameters'];parameters=Area((c.c_float*16)(*p['coefficients']),p['selector'])
        status=api.af_edit_ref_area(c.byref(parameters),source,pixels,output)
    else:
        s,t,arrays=chroma_parameters(fixture);parameters=Chroma()
        assert api.af_edit_ref_chroma_controls(c.byref(s),c.byref(t),c.byref(parameters))==0
        assert {name:getattr(parameters,name) for name,_ in Chroma._fields_}==fixture['chroma_expected']
        status=api.af_edit_ref_chroma(c.byref(parameters),source,pixels,output)
    assert status==0 and bytes(source)==before
    actual=bytes(output)
    if stage=='matrix16':
        # 原采样窗只有内部列含真实左右邻点，不能把人工窗边当原图边。
        actual=b''.join(actual[(row*width+2)*6:(row*width+width-2)*6] for row in range(height))
        expected=b''.join(expected[(row*width+2)*6:(row*width+width-2)*6] for row in range(height))
    if actual!=expected:
        got=struct.unpack('<'+'H'*(len(actual)//2),actual);want=struct.unpack('<'+'H'*(len(expected)//2),expected)
        differences=[(i,g,w) for i,(g,w) in enumerate(zip(got,want)) if g!=w]
        pytest.fail(f'{stage}: {len(differences)}项不同，前八项{differences[:8]}')


def test_extra_color_stage_rejections_and_no_hidden_identity_default(api,fixture):
    source=(c.c_uint16*15)(*(list(range(5))*3));output=(c.c_uint16*15)(*([0xa5a5]*15));before=bytes(output)
    p,table,angles=matrix_parameters(fixture);p.luma_smooth=2
    assert api.af_edit_ref_matrix16(c.byref(p),source,5,1,output)==-1 and bytes(output)==before
    p.luma_smooth=1;table[0]=float('nan')
    assert api.af_edit_ref_matrix16(c.byref(p),source,5,1,output)==-1 and bytes(output)==before
    p.enabled=0
    assert api.af_edit_ref_matrix16(c.byref(p),source,5,1,output)==0 and bytes(output)==bytes(source)
    output[:]=[0xa5a5]*15
    area=Area((c.c_float*16)(),2)
    assert api.af_edit_ref_area(c.byref(area),source,5,output)==-1 and bytes(output)==before
    area.selector=0;area.coefficients[15]=float('inf')
    assert api.af_edit_ref_area(c.byref(area),source,5,output)==-1 and bytes(output)==before
    s,t,arrays=chroma_parameters(fixture);params=Chroma(1,2,3,4);saved=bytes(params)
    s.gain_raw=0
    assert api.af_edit_ref_chroma_controls(c.byref(s),c.byref(t),c.byref(params))==-1 and bytes(params)==saved
    s.gain_raw=64;t.inverse_main_entries-=1
    assert api.af_edit_ref_chroma_controls(c.byref(s),c.byref(t),c.byref(params))==-1 and bytes(params)==saved


def test_chroma_signed_luma_integer_rounding_and_explicit_area_wrap(api):
    p=Chroma(100,0,4096,4096);source=(c.c_uint16*9)(65535,0,65535,100,32769,32767,101,0,65535)
    result=(c.c_uint16*9)()
    assert api.af_edit_ref_chroma(c.byref(p),source,3,result)==0
    assert list(result)==[0,256,65279,100,32768,32768,101,256,65279]
    # 原AreaComp低16位存储须保留，不能替换成0..65535限幅。
    coefficients=(c.c_float*16)();coefficients[4]=1;coefficients[5]=1;coefficients[12]=2
    area=Area(coefficients,0);src=(c.c_uint16*3)(100,65535,32768);out=(c.c_uint16*3)()
    assert api.af_edit_ref_area(c.byref(area),src,1,out)==0
    assert list(out)==[100,65533,32768]


def test_native_signed_luma_and_explicit_chroma_clip_are_preserved(api):
    # 有符号负亮度的ASR与向零截断不同；两条色度都须限幅。
    source=(c.c_int16*6)(-32768,32767,0,32767,-32768,0)
    coefficients=(c.c_int16*8)(0,0,0,0,2040,2040,2040,2040)
    luma=(c.c_int16*3)(8192,0,0);output=(c.c_uint16*6)()
    assert api.af_edit_ref_rgb_ycc(source,2,coefficients,luma,0,output)==0
    assert list(output)==[32768,24576,24576,32767,40959,40959]
    assert api.af_edit_ref_rgb_ycc(source,2,coefficients,luma,1,output)==0
    assert list(output)==[32768,0,0,32767,65535,65535]
    tiny=(c.c_int16*3)(-1,0,0);weights=(c.c_int16*3)(1,0,0)
    assert api.af_edit_ref_rgb_ycc(tiny,1,coefficients,weights,0,output)==0 and output[0]==65535


def test_bad_late_pixel_bounds_overlap_or_y_configuration_never_publish(api,fixture):
    source=(c.c_uint16*6)(1,2,3,4,5,6);output=(c.c_uint16*6)(*([0xa5a5]*6))
    table=u16(unpack(fixture['main_gamma']));before=bytes(output)
    source[5]=32768
    assert api.af_edit_ref_main_gamma(table,len(table),source,2,output)==-1 and bytes(output)==before
    source[5]=6
    for count in (0,4097):
        assert api.af_edit_ref_main_gamma(table,len(table),source,count,output)==-1 and bytes(output)==before
    assert api.af_edit_ref_main_gamma(table,len(table)-1,source,2,output)==-1 and bytes(output)==before
    assert api.af_edit_ref_ycc_rgb(source,2,source)==-1
    ytable=u16(unpack(fixture['y_gamma']));p=YGamma(**fixture['y_parameters'])
    source[3]=32768
    assert api.af_edit_ref_y_gamma(ytable,len(ytable),c.byref(p),source,2,output)==-1 and bytes(output)==before
    source[3]=4;p.gain=float('nan')
    assert api.af_edit_ref_y_gamma(ytable,len(ytable),c.byref(p),source,2,output)==-1 and bytes(output)==before
    p.gain=1;p.white_level=512
    assert api.af_edit_ref_y_gamma(ytable,len(ytable),c.byref(p),source,2,output)==-1 and bytes(output)==before
    p.white_level=511;p.gain=3.4e38
    assert api.af_edit_ref_y_gamma(ytable,len(ytable),c.byref(p),source,2,output)==-1 and bytes(output)==before
