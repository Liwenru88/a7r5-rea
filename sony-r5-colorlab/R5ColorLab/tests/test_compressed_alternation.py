"""Fixed-grid forward, full native loss, and block derivatives match float64."""
import unittest
import numpy as np
from test_gpu_alternation import GPUAlternationTests
from compressed_alternation import CompressedGridObjective, residual
from measured_response import default_response,get

class CompressedAlternationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        GPUAlternationTests.setUpClass()
        src=GPUAlternationTests
        cls.smooth,cls.start,cls.vector=src.smooth,src.start,src.vector
        cls.target,cls.weights=src.target,src.weights
        cls.grid=np.random.default_rng(42).integers(-8,9,(405,3),dtype=np.int8)
        cls.response=default_response()
        cls.objective=CompressedGridObjective(cls.smooth,cls.target*16383,cls.weights,
            cls.start,cls.grid,cls.response,device='cpu',dtype=src.torch.float64)

    @classmethod
    def rows(cls,v):
        return residual(cls.smooth,cls.target*16383,cls.weights,cls.start,cls.grid,cls.response,v)

    def test_forward_and_loss_match_packed_grid_cpu(self):
        t=self.objective.gpu.tensor(self.vector)
        result=self.objective.corrected(self.objective.gpu.render(t)/16383).detach().numpy()
        expected=get(self.response).predict_cpu(self.smooth.render(self.vector)/16383,self.grid)
        np.testing.assert_allclose(result,expected,atol=2e-10,rtol=0)
        rows=self.rows(self.vector)
        self.assertAlmostEqual(float(self.objective.loss(t)),float(rows@rows)/len(self.weights),places=11)

    def test_both_native_blocks_differentiate_through_grid_coordinates(self):
        _,gradient=self.objective.value_gradient(self.vector,slice(None))
        rng=np.random.default_rng(5)
        for block in (slice(0,104),slice(104,None)):
            direction=np.zeros_like(self.vector);direction[block]=rng.normal(size=len(direction[block]));direction/=np.linalg.norm(direction)
            eps=1e-6;lo=self.rows(self.vector-eps*direction);hi=self.rows(self.vector+eps*direction)
            expected=(hi@hi-lo@lo)/(2*eps*len(self.weights))
            self.assertAlmostEqual(float(gradient@direction),expected,delta=max(1e-8,abs(expected)*.02))

    def test_fitting_guard_penalizes_gray_and_each_saturation_domain(self):
        from types import SimpleNamespace
        from adaptive_gpu import FitGuard
        from gpu_tensor import TensorTools

        tools = TensorTools(device='cpu', dtype=self.objective.gpu.tensor([0.]).dtype)
        bank = SimpleNamespace(triplets=np.arange(6).reshape(2, 3),
            mix=np.full((2, 1), .5), allowance=np.full(2, .35),
            groups=[('saturation', 1), ('native-saturation', 1)])
        probes = np.full((6, 3), .5)
        gray = np.full((2, 3), .5)
        guard = FitGuard(tools, bank, probes, gray, gray)
        reference_gray = tools.tensor(gray)
        self.assertEqual(float(guard.loss(reference_gray, tools.tensor(probes))), 0.)
        self.assertGreater(float(guard.loss(reference_gray+.02, tools.tensor(probes))), 0.)
        for center in (1, 4):
            with self.subTest(center=center):
                changed = probes.copy()
                changed[center, 0] += .05
                candidate = tools.tensor(changed).requires_grad_(True)
                loss = guard.loss(reference_gray, candidate)
                loss.backward()
                self.assertGreater(float(loss.detach()), 0.)
                self.assertGreater(float(candidate.grad[center, 0]), 0.)

class JointCandidateSelectionTests(unittest.TestCase):
    def test_color_gain_cannot_override_gray_or_transition_ceiling(self):
        from fit_bin_joint import TRANSITION_LIMITS, selection_failures
        baseline = dict(gray_rmse=.75, continuity_cost=.71, color_score=14.,
                        rgb_rmse=3., delta_e00_mean=.95)
        baseline.update(dict.fromkeys(TRANSITION_LIMITS, .5))
        better = dict(baseline, color_score=13., rgb_rmse=2.9, delta_e00_mean=.94)
        self.assertEqual(selection_failures(better, baseline, 14.), [])
        for field in ('gray_rmse', 'continuity_cost', *TRANSITION_LIMITS, 'rgb_rmse', 'delta_e00_mean'):
            with self.subTest(field=field):
                worse = dict(better)
                worse[field] = baseline[field]+.01
                self.assertEqual(selection_failures(worse, baseline, 14.), [field])
        self.assertEqual(selection_failures(better, baseline, 13.), ['validation_color_score'])


if __name__=='__main__':unittest.main()
