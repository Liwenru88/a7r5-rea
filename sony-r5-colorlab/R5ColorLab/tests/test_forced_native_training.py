"""强制新训练不被品质回退替换，非法配方仍被拒绝。"""
import copy
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
import core
import training_profile as tp
import numpy as np


class ForcedTrainingTests(unittest.TestCase):
    def rows(self):
        from native_runtime import blob
        old=copy.deepcopy(core.presets()[0][0]);new=copy.deepcopy(old)
        new['gamma_native_129'][1]+=1
        m=dict(rgb_rmse=5.,delta_e00_mean=3.,delta_e00_p95=6.,gray_rmse=2.,weighted_loss=1.)
        reference=dict(label='reference',entry=old,sha256=core.sha(blob(old)),metrics=m,score=2.,failures=[],fully_evaluated=True)
        row=dict(reference,label='C/000200',entry=new,sha256=core.sha(blob(new)),
            metrics=dict(m,rgb_rmse=4.8),failures=['dense:native-hue:max'],fully_evaluated=False)
        return reference,row

    def test_all_new_requests_bind_c_without_changing_target_identity(self):
        for mode in (None,'custom','upstream-formal/1','native-joint/1'):
            for kind in ('chart-image','lut'):
                with self.subTest(mode=mode,kind=kind):
                    original=dict(training_profile=mode,target_kind=kind,number=24,lut='source',gamut='S-Gamut3')
                    bound=tp.bind(original)
                    self.assertEqual(bound['training_profile'],'native-joint/1')
                    self.assertEqual(bound['joint_options']['selection_policy'],'force-new')
                    self.assertEqual(bound['target_kind'],kind)
                    self.assertEqual(bound['number'],24)
                    self.assertEqual(bound['lut'],'source')
                    self.assertEqual(original['training_profile'],mode)

    def test_new_candidate_survives_quality_failure_and_later_pool(self):
        from native_joint import choose_forced
        ref,row=self.rows()
        gate=SimpleNamespace(selection_score=lambda r:r['metrics']['rgb_rmse'])
        better=dict(row,label='earlier-C',metrics=dict(row['metrics'],rgb_rmse=4.7))
        from native_runtime import blob
        better['entry']=copy.deepcopy(row['entry']);better['entry']['gamma_native_129'][2]+=1
        better['sha256']=core.sha(blob(better['entry']))
        result=choose_forced(ref,[ref,row,better],gate)
        self.assertEqual(result['label'],'earlier-C')
        with self.assertRaisesRegex(ValueError,'新候选'):choose_forced(ref,[ref],gate)
        renamed=dict(ref,entry=dict(ref['entry'],short_name='改名'))
        with self.assertRaisesRegex(ValueError,'新候选'):choose_forced(ref,[renamed],gate)
        bad=dict(row,metrics=dict(row['metrics'],rgb_rmse=float('nan')))
        with self.assertRaises(ValueError):choose_forced(ref,[bad],gate)

    def test_development_color_rank_is_independent_of_quality_short_circuit(self):
        from native_joint import Gate
        from native_scoring import color_metrics
        ref,row=self.rows();gate=Gate.__new__(Gate)
        before=np.array([[.1,.2,.3],[.4,.5,.6]])
        after=before+.01;target=before+.02
        gate.baseline=ref
        gate.data=SimpleNamespace(photos=[dict(inputs=np.zeros((2,9,3)),target=target)])
        gate.development=[('scene',before,target,None)]
        gate._predict=Mock(return_value=after)
        without=gate.selection_score(row)
        gate.__dict__.pop('_selection_scores')
        complete=dict(row,fully_evaluated=True,photos=[dict(metrics=color_metrics(after,target),baseline=color_metrics(before,target))])
        self.assertAlmostEqual(without,gate.selection_score(complete))
        gate._predict.assert_called_once()

    def test_quality_failure_keeps_new_recipe_and_reports_both_scopes(self):
        from native_joint_workbench import accept
        ref,row=self.rows();row['fully_evaluated']=True
        final=dict(row,failures=['photo:roof:rgb_rmse'])
        gate=SimpleNamespace(baseline=ref,assess=Mock(return_value=final))
        chosen,quality=accept(row['entry'],dict(selected=row),gate,force_new=True)
        self.assertEqual(chosen,row['entry']);self.assertNotEqual(chosen,ref['entry'])
        self.assertFalse(quality['quality_passed']);self.assertFalse(quality['retained_baseline'])
        self.assertEqual(quality['policy'],'native-joint-forced/1')
        self.assertEqual(len(quality['failed_checks']),2)
        self.assertEqual(quality['fallback_reason'],[])
        gate.assess.assert_called_once()

    def test_illegal_or_mismatched_candidate_cannot_be_published(self):
        from native_joint_workbench import accept
        ref,row=self.rows();gate=SimpleNamespace(baseline=ref,assess=Mock(return_value=row))
        illegal=copy.deepcopy(row['entry']);illegal['gamma_native_129'][1]=-1
        for candidate in (illegal,ref['entry']):
            with self.subTest(candidate=candidate['gamma_native_129'][1]):
                with self.assertRaises(ValueError):accept(candidate,dict(selected=row),gate,force_new=True)
        bad=dict(row,fully_evaluated=True,metrics=dict(row['metrics'],gray_rmse=float('nan')))
        with self.assertRaises(ValueError):accept(row['entry'],dict(selected=bad),gate,force_new=True)

    def test_direct_service_execution_cannot_route_to_old_algorithm(self):
        import server
        with patch('native_joint_workbench.work') as joint,patch('training_profile.work') as old,patch.object(server,'native_work') as native:
            for mode in ('custom','upstream-formal/1','native-joint/1'):
                server.work('test',dict(training_profile=mode,target_kind='chart-image'))
            self.assertEqual(joint.call_count,3);old.assert_not_called();native.assert_not_called()


if __name__=='__main__':unittest.main()
