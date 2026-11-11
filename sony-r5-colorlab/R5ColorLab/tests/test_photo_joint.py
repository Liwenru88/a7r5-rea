"""验证照片验收分场景执行，并保护被否决的整数改动。"""
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import numpy as np

from benchmark_photo_joint import photo_failures
from integer_grid import TRANSITION_LIMITS, polish_grid


class PhotoJointTests(unittest.TestCase):
    def test_one_scene_cannot_be_hidden_by_the_other_scenes(self):
        baseline = dict(rgb_rmse=8., delta_e00_mean=4., delta_e00_p95=10.)
        good = dict(rgb_rmse=7., delta_e00_mean=3., delta_e00_p95=9.)
        photos = [dict(scene=str(i), baseline=baseline, candidate=good) for i in range(3)]
        self.assertFalse(photo_failures(photos, .05))
        for key, value in (('rgb_rmse', 8.), ('delta_e00_mean', 4.001), ('delta_e00_p95', 10.051)):
            with self.subTest(key=key):
                last = dict(photos[2], candidate=dict(good, **{key:value}))
                self.assertEqual(photo_failures([*photos[:2], last], .05), [f'2:{key}'])
        self.assertEqual(photo_failures(photos[:2], .05), ['photo-set-incomplete'])
        one_unchanged = [*photos[:2], dict(photos[2], candidate=baseline)]
        self.assertFalse(photo_failures(one_unchanged, .05, strict=False))
        self.assertEqual(photo_failures(one_unchanged, .05), ['2:rgb_rmse', '2:delta_e00_mean'])
        all_unchanged = [dict(photo, candidate=baseline) for photo in photos]
        self.assertEqual(photo_failures(all_unchanged, .05, strict=False),
                         ['calibration-no-improvement:rgb_rmse', 'calibration-no-improvement:delta_e00_mean'])

    def test_integer_move_with_photo_regression_is_rolled_back(self):
        source = np.tile([.4, .3, .2], (12, 1))
        target = source + [.02, 0, 0]
        gray = np.arange(len(source)) == 0
        probe = np.array([[.2, .4, .6]])
        model = SimpleNamespace(
            stencil=lambda rgb: (None, np.zeros((len(rgb), 1), int), np.ones((len(rgb), 1))),
            response=lambda rgb: np.broadcast_to(np.eye(3)/256, (len(rgb), 3, 3)),
            predict_cpu=lambda rgb, table, clip=False: rgb+table[0]/256,
        )
        transitions = dict(continuity_cost=0., **dict.fromkeys(TRANSITION_LIMITS, 0.))
        initial = np.zeros((405, 3), np.int8)
        args = (initial, source, target, gray, probe, {}, None, 30, dict(gray_rmse=100., **transitions))
        first = (source, source+[.1, 0, 0])
        second = (source, source-[.02, 0, 0])
        with patch('measured_response.get', return_value=model), patch('integer_grid.transition_metrics', return_value=transitions):
            _, allowed = polish_grid(*args, color_guards=(first,))
            blocked, moves = polish_grid(*args, color_guards=(first, second), color_guard_priority=True)
        self.assertGreater(allowed, 0)
        self.assertEqual(moves, 0)
        np.testing.assert_array_equal(blocked, initial)


if __name__ == '__main__':
    unittest.main()
