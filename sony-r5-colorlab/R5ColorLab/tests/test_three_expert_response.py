"""Production three-expert response against an independent mathematical oracle.

The oracle deliberately imports no grid-calibrator or production basis,
coordinate, stencil, gate or rendering helper. GPU checks use small synthetic
targets; they validate routing and gradients, not camera color accuracy.
"""
import copy
import hashlib
from itertools import product
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'scripts'))

import measured_response as measured
from paired_response import PairedModel


def oracle_coordinates(rgb, value):
    x = np.asarray(rgb, float)
    a = np.asarray(value['coordinate_affine'], float)
    out = np.column_stack([sum(x[:, j] * a[i, j] for j in range(3)) + a[i, 3]
                           for i in range(3)])
    if value.get('coordinate_warp') is not None:
        c = np.asarray(value['coordinate_warp']['control'], float)
        for i, j, k in product(range(3), repeat=3):
            b = []
            for channel, degree in enumerate((i, j, k)):
                z = x[:, channel]
                b.append(((1-z)**2, 2*z*(1-z), z*z)[degree])
            out += (b[0]*b[1]*b[2])[:, None] * c[i, j, k]
    return out


def oracle_basis(rgb):
    x = np.asarray(rgb, float)
    corner_indices = list(product((0, 2), repeat=3))
    columns = []
    for node in corner_indices:
        columns.append(np.prod([x[:, c] if node[c] == 2 else 1-x[:, c]
                                for c in range(3)], axis=0))
    for node in product(range(3), repeat=3):
        if node in corner_indices:
            continue
        v = np.ones(len(x))
        for channel, center in enumerate(node):
            h = np.maximum(1-np.abs(2*x[:, channel]-center), 0)
            v *= 3*h*h-2*h*h*h
        columns.append(v)
    return np.column_stack(columns)


def oracle_response(rgb, value):
    x = np.asarray(rgb, float)
    basis = oracle_basis(x)
    shared = np.asarray(value['response_weights'], float).reshape(3, 27, 3)
    extra = np.asarray(value['expert_weights'], float).reshape(3, 3, 27, 3)
    # Calculate each component/output independently, avoiding the production
    # response-field einsum and all exported helper functions.
    result = np.empty((len(x), 3, 3))
    gate = value.get('expert_gate', dict(kappa=2., s0=.25, c0=.04))
    u, v = x[:, 0]-(x[:, 1]+x[:, 2])/2, np.sqrt(3)*(x[:, 1]-x[:, 2])/2
    q = u*u+v*v
    logits = gate['kappa']/gate['s0'] * np.column_stack(
        [u, -.5*u+np.sqrt(3)/2*v, -.5*u-np.sqrt(3)/2*v])
    p = np.exp(logits-logits.max(axis=1, keepdims=True))
    p /= p.sum(axis=1, keepdims=True)
    p *= (q/(q+gate['c0']**2))[:, None]
    for component, output in product(range(3), repeat=2):
        result[:, component, output] = basis @ shared[component, :, output]
        for expert in range(3):
            result[:, component, output] += p[:, expert] * (basis @ extra[expert, component, :, output])
    return result / 256


def oracle_predict(rgb, table, value, clip=True):
    x = np.asarray(rgb, float)
    position = np.clip(oracle_coordinates(x, value)*[4, 8, 8]+[0, 4, 4],
                       0, [4, 8, 8])
    low = np.minimum(np.floor(position).astype(int), [3, 7, 7])
    fraction = position-low
    delta = np.zeros_like(x)
    table = np.asarray(table).reshape(5, 9, 9, 3)
    for y, u, v in product((0, 1), repeat=3):
        w = ((fraction[:, 0] if y else 1-fraction[:, 0]) *
             (fraction[:, 1] if u else 1-fraction[:, 1]) *
             (fraction[:, 2] if v else 1-fraction[:, 2]))
        delta += w[:, None] * table[low[:, 0]+y, low[:, 1]+u, low[:, 2]+v]
    matrix = oracle_response(x, value)
    out = x + sum(delta[:, c, None]*matrix[:, c, :] for c in range(3))
    return np.clip(out, 0, 1) if clip else out


class ThreeExpertResponseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.identity = measured.default_response()
        cls.model = measured.get(cls.identity)
        cls.value = cls.model.value
        cls.rng = np.random.default_rng(2026110203)
        gray = np.repeat(np.linspace(0, 1, 257)[:, None], 3, axis=1)
        knots = np.asarray(list(product((0., .5, 1.), repeat=3)))
        cls.rgb = np.r_[cls.rng.random((1024, 3)), gray, knots, np.eye(3), 1-np.eye(3)]
        cls.grid = cls.rng.integers(-64, 64, (405, 3))

    def test_pinned_default_and_old_nonlinear_identity_are_separate(self):
        self.assertEqual(self.identity['preset'], 'r5-paired-20261102-three-experts')
        self.assertEqual(self.value['response_basis'], 'rgb-hue-experts-c1/1')
        raw = (Path(measured.__file__).resolve().parent / 'data/r5/paired-20261102-three-experts.json').read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), self.identity['sha256'])
        old = measured.nonlinear_response()
        self.assertEqual(old['preset'], 'r5-paired-20261102-nonlinear')
        self.assertEqual(old['sha256'], 'a312761c8500e8a9ecb3b1b23ad27cf7709cb6eb8bf41c956970e1bdcc2c82f0')
        self.assertEqual(measured.get(old).value['response_basis'], 'rgb-quadratic')
        self.assertNotEqual(old, self.identity)
        for identity in (self.identity, old):
            bad = dict(identity, sha256='0'*64)
            with self.assertRaises(ValueError): measured.get(bad)

    def test_cpu_independent_oracle_random_gray_knots_and_signed_tables(self):
        np.testing.assert_allclose(self.model.coordinates(self.rgb), oracle_coordinates(self.rgb, self.value), atol=3e-15, rtol=0)
        np.testing.assert_allclose(self.model.response(self.rgb), oracle_response(self.rgb, self.value), atol=2e-16, rtol=0)
        tables = [self.grid, -np.ones((405, 3))*64, np.ones((405, 3))*63]
        tables += [self.rng.integers(-64, 64, (405, 3)) for _ in range(3)]
        for table in tables:
            for clipped in (False, True):
                np.testing.assert_allclose(self.model.predict_cpu(self.rgb, table, clip=clipped),
                    oracle_predict(self.rgb, table, self.value, clipped), atol=3e-15, rtol=0)
        np.testing.assert_array_equal(self.model.predict_cpu(self.rgb, np.zeros((405, 3))), self.rgb)

    def test_each_lookup_component_and_cross_channel_output_order(self):
        for component in range(3):
            table = np.zeros((405, 3)); table[:, component] = np.arange(405) % 128-64
            np.testing.assert_allclose(self.model.predict_cpu(self.rgb, table, clip=False),
                oracle_predict(self.rgb, table, self.value, False), atol=3e-15, rtol=0)

    def test_exact_gray_uses_shared_response_and_grid_remains_linear(self):
        gray = np.repeat(np.linspace(0, 1, 257)[:, None], 3, axis=1)
        shared = copy.deepcopy(self.value); shared['expert_weights'] = np.zeros((3, 81, 3)).tolist()
        np.testing.assert_array_equal(self.model.response(gray), PairedModel(shared, 'shared-test').response(gray))
        np.testing.assert_allclose(self.model.response(gray), oracle_response(gray, shared), atol=2e-17, rtol=0)
        other = self.rng.integers(-64, 64, (405, 3))
        first = self.model.predict_cpu(self.rgb, self.grid, False)-self.rgb
        second = self.model.predict_cpu(self.rgb, other, False)-self.rgb
        combined = self.model.predict_cpu(self.rgb, self.grid+other, False)-self.rgb
        np.testing.assert_allclose(combined, first+second, atol=6e-16, rtol=0)

    def test_synthetic_parameters_cover_nondefault_gate_and_all_coefficients(self):
        value = copy.deepcopy(self.value)
        value['response_weights'] = self.rng.normal(0, .1, (81, 3)).tolist()
        value['expert_weights'] = self.rng.normal(0, .2, (3, 81, 3)).tolist()
        value['expert_gate'] = dict(kappa=1.3, s0=.19, c0=.07)
        model = PairedModel(value, 'synthetic-test')
        np.testing.assert_allclose(model.predict_cpu(self.rgb, self.grid, False),
            oracle_predict(self.rgb, self.grid, value, False), atol=3e-15, rtol=0)

    def test_malformed_expert_coefficients_and_gate_are_rejected(self):
        changes = [dict(expert_weights=np.zeros((24, 3, 3, 3)).tolist()),
                   dict(expert_weights=np.full((3, 81, 3), np.nan).tolist()),
                   dict(response_weights=np.zeros((30, 3)).tolist())]
        changes += [dict(expert_gate=gate) for gate in
                    ({'kappa': True, 's0': .25, 'c0': .04},
                     {'kappa': 2, 's0': 0, 'c0': .04},
                     {'kappa': 2, 's0': .25, 'c0': float('inf')},
                     {'kappa': 2, 's0': .25, 'c0': .04, 'extra': 1})]
        for change in changes:
            with self.subTest(change=list(change)):
                value = copy.deepcopy(self.value); value.update(change)
                with self.assertRaises(ValueError): PairedModel(value, 'invalid')

    def _tensor_parity_and_gradients(self, device):
        import torch
        from gpu_tensor import TensorTools
        from gpu_color import paired_tensor
        torch.set_num_threads(8)
        tools = TensorTools(device, torch.float64 if device == 'cpu' else torch.float32)
        tolerance = 3e-15 if device == 'cpu' else 3e-6
        x = tools.tensor(self.rgb); grid = tools.tensor(self.grid)
        np.testing.assert_allclose(self.model.response_tensor(tools, x).detach().cpu().numpy(),
            oracle_response(self.rgb, self.value), atol=tolerance, rtol=0)
        y = paired_tensor(tools, x, grid, self.identity)
        np.testing.assert_allclose(y.detach().cpu().numpy(),
            oracle_predict(self.rgb, self.grid, self.value), atol=tolerance, rtol=0)
        zero = paired_tensor(tools, x, tools.tensor(np.zeros((405, 3))), self.identity)
        np.testing.assert_array_equal(zero.detach().cpu().numpy(), x.detach().cpu().numpy())

        # Small signed offsets and interior colors keep finite differences away
        # from final clipping; randomized points avoid native-cell boundaries.
        rng = np.random.default_rng(519)
        samples = rng.uniform(.18, .82, (96, 3))
        table = rng.integers(-8, 9, (405, 3)).astype(float)
        cotangent = rng.normal(size=samples.shape)
        tx = tools.tensor(samples).requires_grad_(True)
        tg = tools.tensor(table).requires_grad_(True)
        output = paired_tensor(tools, tx, tg, self.identity)
        loss = (output*tools.tensor(cotangent)).sum()/len(samples)
        loss.backward()
        self.assertTrue(bool(torch.isfinite(tx.grad).all()))
        self.assertTrue(bool(torch.isfinite(tg.grad).all()))
        directions = [(rng.normal(size=samples.shape), 'input'), (rng.normal(size=table.shape), 'grid')]
        for direction, kind in directions:
            direction /= np.linalg.norm(direction)
            epsilon = 1e-5
            if kind == 'input':
                high = oracle_predict(samples+epsilon*direction, table, self.value)
                low = oracle_predict(samples-epsilon*direction, table, self.value)
                actual = float((tx.grad*tools.tensor(direction)).sum().cpu())
            else:
                high = oracle_predict(samples, table+epsilon*direction, self.value)
                low = oracle_predict(samples, table-epsilon*direction, self.value)
                actual = float((tg.grad*tools.tensor(direction)).sum().cpu())
            expected = float(((high-low)*cotangent).sum()/(2*epsilon*len(samples)))
            self.assertAlmostEqual(actual, expected, delta=2e-9 if device == 'cpu' else 3e-6)

        gray = tools.tensor(np.repeat(np.linspace(.05, .95, 17)[:, None], 3, 1)).requires_grad_(True)
        self.model.response_tensor(tools, gray).square().sum().backward()
        self.assertTrue(bool(torch.isfinite(gray.grad).all()))

    def test_torch_cpu_parity_input_gradient_and_grid_gradient(self):
        self._tensor_parity_and_gradients('cpu')

    def test_mps_parity_input_gradient_and_grid_gradient(self):
        import torch
        if not torch.backends.mps.is_available(): self.skipTest('Apple MPS unavailable in this environment')
        self._tensor_parity_and_gradients('mps')

    def test_gpu_dispatch_preserves_exact_snapshot_identity(self):
        for identity in (self.identity, measured.nonlinear_response(), measured.v2_response(), measured.previous_r5_response()):
            with patch('gpu_runtime.available', return_value=True), patch('gpu_color.paired_numpy', return_value=self.rgb) as render:
                measured.get(identity).predict(self.rgb, self.grid)
                self.assertEqual(render.call_args.args[2], identity)

    def test_mps_grid_solver_integer_refinement_and_output_continuity_smoke(self):
        import torch
        if not torch.backends.mps.is_available(): self.skipTest('Apple MPS unavailable in this environment')
        from gpu_grid import fit
        from gpu_grid_refine import refine
        from continuity_grid import constrain
        from output_continuity import ProbeBank
        rng = np.random.default_rng(730)
        x = rng.uniform(.12, .88, (256, 3))
        target_table = rng.integers(-6, 7, (405, 3))
        target = oracle_predict(x, target_table, self.value)
        mass = np.ones(len(x))
        grid, solve = fit(x, target, mass, .001, response=self.identity, iterations=50)
        self.assertEqual(grid.dtype, np.int8)
        self.assertLessEqual(solve['after'], solve['before'])
        self.assertLess(np.mean((oracle_predict(x, grid, self.value)-target)**2), np.mean((x-target)**2))
        final, integer = refine(grid, x, target, np.ones(len(x)), mass, 1, .35,
                                self.identity, None, 30)
        self.assertEqual(final.dtype, np.int8)
        self.assertLessEqual(integer['after'], integer['before'])
        bank = ProbeBank()
        result, output = constrain(final, x, target, mass, self.identity, 30,
                                   (bank, bank.rgb, 30), evaluations=2, device='mps')
        self.assertEqual(result.dtype, np.int8)
        self.assertTrue(np.all((result >= -64) & (result <= 63)))
        self.assertLessEqual(output['after'], output['before'])
        self.assertTrue(output['integer_output_acceptance'])
        self.assertTrue(output['native_parameters_frozen'])


if __name__ == '__main__':
    unittest.main()
