"""同一联合求解可在UI轮询间分批推进；测试模型不提供机身标定资格。"""
import ctypes as c
import pytest
from test_native_joint import api  # noqa: F401
from joint_support import Recipe, Work, Fit, Options, Predict, model, seed
from grid_support import Progress, cube, samples


def setup(api, callback=None):
    api.af_joint_state_bytes.restype=c.c_size_t
    api.af_joint_fit_start.argtypes=[c.c_void_p,c.c_void_p,c.c_uint32,c.c_void_p,c.c_void_p,c.c_size_t,
        c.c_void_p,c.c_void_p,c.c_void_p,c.c_void_p,c.c_void_p,Progress,c.c_void_p]
    api.af_joint_fit_step.argtypes=[c.c_void_p,c.c_uint32]
    state=c.create_string_buffer(api.af_joint_state_bytes())
    predict=callback or Predict(api.af_joint_synthetic_predict)
    m=model(predict);r=seed();w=Work()
    target,storage,_=cube(api,lambda r,g,b:(r*.97,g*1.025,b*.985))
    train=samples([(.2,.4,.6),(.7,.3,.5),(.1,.8,.4)])
    out=Recipe.from_buffer_copy(b'\x5a'*c.sizeof(Recipe));fit=Fit.from_buffer_copy(b'\xa5'*c.sizeof(Fit))
    opts=Options(65,256,16,16,16,4)
    return state,predict,m,r,w,target,storage,train,out,fit,opts


@pytest.mark.parametrize('batch',[1,7,64])
def test_incremental_fit_yields_without_publishing_and_matches_existing_result(api,batch):
    state,predict,m,r,w,target,storage,train,out,fit,opts=setup(api)
    old=bytes(out),bytes(fit);progress=[]
    watch=Progress(lambda _,done,total:progress.append((done,total))or 0)
    assert api.af_joint_fit_start(state,c.byref(m),0,c.byref(target),train,3,c.byref(r),c.byref(opts),
        c.byref(w),c.byref(out),c.byref(fit),watch,None)==1
    assert (bytes(out),bytes(fit))==old
    assert api.af_joint_fit_step(state,0)==-1 and api.af_joint_fit_step(state,65)==-1
    assert (bytes(out),bytes(fit))==old
    for _ in range(65):
        result=api.af_joint_fit_step(state,batch)
        if result==0:break
        assert result==1 and (bytes(out),bytes(fit))==old
    else:pytest.fail('未在有界候选数内完成')
    assert fit.evaluations==65 and fit.attempted_components==15 and fit.final_mse<=fit.initial_mse
    assert all(a[0]<=b[0]for a,b in zip(progress,progress[1:]))
    assert api.af_joint_fit_step(state,1)==-5
    other=Recipe();stats=Fit();workspace=Work()
    assert api.af_joint_fit(c.byref(m),0,c.byref(target),train,3,c.byref(r),c.byref(opts),
        c.byref(workspace),c.byref(other),c.byref(stats),Progress(),None)==0
    assert bytes(out)==bytes(other) and bytes(fit)==bytes(stats)


@pytest.mark.parametrize('failure',['cancel','model'])
def test_incremental_failure_after_yield_keeps_outputs_and_allows_explicit_new_job(api,failure):
    broken=[False]
    def predict(ctx,recipe,rgb,out):
        if broken[0]and failure=='model':return -6
        return api.af_joint_synthetic_predict(ctx,recipe,rgb,out)
    state,callback,m,r,w,target,storage,train,out,fit,opts=setup(api,Predict(predict))
    old=bytes(out),bytes(fit)
    watch=Progress(lambda _,done,total:int(broken[0]and failure=='cancel'))
    args=(state,c.byref(m),0,c.byref(target),train,3,c.byref(r),c.byref(opts),c.byref(w),c.byref(out),c.byref(fit),watch,None)
    assert api.af_joint_fit_start(*args)==1
    assert api.af_joint_fit_start(*args)==-4
    assert api.af_joint_fit_step(state,1)==1
    broken[0]=True
    assert api.af_joint_fit_step(state,64)==(-20 if failure=='cancel'else -22)
    assert (bytes(out),bytes(fit))==old
    broken[0]=False
    assert api.af_joint_fit_start(*args)==1
    assert api.af_joint_fit_step(state,64)==0 and fit.evaluations==65
