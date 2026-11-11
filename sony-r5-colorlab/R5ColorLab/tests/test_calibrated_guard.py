"""离线验收区分量化波动、单点严重跳变与连续区域退步。"""
import unittest
from types import SimpleNamespace
from unittest.mock import patch

import numpy as np

from calibrated_guard import FocusedRampLoss, RampBank, SceneProtection, metric_failures, ramp_report
from integer_grid import PROBE_AXES, TRANSITION_LIMITS, polish_grid
from native_scoring import adoption_failures


class CalibratedGuardTests(unittest.TestCase):
    def setUp(self):
        self.limits = dict(gray_rmse=.03, delta_e00_p95=.04,
            axes={axis: dict(p95=.05, peak=.75, local=.5) for axis in PROBE_AXES})

    def test_minor_tail_changes_can_pass_but_color_and_gray_are_still_protected(self):
        reference = dict(rgb_rmse=10., delta_e00_mean=4., delta_e00_p95=12., gray_rmse=3.,
            continuity_cost=2., color_score=200., **dict.fromkeys(TRANSITION_LIMITS, 1.))
        candidate = dict(reference, rgb_rmse=9.8, delta_e00_mean=3.9, gray_rmse=3.02,
            delta_e00_p95=12.03, saturation_over=2, saturation_max=1.1)
        self.assertTrue(adoption_failures(candidate, reference))
        self.assertFalse(metric_failures(candidate, reference, self.limits))
        for name, value in (('gray_rmse', 3.04), ('delta_e00_p95', 12.05),
                            ('rgb_rmse', 10.), ('native-saturation_max', 1.8),
                            ('saturation_p95', float('nan'))):
            with self.subTest(name=name):
                self.assertTrue(metric_failures(dict(candidate, **{name: value}), reference, self.limits))

    def test_independent_ramps_deny_severe_peak_and_connected_regression(self):
        base = {'native-saturation': np.zeros((4, 73))}
        for points, amplitude, reason in (((2,), .55, None), ((2,), .8, 'peak'),
                                          ((2, 3, 4), .55, 'cluster')):
            with self.subTest(points=points, amplitude=amplitude):
                newer = {key: value.copy() for key, value in base.items()}
                newer['native-saturation'][0, points] = amplitude
                _, errors = ramp_report(base, newer, self.limits)
                self.assertEqual(errors, [] if reason is None else [f'ramp:native-saturation:{reason}'])

    def test_calibration_screen_and_blind_ramps_have_distinct_inputs_in_both_domains(self):
        ramps = [RampBank(phase) for phase in (.17, .53, .87)]
        self.assertEqual(len({bank.sha256 for bank in ramps}), 3)
        for bank in ramps:
            self.assertEqual(tuple(bank.jumps(bank.rgb)), PROBE_AXES)
            self.assertEqual(len(bank.rgb), 2*bank.domain_size)

    def test_scene_protection_rejects_local_tail_despite_better_whole_photo(self):
        target = np.tile([.4, .35, .3], (100, 1))
        baseline = target + [.06, 0, 0]
        guard = SceneProtection(baseline, target,
                                {'whole': np.arange(100), 'skin': np.arange(20)})
        candidate = target.copy()
        candidate[:2] += [.12, 0, 0]
        self.assertFalse(guard.failures(guard.baseline))
        scores = guard.score(candidate)
        self.assertLess(scores['whole']['delta_e00_mean'], guard.baseline['whole']['delta_e00_mean'])
        self.assertLess(scores['skin']['delta_e00_mean'], guard.baseline['skin']['delta_e00_mean'])
        self.assertEqual(guard.failures(scores), ['skin:delta_e00_p95'])
        self.assertFalse(guard.failures(guard.score(baseline)))

    def test_targeted_training_penalizes_ramp_tail_and_backpropagates_to_its_rows(self):
        from gpu_tensor import TensorTools

        tools = TensorTools('cpu')
        axis = 'native-full-exposure'
        bank = RampBank(.19)
        base = bank.lines(bank.rgb, axis)[:4, :20].copy()
        guard = FocusedRampLoss(tools, [(axis, base.shape[:2])], base.reshape(-1, 3), self.limits)
        prefix = np.full((5, 3), .4)
        unchanged = tools.tensor(np.concatenate((prefix, base.reshape(-1, 3))))
        self.assertEqual(float(guard(unchanged)), 0.)
        changed = base.copy()
        changed[:, 2::3, 0] = np.clip(changed[:, 2::3, 0]+.12, 0, 1)
        candidate = tools.tensor(np.concatenate((prefix, changed.reshape(-1, 3)))).requires_grad_(True)
        loss = guard(candidate)
        loss.backward()
        self.assertGreater(float(loss.detach()), 0.)
        self.assertTrue(bool(tools.torch.isfinite(candidate.grad).all()))
        self.assertTrue(bool((candidate.grad[len(prefix):] != 0).any()))
        self.assertFalse(bool((candidate.grad[:len(prefix)] != 0).any()))

    def test_integer_polish_does_not_keep_a_move_rejected_by_ramp_screen(self):
        source = np.tile([.4, .3, .2], (12, 1))
        target = source + [.02, 0, 0]
        gray = np.arange(len(source)) == 0
        probe = np.array([[.2, .4, .6]])
        extra = np.array([[.6, .4, .2], [.65, .4, .2]])
        model = SimpleNamespace(
            stencil=lambda rgb: (None, np.zeros((len(rgb), 1), int), np.ones((len(rgb), 1))),
            response=lambda rgb: np.broadcast_to(np.eye(3)/256, (len(rgb), 3, 3)),
            predict_cpu=lambda rgb, table, clip=False: rgb+table[0]/256,
        )
        transitions = dict(continuity_cost=0., **dict.fromkeys(TRANSITION_LIMITS, 0.))
        limits = dict(gray_rmse=100., **transitions)
        initial = np.zeros((405, 3), np.int8)
        seen = []

        def reject_red_change(pixels):
            seen.append(pixels.copy())
            return not np.any(pixels[:, 0] > extra[:, 0])

        with patch('measured_response.get', return_value=model), patch('integer_grid.transition_metrics', return_value=transitions):
            args = (initial, source, target, gray, probe, {}, None, 30, limits)
            accepted, moves = polish_grid(*args)
            blocked, blocked_moves = polish_grid(*args, ramp_screen=(extra, reject_red_change))
        self.assertGreater(moves, 0)
        self.assertGreater(accepted[0, 0], 0)
        self.assertTrue(seen)
        self.assertEqual(seen[0].shape, extra.shape)
        self.assertEqual(blocked_moves, 0)
        np.testing.assert_array_equal(blocked, initial)


if __name__ == '__main__':
    unittest.main()
