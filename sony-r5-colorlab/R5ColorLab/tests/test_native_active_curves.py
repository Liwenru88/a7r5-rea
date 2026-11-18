"""活动集保留真实相邻输入，不插值输出或把局部峰值当P95。"""
from types import SimpleNamespace
import numpy as np
from native_robust_grid import ActiveCurves


def test_active_curve_adds_real_neighbourhood_at_new_peak():
    x=np.repeat(np.arange(10)[:,None,None],27,axis=1).reshape(10,9,3).astype(np.uint16)
    ref=np.full((10,3),.5);candidate=ref.copy();candidate[8]=[1.,0.,0.]
    section={'saturation':(slice(0,10),(2,5,3))}
    gate=SimpleNamespace(phases=(.1,),geometry_for=lambda p:(x,ref,section),_predict=lambda e,v:candidate,
        baseline={'dense':{'0.1':{'saturation':{'reference':{'max':2.}}}}})
    bank=ActiveCurves(gate,include_p95=False);bank.observe({})
    assert (1,2) in bank.points[(.1,'saturation')]
    geometry=bank.geometry()[0];raw=geometry['geometry'][0].reshape(-1,3,9,3)
    assert any(np.array_equal(triple[:,4,0],[7,8,9]) for triple in raw)
    assert geometry['bounds']['saturation']==(2.,2.)


def test_p95_constraint_uses_complete_curve_not_selected_peak_distribution():
    x=np.zeros((10,9,3),np.uint16)
    ref=np.full((10,3),.5);candidate=ref.copy();candidate[3]=[.8,.2,.3]
    section={'hue':(slice(0,10),(2,5,3))}
    gate=SimpleNamespace(phases=(.1,),geometry_for=lambda p:(x,ref,section),_predict=lambda e,v:candidate,
        baseline={'dense':{'0.1':{'hue':{'reference':{'p95':.1,'max':2.}}}}})
    bank=ActiveCurves(gate);bank.observe({});item=bank.geometry()[0]
    assert item['geometry'][2]['hue'][1]==(2,5,3)
    assert len(item['geometry'][0])==10
    assert item['bounds']['hue']==(.1,2.)


def test_short_repair_keeps_at_least_one_complete_p95_round():
    from native_robust_grid import p95_round
    assert [p95_round(i,6) for i in range(6)]==[False,False,False,False,True,True]
    assert p95_round(0,1)


def test_robust_coverage_retains_earlier_development_regressions():
    from native_robust_grid import PHASES,accumulate_phases
    assert {.17,.53,.87}<=set(PHASES)
    assert {(i+.5)/16 for i in range(16)}<=set(PHASES)
    assert set(PHASES)<=set(accumulate_phases(PHASES,[(i+.5)/64 for i in range(64)]))
