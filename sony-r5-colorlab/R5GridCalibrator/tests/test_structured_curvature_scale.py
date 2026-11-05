import sys
import unittest
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import structured_response as s


class StructuredCurvatureScaleTests(unittest.TestCase):
    def test_only_two_curvature_rates_change_without_mutating_constants(self):
        before = (s.PENALTY_RATES.copy(), s.PENALTY_RATES_C1.copy())
        for kind, original in zip((s.KIND, s.KIND_C1), before):
            self.assertEqual(s.penalty_rates(kind), original)
            for scale in (0, .5, .75, 1., np.float32(.75)):
                rates = s.penalty_rates(kind, scale)
                self.assertEqual(set(rates), set(original))
                for key in original:
                    expected = original[key]*float(scale) if key in ('curvature','path_curvature') else original[key]
                    self.assertEqual(rates[key], expected)
            rates = s.penalty_rates(kind, .5)
            rates['detail'] = -1
            self.assertEqual(s.penalty_rates(kind)['detail'], original['detail'])
        self.assertEqual((s.PENALTY_RATES, s.PENALTY_RATES_C1), before)

    def test_invalid_values_are_rejected_in_helper_and_solver(self):
        x = np.full((3,3), .5)
        for value in (True, False, np.bool_(True), -.1, 1.1, np.nan, np.inf,
                      -np.inf, '0.5', None, [0.5], np.array(.5), complex(.5)):
            with self.subTest(value=repr(value)):
                with self.assertRaises(ValueError):
                    s.penalty_rates(s.KIND_C1, value)
                with self.assertRaises(ValueError):
                    s.solve(x,x,np.zeros_like(x),np.ones(len(x)),np.zeros((81,3)),
                            device='cpu',iterations=1,curvature_scale=value)
        with self.assertRaises(ValueError):
            s.penalty_rates('unsupported', .5)

    def test_default_solver_compatibility_and_numpy_torch_weighted_preflight(self):
        try: import torch
        except ImportError: self.skipTest('torch unavailable')
        rng = np.random.default_rng(394)
        x = rng.uniform(.15,.85,(24,3))
        d = rng.uniform(-.03,.03,x.shape)
        initial = rng.normal(0,.01,(81,3))
        y = x+s.predict_correction(x,d,initial,s.KIND_C1)*.9
        paths = {name:rng.normal(0,.03,(7,81)) for name in ('first','second')}
        args = dict(x=x,y=y,d=d,weights=np.ones(len(x)),initial=initial,
                    regularization=.25,device='cpu',iterations=2,scale=0,mix=0,
                    path_constraints=paths,kind=s.KIND_C1)
        default, default_note = s.solve(**args)
        explicit, explicit_note = s.solve(**args,curvature_scale=1.)
        np.testing.assert_array_equal(default, explicit)
        self.assertEqual(default_note, explicit_note)
        for scale in (.5,.75):
            coef,note = s.solve(**args,curvature_scale=scale)
            self.assertEqual(note['curvature_scale'],scale)
            self.assertEqual(note['penalty_rates'],s.penalty_rates(s.KIND_C1,scale))
            self.assertLess(note['preflight_regularizer_relative_error'],1e-12)
            self.assertLess(note['preflight_regularization_loss_error'],1e-12)
            terms=s.regularization_terms(coef,initial,np.asarray(note['detail_support_factor']),paths,s.KIND_C1)
            expected=.25*sum(note['penalty_rates'][key]*value for key,value in terms.items())
            self.assertAlmostEqual(note['final_regularization_loss'],expected,places=14)


if __name__ == '__main__':
    unittest.main()
