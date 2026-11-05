"""原生整数约束、完整组合选优和错误不发布；像素模型另行验收。"""
import ctypes as c
from pathlib import Path
import random
import struct
import subprocess
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from grid_support import cube,samples,Progress
from joint_support import Recipe,Model,Options,Work,Fit,Predict,bind,seed,model

HOME=Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    path=tmp_path_factory.mktemp('joint')/'native.so'
    files=[HOME/'native'/n for n in ('af_joint.c','af_joint_fit.c','af_cube.c')]+[HOME/'tests/native_joint_target.c']
    result=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',*map(str,files),'-o',str(path)],capture_output=True,text=True)
    assert result.returncode==0,result.stderr
    return bind(c.CDLL(str(path)))


def test_all_four_integer_components_share_one_objective_and_cancel_atomically(api):
    assert api.af_joint_target_check()==0
    report=(c.c_uint32*8).in_dll(api,'af_joint_target_report')
    assert report[0]==0x4a323031 and report[1]>1800 and report[2]==65 and report[3]==c.sizeof(Work) and report[4]==15 and report[5]==1


def test_gamma_integer_order_tail_and_independent_matrix_expansion(api):
    rng=random.Random(20261026)
    for tone in ((0,0,0),(37,-41,57),(-128,70,-11),(1024,0,0)):
        values=[(i*i*262143)//(128*128) for i in range(129)]
        raw=bytearray(rng.randbytes(576));struct.pack_into('<129I',raw,0,*values)
        source=c.create_string_buffer(bytes(raw));destination=c.create_string_buffer(b'\xa5'*576,576)
        t=(c.c_int16*3)(*tone)
        expected=[]
        for y in values:
            x=(y<<12)//values[-1];v=4096-x
            value=y+((y*tone[0])>>10)
            value+=(((((y*tone[1])>>10)*v)>>12)*v)>>12
            value+=(((((y*tone[2])>>10)*x)>>12)*v)>>12
            expected.append(max(0,min(262143,value)))
        assert api.af_joint_gamma_record(source,t,destination)==0
        want=bytearray(raw);struct.pack_into('<129I',want,0,*expected);struct.pack_into('<I',want,0x220,expected[-1])
        assert destination.raw==want and source.raw[:-1]==raw
    inp=(c.c_int16*18)(*range(-9,9));out=(c.c_int16*27)()
    assert api.af_joint_expand_matrix(inp,out)==0
    expected=[]
    for a,b,cc,d,e,f in zip(*[list(inp)[i::6] for i in range(6)]):expected.extend((a+b,-a,-b,-cc,cc+d,-d,-e,-f,e+f))
    assert list(out)==expected and all(sum(list(out)[i:i+3])==0 for i in range(0,27,3))
    before=bytes(out);inp[17]=1025
    assert api.af_joint_expand_matrix(inp,out)==-1 and bytes(out)==before
    assert api.af_joint_gamma_record(source,t,source)==-1


@pytest.mark.parametrize('failure',[float('nan'),'model_error','late_model_error','invalid_base','grid_only','source_cp','overlap'])
def test_joint_backend_error_or_missing_full_capability_never_publishes(api,failure):
    calls=[]
    def predict(ctx,recipe,rgb,out):
        calls.append(tuple(rgb[i] for i in range(3)))
        if failure=='model_error':return -6
        if failure=='late_model_error':
            if len(calls)>=5:return -6
            return api.af_joint_synthetic_predict(ctx,recipe,rgb,out)
        for j in range(3):out[j]=float('nan') if failure!= 'overlap' else rgb[j]
        return 0
    callback=Predict(predict);m=model(callback);r=seed()
    target,storage,_=cube(api,lambda r,g,b:(r*1.015625,g*1.015625,b*1.015625))
    training=samples([(.2,.4,.6),(.7,.3,.5)]);w=Work();o=Recipe.from_buffer_copy(b'\x5a'*c.sizeof(Recipe));f=Fit.from_buffer_copy(b'\xa5'*c.sizeof(Fit))
    if failure=='grid_only':m.components=8
    if failure=='source_cp':m.cp_sha256[0]^=1
    before=bytes(o),bytes(f);output=c.byref(w) if failure=='overlap' else c.byref(o)
    status=api.af_joint_fit(c.byref(m),17 if failure=='invalid_base' else 0,c.byref(target),training,2,c.byref(r),
        c.byref(Options(17,256,16,16,16,4)),c.byref(w),output,c.byref(f),Progress(),None)
    expected=-22 if not isinstance(failure,str) or failure in ('model_error','late_model_error') else -1
    assert status==expected
    assert (bytes(o),bytes(f))==before
    if failure in ('invalid_base','grid_only','source_cp','overlap'):assert calls==[]


def test_infeasible_candidates_are_skipped_without_replacing_the_seed(api):
    calls=[]
    r=seed();original=bytes(r)
    def predict(ctx,recipe,rgb,out):
        calls.append(1)
        if bytes(recipe.contents)!=original:return -21
        for j in range(3):out[j]=rgb[j]
        return 0
    cb=Predict(predict);m=model(cb);target,storage,_=cube(api);training=samples([(.2,.4,.6),(.7,.3,.5)])
    o=Recipe();f=Fit();w=Work();options=Options(17,256,16,16,16,4)
    assert api.af_joint_fit(c.byref(m),0,c.byref(target),training,2,c.byref(r),c.byref(options),c.byref(w),c.byref(o),c.byref(f),Progress(),None)==0
    assert bytes(o)==original and f.final_mse==0 and f.rejected==16 and sum(f.accepted)==0


def test_joint_source_and_research_mode_precede_execution(monkeypatch):
    from a7filters import native_joint
    from a7filters.baseline import audit
    def forbidden(*args,**kwargs):pytest.fail('未核对当前CP就执行联合模块')
    monkeypatch.setattr(native_joint,'JointMachine',forbidden)
    with pytest.raises(ValueError,match='CP不是已锁定4.06'):native_joint.collect(b'changed CP',b'not ELF')
    with pytest.raises(ValueError,match='同时启用接入研究'):audit('/missing',joint_adapter='/missing')
