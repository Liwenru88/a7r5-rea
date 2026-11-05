import sys
import unittest
from itertools import product
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import structured_response as s


class StructuredC1Tests(unittest.TestCase):
    def test_default_hat_remains_exact_and_c1_nodes_match(self):
        rng = np.random.default_rng(171)
        x = rng.uniform(0, 1, (100, 3))
        corners = np.asarray(list(product((0, 2), repeat=3)))
        details = [p for p in product(range(3), repeat=3) if tuple(p) not in map(tuple, corners)]
        coarse = np.stack([np.prod(np.where(c == 2, x, 1-x), axis=1) for c in corners], axis=1)
        hats = np.maximum(1-np.abs(2*x[:, :, None]-np.arange(3)), 0)
        fine = np.stack([hats[:,0,a]*hats[:,1,b]*hats[:,2,c] for a,b,c in details], axis=1)
        np.testing.assert_array_equal(s.basis(x), np.concatenate([coarse, fine], axis=1))
        np.testing.assert_array_equal(s.basis(s.NODES), s.basis(s.NODES, s.KIND_C1))
        b = s.basis(x, s.KIND_C1)
        self.assertTrue(np.all(b >= 0))
        np.testing.assert_allclose(b[:,:8].sum(1), 1, atol=1e-15)
        nodes = rng.normal(size=(3,3,3,3,3))
        np.testing.assert_allclose(s.field_nodes(s.from_nodes(nodes, s.KIND_C1), s.KIND_C1), nodes, atol=1e-15)

    def test_c1_is_independent_smoothstep_interpolant_not_linear_hat(self):
        # A single midpoint residual demonstrates a local cubic segment.
        coef = np.zeros((3,27,3))
        index = list(s.DETAILS).index((1,1,1)) + 8
        coef[0,index,0] = 1
        x = np.array([[.125,.5,.5],[.25,.5,.5],[.75,.5,.5],[0,.5,.5]])
        d = np.tile([1.,0,0],(len(x),1))
        result = s.predict_correction(x,d,coef.reshape(81,3),s.KIND_C1)[:,0]
        np.testing.assert_allclose(result, [.15625,.5,.5,0], atol=1e-15)
        self.assertNotEqual(result[0], s.predict_correction(x,d,coef.reshape(81,3))[0,0])
        np.testing.assert_array_equal(s.predict_correction(x,np.zeros_like(x),coef.reshape(81,3),s.KIND_C1),0)

    def test_first_derivative_continuity_on_all_halfstep_planes(self):
        rng = np.random.default_rng(291)
        coef = rng.normal(size=(81,3))
        # Three-point one-sided derivative is exact for quadratic, with O(h²)
        # error for these piecewise cubics. Repeat at h/2 to confirm convergence.
        for axis in range(3):
            center = rng.uniform(.05,.95,(24,3)); center[:,axis] = .5
            d = rng.normal(size=center.shape)
            jumps = []
            for h in (1e-3,5e-4):
                def at(offset):
                    x = center.copy(); x[:,axis] += offset
                    return s.predict_correction(x,d,coef,s.KIND_C1)
                mid = at(0)
                left = (3*mid-4*at(-h)+at(-2*h))/(2*h)
                right = (-3*mid+4*at(h)-at(2*h))/(2*h)
                jumps.append(np.max(abs(right-left)))
            self.assertLess(jumps[1], 1e-4)
            self.assertLessEqual(jumps[1], jumps[0]*.251+1e-10)
        diagnostic = s.roughness(coef,s.KIND_C1)
        self.assertEqual(diagnostic['exact_knot_gradient_jump'],0)
        self.assertIn('not C2',diagnostic['continuity'])
        self.assertGreater(diagnostic['nodal_curvature_surrogate_rms'],0)

    def test_quadratic_initialization_is_nodal_only(self):
        rng = np.random.default_rng(42)
        old = rng.normal(size=(30,3))
        np.testing.assert_array_equal(s.from_quadratic(old,s.KIND_C1),s.from_quadratic(old))
        # Nodal coefficients match; interior interpolation deliberately differs.
        coef=s.from_quadratic(old,s.KIND_C1)
        x=np.array([[.15,.23,.78]])
        self.assertGreater(np.max(abs(s.predict_correction(x,np.ones_like(x),coef,s.KIND_C1)-s.predict_correction(x,np.ones_like(x),coef))),1e-3)

    def test_cpu_solver_uses_c1_features_and_matching_regularizer(self):
        try: import torch
        except ImportError: self.skipTest('torch unavailable')
        rng=np.random.default_rng(11)
        x=rng.uniform(.15,.85,(300,3));d=rng.uniform(-.08,.08,x.shape)
        true=np.zeros((3,27,3))
        true[:, :8] = np.eye(3)[:,None,:]*.2
        true[0,8,0]=.03
        true=true.reshape(81,3)
        y=x+s.predict_correction(x,d,true,s.KIND_C1)
        paths={'first':rng.normal(size=(3,81))*.001,'second':rng.normal(size=(3,81))*.001}
        coef,note=s.solve(x,y,d,np.ones(len(x)),np.zeros_like(true),regularization=.25,
                          device='cpu',iterations=120,scale=0,mix=0,path_constraints=paths,kind=s.KIND_C1)
        self.assertTrue(note['accepted'])
        self.assertEqual(note['response_basis'],s.KIND_C1)
        self.assertEqual(note['penalty_rates']['path_curvature'],3e-5)
        self.assertEqual(note['penalty_rates']['path_gradient'],1e-7)
        self.assertEqual(s.PENALTY_RATES['path_curvature'],3e-8)
        self.assertLess(note['preflight_regularizer_relative_error'],1e-12)
        self.assertLess(note['final_data_loss'],note['initial_objective']*.001)
        self.assertLess(np.sqrt(np.mean((s.predict_correction(x,d,coef,s.KIND_C1)-(y-x))**2)),1e-4)


if __name__ == '__main__':
    unittest.main()
