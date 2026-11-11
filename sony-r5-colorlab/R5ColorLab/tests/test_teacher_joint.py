"""保护最终BIN契约、负矩阵刻度及P95回退，不以训练Loss代替验收。"""
import unittest
import numpy as np

from gpu_tensor import TensorTools
from native_rounding import Rounding
from teacher_joint import failures
from integer_grid import TRANSITION_LIMITS


class TeacherJointTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            import torch
        except ImportError:
            raise unittest.SkipTest('optional PyTorch unavailable')

    def test_unsupported_pipeline_modes_do_not_silently_skip_teacher(self):
        from unittest.mock import patch
        from grid_distillation import generate
        for objective,adaptive,available in [('pc-teacher',True,True),('fuji-target',False,True),('fuji-target',True,False)]:
            with self.subTest(objective=objective,adaptive=adaptive,available=available),patch('gpu_runtime.available',return_value=available):
                with self.assertRaises((ValueError,RuntimeError)):
                    generate('unused-job',{},objective=objective,adaptive_color=adaptive,joint_native=True)

    def test_teacher_loss_log_uses_training_loss_in_one_consistent_scale(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        import neural_teacher
        bank=SimpleNamespace(triplets=np.arange(6).reshape(2,3),mix=np.full((2,1),.5),
            allowance=np.ones(2),groups=[('saturation',1),('native-saturation',1)],
            mass=np.full(2,.5),distance=np.ones(2),gain_limit=np.full(2,32.))
        inputs=np.random.default_rng(22).uniform(.1,.4,(10,3))
        gray=np.array([True,True]+[False]*8)
        valid=np.array([False]*6+[True]*2+[False]*2)
        limits=dict(gray_rmse=100.,continuity_cost=100.,**{key:100. for key in TRANSITION_LIMITS})
        events=[]
        with patch('integer_grid.transition_metrics',return_value=dict(continuity_cost=0.,**{key:0. for key in TRANSITION_LIMITS})):
            first_prediction,first_audit=neural_teacher.fit(inputs,inputs,np.arange(6),gray,valid,bank,np.full((6,3),.2),
                np.full((6,3),.2),inputs[gray],limits,30,.35,
                progress=lambda **event:events.append(event),steps=3,guard_steps=2,device='cpu')
            # 未进入训练或验证的样本即使目标剧变，也不能改变训练与选定结果。
            changed=inputs.copy();changed[8:]=1.
            second_prediction,second_audit=neural_teacher.fit(inputs,changed,np.arange(6),gray,valid,bank,np.full((6,3),.2),
                np.full((6,3),.2),inputs[gray],limits,30,.35,steps=3,guard_steps=2,device='cpu')
        np.testing.assert_array_equal(first_prediction.numpy(),second_prediction.numpy())
        self.assertEqual(first_audit['trace'],second_audit['trace'])
        first=next(e['loss_sample'] for e in events if e['loss_sample'][0]=='teacher-Adam')
        self.assertEqual(first[2],first[3])
        for event in events:
            _,_,current,best=event['loss_sample']
            self.assertLessEqual(best,current)

    def test_integer_polish_rejects_mean_improvement_that_worsens_color_tail(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from integer_grid import polish_grid
        from neural_teacher import color_metrics
        source=np.tile([.741294225811353,.47590688671339126,.42561409719331417],(100,1))
        target=source.copy();target[:90,0]+=.02;target[90:,0]-=.1
        def stencil(rgb):
            return None,np.zeros((len(rgb),1),int),np.ones((len(rgb),1))
        def response(rgb):
            return np.tile(np.eye(3)[None]/256,(len(rgb),1,1))
        model=SimpleNamespace(stencil=stencil,response=response,
            predict_cpu=lambda rgb,grid,clip=False:rgb+grid[0]/256)
        limits=dict(gray_rmse=100.,continuity_cost=0.,
            delta_e00_p95=color_metrics(source,target)['delta_e00_p95'],
            **{key:0. for key in TRANSITION_LIMITS})
        gray=np.zeros(100,bool);gray[0]=True
        with patch('measured_response.get',return_value=model),patch('integer_grid.transition_metrics',
                return_value=dict(continuity_cost=0.,**{key:0. for key in TRANSITION_LIMITS})):
            results=[]
            for protected in (False,True):
                grid,moves=polish_grid(np.zeros((405,3),np.int8),source,target,gray,
                    np.array([[.3,.4,.5]]),{},None,30,limits,
                    validation_data=(source,target),protect_color_p95=protected)
                results.append((grid,moves))
        plain,protected=results
        self.assertGreater(plain[1],0)
        self.assertGreater(color_metrics(model.predict_cpu(source,plain[0]),target)['delta_e00_p95'],limits['delta_e00_p95'])
        self.assertEqual(protected[1],0)
        np.testing.assert_array_equal(protected[0],0)

    def test_p95_and_independent_color_metrics_block_adoption(self):
        baseline=dict(rgb_rmse=10.,delta_e00_mean=4.,delta_e00_p95=12.,color_score=200.,
                      gray_rmse=3.,continuity_cost=2.,**{key:1. for key in TRANSITION_LIMITS})
        candidate=dict(baseline,rgb_rmse=9.,delta_e00_mean=3.5,color_score=180.)
        self.assertEqual(failures(candidate,baseline,200.),[])
        for field,value in [('delta_e00_p95',12.01),('gray_rmse',3.01),
                            ('rgb_rmse',10.),('delta_e00_mean',4.),('native-saturation_max',1.01)]:
            with self.subTest(field=field):
                self.assertIn(field,failures(dict(candidate,**{field:value}),baseline,200.))

    def test_hard_rounding_matches_independent_native_matrix_quantizer(self):
        import torch
        from edit_parameter_context import quantize_matrix_coefficients
        import baseline
        from edit_parameter_context import ParameterContext, RuntimeColor
        tools=TensorTools('cpu',torch.float64)
        coefficients=np.random.default_rng(13).uniform(-2,2,96)
        vector=tools.tensor(np.r_[[.1,-.2,.3,-.4,1.2,1.3,1.4,1.5],coefficients,np.zeros(128)])
        gamma=tools.tensor(np.linspace(0,16000,128))
        grid=tools.tensor(np.random.default_rng(3).uniform(-64,63,(405,3)))
        rounding=Rounding(tools,vector,gamma,grid)
        rounded,y,table,_=rounding.values(rounding.initial,hard=True)
        # 编码器的负数为奇数刻度，独立解码结果必须一致。
        payload=ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.PT_ID))).payload
        _,expected=quantize_matrix_coefficients(payload,coefficients.reshape(6,16))
        np.testing.assert_allclose(rounded[8:104].numpy(),expected.ravel(),atol=0,rtol=0)
        self.assertTrue(bool((torch.diff(y)>=0).all()))
        self.assertTrue(bool((table>=-64).all() and (table<=63).all()))
        self.assertEqual(float(y[0]),0.)

    def test_soft_rounding_has_finite_gradients_for_all_parameter_groups(self):
        import torch
        tools=TensorTools('cpu',torch.float64)
        vector=tools.tensor(np.r_[np.ones(8)*.731,np.linspace(-1,1,96),np.zeros(128)])
        rounding=Rounding(tools,vector,tools.tensor(np.linspace(0,16000,128)),tools.tensor(np.ones((405,3))*.37))
        values=rounding.initial.clone().requires_grad_(True)
        native,gamma,grid,soft=rounding.values(values)
        loss=native.square().sum()+gamma.square().mean()+grid.square().mean()+rounding.penalty(soft,.5)
        loss.backward()
        self.assertTrue(bool(torch.isfinite(values.grad).all()))
        for group in (slice(0,8),slice(8,104),slice(104,231),slice(231,None)):
            self.assertGreater(float(values.grad[group].abs().sum()),0.)


if __name__=='__main__':
    unittest.main()
