"""Check full frozen-PC loss and derivatives against the CPU implementation."""
import unittest
import numpy as np
import baseline
import v4_dataset
from fit_anchor_native import SmoothNative, vector_for
from edit_parameter_context import ParameterContext, RuntimeColor
from optimizer_policy import smooth_loss_rows
from parameter_smoothing import native_rows
import pc_stages


class GPUAlternationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import torch
        except ImportError:
            raise unittest.SkipTest('optional PyTorch unavailable')
        from gpu_alternation import BlockObjective
        cls.torch = torch
        context = ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.PT_ID)))
        arrays, _ = v4_dataset.load()
        indices = np.flatnonzero(arrays['sample_kind'] == 'uniform_luma')[::173]
        cls.smooth = SmoothNative(context, arrays['input'][indices])
        cls.start = vector_for(context)
        cls.vector = cls.start + np.random.default_rng(4).normal(0, .025, len(cls.start))
        base = cls.smooth.render(cls.start) / 16383
        gray_input = np.linspace(0, 1, 256)[:, None] * np.ones((1, 3))
        curve = pc_stages.fit_curves(gray_input, gray_input**1.08)
        curve['tint'] = (np.asarray(curve['tint']) + np.array([.002, -.001, .001]) -
            np.array([.002, -.001, .001]) @ pc_stages.LUMA).tolist()
        grid = np.random.default_rng(6).integers(-5, 6, (405, 3), dtype=np.int8)
        cls.bundle = (curve, grid, {})
        cls.target = np.clip(base * [.91, 1.02, .95], 0, 1)
        cls.weights = np.linspace(.5, 1.5, len(indices))
        cls.objective = BlockObjective(cls.smooth, cls.target * 16383, cls.weights,
            cls.start, cls.bundle, .35, 30, device='cpu', dtype=torch.float64)
        cls.context = context

    @classmethod
    def residual(cls, vector):
        predicted = pc_stages.render(cls.smooth.render(vector) / 16383, *cls.bundle[:2])
        data = smooth_loss_rows(predicted, cls.target, .35) * np.sqrt(cls.weights)[:, None]
        smoothing = native_rows(vector[8:104], cls.smooth.gamma(vector) * 16,
            cls.context.axis, 30, cc1=vector[:8],config=cls.context.base.config) * np.sqrt(len(cls.weights))
        return np.r_[data.ravel(), smoothing]

    def test_forward_and_full_loss_match_cpu(self):
        tensor = self.objective.gpu.tensor(self.vector)
        predicted = self.objective.corrected(self.objective.gpu.render(tensor) / 16383)
        reference = pc_stages.render(self.smooth.render(self.vector) / 16383, *self.bundle[:2])
        np.testing.assert_allclose(predicted.detach().numpy(), reference, atol=2e-10, rtol=0)
        rows = self.residual(self.vector)
        self.assertAlmostEqual(float(self.objective.loss(tensor)), float(rows @ rows) / len(self.weights), places=11)

    def test_autograd_directional_derivatives_match_cpu(self):
        _, gradient = self.objective.value_gradient(self.vector, slice(None))
        rng = np.random.default_rng(15)
        for block in (slice(0, 104), slice(104, None)):
            direction = np.zeros_like(self.vector)
            direction[block] = rng.normal(0, 1, len(direction[block]))
            direction /= np.linalg.norm(direction)
            epsilon = 1e-6
            lo = self.residual(self.vector - epsilon * direction)
            hi = self.residual(self.vector + epsilon * direction)
            expected = (hi @ hi - lo @ lo) / (2 * epsilon * len(self.weights))
            self.assertAlmostEqual(float(gradient @ direction), expected,
                delta=max(1e-8, abs(expected) * .02))


if __name__ == '__main__':
    unittest.main()
