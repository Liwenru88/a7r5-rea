"""多个联合候选真实进入参考消费者；研究整数域、无sRGB或网格许可。"""
import base64
import ctypes as c
import hashlib
from pathlib import Path
import struct
import subprocess

import pytest

from test_edit_context import Input as ContextInput,Context,Work as ContextWork,parameters
from test_edit_chain import Work as PixelWork
from test_edit_cp_gamma import Output as Gamma,RECORD_BASE64,Progress
from joint_support import Recipe

HOME=Path(__file__).resolve().parents[1]
# 固定8b563d4的presets.json entries[0].block13，端点/扇区/六项顺序，小端半字。
MATRIX_BASE64='xQCE/+v/m/+X/pwAjQBr/+r/AQBN/+7/awBD/83/JwDo/4D/fAAO/+X/2v8JAJX/RgAU/xYAhv/F/xEADwBJ/zYA0//Y/64AgwAs/3EAX//s/34ApABI/zgAY/8DAJcA4QCr/gYAnP8kAMwA4QCZ/hMAIP/7/4EA4QDr/sL/cf+H/+EA4QAB/5L/of93/+EA0AAL/3n/uv9w/9oAyAAu/1r/2f87/9QAwACy/2//BQCN/s0AtgBRAM3+ZwBi/tEAwgDj/3H/mgDD/zgAvgDV/7X/mgAUAKL/ngDA/7f/hwA7ALf/jQC1/7X/YwBlAJv/SgCB/wIAOQDC/zgAUgCm/+7/dQDY/64AwgCs/x8ATgDU/3EAtgCi/97/cADs/4wA4QDK/rX/IAAFANkA4QCM/r3/vf/P/+EA4QB4/s//HADj/+EA4QDQ/rn/RgDF/9oA4QBE/3j/cwB3/+EA2QCn/0f/lgAs/+EA0gAWAC7/mADZ/tQA4QBUAKr+mgBT/2UA4QAmAM//kAAeAOX/4QDP/+T/XAA2AIj/4QD///f/NwCHACz/4QAhAEsAEgBsAIT/4QAcAIYAFQD7/y8A1QCk/wAAcwAcAJQAowD4/0YABgAeAEsA4QAJAJ0AIQD5/7sA4QCL/ygAggBOAKIA4QBz/xEAFgAaAKEA4QDy/jMAPgAcAK0AxAA9/wgAUwAnAJwA2ACY/7z/dQBBAIYA4QD2/5X/fwBDAG8A3AAyAO7/RQAHAGQA4QAUAAwATwA+AFAA'
CC1=[-193,-269,-251,-51,408,554,563,563,9,17,-145,0,12,-87,0,-154,-60,38,67,0,3,-197,0,-197]


class Input(c.Structure):
    _fields_=[('edit',c.c_void_p),('cp_gamma_record',c.c_void_p),('matrix_raw',c.c_void_p),
              ('cc1_raw',c.c_void_p),('matrix_weights',c.c_uint16*4),('cc1_weights',c.c_uint16*4)]


class Parameters(c.Structure):
    _fields_=[('gamma',Gamma),('matrix_payload',c.c_uint8*276),('cc1',c.c_int16*8),('matrix_quantized',c.c_uint32)]


class Cache(c.Structure):
    _fields_=[('valid',c.c_uint32),('builds',c.c_uint32),('hits',c.c_uint32),
              ('recipe_sha256',c.c_uint8*32),('source_sha256',c.c_uint8*32),('context',Context)]


class Work(c.Structure):
    _fields_=[('build',ContextWork),('parameters',Parameters)]


class EvalWork(c.Structure):
    _fields_=[('pixels',PixelWork),('patch',c.c_uint16*15),('rendered',c.c_uint16*15)]


SOURCES=['af_edit_joint.c','af_joint.c','af_color406.c','af_edit_cp_gamma.c','af_gamma406.c',
         'af_sha256.c','af_edit_reference.c','af_edit_chain.c','af_edit_gamma_table.c',
         'af_edit_matrix_table.c','af_edit_context.c']


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    path=tmp_path_factory.mktemp('edit-joint')/'native.so'
    run=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-ffp-contract=off',
        '-shared','-fPIC',*[str(HOME/'native'/n) for n in SOURCES],'-o',str(path)],capture_output=True,text=True)
    assert run.returncode==0,run.stderr
    lib=c.CDLL(str(path));lib.af_edit_joint_parameters.argtypes=[c.c_void_p]*3
    lib.af_edit_joint_init.argtypes=[c.c_void_p]
    lib.af_edit_joint_prepare.argtypes=[c.c_void_p]*4+[Progress,c.c_void_p]
    lib.af_edit_joint_eval.argtypes=[c.c_void_p]*4
    lib.af_edit_context_build.argtypes=[c.c_void_p]*3+[Progress,c.c_void_p]
    lib.af_edit_ref_color.argtypes=[c.c_void_p,c.c_void_p,c.c_size_t,c.c_size_t,c.c_void_p,c.c_void_p]
    return lib


def source():
    data,edit,owners=parameters()
    matrix=base64.b64decode(MATRIX_BASE64,validate=True)
    assert len(matrix)==576 and hashlib.sha256(matrix).hexdigest()=='8e1389747320727fa862211de0864b8bf2d919beba30067c0fc35570440273bf'
    owners.update(edit=edit,record=c.create_string_buffer(base64.b64decode(RECORD_BASE64)),
        matrix=(c.c_uint16*288).from_buffer_copy(matrix),cc1_raw=(c.c_uint16*24)(*[x&65535 for x in CC1]))
    value=Input(*(c.addressof(owners[k]) for k in ('edit','record','matrix','cc1_raw')),
                (c.c_uint16*4)(256,0,0,0),(c.c_uint16*4)(256,0,0,0))
    recipe=Recipe();recipe.gamma[:]=struct.unpack_from('<129I',owners['record'].raw)
    return data,value,owners,recipe


def evaluate(api,cache,rgb=(1736,1000,9000)):
    color=(c.c_uint16*3)(*rgb);out=(c.c_uint16*3)();work=EvalWork()
    assert api.af_edit_joint_eval(c.byref(cache),color,c.byref(work),out)==0
    return tuple(out)


def prepare(api,value,recipe,work,cache):
    assert api.af_edit_joint_prepare(c.byref(value),c.byref(recipe),c.byref(work),c.byref(cache),Progress(),None)==0


def test_fixed_baseline_parameters_preserve_template_and_reference_runtime(api):
    data,value,owners,recipe=source();out=Parameters()
    assert api.af_edit_joint_parameters(c.byref(value),c.byref(recipe),c.byref(out))==0
    assert list(out.gamma.gamma_y)==list(owners['gamma_y'])
    assert bytes(out.matrix_payload)==owners['matrix_payload'].raw
    assert list(out.cc1)==data['cc1'] and out.matrix_quantized==20
    work=Work();cache=Cache();assert api.af_edit_joint_init(c.byref(cache))==0
    prepare(api,value,recipe,work,cache)
    direct=Context();direct_work=ContextWork()
    assert api.af_edit_context_build(c.byref(owners['edit']),c.byref(direct_work),c.byref(direct),Progress(),None)==0
    for name in ('main_gamma','matrix_table','main_inverse','secondary_inverse'):
        assert bytes(getattr(cache.context,name))==bytes(getattr(direct,name))


def test_nonzero_endpoints_and_odd_negative_encoding_are_not_field_passthrough(api):
    _,value,owners,recipe=source();before=Parameters();after=Parameters()
    assert api.af_edit_joint_parameters(c.byref(value),c.byref(recipe),c.byref(before))==0
    recipe.matrix[6]=1;recipe.cc1[8]=3
    assert api.af_edit_joint_parameters(c.byref(value),c.byref(recipe),c.byref(after))==0
    for sector in range(16):
        position=24+2*(sector^1)
        old=struct.unpack_from('<h',bytes(before.matrix_payload),position)[0]>>2
        new=struct.unpack_from('<h',bytes(after.matrix_payload),position)[0]>>2
        assert new==old+1
    assert after.cc1[1]==before.cc1[1]+3
    # 未被选择的端点0增量不得经raw差分传播到端点1。
    recipe.matrix[6]=0;recipe.matrix[0]=9;recipe.cc1[8]=0;recipe.cc1[0]=7
    assert api.af_edit_joint_parameters(c.byref(value),c.byref(recipe),c.byref(after))==0
    assert bytes(after)==bytes(before)


def test_each_nonzero_component_changes_actual_native_integer_evaluation(api):
    _,value,owners,seed=source();work=Work();cache=Cache();api.af_edit_joint_init(c.byref(cache))
    probes=((1736,1000,9000),(4000,1100,2000),(6000,11000,5000),(8000,8000,8000),(2000,9000,500))
    prepare(api,value,seed,work,cache)
    baseline=[evaluate(api,cache,rgb) for rgb in probes]
    for component in ('gamma','matrix','cc1'):
        recipe=Recipe.from_buffer_copy(seed)
        if component=='gamma':recipe.gamma[:]=[v*3//4 for v in recipe.gamma]
        elif component=='matrix':recipe.matrix[6]=256
        else:recipe.cc1[8]=64;recipe.cc1[12]=8
        prepare(api,value,recipe,work,cache)
        assert [evaluate(api,cache,rgb) for rgb in probes]!=baseline,component
    assert cache.builds==4


def test_candidate_cache_reuses_per_color_and_invalidates_on_actual_source_change(api):
    _,value,owners,recipe=source();work=Work();cache=Cache();api.af_edit_joint_init(c.byref(cache))
    prepare(api,value,recipe,work,cache);base=evaluate(api,cache)
    assert (cache.builds,cache.hits)==(1,0)
    for rgb in ((1736,1000,9000),(4000,1100,2000),(8000,8000,8000)):
        evaluate(api,cache,rgb)
    assert (cache.builds,cache.hits)==(1,0)
    # C末尾填充不属于配方身份。
    if c.sizeof(recipe)>1815:c.memset(c.addressof(recipe)+1815,0x6a,c.sizeof(recipe)-1815)
    prepare(api,value,recipe,work,cache);assert (cache.builds,cache.hits)==(1,1)
    recipe.gamma[:]=[v*3//4 for v in recipe.gamma]
    recipe.matrix[6]=32;recipe.cc1[8]=8;recipe.cc1[12]=4
    prepare(api,value,recipe,work,cache);full=evaluate(api,cache)
    assert full!=base and cache.builds==2
    saved=bytes(cache)
    # eval不借调用方参数，缓存发布后不随输入改变。
    owners['cc1_raw'][0]^=1
    assert evaluate(api,cache)==full and bytes(cache)==saved
    before=bytes(cache)
    assert api.af_edit_joint_prepare(c.byref(value),c.byref(recipe),c.byref(work),c.byref(cache),Progress(),None)==-1
    assert bytes(cache)==before
    owners['cc1_raw'][0]^=1
    owners['contrast'][512]-=16
    prepare(api,value,recipe,work,cache)
    assert cache.builds==3 and bytes(cache.source_sha256)!=bytes(Cache.from_buffer_copy(saved).source_sha256)


def test_bad_or_unsupported_candidate_cancel_and_alias_keep_published_cache(api):
    _,value,owners,recipe=source();work=Work();cache=Cache();api.af_edit_joint_init(c.byref(cache))
    prepare(api,value,recipe,work,cache);before=bytes(cache)
    recipe.grid[0]=1
    assert api.af_edit_joint_prepare(c.byref(value),c.byref(recipe),c.byref(work),c.byref(cache),Progress(),None)==-21
    assert bytes(cache)==before;recipe.grid[0]=0
    value.matrix_weights[0]=128
    assert api.af_edit_joint_prepare(c.byref(value),c.byref(recipe),c.byref(work),c.byref(cache),Progress(),None)==-21
    assert bytes(cache)==before;value.matrix_weights[0]=256
    recipe.cc1[12]=-1024
    assert api.af_edit_joint_prepare(c.byref(value),c.byref(recipe),c.byref(work),c.byref(cache),Progress(),None)==-21
    assert bytes(cache)==before;recipe.cc1[12]=0;recipe.matrix[6]=7
    callback=Progress(lambda context,done,total:done==total)
    assert api.af_edit_joint_prepare(c.byref(value),c.byref(recipe),c.byref(work),c.byref(cache),callback,None)==-20
    assert bytes(cache)==before
    assert api.af_edit_joint_prepare(c.byref(value),c.byref(recipe),c.byref(work),c.byref(work),Progress(),None)==-1
    empty=Cache();api.af_edit_joint_init(c.byref(empty));out=(c.c_uint16*3)(77,77,77);evalwork=EvalWork();rgb=(c.c_uint16*3)(1,2,3)
    assert api.af_edit_joint_eval(c.byref(empty),rgb,c.byref(evalwork),out)==-1 and list(out)==[77]*3
