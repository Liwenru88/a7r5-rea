"""Applied-response grid regularization: independent path values and gradients."""
from collections import Counter
import copy
import hashlib
from itertools import product
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent/'scripts'))

from grid_regularization import (GridPenalty, get_penalty, fixed_paths, _geometry,
                                  FIRST_RATE, SECOND_RATE, FAMILIES, POLICY)
from measured_response import default_response, nonlinear_response, get
from test_three_expert_response import oracle_predict


def independent_path_loss(paths, grid, value):
    """Direct field evaluation and loop quadrature, without sparse/Gram math."""
    counts = Counter(path['family'] for path in paths)
    pieces = dict(first=0., second=0.)
    for path in paths:
        rgb = path['rgb']
        correction = oracle_predict(rgb, grid, value, clip=False)-rgb
        distance = np.sqrt(np.sum(np.diff(rgb, axis=0)**2, axis=1))
        velocity = np.diff(correction, axis=0)/distance[:, None]
        curvature = np.diff(velocity, axis=0)/((distance[:-1]+distance[1:])/2)[:, None]
        width = (distance[:-1]+distance[1:])/2
        family_mass = 1/(len(FAMILIES)*counts[path['family']])
        pieces['first'] += FIRST_RATE*family_mass*np.sum(np.mean(velocity**2, axis=1)*distance/distance.sum())
        pieces['second'] += SECOND_RATE*family_mass*np.sum(np.mean(curvature**2, axis=1)*width/width.sum())
    return pieces


class GridRegularizationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.identity = default_response()
        cls.penalty = get_penalty(cls.identity)
        cls.model = get(cls.identity)
        cls.rng = np.random.default_rng(631)
        cls.grid = cls.rng.integers(-32, 33, (405, 3)).astype(float)

    def test_fixed_input_geometry_equal_family_mass_and_no_hsv_corner_curvature(self):
        paths = fixed_paths()
        rgb, first, second = _geometry(paths)
        np.testing.assert_array_equal(rgb, self.penalty.rgb)
        self.assertEqual(hashlib.sha256(rgb.tobytes()).hexdigest(), self.penalty.metadata['input_sha256'])
        counts = Counter(path['family'] for path in paths)
        self.assertEqual(set(counts), set(FAMILIES))
        # Every segment is a line in RGB. The independent second difference
        # of the input identity must vanish, even on HSV hexagon vertices.
        np.testing.assert_allclose(second@rgb, 0., atol=2e-13, rtol=0)
        self.assertAlmostEqual(float(np.sum((first@rgb)**2)), FIRST_RATE/3, places=14)
        for family in FAMILIES:
            subset = [path for path in paths if path['family'] == family]
            # _geometry uses four-family mass even when just one family is
            # evaluated, so each family contributes exactly 1/4 of the gain.
            points, d1, d2 = _geometry(subset)
            self.assertAlmostEqual(float(np.sum((d1@points)**2)), FIRST_RATE/(3*4), places=14)
            np.testing.assert_allclose(d2@points, 0., atol=2e-13, rtol=0)

    def test_sparse_correction_operator_matches_independent_render(self):
        observed = (self.penalty.correction_matrix@self.grid.ravel()).reshape(-1, 3)
        expected = oracle_predict(self.penalty.rgb, self.grid, self.model.value, clip=False)-self.penalty.rgb
        np.testing.assert_allclose(observed, expected, atol=2e-15, rtol=0)

    def test_sparse_derivatives_and_gram_match_independent_path_values(self):
        pieces = independent_path_loss(self.penalty.paths, self.grid, self.model.value)
        first = self.penalty.first_rows@self.grid.ravel()
        second = self.penalty.second_rows@self.grid.ravel()
        self.assertAlmostEqual(float(first@first), pieces['first'], delta=1e-13)
        self.assertAlmostEqual(float(second@second), pieces['second'], delta=1e-13)
        expected = sum(pieces.values())
        self.assertAlmostEqual(self.penalty.raw_loss(self.grid), expected, delta=1e-13)
        flat = self.grid.ravel()
        self.assertAlmostEqual(float(flat@(self.penalty.gram@flat)), expected, delta=1e-13)
        np.testing.assert_allclose(self.penalty.dense_gram, self.penalty.gram.toarray(), atol=0, rtol=0)
        np.testing.assert_allclose(self.penalty.dense_gram, self.penalty.dense_gram.T, atol=1e-18, rtol=0)

    def test_zero_exact_strength_scaling_and_validation(self):
        zero = np.zeros((405, 3))
        self.assertEqual(self.penalty.raw_loss(zero), 0.)
        self.assertEqual(self.penalty.cost(zero, 30), 0.)
        self.assertEqual(self.penalty.cost(self.grid, 0), 0.)
        for strength in (1, 30, 100):
            expected = self.penalty.raw_loss(self.grid)*.01*(1+strength/5)*255**2
            self.assertAlmostEqual(self.penalty.cost(self.grid, strength), expected, places=12)
        for invalid in (True, -1, 101, float('nan')):
            with self.assertRaises(ValueError): self.penalty.cost(self.grid, invalid)
        for invalid in (np.ones((404, 3)), np.full((405, 3), np.nan)):
            with self.assertRaises(ValueError): self.penalty.raw_loss(invalid)

    def test_actual_response_not_bare_neighbor_penalty(self):
        # A constant table has no bare coefficient-neighbor differences, but
        # the three-expert response varies with color and must be measured.
        constant = np.ones((405, 3))*16
        self.assertGreater(self.penalty.raw_loss(constant), 1e-9)
        value = copy.deepcopy(self.model.value)
        value['response_basis'] = 'constant-test'
        value['smooth'] = False
        value['response_weights'] = np.eye(3).tolist()
        from paired_response import PairedModel
        model = PairedModel(value, 'constant-test')
        with patch('measured_response.get', return_value=model):
            fixed = GridPenalty(dict(test='constant-response'))
        self.assertLess(fixed.raw_loss(constant), 1e-25)

    def test_quadratic_joint_delta_and_same_parity_coupling(self):
        q = self.penalty.gram
        flat = self.grid.ravel()
        direction = self.rng.normal(size=1215)
        expected = 2*direction@(q@flat)+direction@(q@direction)
        actual = self.penalty.raw_loss(flat+direction)-self.penalty.raw_loss(flat)
        self.assertAlmostEqual(actual, expected, delta=1e-13)
        nodes = np.arange(405)
        group = (nodes//81 % 2)*4+(nodes//9 % 9 % 2)*2+nodes % 9 % 2
        coo = q.tocoo()
        same_parity = ((coo.row//3 != coo.col//3) &
                       (group[coo.row//3] == group[coo.col//3]) & (abs(coo.data)>1e-13))
        self.assertTrue(same_parity.any(), 'Full path penalty couples nodes even within old parity groups')
        chosen = np.flatnonzero(same_parity)[0]
        i, j = coo.row[chosen], coo.col[chosen]
        d1, d2 = np.zeros(1215), np.zeros(1215); d1[i] = 1; d2[j] = 1
        joint = self.penalty.raw_loss(flat+d1+d2)-self.penalty.raw_loss(flat)
        separate = (self.penalty.raw_loss(flat+d1)+self.penalty.raw_loss(flat+d2)
                    -2*self.penalty.raw_loss(flat))
        self.assertAlmostEqual(joint-separate, 2*float(q[i, j]), delta=1e-13)
        self.assertGreater(abs(joint-separate), 1e-13)

    def test_cache_fixed_identity_and_spectral_upper_bound(self):
        self.assertIs(get_penalty(dict(reversed(list(self.identity.items())))), self.penalty)
        self.assertEqual(self.penalty.metadata['policy'], POLICY)
        self.assertEqual(self.penalty.metadata['identity'], self.identity)
        self.assertTrue(self.penalty.metadata['target_independent'])
        self.assertEqual(self.penalty.rows.shape[1], 1215)
        for _ in range(5):
            v = self.rng.normal(size=1215)
            rayleigh = float(v@(self.penalty.gram@v)/(v@v))
            self.assertGreaterEqual(rayleigh, -1e-16)
            self.assertLessEqual(rayleigh, self.penalty.max_row_sum_upper+1e-16)
        old = get_penalty(nonlinear_response())
        self.assertNotEqual(old.identity, self.penalty.identity)
        self.assertEqual(old.metadata['input_sha256'], self.penalty.metadata['input_sha256'])
        with self.assertRaises(ValueError): get_penalty(None)
        with self.assertRaises(ValueError): get_penalty(dict(self.identity, sha256='0'*64))

    def _tensor_cost_and_gradient(self, device):
        import torch
        from gpu_tensor import TensorTools
        tools = TensorTools(device, torch.float64 if device == 'cpu' else torch.float32)
        grid = tools.tensor(self.grid).requires_grad_(True)
        loss = self.penalty.tensor_loss(tools, grid, 30)
        loss.backward()
        expected = self.penalty.cost(self.grid, 30)/255**2
        tolerance = 1e-14 if device == 'cpu' else max(1e-9, expected*1e-4)
        self.assertAlmostEqual(float(loss.detach().cpu()), expected, delta=tolerance)
        gradient = 2*self.penalty.gram@self.grid.ravel()*.07
        np.testing.assert_allclose(grid.grad.detach().cpu().numpy().ravel(), gradient,
            atol=1e-15 if device == 'cpu' else 1e-9, rtol=1e-10 if device == 'cpu' else 1e-4)
        direction = np.random.default_rng(72).normal(size=(405, 3))
        direction /= np.linalg.norm(direction)
        epsilon = 1e-4
        high = self.penalty.cost(self.grid+epsilon*direction, 30)/255**2
        low = self.penalty.cost(self.grid-epsilon*direction, 30)/255**2
        actual = float((grid.grad*tools.tensor(direction)).sum().cpu())
        self.assertAlmostEqual(actual, (high-low)/(2*epsilon), delta=1e-12 if device == 'cpu' else 1e-9)
        zero = tools.tensor(np.zeros((405, 3))).requires_grad_(True)
        self.penalty.tensor_loss(tools, zero, 30).backward()
        np.testing.assert_array_equal(zero.grad.detach().cpu().numpy(), np.zeros((405, 3)))
        disabled = tools.tensor(self.grid).requires_grad_(True)
        self.assertEqual(float(self.penalty.tensor_loss(tools, disabled, 0).detach().cpu()), 0.)
        self.penalty.tensor_loss(tools, disabled, 0).backward()
        np.testing.assert_array_equal(disabled.grad.detach().cpu().numpy(), np.zeros((405, 3)))

    def test_torch_cpu_cost_and_gradient(self):
        self._tensor_cost_and_gradient('cpu')

    def test_mps_cost_and_gradient(self):
        import torch
        if not torch.backends.mps.is_available(): self.skipTest('Apple MPS unavailable in this environment')
        self._tensor_cost_and_gradient('mps')


if __name__ == '__main__':
    unittest.main()
