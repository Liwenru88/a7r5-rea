from legacy_fit_fixture import legacy_fit
import copy
import importlib
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import model,structured_response as sr
import hue_training
from test_calibrator import FitTests

CASES = (('hue_experts',3,(3,81,3),243,5),
         ('hue24_experts',24,(24,9,3),216,6))


def fixture():
    pairs,_=FitTests().pairs()
    m=legacy_fit(pairs,refine=False,options=dict(response_degree=2,perceptual_mix=1))
    q=np.zeros((30,3));old=np.asarray(m['response_weights']);q[:len(old)]=old
    m.update(response_basis=sr.KIND_C1,response_weights=sr.from_quadratic(q,sr.KIND_C1).tolist(),smooth=True)
    m['report']['structured_response']=dict(scope='synthetic shared fixture')
    return pairs,m


class HueTrainingTests(unittest.TestCase):
    def test_frozen_shared_and_test_grid_color_target_isolation(self):
        pairs,base=fixture();saved=copy.deepcopy(base)
        changed=copy.deepcopy(pairs)
        for pair in changed:
            # The synthetic fixture shares one x array across probes; break
            # that alias so poisoning the test probe cannot mutate train RGB.
            pair['x']=pair['x'].copy();pair['y']=pair['y'].copy()
            keep=np.ones(len(pair['x']),bool) if pair['role']=='test' else np.asarray(pair['buckets'])>=9
            pair['x'][keep]=.13;pair['y'][keep]=0
            if pair['role']=='test':pair['grid']=np.full_like(pair['grid'],-63)
        for module,count,shape,width,schema in CASES:
            with self.subTest(experts=count):
                seen=[];candidates=[]
                def zero(x,y,d,w,shared,**kw):
                    paths=kw['path_constraints']
                    self.assertEqual(paths['first'].shape[1],width)
                    seen.append([v.copy() for v in [x,y,d,w,shared,*[paths[k] for k in sorted(paths)]]])
                    return np.zeros(shape),dict(device='test-double')
                def candidate_hook(candidate,row,note):candidates.append(copy.deepcopy(candidate))
                with patch(module+'.solve',side_effect=zero):
                    a=hue_training.refine(pairs,base,device='cpu',strengths=(1,),iterations=1,expert_module=module,on_candidate=candidate_hook)
                    b=hue_training.refine(changed,base,device='cpu',strengths=(1,),iterations=1,expert_module=module,on_candidate=candidate_hook)
                self.assertEqual(len(seen),2)
                for x,y in zip(*seen):np.testing.assert_array_equal(x,y)
                self.assertEqual(a['report']['hue_experts']['selected_validation_objective'],b['report']['hue_experts']['selected_validation_objective'])
                np.testing.assert_array_equal(a['response_weights'],base['response_weights'])
                self.assertFalse(a['report']['hue_experts']['selected_experts'])
                self.assertEqual(a['report']['hue_experts']['expert_count'],count)
                self.assertEqual(a['report']['hue_experts']['parameters_trained'],int(np.prod(shape)))
                self.assertEqual(base,saved)
                self.assertEqual(candidates[0]['schema'],f'r5-grid-response-calibration/{schema}')
                self.assertEqual(np.asarray(candidates[0]['expert_weights']).shape,shape)

    def test_path_matrices_match_complete_mixed_function(self):
        pairs,base=fixture();g=np.asarray(pairs[0]['grid'])
        for module,count,shape,width,_ in CASES:
            with self.subTest(experts=count):
                ex=importlib.import_module(module)
                paths=hue_training.path_constraints([g],base,expert_module=module)
                self.assertEqual(paths['first'].shape,(3*31*25,width))
                self.assertEqual(paths['second'].shape,(3*31*25,width))
                self.assertEqual(paths['base_first'].shape,(3*31*25,3))
                rng=np.random.default_rng(9);coef=rng.normal(0,.01,shape);flat=coef.reshape(width,3)
                # Independently rebuild every fixed triplet, rather than
                # merely checking the first row or a copied feature matrix.
                points=[];axis_ids=[]
                for axis in range(3):
                    other=[i for i in range(3) if i!=axis]
                    for t in np.linspace(1/32,31/32,31):
                        for a in np.linspace(0,1,5):
                            for b in np.linspace(0,1,5):
                                p=np.zeros(3);p[axis]=t;p[other]=[a,b]
                                points.append(p);axis_ids.append(axis)
                center=np.asarray(points);h=1/64;minus=center.copy();plus=center.copy()
                minus[np.arange(len(center)),axis_ids]-=h;plus[np.arange(len(center)),axis_ids]+=h
                def corr(x):
                    d=model.delta(x,g,base['coordinate_affine'],base.get('coordinate_warp'))
                    return ex.predict_correction(x,d,np.asarray(base['response_weights']),coef)
                lo,mid,hi=corr(minus),corr(center),corr(plus)
                np.testing.assert_allclose(paths['base_first']+paths['first']@flat,(hi-lo)/(2*h),atol=1e-13)
                np.testing.assert_allclose(paths['base_second']+paths['second']@flat,(hi-2*mid+lo)/h**2,atol=1e-11)

    def test_schema_predictions_match_manual_mix_and_zero_identities(self):
        pairs,base=fixture();x=np.asarray(pairs[0]['x']);g=np.asarray(pairs[0]['grid'])
        d=model.delta(x,g,base['coordinate_affine'],base.get('coordinate_warp'))
        for module,count,shape,_,schema in CASES:
            with self.subTest(experts=count):
                ex=importlib.import_module(module);rng=np.random.default_rng(72)
                candidate=copy.deepcopy(base)
                candidate.update(schema=f'r5-grid-response-calibration/{schema}',response_basis=ex.KIND,
                                 expert_weights=np.zeros(shape).tolist(),expert_gate=ex.GATE.copy())
                np.testing.assert_array_equal(model.predict(x,g,candidate),model.predict(x,g,base))
                candidate['expert_weights']=rng.normal(0,.01,shape).tolist()
                expected=np.clip(x+ex.predict_correction(x,d,np.asarray(base['response_weights']),np.asarray(candidate['expert_weights']),ex.GATE),0,1)
                np.testing.assert_array_equal(model.predict(x,g,candidate),expected)
                np.testing.assert_array_equal(model.predict(x,np.zeros_like(g),candidate),x)

    def test_expert_option_validation(self):
        for value in [None,1,'yes']:
            with self.assertRaises(ValueError):model.optimization_options(dict(hue_experts=value))
        with self.assertRaises(ValueError):model.optimization_options(dict(hue_experts=True,structured_response=False))
        self.assertTrue(model.optimization_options(dict(hue_experts=True,structured_response=True,response_degree=2))['hue_experts'])
        for value in [None,True,False,0,1,4,23,25,3.,24.,'3','24',np.int64(24)]:
            with self.assertRaises(ValueError):model.optimization_options(dict(hue_expert_count=value))
        for value in (3,24):
            self.assertEqual(model.optimization_options(dict(hue_expert_count=value))['hue_expert_count'],value)
            opts=model.optimization_options(dict(hue_experts=True,structured_response=True,response_degree=2,hue_expert_count=value))
            self.assertEqual(opts['hue_expert_count'],value)
        self.assertEqual(model.optimization_options()['hue_expert_count'],3)
        with self.assertRaises(ValueError):hue_training.refine([],{},expert_module='untrusted_plugin')


if __name__=='__main__':unittest.main()
