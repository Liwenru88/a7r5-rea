"""联合目标与独立 CPU 色差定义一致，零色差和预算边界可正常求解。"""
from types import SimpleNamespace
import time
import unittest

import numpy as np

from gpu_tensor import TensorTools
from joint_fit import JointObjective, delta_e_squared, solve
import test_gpu_alternation as gpu_fixture


class JointFitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        gpu_fixture.GPUAlternationTests.setUpClass()
        cls.source = gpu_fixture.GPUAlternationTests
        cls.torch = cls.source.torch

    def test_flat_patch_compaction_preserves_values_and_gradients(self):
        from apple_gpu import SmoothGPU

        full = SmoothGPU(self.source.smooth, 'cpu', self.torch.float64)
        compact = SmoothGPU(self.source.smooth, 'cpu', self.torch.float64, compact_flat=True)
        left = full.tensor(self.source.vector).requires_grad_(True)
        right = compact.tensor(self.source.vector).requires_grad_(True)
        a, b = full.render(left), compact.render(right)
        np.testing.assert_allclose(a.detach().numpy(), b.detach().numpy(), atol=1e-10, rtol=0)
        a.square().mean().backward()
        b.square().mean().backward()
        np.testing.assert_allclose(left.grad.numpy(), right.grad.numpy(), atol=1e-7, rtol=1e-10)

    def test_delta_e_and_neutral_gradients_match_cpu(self):
        from perceptual import de2000

        tools = TensorTools('cpu', self.torch.float64)
        first = np.array([[50, 2.6772, -79.7751], [50, 3.1571, -77.2803],
                          [50, 2.8361, -74.0200], [0, 0, 0], [50, 0, 0], [100, 0, 0]])
        second = np.array([[50, 0, -82.7485]] * 3 + [[0, 0, 0], [50, 0, 0], [100, 0, 0]])
        for dtype in (self.torch.float64, self.torch.float32):
            with self.subTest(dtype=dtype):
                tools = TensorTools('cpu', dtype)
                values = tools.tensor(first).requires_grad_(True)
                result = delta_e_squared(tools, values, tools.tensor(second))
                np.testing.assert_allclose(result.detach().numpy(), de2000(first, second)**2,
                                           rtol=3e-5, atol=1e-5)
                result.sum().backward()
                self.assertTrue(bool(self.torch.isfinite(values.grad).all()))

    def test_full_objective_and_both_gradients_match_independent_float64(self):
        from fit_anchor_native import SmoothNative
        from grid_regularization import get_penalty
        from measured_response import get, shared_response
        from optimizer_policy import display_cost_rows

        source = self.source
        count = 12
        smooth = SmoothNative(source.context, source.smooth.x[:count])
        initial = source.vector
        exact = smooth.render(initial) / 16383
        target = np.clip(exact[:-6] * [.98, 1.01, .97], 0, 1)
        grid = np.random.default_rng(7).integers(-8, 9, (405, 3), dtype=np.int8)
        bank = SimpleNamespace(triplets=np.arange(6).reshape(2, 3), mix=np.full((2, 1), .5),
            allowance=np.ones(2), groups=[('saturation', 1), ('native-saturation', 1)],
            mass=np.full(2, .5), distance=np.ones(2), gain_limit=np.full(2, 32))
        response = shared_response()
        objective = JointObjective(smooth, initial, exact, target, np.ones(6), np.arange(2),
            bank, grid, response, .35, 0, 30, device='cpu', dtype=self.torch.float64)
        n_native = objective.basis.shape[1]
        values = np.r_[np.zeros(n_native), grid.ravel() / 32]
        tools = objective.tools

        def gpu_loss(tensor):
            controls = tensor[:n_native]
            return objective.loss(objective.native(controls), tensor[n_native:].reshape(405, 3) * 32,
                                  objective.vector(controls), 0)

        def cpu_loss(vector):
            native = objective.vector(tools.tensor(vector[:n_native])).numpy()
            base = smooth.render(native) / 16383
            table = vector[n_native:].reshape(405, 3) * 32
            predicted = get(response).predict_cpu(base, table)[:6]
            return display_cost_rows(predicted, target, .35).mean() / 255**2 + .001 * get_penalty(response).raw_loss(table)

        tensor = tools.tensor(values).requires_grad_(True)
        loss = gpu_loss(tensor)
        loss.backward()
        self.assertAlmostEqual(float(loss.detach()), cpu_loss(values), places=10)
        gradient = tensor.grad.numpy()
        for block in (slice(0, n_native), slice(n_native, None)):
            direction = np.zeros_like(values)
            direction[block] = np.random.default_rng(23).normal(size=len(values[block]))
            direction /= np.linalg.norm(direction)
            epsilon = 1e-5
            expected = (cpu_loss(values + epsilon * direction) - cpu_loss(values - epsilon * direction)) / (2 * epsilon)
            self.assertAlmostEqual(float(gradient @ direction), expected,
                                   delta=max(1e-8, abs(expected) * .01))

    def test_expired_budget_returns_unchanged_values(self):
        tools = TensorTools('cpu', self.torch.float64)
        original = np.array([2., -1.])
        values, audit = solve((tools, lambda x: x.square().sum()), original,
            [(-3., 3.)] * 2, time.perf_counter() - 1, 20, None, 'expired')
        np.testing.assert_array_equal(values, original)
        self.assertEqual(audit['evaluations'], 0)
        self.assertIsNone(audit['training_loss'])


if __name__ == '__main__':
    unittest.main()
