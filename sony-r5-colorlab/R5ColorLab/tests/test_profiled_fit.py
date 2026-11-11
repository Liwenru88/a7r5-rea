"""内层条件网格的可达目标与经过重解网格的完整梯度验证。"""
import unittest

import numpy as np

from gpu_color import paired_tensor
from gpu_tensor import TensorTools
from measured_response import get, shared_response
from profiled_fit import conditional_grid


class ProfiledGridTests(unittest.TestCase):
    def setUp(self):
        import torch
        self.torch = torch
        self.tools = TensorTools('cpu', torch.float64)
        self.response = shared_response()
        self.rgb = np.random.default_rng(18).uniform(.15, .75, (12, 3))
        self.table = np.tile([5, -3, 2], (405, 1)).astype(np.int8)
        self.target = get(self.response).predict_cpu(self.rgb, self.table)

    def test_recovers_output_of_known_integer_grid(self):
        tools = self.tools
        rgb, target = tools.tensor(self.rgb), tools.tensor(self.target)
        mass = tools.tensor(np.full(len(self.rgb), 1 / len(self.rgb)))
        grid = conditional_grid(tools, rgb, target, mass, self.response,
                                tools.tensor(np.zeros((1215, 1215))), steps=100)
        prediction = paired_tensor(tools, rgb, grid, self.response).detach().numpy()
        before = np.mean((self.rgb - self.target)**2)
        self.assertLess(np.mean((prediction - self.target)**2), before * .01)
        self.assertTrue(bool((grid >= -64).all() and (grid <= 63).all()))

    def test_gradient_includes_conditionally_resolved_grid(self):
        tools = self.tools
        desired = tools.tensor(self.target)
        mass = tools.tensor(np.full(len(self.rgb), 1 / len(self.rgb)))
        gram = tools.tensor(np.eye(1215) * 1e-5)

        def objective(values):
            table = conditional_grid(tools, values, desired, mass, self.response, gram, steps=20)
            return (paired_tensor(tools, values, table, self.response) - desired).square().mean()

        values = tools.tensor(self.rgb).requires_grad_(True)
        loss = objective(values)
        loss.backward()
        self.assertTrue(bool(self.torch.isfinite(values.grad).all()))
        direction = np.random.default_rng(9).normal(size=self.rgb.shape)
        direction /= np.linalg.norm(direction)
        epsilon = 1e-6
        expected = float((objective(tools.tensor(self.rgb + epsilon * direction)) -
                          objective(tools.tensor(self.rgb - epsilon * direction))) / (2 * epsilon))
        self.assertAlmostEqual(float((values.grad * tools.tensor(direction)).sum()), expected,
                               delta=max(1e-9, abs(expected) * .01))


if __name__ == '__main__':
    unittest.main()
