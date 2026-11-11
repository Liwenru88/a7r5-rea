import unittest
import core
import numpy as np
import pc_stages
from grid_distillation import compress, fit_target
from residual_grid import evaluate, pack, unpack


class TotalGridTests(unittest.TestCase):
    def test_direct_target_uses_real_targets_only_and_exports_integer_grid(self):
        from unittest.mock import patch
        base=np.array([[.15,.25,.35],[.45,.55,.65]])
        table=np.tile([2,-1,1],(405,1)).astype(np.int8)
        target=evaluate(base,table,np.eye(3))
        calls=[]
        def solve(x,y,mass,response,strength):
            calls.append((x.copy(),y.copy(),mass.copy()))
            return table.copy(),dict(converged=True)
        with patch('pc_stages.fit_response_grid',side_effect=solve), patch('optimizer_policy.refine_grid',side_effect=lambda grid,*a,**kw:(grid,{})):
            grid,audit=fit_target(base,target,np.array([1.,3.]),np.eye(3))
        self.assertEqual(len(calls),3)
        for x,y,mass in calls:
            np.testing.assert_array_equal(x,base)
            np.testing.assert_array_equal(y,target)
            np.testing.assert_array_equal(mass,[.25,.75])
        np.testing.assert_array_equal(unpack(pack(grid)),table)
        self.assertEqual(audit['synthetic_probes'],0)
        self.assertEqual(audit['objective'],'fuji-target')
        self.assertEqual(audit['train_probe_mass'],[1,0])
        with self.assertRaises(ValueError):fit_target(base,target[:1],np.ones(2),np.eye(3))

    def test_nonidentity_total_tone_and_tint_are_baked_into_single_payload(self):
        rng=np.random.default_rng(621)
        gray=np.repeat(np.linspace(0,1,256)[:,None],3,axis=1)
        target=np.clip(gray+.025+np.array([.008,-.003,.006]),0,1)
        curve=pc_stages.fit_curves(gray,target)
        color_grid=np.tile([2,-1,1],(405,1)).astype(np.int8)
        teacher=lambda rgb:pc_stages.render(rgb,curve,color_grid)
        train=np.r_[gray,rng.random((120,3))]
        grid,audit=compress(train,np.ones(len(train)),teacher,np.eye(3),probe_side=5,sweeps=1)
        packed=pack(grid)
        self.assertEqual(len(packed),1215)
        self.assertTrue(audit['training_only'])
        probes=rng.uniform(.1,.8,(100,3))
        student=evaluate(probes,unpack(packed),np.eye(3))
        self.assertLess(np.mean((student-teacher(probes))**2),np.mean((probes-teacher(probes))**2)*.1)
        self.assertGreater(np.max(np.abs(student-probes)),.01)
        # In particular, nonzero gray changes survive without runtime curves/gate.
        neutral=np.full((1,3),.4)
        self.assertGreater(float(np.max(np.abs(evaluate(neutral,grid,np.eye(3))-neutral))),.015)

    def test_holdout_rejects_a_better_average_that_tints_neutral_shadows(self):
        from chart_grid_selection import select

        response = np.eye(3)
        source = np.r_[np.full((16, 3), .08), np.tile([.35, .45, .52], (112, 1))]
        gray = np.full((16, 3), .4)
        zero = np.zeros((405, 3), dtype=np.int8)
        shifted = np.tile([8, 0, 0], (405, 1)).astype(np.int8)
        baseline = (0., zero, dict(smoothness=.001))
        alternative = (1., shifted, dict(smoothness=.01))
        wanted = evaluate(source, shifted, response)
        protected = wanted.copy()
        protected[:16] = source[:16]
        for target, expected in ((protected, baseline), (wanted, alternative)):
            with self.subTest(adopt=expected is alternative):
                result, report = select([baseline, alternative], baseline, response,
                    (source, target), (gray, evaluate(gray, shifted, response)))
                self.assertIs(result, expected)
                self.assertEqual(report['coverage']['dark_neutral'], 16)
                self.assertFalse(report['test_used_for_selection'])
                trial, = report['candidates']
                self.assertLess(trial['metrics']['delta_e00_mean'], report['before']['delta_e00_mean'])
                if expected is baseline:
                    self.assertIn('dark_neutral_ab_rmse', trial['rejected_by'])
                else:
                    self.assertEqual(trial['rejected_by'], [])

    def test_focused_proposal_refines_training_rows_without_another_solve(self):
        from unittest.mock import patch

        source = np.array([[.08, .08, .08], [.4, .4, .4], [.6, .6, .6]])
        target = source.copy()
        target[-1] += .1
        table = np.zeros((405, 3), dtype=np.int8)
        calls = []

        def refine(grid, base, wanted, gate, weights, **options):
            np.testing.assert_array_equal(base, source)
            np.testing.assert_array_equal(wanted, target)
            self.assertEqual(options['sweeps'], 1)
            calls.append(weights.copy())
            return grid, {}

        def select(candidates, baseline):
            self.assertEqual([item[2]['kind'] for item in candidates[-2:]], ['focused', 'focused-half'])
            return baseline, {}

        with patch('pc_stages.fit_response_grid', return_value=(table, {})) as solve, \
             patch('optimizer_policy.refine_grid', side_effect=refine):
            _, audit = fit_target(source, target, np.ones(3), np.eye(3), select_candidates=select)
        self.assertEqual(solve.call_count, 3)
        self.assertEqual(len(calls), 4)
        np.testing.assert_allclose(calls[-1], [.375, .25, .375])
        self.assertEqual(audit['chart_holdout']['focused_training'], dict(shadows=1, dark_neutral=1, tail=1))


    def test_teacher_receives_training_and_synthetic_queries_only(self):
        train=np.array([[.123,.234,.345],[.456,.567,.678]])
        seen=[]
        def teacher(rgb):seen.append(rgb.copy());return rgb
        grid,audit=compress(train,np.array([1.,3.]),teacher,np.eye(3),probe_side=3,sweeps=0)
        self.assertEqual(len(seen),1)
        np.testing.assert_array_equal(seen[0][:2],train)
        self.assertEqual(len(seen[0]),2+27)
        np.testing.assert_array_equal(grid,0)
        self.assertEqual(audit['train_probe_mass'],[.5,.5])

    def test_rejects_invalid_response_and_weights(self):
        for response,weights in [(np.zeros((3,3)),[1,1]),(np.eye(3),[0,1])]:
            with self.assertRaises(ValueError):
                compress(np.ones((2,3)),weights,lambda x:x,response,probe_side=3,sweeps=0)


if __name__=='__main__':unittest.main()
