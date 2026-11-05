from legacy_fit_fixture import legacy_fit
import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import model,structured_response as s
from structured_training import refine
from test_calibrator import FitTests


class StructuredTrainingTests(unittest.TestCase):
    def test_prediction_compatibility_and_schema_dispatch(self):
        rng=np.random.default_rng(12);x=rng.uniform(.1,.9,(40,3));g=rng.integers(-12,13,(405,3));a=np.column_stack([model.BT,model.OFFSET])
        old=dict(coordinate_affine=a.tolist(),smooth=False,response_weights=np.eye(3).tolist())
        np.testing.assert_array_equal(model.predict(x,g,old),np.clip(x+model.delta(x,g,a),0,1))
        new=dict(coordinate_affine=a.tolist(),smooth=True,response_basis=s.KIND,response_weights=s.from_nodes(np.tile(np.eye(3),(3,3,3,1,1))).tolist())
        np.testing.assert_allclose(model.predict(x,g,new),model.predict(x,g,old),atol=1e-16)
        np.testing.assert_array_equal(model.predict(x,np.zeros_like(g),new),x)
        new['response_basis']=s.KIND_C1
        np.testing.assert_allclose(model.predict(x,g,new),model.predict(x,g,old),atol=1e-16)
        np.testing.assert_array_equal(model.predict(x,np.zeros_like(g),new),x)

    def test_test_probe_colors_targets_and_grid_cannot_affect_training(self):
        pairs,_=FitTests().pairs();initial=legacy_fit(pairs,refine=False,options=dict(response_degree=2,perceptual_mix=1))
        seen=[]
        def fake(x,y,d,weights,init,**kwargs):
            seen.append([v.copy() for v in [x,y,d,weights,init,kwargs['path_constraints']['first'],kwargs['path_constraints']['second']]])
            return init.copy(),dict(device='test-double',accepted=True)
        changed=copy.deepcopy(pairs);changed[-1]['x']=np.full_like(changed[-1]['x'],.2);changed[-1]['y']=np.zeros_like(changed[-1]['y']);changed[-1]['grid']=np.full_like(changed[-1]['grid'],-63)
        with patch('structured_response.solve',side_effect=fake):
            a=refine(pairs,initial,device='cpu',strengths=(1,),iterations=1,curvature_scales=(.5,))
            b=refine(changed,initial,device='cpu',strengths=(1,),iterations=1,curvature_scales=(.5,))
        for x,y in zip(*seen):np.testing.assert_array_equal(x,y)
        np.testing.assert_array_equal(a['response_weights'],b['response_weights'])
        self.assertEqual(a['report']['structured_response']['selected_validation_objective'],b['report']['structured_response']['selected_validation_objective'])
        np.testing.assert_array_equal(a['coordinate_affine'],initial['coordinate_affine'])

    def test_option_validation(self):
        for value in [None,1,'true']:
            with self.assertRaises(ValueError):model.optimization_options(dict(structured_response=value))
        with self.assertRaises(ValueError):model.optimization_options(dict(structured_response=True,response_degree=1))
        for v in [True,None,-.01,1.01,float('nan'),'0.5']:
            with self.assertRaises(ValueError):model.optimization_options(dict(curvature_scale=v))
        self.assertEqual(model.optimization_options(dict(curvature_scale=.75))['curvature_scale'],.75)

    def test_curvature_candidates_preserve_fallback_and_frozen_coordinates(self):
        pairs,_=FitTests().pairs();initial=legacy_fit(pairs,refine=False,options=dict(response_degree=2,perceptual_mix=1))
        captured=[];seen=[]
        def poor_candidate(x,y,d,weights,init,**kwargs):
            seen.append(kwargs['curvature_scale'])
            return np.zeros_like(init),dict(device='test-double')
        with patch('structured_response.solve',side_effect=poor_candidate):
            result=refine(pairs,initial,device='cpu',strengths=(.25,),iterations=1,curvature_scales=(.75,.5),baseline_model=initial,on_candidate=lambda *args:captured.append(args))
        self.assertEqual(seen,[.75,.5]);self.assertEqual(len(captured),2)
        np.testing.assert_array_equal(result['response_weights'],initial['response_weights'])
        wrong=copy.deepcopy(initial);wrong['coordinate_affine'][0][0]+=.01
        with self.assertRaises(ValueError):refine(pairs,initial,baseline_model=wrong)


if __name__=='__main__':unittest.main()
