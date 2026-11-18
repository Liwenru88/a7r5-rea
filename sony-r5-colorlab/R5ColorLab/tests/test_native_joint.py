"""统一入口的数据隔离、完整证据和无收益回退。"""
import copy
import unittest
import numpy as np
from types import SimpleNamespace
from unittest.mock import patch
from native_joint import validate_arrays,choose


class JointTests(unittest.TestCase):
    def test_bound_development_photos_require_independent_final_photos(self):
        import core
        from native_joint import Gate
        gate=Gate.__new__(Gate);entry=core.presets()[0][0]
        gate.reference=entry;gate.context=None;gate.response=None;gate.cache={};gate.final_calls=0
        gate.phases=(.17,);gate.final_phases=(.113,);gate.calibration={'photo':{}}
        gate.data=SimpleNamespace(inputs=np.zeros((6,9,3)),target=np.zeros((6,3)),
            split=np.array(['train','train','train','valid','test','test']),gray=np.array([True,True,False,False,False,False]),
            photos=[{'role':'development'}],holdout_loader=lambda:[])
        gate.geometry_for=lambda _: (np.zeros((1,9,3)),np.zeros((1,3)),{})
        with patch('native_joint.predict',side_effect=lambda c,e,x,r:np.full((len(x),3),.2)):
            result=gate.assess(entry,'final',final=True)
        self.assertIn('photo:holdout-missing',result['failures'])
        self.assertEqual(result['photo_scope'],'holdout')

    def test_research_and_solver_share_one_native_replay(self):
        import native_runtime,native_solver,benchmark_native_four
        self.assertIs(native_solver.predict,native_runtime.predict)
        self.assertIs(benchmark_native_four.predict,native_runtime.predict)

    def data(self):
        return dict(inputs=np.zeros((6,9,3),dtype=np.uint16),target=np.zeros((6,3)),
            split=np.array(['train','train','train','valid','test','test']),
            anchors=np.array([4,5,-1,-1,-1,-1]),design=np.zeros((6,3)),kinds=np.full(6,'random'))

    def test_invalid_training_data_cannot_enter_solver(self):
        value=self.data();validate_arrays(**value)
        for change in (dict(target=np.full((6,3),np.nan)),dict(split=np.full(6,'train')),
                       dict(anchors=np.array([4,5,-1,6,-1,-1])),dict(inputs=np.zeros((6,3)))):
            with self.subTest(change=list(change)):
                with self.assertRaises(ValueError):validate_arrays(**dict(value,**change))

    def test_selection_requires_complete_evidence_and_real_improvement(self):
        metrics=dict(rgb_rmse=5.,delta_e00_mean=3.,delta_e00_p95=6.,gray_rmse=2.,weighted_loss=1.)
        reference=dict(label='reference',metrics=metrics,score=2.,failures=[],fully_evaluated=True)
        candidate=dict(reference,label='candidate',metrics=dict(metrics,rgb_rmse=4.,delta_e00_mean=2.,weighted_loss=.8),score=1.5)
        self.assertEqual(choose(reference,[candidate])['label'],'candidate')
        for row in (dict(candidate,fully_evaluated=False),dict(candidate,failures=['dense:native:max']),
                    dict(candidate,metrics=dict(candidate['metrics'],delta_e00_mean=3.1)),
                    dict(candidate,metrics=dict(candidate['metrics'],rgb_rmse=float('nan')))):
            with self.subTest(row=row):self.assertEqual(choose(reference,[row])['label'],'reference')


if __name__=='__main__':unittest.main()
