"""验证导出保护、联合跨越和整数编码，避免只测试同源梯度。"""
import copy
import unittest

import numpy as np

from integer_grid import TRANSITION_LIMITS
from integer_blocks import CandidatePool, Mesh, matrix_move, native_moves
from native_scoring import ScoredRecipe, adoption_failures, validate_splits


def recipe(number=0, **changes):
    metrics = dict(rgb_rmse=10.,delta_e00_mean=4.,delta_e00_p95=12.,
        delta_e00_tail_mean=14.,color_score=200.,float_rgb_rmse=10.,
        gray_rmse=3.,continuity_cost=2.,**{key:1. for key in TRANSITION_LIMITS})
    metrics.update(changes)
    return ScoredRecipe({},str(number),metrics,{},str(number))


class IntegerBlockTests(unittest.TestCase):
    def test_fingerprint_resolves_real_modules(self):
        from integer_blocks import fingerprint
        sources = fingerprint()
        self.assertIn('web/native_scoring.py',sources)
        self.assertIn('scripts/residual_grid.py',sources)
        self.assertTrue(all(len(value) == 64 for value in sources.values()))

    def test_exploration_never_replaces_feasible_export_and_can_reach_joint_solution(self):
        baseline = recipe()
        pool = CandidatePool(baseline)
        # 独立的两步都不能导出，联合补偿后才通过全部门槛。
        first = recipe(1,rgb_rmse=9.8,delta_e00_mean=3.9,gray_rmse=3.1)
        second = recipe(2,rgb_rmse=10.1,delta_e00_mean=3.8)
        for item in (first,second):
            self.assertTrue(pool.admit(item))
            self.assertIs(pool.best,baseline)
            self.assertIn(item,pool.exploratory)
            self.assertTrue(adoption_failures(item.metrics,baseline.metrics))
        joint = recipe(3,rgb_rmse=9.7,delta_e00_mean=3.8,delta_e00_tail_mean=13.8)
        self.assertTrue(pool.admit(joint))
        self.assertIs(pool.best,joint)
        self.assertFalse(adoption_failures(pool.best.metrics,baseline.metrics))
        self.assertFalse(pool.admit(recipe(4,rgb_rmse=9.,delta_e00_mean=3.,gray_rmse=4.)))
        self.assertIs(pool.best,joint)

    def test_nonfinite_and_p95_cannot_bypass_gate(self):
        baseline = recipe().metrics
        candidate = recipe(1,rgb_rmse=9.,delta_e00_mean=3.).metrics
        self.assertFalse(adoption_failures(candidate,baseline))
        for key in ('delta_e00_p95','gray_rmse','rgb_rmse','native-saturation_max'):
            for value in (float('nan'),float('inf'),baseline[key]+.01):
                with self.subTest(key=key,value=value):
                    self.assertTrue(adoption_failures(dict(candidate,**{key:value}),baseline))

    def test_float_plateau_only_guides_exploration_and_never_claims_display_improvement(self):
        pool = CandidatePool(recipe())
        first,better = recipe(1,float_rgb_rmse=9.99),recipe(2,float_rgb_rmse=9.98)
        self.assertTrue(pool.admit(first))
        self.assertTrue(pool.admit(better))
        self.assertEqual([row.sha256 for row in pool.exploratory],['2'])
        self.assertEqual(pool.best.sha256,'0')
        self.assertTrue(adoption_failures(better.metrics,pool.baseline.metrics))

    def test_matrix_moves_change_effective_value_and_match_independent_decoder(self):
        from edit_native_model import decode_matrix16
        from edit_parameter_context import ParameterContext,RuntimeColor
        import baseline
        import struct
        context = ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.PT_ID)))
        def decoded(code):
            payload = bytearray(context.payload)
            struct.pack_into('<H',payload,26,(code << 2)&65535)
            return struct.unpack_from('<f',decode_matrix16(bytes(payload)),0x28)[0]
        for code in (-8190,-17,-2,-1,0,1,17,8190):
            for direction in (-1,1):
                changed = matrix_move(code,direction)
                if -8192 <= changed <= 8191:
                    self.assertGreater(direction*(decoded(changed)-decoded(code)),0.)

    def test_native_blocks_keep_gamma_plateaus_and_fixed_endpoints(self):
        entry = dict(gamma_native_129=[0]+[100]*5+list(range(101,223))+[1000],
            cc1_delta=[[0]*8,[0]*8,[0]*8],block13=np.zeros((3,16,6),int).tolist())
        original = copy.deepcopy(entry)
        gradient = np.zeros(231)
        gradient[104:111] = np.arange(1,8)
        proposals = list(native_moves(entry,gradient,1,count=7))
        self.assertTrue(proposals)
        for value,_ in proposals:
            gamma = value['gamma_native_129']
            self.assertEqual(gamma[0],0)
            self.assertEqual(gamma[-1],1000)
            self.assertTrue(np.all(np.diff(gamma) >= 0))
        self.assertEqual(entry,original)
        mesh = Mesh()
        mesh.update(False);self.assertEqual(mesh.size,1)
        mesh.update(True);self.assertEqual(mesh.size,2)
        mesh.update(True);self.assertEqual(mesh.size,4)

    def test_splits_reject_validation_leak_and_duplicate_train(self):
        inputs = np.zeros((6,9,3))
        target = np.zeros((6,3))
        gray = np.array([True,False,False,False,False,False])
        valid = np.array([False,False,False,True,True,False])
        validate_splits(inputs,target,np.arange(3),gray,valid)
        for train in (np.array([0,1,3]),np.array([0,0,1]),np.array([1,2])):
            with self.assertRaises(ValueError):
                validate_splits(inputs,target,train,gray,valid)

    def test_scoring_matches_independent_renderer_and_excludes_unselected_targets(self):
        import baseline
        import core
        from compute_backend import render_native
        from edit_parameter_context import ParameterContext,RuntimeColor
        from fit_bin_joint import grid_from,projected
        from gpu_runtime import cpu_reference
        from integer_grid import candidate_metrics
        from measured_response import shared_response
        from native_scoring import RecipeScorer
        from output_continuity import ProbeBank
        from patch_sampling import center_mean

        context = ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.PT_ID)))
        entry = copy.deepcopy(core.presets()[0][0])
        entry = projected(entry,dict(cc1=context.cc1,matrix_payload=context.payload,gamma_y=context.gamma_y))
        config = core.compiler.config([entry],5)
        inputs = np.repeat(np.random.default_rng(5).integers(100,3000,(10,1,3)),9,axis=1)
        target = np.random.default_rng(6).uniform(.1,.7,(10,3))
        train = np.array([3,0,5,2])
        gray = np.isin(np.arange(10),[0,3])
        valid = np.isin(np.arange(10),[4,6])
        bank,response = ProbeBank(),shared_response()
        scorer = RecipeScorer(config,context,inputs,target,train,gray,valid,response,bank,30,.35)
        actual = scorer.score(entry,'baseline')
        # 独立按原始灰阶顺序渲染，能发现评分器训练索引重排或缓存绑定错误。
        model = context.build(**core.slot_native_parameters(context,entry))
        with cpu_reference():
            bases = [center_mean(render_native(model,values))/16383 for values in
                (inputs[gray],inputs[valid],bank.inputs(model))]
        expected = candidate_metrics(target[gray],target[valid],response,bank,30,.35,
                                     include_p95=True)(grid_from(entry),*bases)
        for key,value in expected.items():
            self.assertAlmostEqual(actual.metrics[key],value,places=10)
        repeated = scorer.score(entry,'same-bytes')
        self.assertIs(actual,repeated)
        altered = copy.deepcopy(entry)
        altered['grid_5x9x9']['coefficients'][0][1][1][1] += 1
        scorer.score(altered,'grid-only')
        self.assertEqual(scorer.counts['native_renders'],1)
        changed = target.copy();changed[[1,7,8,9]] = 1.
        other = RecipeScorer(config,context,inputs,changed,train,gray,valid,response,bank,30,.35)
        self.assertEqual(actual.metrics,other.score(entry,'excluded-changed').metrics)
        self.assertEqual(actual.training,other.score(entry,'excluded-changed').training)


if __name__ == '__main__':
    unittest.main()
