import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import model
from perceptual import oklab,lab_jacobian,joint_residual,metrics
from quality import response_solve
class PerceptualTests(unittest.TestCase):
 def test_reference_and_jacobian(self):
  np.testing.assert_allclose(oklab([[0,0,0],[1,1,1]]),[[0,0,0],[1,0,0]],atol=1e-7)
  x=np.random.default_rng(4).uniform(.05,.95,(20,3));j=lab_jacobian(x)
  for k in range(3):
   step=np.zeros_like(x);step[:,k]=1e-6;np.testing.assert_allclose(j[:,:,k],(oklab(x+step)-oklab(x-step))/2e-6,atol=1e-7)
 def test_gray_hue_gate_and_zero(self):
  x=np.array([[.2,.2,.2],[.8,.2,.1],[0,0,0],[1,1,1]])
  m=metrics(x,x);self.assertEqual(m['hue_count'],1);self.assertEqual(m['hue_degrees_mae'],0);self.assertEqual(m['deltaE_OK_mean'],0)
  np.testing.assert_array_equal(joint_residual(x,x,3,1),np.zeros((4,6)))
 def test_joint_response_decreases_objective(self):
  rng=np.random.default_rng(9);x=rng.uniform(.15,.8,(160,3));d=rng.uniform(-.03,.03,x.shape);y=np.clip(x+d@np.array([[1,.2,.3],[.1,.8,.1],[.2,.1,.9]]),0,1);w=np.ones(len(x))/len(x);mask=np.ones(len(x),bool)
  c,p,_=response_solve(x,y,d,True,model.features,w,mask,3,1)
  self.assertTrue(np.isfinite(c).all());self.assertLess(np.mean(joint_residual(p,y,3,1)**2),np.mean(joint_residual(x,y,3,1)**2)/10)
 def test_invalid_mix(self):
  for v in [True,-1,11,float('nan')]:
   with self.assertRaises(ValueError):model.optimization_options(dict(perceptual_mix=v))
