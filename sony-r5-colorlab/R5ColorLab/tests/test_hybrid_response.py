"""Independent mathematical oracle for the pinned Hybrid response."""
from itertools import product
import json
from pathlib import Path
import sys
import unittest

import numpy as np

HERE = Path(__file__).resolve().parents[1]/'web'
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'scripts'))

import measured_response

DETAIL = np.array([a * 9 + b * 3 + c for a, b, c in product(range(3), repeat=3)
                   if (a, b, c) not in tuple(product((0, 2), repeat=3))])
DIRECTIONS = np.array([[1., 0.], [-.5, np.sqrt(3) / 2],
                       [-.5, -np.sqrt(3) / 2]])


def oracle_coordinates(rgb, value):
    x = np.asarray(rgb, float)
    affine = np.asarray(value['coordinate_affine'], float)
    out = x @ affine[:, :3].T + affine[:, 3]
    control = np.asarray(value['coordinate_warp']['control'], float).reshape(27, 3)
    bernstein = np.stack([(1 - x) ** 2, 2 * x * (1 - x), x ** 2], axis=2)
    basis = np.einsum('ni,nj,nk->nijk', bernstein[:, 0], bernstein[:, 1],
                      bernstein[:, 2]).reshape(-1, 27)
    return out + basis @ control


def oracle_stencil(coordinates):
    shape = np.array([5, 9, 9])
    position = np.clip((coordinates + [0, .5, .5]) * (shape - 1), 0, shape - 1)
    low = np.minimum(np.floor(position).astype(int), shape - 2)
    fraction = position - low
    indices, weights = [], []
    for y, u, v in product((0, 1), repeat=3):
        indices.append(((low[:, 0] + y) * 9 + low[:, 1] + u) * 9 + low[:, 2] + v)
        weights.append((fraction[:, 0] if y else 1 - fraction[:, 0]) *
                       (fraction[:, 1] if u else 1 - fraction[:, 1]) *
                       (fraction[:, 2] if v else 1 - fraction[:, 2]))
    return np.stack(indices, axis=1), np.stack(weights, axis=1)


def oracle_c1_basis(rgb):
    x = np.asarray(rgb, float)
    ends = np.stack([1 - x, x], axis=2)
    coarse = np.einsum('ni,nj,nk->nijk', ends[:, 0], ends[:, 1],
                       ends[:, 2]).reshape(-1, 8)
    hats = np.maximum(1 - np.abs(2 * x[:, :, None] - np.arange(3)), 0)
    hats = hats * hats * (3 - 2 * hats)
    fine = np.einsum('ni,nj,nk->nijk', hats[:, 0], hats[:, 1],
                     hats[:, 2]).reshape(-1, 27)
    return np.concatenate([coarse, fine[:, DETAIL]], axis=1)


def oracle_response(rgb, value):
    x = np.asarray(rgb, float)
    weights = np.asarray(value.get('base_response_weights', value['response_weights']), float)
    z = x - .5
    response = np.broadcast_to(weights[:3], (len(x), 3, 3)).copy()
    response += np.einsum('nj,cjo->nco', z, weights[3:12].reshape(3, 3, 3))
    quadratic = np.column_stack([z[:, 0] ** 2, z[:, 1] ** 2, z[:, 2] ** 2,
                                 z[:, 0] * z[:, 1], z[:, 0] * z[:, 2],
                                 z[:, 1] * z[:, 2]])
    response += np.einsum('nj,cjo->nco', quadratic, weights[12:].reshape(3, 6, 3))

    hue = np.column_stack([x[:, 0] - (x[:, 1] + x[:, 2]) / 2,
                           np.sqrt(3) / 2 * (x[:, 1] - x[:, 2])])
    squared_chroma = np.sum(hue * hue, axis=1)
    gate = value['expert_gate']
    logits = gate['kappa'] * (hue @ DIRECTIONS.T) / gate['s0']
    logits -= logits.max(axis=1, keepdims=True)
    probabilities = np.exp(logits)
    probabilities /= probabilities.sum(axis=1, keepdims=True)
    gates = (squared_chroma / (squared_chroma + gate['c0'] ** 2))[:, None] * probabilities
    experts = np.asarray(value['expert_weights'], float).reshape(3, 3, 27, 3)
    extra = np.einsum('nb,ecbo->neco', oracle_c1_basis(x), experts)
    return (response + np.einsum('ne,neco->nco', gates, extra)) / 256


def oracle_predict(rgb, table, value, clip=True):
    x = np.asarray(rgb, float)
    indices, weights = oracle_stencil(oracle_coordinates(x, value))
    delta = (np.asarray(table)[indices] * weights[:, :, None]).sum(axis=1)
    out = x + np.einsum('nc,nco->no', delta, oracle_response(x, value))
    return np.clip(out, 0, 1) if clip else out


class HybridResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.identity = measured_response.hybrid_response()
        cls.model = measured_response.get(cls.identity)
        cls.value = json.loads((HERE / 'data/r5/paired-20261107-nonlinear-he3.json').read_text())
        rng = np.random.default_rng(20261107)
        cls.rgb = np.r_[rng.random((1024, 3)),
                        np.repeat(np.linspace(0, 1, 129)[:, None], 3, axis=1),
                        np.array(list(product([0., .5, 1.], repeat=3)))]
        cls.table = rng.integers(-64, 64, (405, 3), dtype=np.int8)

    def test_cpu_coordinates_response_and_render_match_oracle(self):
        np.testing.assert_allclose(self.model.coordinates(self.rgb),
                                   oracle_coordinates(self.rgb, self.value), atol=2e-15, rtol=0)
        np.testing.assert_allclose(self.model.response(self.rgb),
                                   oracle_response(self.rgb, self.value), atol=3e-16, rtol=0)
        for clip in (False, True):
            np.testing.assert_allclose(self.model.predict_cpu(self.rgb, self.table, clip),
                oracle_predict(self.rgb, self.table, self.value, clip), atol=5e-15, rtol=0)

    def _tensor_matches_oracle(self, device):
        import torch
        from gpu_color import paired_tensor
        from gpu_tensor import TensorTools
        dtype = torch.float64 if device == 'cpu' else torch.float32
        tools = TensorTools(device, dtype)
        rgb = tools.tensor(self.rgb).requires_grad_(True)
        table = tools.tensor(self.table.astype(float)).requires_grad_(True)
        output = paired_tensor(tools, rgb, table, self.identity)
        tolerance = 2e-12 if device == 'cpu' else 3e-6
        np.testing.assert_allclose(output.detach().cpu().numpy(),
            oracle_predict(self.rgb, self.table, self.value), atol=tolerance, rtol=0)
        output.square().sum().backward()
        self.assertTrue(bool(torch.isfinite(rgb.grad).all()))
        self.assertTrue(bool(torch.isfinite(table.grad).all()))

    def test_torch_cpu_render_and_gradients(self):
        self._tensor_matches_oracle('cpu')

    def test_mps_render_and_gradients(self):
        import torch
        if not torch.backends.mps.is_available():
            self.skipTest('Apple MPS unavailable in this environment')
        self._tensor_matches_oracle('mps')

    def test_zero_grid_is_identity_and_gray_expert_residual_is_zero(self):
        zero = np.zeros((405, 3), np.int8)
        np.testing.assert_array_equal(self.model.predict_cpu(self.rgb, zero), self.rgb)
        gray = np.repeat(np.linspace(0, 1, 257)[:, None], 3, axis=1)
        value_without_experts = dict(self.value, expert_weights=np.zeros((3, 81, 3)).tolist())
        np.testing.assert_allclose(oracle_response(gray, self.value),
                                   oracle_response(gray, value_without_experts), atol=0, rtol=0)


if __name__ == '__main__':
    unittest.main()
