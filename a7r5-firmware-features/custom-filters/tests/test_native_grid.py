"""独立节点/量化/误差契约；完整原CP打包与上游实现对照另有集成回执。"""
import ctypes as c
import itertools
import math
from pathlib import Path
import random
import subprocess
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from grid_support import Model,Sample,Row,Work,Fit,Report,Progress,bind,reference_model,cube,samples

NATIVE=Path(__file__).resolve().parents[1]/'native'


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    path=tmp_path_factory.mktemp('grid')/'native.so'
    p=subprocess.run(['clang','-std=c11','-O2','-Wall','-Wextra','-Werror','-shared','-fPIC',
        *[str(NATIVE/n) for n in ('af_grid.c','af_grid_fit.c','af_cube.c')],'-o',str(path)],
        capture_output=True,text=True)
    assert p.returncode==0,p.stderr
    return bind(c.CDLL(str(path)))


def test_native_source_to_destination_permutation_signed_shift_and_rejection(api):
    values=[(i*29+17)%128-64 for i in range(1215)]
    grid=(c.c_int8*1215)(*values);perm=(c.c_uint16*405)(*[(i+137)%405 for i in range(405)])
    for level in (1,3,8):
        out=(c.c_uint32*405)(*([0xa5a5a5a5]*405));expected=[0]*405
        for i in range(405):expected[perm[i]]=sum((((values[c*405+i]*level)//8)&127)<<(22-10*c) for c in range(3))
        assert api.af_grid_pack(grid,perm,level,out)==0
        assert list(out)==expected
    before=bytes(out);perm[400]=perm[399]
    assert api.af_grid_pack(grid,perm,8,out)==-1 and bytes(out)==before
    assert api.af_grid_pack(grid,perm,0,out)==-1 and bytes(out)==before
    perm[400]=(400+137)%405
    for invalid in (-65,64):
        grid[1200]=invalid
        assert api.af_grid_pack(grid,perm,8,out)==-1 and bytes(out)==before


def test_predictor_axis_order_and_spatial_response(api):
    m=Model();m.schema=m.base_mask=m.smooth=1;m.sha256[0]=1
    # 原点落在节点(1,2,3)，响应含交叉项和随RGB变化项，可捕获平面或矩阵转置。
    m.coordinates[:]=[0,0,0,.25,0,0,0,-.25,0,0,0,-.125]
    m.response[1]=2;m.response[5]=3;m.response[6]=-1;m.response[(3+3*1+0)*3+2]=4
    node=1*81+2*9+3;grid=(c.c_int8*1215)();grid[node]=7;grid[405+node]=-5;grid[810+node]=3
    out=(c.c_float*3)();rgb=(c.c_float*3)(.3,.4,.5)
    assert api.af_grid_predict(c.byref(m),grid,rgb,out)==0
    assert list(out)==pytest.approx((.3-3/256,.4+14/256,.5-5*(3+4*(.3-.5))/256),abs=2e-7)
    row=Row();assert api.af_grid_row(c.byref(m),rgb,c.byref(row))==0
    assert row.index[0]==node and sum(row.weights)==pytest.approx(1)


def test_pt_capture_identity_is_not_a_st_or_unbound_pt_model(api):
    model,metadata=reference_model()
    model.sha256[:]=bytes.fromhex(metadata['source_sha256'])
    target,storage,_=cube(api)
    data=samples(((.2,.3,.4),(.7,.6,.5)));work=Work()
    out=(c.c_int8*1215)(*([55]*1215));fit=Fit.from_buffer_copy(b'\xa5'*c.sizeof(Fit))
    before=bytes(out),bytes(fit),bytes(work)
    for base in (0,1):
        model.base_mask=1<<base
        assert api.af_grid_model_valid(c.byref(model))==-1
        assert api.af_grid_fit(c.byref(model),base,c.byref(target),data,len(data),1,0,
            out,c.byref(work),c.byref(fit),Progress(),None)==-1
        assert (bytes(out),bytes(fit),bytes(work))==before


def test_reference_loader_is_closed_until_explicit_mathematical_fixture(api):
    model,metadata=reference_model()
    assert metadata['source_base_look']=='PT' and metadata['camera_apply_allowed'] is False
    assert metadata['source_parameter_sha256']=='0ce71ba0e51fbf685cb4683f5ffd976f55cd922038e5dc17b18db354ab416181'
    assert model.base_mask==0 and api.af_grid_model_valid(c.byref(model))==-1
    mathematical,explicit=reference_model(mathematical_fixture=True)
    assert mathematical.base_mask==2 and api.af_grid_model_valid(c.byref(mathematical))==0
    assert bytes(mathematical.sha256).hex()==explicit['mathematical_fixture_sha256']!=metadata['source_sha256']


@pytest.mark.parametrize('bad',[float('nan'),float('inf'),-.1,1.1])
def test_invalid_later_rgb_component_does_not_publish(api,bad):
    m,_=reference_model(mathematical_fixture=True);grid=(c.c_int8*1215)();out=(c.c_float*3)(42,42,42)
    assert api.af_grid_predict(c.byref(m),grid,(c.c_float*3)(.2,bad,.4),out)==-1
    assert list(out)==[42,42,42]


def test_identity_and_nonidentity_fit_are_evaluated_on_separate_samples(api):
    m,_=reference_model(mathematical_fixture=True);rng=random.Random(1801)
    training=samples([tuple(rng.uniform(.04,.96) for _ in range(3)) for _ in range(512)])
    holdout=samples([(*p,0) for p in itertools.product((.12,.31,.55,.73,.89),repeat=3)]+[
        (v/32,v/32,v/32,1) for v in range(1,32)]+[(.61,.39,.28,2),(.82,.62,.49,2)])
    w=Work();out=(c.c_int8*1215)();fit=Fit();reports=[]
    for transform in (lambda r,g,b:(r,g,b),lambda r,g,b:(.94*r+.035,.96*g+.01,.95*b+.023)):
        target,storage,_=cube(api,transform);before=bytes(m)
        assert api.af_grid_fit(c.byref(m),1,c.byref(target),training,len(training),180,.001,
            out,c.byref(w),c.byref(fit),Progress(),None)==0
        assert bytes(m)==before and 1<=fit.iterations<=180 and min(out)>=-64 and max(out)<=63
        report=Report();zero=Report()
        assert api.af_grid_report(c.byref(m),c.byref(target),out,holdout,len(holdout),c.byref(w),c.byref(report))==0
        assert api.af_grid_report(c.byref(m),c.byref(target),(c.c_int8*1215)(),holdout,len(holdout),c.byref(w),c.byref(zero))==0
        reports.append((list(out),report,zero))
        assert fit.quantized_mse<=fit.zero_mse+1e-12
        assert report.gray_samples==31 and report.skin_samples==2 and report.samples==158
        assert report.delta_e76[0]<=report.delta_e76[2] and report.delta_e76[1]<=report.delta_e76[2]
    assert not any(reports[0][0]) and reports[0][1].rgb_rmse<1e-7 and reports[0][1].delta_e76[2]==0
    assert any(reports[1][0]) and reports[1][1].rgb_rmse<reports[1][2].rgb_rmse*.5


def test_cancel_invalid_base_and_alias_keep_published_candidate(api):
    m,_=reference_model(mathematical_fixture=True);target,storage,_=cube(api,lambda r,g,b:(.9*r+.04,.95*g+.02,.94*b+.02))
    training=samples(list(itertools.product((.2,.5,.8),repeat=3)));w=Work()
    out=(c.c_int8*1215)(*([55]*1215));fit=Fit.from_buffer_copy(b'\xa5'*c.sizeof(Fit))
    before=bytes(out),bytes(fit);events=[]
    def progress(context,done,total):events.append((done,total));return done==3
    cb=Progress(progress)
    assert api.af_grid_fit(c.byref(m),1,c.byref(target),training,len(training),40,.01,out,c.byref(w),c.byref(fit),cb,None)==-20
    assert events[-1]==(3,40) and (bytes(out),bytes(fit))==before
    for base,budget in ((0,40),(17,40),(1,257)):
        assert api.af_grid_fit(c.byref(m),base,c.byref(target),training,len(training),budget,.01,
            out,c.byref(w),c.byref(fit),Progress(),None)==-1
    assert api.af_grid_fit(c.byref(m),1,c.byref(target),training,len(training),40,.01,
        c.addressof(w),c.byref(w),c.byref(fit),Progress(),None)==-1
    assert (bytes(out),bytes(fit))==before


def test_quantized_lab_report_matches_independent_scalar_reference(api):
    m,_=reference_model(mathematical_fixture=True);target,storage,_=cube(api,lambda r,g,b:(.8*r+.08,.9*g+.04,.7*b+.12))
    data=samples([(.1,.2,.3,1),(.9,.5,.4,2),(.4,.3,.8,0),(.7,.7,.7,1)])
    def lab(v):
        linear=[x/12.92 if x<=.04045 else ((x+.055)/1.055)**2.4 for x in [math.floor(x*255+.5)/255 for x in v]]
        xyz=[sum(a*b for a,b in zip(row,linear))/white for row,white in zip(
            ((.4124564,.3575761,.1804375),(.2126729,.7151522,.0721750),(.0193339,.1191920,.9503041)),(.95047,1,1.08883))]
        f=[math.cbrt(x) if x>(6/29)**3 else x/(3*(6/29)**2)+4/29 for x in xyz]
        return 116*f[1]-16,500*(f[0]-f[1]),200*(f[1]-f[2])
    errors=[]
    for p in data:
        x=list(p.rgb);y=(.8*x[0]+.08,.9*x[1]+.04,.7*x[2]+.12)
        errors.append(math.dist(lab(x),lab(y)))
    out=Report();w=Work()
    assert api.af_grid_report(c.byref(m),c.byref(target),(c.c_int8*1215)(),data,len(data),c.byref(w),c.byref(out))==0
    assert list(out.delta_e76)==pytest.approx((sum(errors)/4,max(errors),max(errors),(errors[0]+errors[3])/2,errors[1]),abs=.00015)


def test_grid_source_and_research_gate_precede_execution(monkeypatch):
    from a7filters import native_grid
    from a7filters.baseline import audit
    def forbidden(*args,**kwargs):pytest.fail('未核对来源就执行网格模块')
    monkeypatch.setattr(native_grid,'GridMachine',forbidden)
    with pytest.raises(ValueError,match='CP不是已锁定4.06'):
        native_grid.collect(b'changed CP',b'not ELF')
    with pytest.raises(ValueError,match='启用接入研究'):
        audit('/missing',grid_adapter='/missing')
