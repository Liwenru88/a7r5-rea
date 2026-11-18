"""网格C接口的测试ABI和公开模型数值；不读取相机或SD。"""
import ctypes as c
import hashlib
import json
from pathlib import Path


class Model(c.Structure):
    _fields_=[('schema',c.c_uint32),('base_mask',c.c_uint32),('smooth',c.c_uint32),
              ('coordinates',c.c_float*12),('response',c.c_float*36),('sha256',c.c_uint8*32)]


class Sample(c.Structure):
    _fields_=[('rgb',c.c_float*3),('weight',c.c_float),('group',c.c_uint32)]


class Row(c.Structure):
    _fields_=[('index',c.c_uint16*8),('weights',c.c_float*8),('response',c.c_float*9),
              ('base',c.c_float*3),('target',c.c_float*3),('mass',c.c_float)]


class Work(c.Structure):
    _fields_=[('rows',Row*4096),*[(name,c.c_float*1215) for name in ('x','y','next','gradient','best')],
              ('errors',c.c_float*4096)]


class Fit(c.Structure):
    _fields_=[(k,c.c_uint32) for k in ('iterations','converged','limited','zero_selected')]+[
        ('zero_mse',c.c_float),('quantized_mse',c.c_float)]


class Report(c.Structure):
    _fields_=[(k,c.c_uint32) for k in ('samples','clipped','gray_samples','skin_samples')]+[
        ('delta_e76',c.c_float*5),('rgb_rmse',c.c_float)]


class Cube(c.Structure):
    _fields_=[('dimension',c.c_uint32),('domain_min',c.c_float*3),('domain_max',c.c_float*3),
              ('values',c.POINTER(c.c_float))]


class Limits(c.Structure):
    _fields_=[('max_dimension',c.c_uint32),('max_bytes',c.c_size_t)]


Progress=c.CFUNCTYPE(c.c_int,c.c_void_p,c.c_uint32,c.c_uint32)


def bind(api):
    api.af_grid_model_valid.argtypes=[c.POINTER(Model)]
    api.af_grid_predict.argtypes=[c.POINTER(Model),c.c_void_p,c.POINTER(c.c_float),c.POINTER(c.c_float)]
    api.af_grid_row.argtypes=[c.POINTER(Model),c.POINTER(c.c_float),c.POINTER(Row)]
    api.af_grid_pack.argtypes=[c.c_void_p,c.c_void_p,c.c_uint,c.c_void_p]
    api.af_cube_parse.argtypes=[c.c_void_p,c.c_size_t,c.POINTER(Cube),c.c_void_p,c.c_size_t,Limits]
    api.af_grid_fit.argtypes=[c.POINTER(Model),c.c_uint32,c.POINTER(Cube),c.POINTER(Sample),c.c_size_t,
        c.c_uint,c.c_float,c.c_void_p,c.POINTER(Work),c.POINTER(Fit),Progress,c.c_void_p]
    api.af_grid_report.argtypes=[c.POINTER(Model),c.POINTER(Cube),c.c_void_p,c.POINTER(Sample),c.c_size_t,
        c.POINTER(Work),c.POINTER(Report)]
    return api


def reference_model(*,mathematical_fixture=False):
    j=json.loads((Path(__file__).parent/'fixtures/r5_paired_v2.json').read_text())
    assert j['base_mask']==0 and j['source_base_look']=='PT' and j['mathematical_fixture_base']==1
    assert j['mathematical_fixture_cp_wire']==3
    assert j['camera_apply_allowed'] is False and j['current_firmware_calibrated'] is False
    m=Model();m.schema=1;m.base_mask=j['base_mask'];m.smooth=j['smooth']
    m.coordinates[:]=[v for row in j['coordinate_affine'] for v in row]
    m.response[:]=[v for row in j['response_weights'] for v in row]
    m.sha256[:]=bytes.fromhex(j['source_sha256'])
    if mathematical_fixture:
        # 模型摘要与数据文件摘要分开；只用于本地数学契约，不代表机身标定。
        identity={k:j[k] for k in ('source_sha256','source_base_look','source_parameter_sha256',
                  'scope','coordinate_affine','response_weights','smooth','mathematical_fixture_base',
                  'mathematical_fixture_cp_wire')}
        encoded=json.dumps(identity,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
        digest=hashlib.sha256(b'AF_GRID_EXPLICIT_MATH_FIXTURE_V1\0'+encoded).digest()
        m.sha256[:]=digest;m.base_mask=1<<j['mathematical_fixture_base']
        j['mathematical_fixture_sha256']=digest.hex()
    return m,j


def cube(api,transform=lambda r,g,b:(r,g,b)):
    rows=['LUT_3D_SIZE 2']
    for b in (0,1):
        for g in (0,1):
            for r in (0,1):rows.append(' '.join(str(v) for v in transform(r,g,b)))
    raw=('\n'.join(rows)+'\n').encode();values=(c.c_float*24)();result=Cube()
    assert api.af_cube_parse(raw,len(raw),c.byref(result),values,24,Limits(33,65536))==0
    return result,values,raw


def samples(points):
    return (Sample*len(points))(*[Sample((c.c_float*3)(*p[:3]),1,p[3] if len(p)>3 else 0) for p in points])
