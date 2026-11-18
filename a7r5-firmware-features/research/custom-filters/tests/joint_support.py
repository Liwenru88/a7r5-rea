"""联合核心测试ABI；合成预测器只验证搜索契约。"""
import ctypes as c
from grid_support import Cube,Sample,Progress


class Recipe(c.Structure):
    _fields_=[('gamma',c.c_uint32*129),('matrix',c.c_int16*18),('cc1',c.c_int16*24),('grid',c.c_int8*1215)]


Predict=c.CFUNCTYPE(c.c_int,c.c_void_p,c.POINTER(Recipe),c.POINTER(c.c_float),c.POINTER(c.c_float))


class Model(c.Structure):
    _fields_=[(n,c.c_uint32) for n in ('schema','base_mask','components','domain')]+[
        ('cp_sha256',c.c_uint8*32),('model_sha256',c.c_uint8*32),('predict',Predict),('context',c.c_void_p)]


class Options(c.Structure):
    _fields_=[('evaluations',c.c_uint32)]+[(n,c.c_uint16) for n in ('gamma_step','tone_step','matrix_step','cc1_step','grid_step')]


class Work(c.Structure):
    _fields_=[('current',Recipe),('trial',Recipe),('target',(c.c_float*3)*512),('mass',c.c_float*512)]


class Fit(c.Structure):
    _fields_=[(n,c.c_uint32) for n in ('evaluations','predictions','rejected','attempted_components')]+[
        ('accepted',c.c_uint32*4),('initial_mse',c.c_float),('final_mse',c.c_float),('research_only',c.c_uint32)]


def bind(api):
    api.af_joint_valid.argtypes=[c.POINTER(Recipe)]
    api.af_joint_expand_matrix.argtypes=[c.c_void_p,c.c_void_p]
    api.af_joint_gamma.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p]
    api.af_joint_gamma_record.argtypes=[c.c_void_p,c.c_void_p,c.c_void_p]
    api.af_cube_parse.argtypes=[c.c_void_p,c.c_size_t,c.POINTER(Cube),c.c_void_p,c.c_size_t,__import__('grid_support').Limits]
    api.af_joint_fit.argtypes=[c.POINTER(Model),c.c_uint32,c.POINTER(Cube),c.POINTER(Sample),c.c_size_t,
        c.POINTER(Recipe),c.POINTER(Options),c.c_void_p,c.c_void_p,c.c_void_p,Progress,c.c_void_p]
    api.af_joint_synthetic_predict.argtypes=[c.c_void_p,c.POINTER(Recipe),c.POINTER(c.c_float),c.POINTER(c.c_float)]
    return api


def seed():
    r=Recipe();r.gamma[:]=[i*1024 for i in range(129)];return r


def model(predict):
    m=Model();m.schema=m.base_mask=m.domain=1;m.components=15;m.model_sha256[0]=0x20
    m.cp_sha256[:]=bytes.fromhex('18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97')
    m.predict=predict;return m
