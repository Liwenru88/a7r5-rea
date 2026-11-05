import sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import model
from quality import response_solve
class QuadraticTests(unittest.TestCase):
 def test_feature_order_and_zero_grid(self):
  x=np.array([[.2,.4,.8],[.7,.1,.3]]);d=np.array([[.1,.2,.3],[-.1,.05,.07]]);z=x-.5
  f=model.features(x,d,'quadratic');self.assertEqual(f.shape,(2,30))
  np.testing.assert_array_equal(f[:,:12],model.features(x,d,True))
  q=np.column_stack([z[:,0]**2,z[:,1]**2,z[:,2]**2,z[:,0]*z[:,1],z[:,0]*z[:,2],z[:,1]*z[:,2]])
  np.testing.assert_allclose(f[:,12:],np.einsum('ni,nj->nij',d,q).reshape(-1,18))
  np.testing.assert_array_equal(model.features(x,np.zeros_like(x),'quadratic'),np.zeros((2,30)))
 def test_predict_and_quadratic_solve(self):
  rng=np.random.default_rng(5);x=rng.uniform(.1,.9,(900,3));d=rng.uniform(-.06,.06,x.shape);c=np.zeros((30,3));c[:3]=np.eye(3);c[12:]=rng.normal(0,1,(18,3))
  y=x+model.features(x,d,'quadratic')@c;w=np.ones(len(x))/len(x);mask=np.arange(len(x))%5!=0
  _,a,_=response_solve(x,y,d,True,model.features,w,mask,3)
  coef,b,_=response_solve(x,y,d,'quadratic',model.features,w,mask,3)
  self.assertLess(np.mean((b[~mask]-y[~mask])**2),np.mean((a[~mask]-y[~mask])**2))
  g=np.ones((405,3))*4;affine=np.column_stack([model.BT,model.OFFSET]);m=dict(coordinate_affine=affine.tolist(),response_basis='rgb-quadratic',smooth=True,response_weights=coef.tolist())
  np.testing.assert_array_equal(model.predict(x,np.zeros((405,3)),m),x)
  np.testing.assert_allclose(model.predict(x,g,m),np.clip(x+model.features(x,model.delta(x,g,affine),'quadratic')@coef,0,1))
 def test_options(self):
  self.assertEqual(model.optimization_options()['response_degree'],2)
  for degree in [0,3,True,'2']:
   with self.assertRaises(ValueError):model.optimization_options(dict(response_degree=degree))
