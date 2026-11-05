"""Pinned nonlinear response parity, old identities and tensor gradients."""
import copy
import unittest
from unittest.mock import patch
import numpy as np
from measured_response import nonlinear_response,previous_r5_response,v2_response,get
from gpu_tensor import TensorTools
from gpu_color import paired_tensor

class NonlinearTests(unittest.TestCase):
    def setUp(self):
        self.rng=np.random.default_rng(531)
        self.x=np.r_[self.rng.random((1024,3)),np.zeros((1,3)),np.ones((1,3)),np.eye(3)]
        self.grid=self.rng.integers(-64,64,(405,3))
    def reference(self,m):
        x=self.x;a=m.affine;c=x@a[:,:3].T+a[:,3]
        if m.warp:
            b=np.stack([(1-x)**2,2*x*(1-x),x*x],2)
            c+=np.einsum('ni,nj,nk->nijk',b[:,0],b[:,1],b[:,2]).reshape(-1,27)@np.asarray(m.warp['control']).reshape(27,3)
        at=np.clip(c*[4,8,8]+[0,4,4],0,[4,8,8]);lo=np.minimum(np.floor(at).astype(int),[3,7,7]);f=at-lo;d=np.zeros_like(x)
        for i in (0,1):
            for j in (0,1):
                for k in (0,1):
                    w=(f[:,0] if i else 1-f[:,0])*(f[:,1] if j else 1-f[:,1])*(f[:,2] if k else 1-f[:,2])
                    d+=w[:,None]*self.grid[(lo[:,0]+i)*81+(lo[:,1]+j)*9+lo[:,2]+k]/256
        z=x-.5;parts=[d]
        if m.smooth:parts.append((d[:,:,None]*z[:,None,:]).reshape(-1,9))
        if m.quadratic:
            q=np.column_stack([z[:,0]**2,z[:,1]**2,z[:,2]**2,z[:,0]*z[:,1],z[:,0]*z[:,2],z[:,1]*z[:,2]])
            parts.append((d[:,:,None]*q[:,None,:]).reshape(-1,18))
        return np.clip(x+np.concatenate(parts,1)@m.weights,0,1)
    def test_all_snapshots_match_independent_feature_definition(self):
        for identity in (previous_r5_response(),v2_response(),nonlinear_response()):
            m=get(identity)
            np.testing.assert_allclose(m.predict_cpu(self.x,self.grid),self.reference(m),atol=3e-15)
            np.testing.assert_array_equal(m.predict_cpu(self.x,np.zeros((405,3))),self.x)
    def test_old_gpu_dispatch_keeps_exact_saved_identity(self):
        for identity in (previous_r5_response(),v2_response(),nonlinear_response()):
            with patch('gpu_runtime.available',return_value=True),patch('gpu_color.paired_numpy',return_value=self.x) as render:
                get(identity).predict(self.x,self.grid)
                self.assertEqual(render.call_args.args[2],identity)
    def test_tensor_parity_and_directional_grid_gradient(self):
        import torch
        torch.set_num_threads(8)
        tools=TensorTools('cpu',torch.float64)
        for identity in (previous_r5_response(),v2_response(),nonlinear_response()):
            m=get(identity);x=tools.tensor(self.x);g=tools.tensor(self.grid).requires_grad_(True)
            np.testing.assert_allclose(m.coordinates_tensor(tools,x).numpy(),m.coordinates(self.x),atol=2e-15)
            np.testing.assert_allclose(m.response_tensor(tools,x).numpy(),m.response(self.x),atol=2e-15)
            y=paired_tensor(tools,x,g,identity)
            np.testing.assert_allclose(y.detach().numpy(),m.predict_cpu(self.x,self.grid),atol=3e-15)
            loss=y.square().mean();loss.backward()
            direction=self.rng.normal(size=(405,3));eps=1e-4
            hi=np.mean(m.predict_cpu(self.x,self.grid+eps*direction)**2)
            lo=np.mean(m.predict_cpu(self.x,self.grid-eps*direction)**2)
            self.assertAlmostEqual(float((g.grad*tools.tensor(direction)).sum()),(hi-lo)/(2*eps),delta=1e-10)
    def test_bad_identity_or_folding_warp_rejected(self):
        identity=nonlinear_response();identity['sha256']='0'*64
        with self.assertRaises(ValueError):get(identity)
        from paired_response import PairedModel
        m=get(nonlinear_response());v=copy.deepcopy(m.value)
        v['coordinate_warp']['control'][0][0][0][0]=1
        with self.assertRaises(ValueError):PairedModel(v,m.sha256)

if __name__=='__main__':unittest.main()
