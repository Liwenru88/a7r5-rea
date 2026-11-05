"""Group importance remains consistent across cohorts and candidate selection."""
import unittest
import numpy as np
import core
from training_policy import group_importance, composite_score
from fit_anchor_native import training_plan


class TrainingPolicyTests(unittest.TestCase):
    def test_color_focus_follows_errors_and_preserves_anchor_mass(self):
        from adaptive_color import focus_weights

        targets = np.repeat([[.85, .15, .15], [.2, .22, .85], [.35, .35, .35]], 200, axis=0)
        weights = np.linspace(1., 2., len(targets))
        eligible = np.ones(len(targets), dtype=bool)
        eligible[0] = False
        for red_error, blue_error in ((100., 1.), (1., 100.)):
            with self.subTest(red_error=red_error):
                costs = np.repeat([red_error, blue_error, 300.], 200)
                result, _ = focus_weights(targets, costs, weights, eligible)
                np.testing.assert_array_equal(result[~eligible], weights[~eligible])
                np.testing.assert_array_equal(result[400:], weights[400:])
                self.assertAlmostEqual(result.sum(), weights.sum())
                higher, lower = (200, 1) if blue_error > red_error else (1, 200)
                self.assertGreater(result[higher]/weights[higher], result[lower]/weights[lower])

    def test_group_weights_are_total_mass_not_per_patch(self):
        ids=np.r_[np.full(20,-1),np.arange(284)]
        importance=dict(random=1,primaries=2,gray=3,colorchecker24=4)
        train,_,random,w=training_plan(np.full(len(ids),'train'),ids,importance)
        n=len(random)
        masses=[w[:n].sum(),w[n:n+4].sum(),w[n+4:n+260].sum(),w[n+260:].sum()]
        np.testing.assert_allclose(np.array(masses)/masses[0],[1,2,3,4])
        self.assertAlmostEqual(composite_score([1,2,3,4],importance),np.sqrt((1+8+27+64)/10))

    def test_rejects_missing_nonfinite_and_boolean_weights(self):
        self.assertEqual(group_importance(),dict(random=1,primaries=1,gray=1,colorchecker24=1))
        for bad in [dict(gray=1),[],dict.fromkeys(('random','primaries','gray','colorchecker24'),True),
                    dict.fromkeys(('random','primaries','gray','colorchecker24'),float('nan')),
                    dict.fromkeys(('random','primaries','gray','colorchecker24'),0)]:
            with self.assertRaises(ValueError):group_importance(bad)


if __name__=='__main__':unittest.main()
