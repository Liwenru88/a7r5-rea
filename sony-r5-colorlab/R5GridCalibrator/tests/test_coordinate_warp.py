from legacy_fit_fixture import legacy_fit
import sys,unittest,copy
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import model,coordinate_warp as w
class WarpTests(unittest.TestCase):
 def test_basis_partition_and_affine_reproduction(self):
  x=np.random.default_rng(1).uniform(0,1,(100,3));b=w.basis(x)
  self.assertTrue((b>=0).all());np.testing.assert_allclose(b.sum(1),1,atol=1e-14)
  controls=np.stack(np.meshgrid(*([np.linspace(0,1,3)]*3),indexing='ij'),-1)
  np.testing.assert_allclose(b@controls.reshape(27,3),x,atol=1e-14)
 def test_certificate_projection_and_identity(self):
  a=np.column_stack([model.BT,model.OFFSET]);rng=np.random.default_rng(2);c=w.projected_control(rng.normal(0,5,(3,3,3,3)),a);check=w.certificate(c,a);self.assertTrue(check['valid'])
  warp=dict(kind=w.KIND,control=c.tolist());x=rng.uniform(0,1,(100,3));np.testing.assert_allclose(w.coordinates(x,a,dict(kind=w.KIND,control=np.zeros_like(c).tolist())),w.coordinates(x,a))
  m=dict(coordinate_affine=a.tolist(),coordinate_warp=warp,response_basis='rgb-quadratic',smooth=True,response_weights=rng.normal(size=(30,3)).tolist())
  np.testing.assert_array_equal(model.predict(x,np.zeros((405,3)),m),x)
  for i in range(3):
   step=np.zeros_like(x);step[:,i]=1e-6;plus=w.coordinates(x+step,a,warp);minus=w.coordinates(x-step,a,warp)
   derivative=(plus-minus)/2e-6
   self.assertTrue(np.isfinite(derivative).all())
  bad=copy.deepcopy(warp);bad['control']=np.ones((3,3,3,3)).tolist()
  with self.assertRaises(ValueError):w.coordinates(x,a,bad)
 def test_predict_legacy_exact_and_no_new_lookup_order(self):
  rng=np.random.default_rng(8);x=rng.uniform(0,1,(100,3));g=rng.integers(-32,33,(405,3));a=np.column_stack([model.BT,model.OFFSET]);
  np.testing.assert_array_equal(model.delta(x,g,a),w.delta_at(w.coordinates(x,a),g))
 def test_options(self):
  for v in [None,1,'true']:
   with self.assertRaises(ValueError):model.optimization_options(dict(nonlinear_coordinates=v))
 def test_warp_training_excludes_test_targets_and_colors(self):
  from unittest.mock import patch
  from test_calibrator import FitTests
  from warp_training import refine
  pairs,_=FitTests().pairs();initial=legacy_fit(pairs,refine=False,options=dict(response_degree=2,perceptual_mix=1))
  coef=np.asarray(initial['response_weights']);expanded=np.zeros((30,3));expanded[:len(coef)]=coef;initial['response_weights']=expanded.tolist();initial['response_basis']='rgb-quadratic';initial['smooth']=True;initial['report']['optimization']['options']['coordinate_device']='mps'
  def fake(x,y,ids,grids,coef,affine,raw,weights,*args):
   c=np.zeros((3,3,3,3));return c,c,dict(device='test-double',autograd=False,closure_calls=0,certificate=w.certificate(c,affine))
  with patch('warp_training.solve_gpu',side_effect=fake):
   a=refine(pairs,initial,starts=1,turns=1,iterations=1)
   changed=copy.deepcopy(pairs);changed[-1]['x']=np.ones_like(changed[-1]['x'])*.2;changed[-1]['y']=np.zeros_like(changed[-1]['y'])
   b=refine(changed,initial,starts=1,turns=1,iterations=1)
  np.testing.assert_array_equal(a['coordinate_affine'],b['coordinate_affine']);np.testing.assert_array_equal(a['response_weights'],b['response_weights'])
  self.assertEqual(a.get('coordinate_warp'),b.get('coordinate_warp'))
