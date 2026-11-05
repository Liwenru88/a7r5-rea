import sys
import unittest
from pathlib import Path
import numpy as np
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import structured_response as s


class StructuredResponseTests(unittest.TestCase):
    def test_hierarchical_nodes_and_coarse_partition(self):
        rng = np.random.default_rng(4)
        x = rng.uniform(0, 1, (100, 3)); b = s.basis(x)
        self.assertEqual(b.shape, (100, 27))
        np.testing.assert_allclose(b[:, :8].sum(1), 1, atol=1e-15)
        self.assertTrue(np.all(b >= 0))
        # Local residuals must not alter the eight broad corner anchors.
        np.testing.assert_array_equal(s.basis(s.NODES[s.CORNER_INDICES])[:, 8:], 0)
        nodes = rng.normal(size=(3, 3, 3, 3, 3))
        np.testing.assert_allclose(s.field_nodes(s.from_nodes(nodes)), nodes, atol=1e-15)
        # Independent ordinary trilinear interpolation of the nodal field.
        at=x*2;lo=np.minimum(np.floor(at).astype(int),1);fraction=at-lo
        expected=np.zeros((len(x),3,3))
        for dx in (0,1):
            for dy in (0,1):
                for dz in (0,1):
                    w=(fraction[:,0] if dx else 1-fraction[:,0])*(fraction[:,1] if dy else 1-fraction[:,1])*(fraction[:,2] if dz else 1-fraction[:,2])
                    expected += w[:,None,None]*nodes[lo[:,0]+dx,lo[:,1]+dy,lo[:,2]+dz]
        actual=np.einsum('nb,cbo->nco',b,s.from_nodes(nodes).reshape(3,27,3))
        np.testing.assert_allclose(actual,expected,atol=2e-15)

    def test_quadratic_initialization_matches_nodes_not_false_global_equality(self):
        rng=np.random.default_rng(8);old=rng.normal(size=(30,3));new=s.from_quadratic(old)
        x=s.NODES;z=x-.5;q=np.column_stack([z[:,0]**2,z[:,1]**2,z[:,2]**2,z[:,0]*z[:,1],z[:,0]*z[:,2],z[:,1]*z[:,2]])
        for component in range(3):
            d=np.zeros_like(x);d[:,component]=1
            f=np.concatenate([d,np.einsum('ni,nj->nij',d,z).reshape(-1,9),np.einsum('ni,nj->nij',d,q).reshape(-1,18)],axis=1)
            np.testing.assert_allclose(s.predict_correction(x,d,new),f@old,atol=2e-15)
        # A quadratic cannot in general be made globally identical by 27 nodal samples.
        old=np.zeros((30,3));old[12,0]=1
        actual=s.predict_correction(np.array([[.25,.2,.3]]),np.array([[1.,0,0]]),s.from_quadratic(old))
        self.assertAlmostEqual(actual[0,0],.125)
        self.assertNotAlmostEqual(actual[0,0],.25**2)

    def test_zero_delta_and_c0_halfstep(self):
        rng=np.random.default_rng(12);c=rng.normal(size=(81,3));x=rng.uniform(.1,.9,(30,3))
        np.testing.assert_array_equal(s.predict_correction(x,np.zeros_like(x),c),np.zeros_like(x))
        center=x.copy();center[:,0]=.5
        left=center.copy();left[:,0]-=1e-9
        right=center.copy();right[:,0]+=1e-9
        d=np.ones_like(x)
        np.testing.assert_allclose(s.predict_correction(left,d,c),s.predict_correction(right,d,c),atol=1e-7)

    def test_roughness_and_unsupported_detail_shrinkage(self):
        nodes=np.ones((3,3,3,3,3));constant=s.from_nodes(nodes)
        oscillatory=nodes.copy();oscillatory[1]*=-1;rough=s.from_nodes(oscillatory)
        self.assertAlmostEqual(s.roughness(constant)['knot_gradient_jump_rms'],0)
        self.assertGreater(s.roughness(rough)['curvature_penalty'],s.roughness(constant)['curvature_penalty'])
        support,factor=s.detail_support(np.zeros((10,3)),np.ones(10))
        self.assertTrue(np.all(support==0));self.assertTrue(np.all(factor==16))
        path=np.zeros((1,81));path[0,8]=1
        penalty=s.regularization_terms(rough,path_constraints={'second':path})
        self.assertGreaterEqual(penalty['path_curvature'],0)

    def test_invalid_inputs(self):
        for x in [np.ones((3,3))*1.1,np.ones((3,2)),np.array([[np.nan,0,0]])]:
            with self.assertRaises(ValueError):s.basis(x)
        with self.assertRaises(ValueError):s.from_quadratic(np.zeros((12,3)))
        with self.assertRaises(ValueError):s.field_nodes(np.zeros((27,3)))

    def test_cpu_solver_recovers_smooth_synthetic_response(self):
        try:import torch
        except ImportError:self.skipTest('torch unavailable')
        rng=np.random.default_rng(20);x=rng.uniform(.15,.85,(480,3));d=rng.uniform(-.08,.08,x.shape)
        field=np.zeros((3,3,3,3,3))
        for i,node in enumerate(s.NODES):
            field.reshape(27,3,3)[i]=np.eye(3)*(.2+.1*node[0])
        true=s.from_nodes(field);y=x+s.predict_correction(x,d,true)
        coef,note=s.solve(x,y,d,np.ones(len(x)),np.zeros((81,3)),regularization=0,device='cpu',iterations=250,scale=0,mix=0)
        self.assertTrue(note['accepted'])
        self.assertLess(np.sqrt(np.mean((s.predict_correction(x,d,coef)-(y-x))**2)),2e-5)
        self.assertLess(note['preflight_max_rgb_error'],1e-12)
        self.assertLess(note['final_data_loss'],note['initial_objective']*.0001)


if __name__=='__main__':unittest.main()
