"""损失实验仅限制辅助梯度，不通过调验收阈值制造收益。"""
import unittest

import numpy as np
import torch


class LossExperimentTests(unittest.TestCase):
    def test_photo_gate_study_keeps_the_accepted_five_percent_control(self):
        import benchmark_native_loss as module
        plan=module.study_plan('photo_guard')
        self.assertEqual([x['research'] for x in plan['fixed_trials']],
            [dict(photo_ratio=.05),dict(photo_guard_budget=.25),
             dict(photo_ratio=.05,photo_guard_budget=.1),dict(photo_ratio=.05,photo_guard_budget=.25)])
        self.assertTrue(all(x['lr']==.003 and x['cap']==.2 for x in plan['fixed_trials']))

    def test_cap_study_accepts_both_parameterizations_before_gpu_preflight(self):
        import sys
        from unittest.mock import patch
        import benchmark_native_loss as module
        for arm in ('C','D'):
            with self.subTest(arm=arm):
                argv=['benchmark_native_loss','--bin','unused.BIN','--manifest','unused.json',
                      '--normalization','unused-scales.json','--output','unused-output',
                      '--study','cap_lr','--arm',arm]
                with patch.object(sys,'argv',argv),patch.object(module.torch.backends.mps,'is_available',return_value=False):
                    with self.assertRaisesRegex(RuntimeError,'MPS不可用'):module.main()

    def test_cap_sweep_freezes_loss_for_all_three_learning_rates(self):
        import benchmark_native_loss as module
        plan=module.study_plan('cap_lr')
        self.assertEqual(plan['loss_trials'],[])
        self.assertEqual([x['lr'] for x in plan['fixed_trials']],[.0015,.003,.006])
        self.assertTrue(all(x['cap']==.2 and x['tone_ratio']==.1 for x in plan['fixed_trials']))
        self.assertEqual(len({x['name'] for x in plan['fixed_trials']}),3)

    def test_original_loss_study_plan_is_preserved(self):
        import benchmark_native_loss as module
        plan=module.study_plan('loss_lr')
        self.assertEqual([x['name'] for x in plan['loss_trials']],['control','tone_off','tone_002','tone_cap02'])
        self.assertEqual(plan['fixed_trials'],[])
        with self.assertRaises(ValueError):module.study_plan('unknown')

    def test_research_plan_varies_loss_terms_with_fixed_lr_and_budget(self):
        import benchmark_native_loss as module
        plan=module.study_plan('objective_plus')
        self.assertEqual(len(plan['fixed_trials']),7)
        self.assertTrue(all(x['lr']==.003 and x['cap']==.2 for x in plan['fixed_trials']))
        configs={x['name']:x['research'] for x in plan['fixed_trials']}
        self.assertEqual(configs['de_half']['de_factor'],.5)
        self.assertEqual(configs['de_double']['de_factor'],2.)
        self.assertEqual(configs['photo05']['photo_ratio'],.05)
        self.assertEqual(configs['photo20']['photo_ratio'],.2)
        self.assertEqual(configs['photo10_transition10']['transition_budget'],.1)

    def test_auxiliary_gradient_cap_preserves_primary_update(self):
        import native_loss_experiment as module
        primary=torch.tensor([1.,0.]);auxiliary=torch.tensor([-2.,1.])
        factor=module.gradient_cap_factor(primary,auxiliary,.2)
        self.assertLessEqual(float((factor*auxiliary).norm()),.200001)
        self.assertGreater(float((primary+factor*auxiliary)[0]),.8)
        self.assertEqual(module.gradient_cap_factor(primary,auxiliary,None),1.)
        self.assertEqual(module.gradient_cap_factor(primary,torch.zeros(2),.2),1.)
        for cap in (-1.,float('nan')):
            with self.subTest(cap=cap):
                with self.assertRaises(ValueError):module.gradient_cap_factor(primary,auxiliary,cap)

    def test_default_research_objective_matches_existing_value_and_gradient(self):
        import colorsys,copy,baseline,core
        from calibrated_guard import RampBank
        from edit_parameter_context import ParameterContext,RuntimeColor
        from grid_models import default_response
        from native_feasible_experiment import OriginalSpace,FlatRenderer
        from native_guard_policy import ReviewedObjective,TargetToneBank,build_calibration
        import native_loss_experiment as module
        from native_objective_research import ResearchObjective
        design=np.array([colorsys.hsv_to_rgb(h,.82,float(v)) for h in np.arange(24)/24 for v in np.linspace(.01,1,9)])
        target=design**.85;inputs=np.repeat(np.rint(design*15000).astype('uint16')[:,None],9,axis=1)
        context=ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID)),native_gamma=True)
        entry=copy.deepcopy(core.presets()[0][0]);entry['cc1_delta'][1:]=[[0]*8,[0]*8]
        entry['block13']=[copy.deepcopy(entry['block13'][0]) for _ in range(3)]
        # 默认损失等价性用CPU双精度检查，MPS归约波动由独立GPU集成测试覆盖。
        space=OriginalSpace(context,entry,device='cpu',dtype=torch.float64);bank=RampBank(.17);response=default_response()
        renderer=FlatRenderer(space,np.concatenate((inputs,bank.inputs(context.base))),response)
        reference=renderer.exact_entry(entry)[0];gray=np.arange(len(design))<9
        calibration=build_calibration(reference[:len(design)],target,gray,
            [('development',reference[:len(design)],target,np.arange(len(design)).reshape(24,9))])
        tones=TargetToneBank(design,target,np.full(len(design),'train'),np.full(len(design),'hue24_tonal'),reference[:len(design)])
        kwargs=dict(new_loss=True,response=response,calibration=calibration,tone_bank=tones)
        old=ReviewedObjective(space,target,gray,bank,reference,**kwargs)
        results=[]
        for objective in (old,module.LossObjective(space,target,gray,bank,reference,**kwargs),
                          module.LossObjective(space,target,gray,bank,reference,**kwargs,tone_ratio=.1,tone_gradient_cap=.2)):
            vector=space.tensor(space.initial).requires_grad_(True)
            prediction,_=renderer.evaluate(vector)
            loss,stats=objective.balanced(prediction,space.decode(vector),vector,space.tensor(space.legacy_scales))
            gradient=torch.autograd.grad(loss,vector)[0]
            self.assertTrue(torch.isfinite(gradient).all())
            results.append((float(loss.detach().cpu()),gradient.detach().cpu().numpy(),stats))
        self.assertEqual(results[0][0],results[1][0])
        np.testing.assert_allclose(results[0][1],results[1][1],rtol=2e-5,atol=1e-10)
        self.assertLessEqual(results[2][2]['effective_tone_gradient_ratio'],.200001)
        self.assertEqual(results[2][2]['raw_penalty'],0.)
        vector=space.tensor(space.initial).requires_grad_(True);prediction,_=renderer.evaluate(vector)
        research=ResearchObjective(space,target,gray,bank,reference,**kwargs)
        loss,_=research.balanced(prediction,space.decode(vector),vector,space.tensor(space.legacy_scales))
        gradient=torch.autograd.grad(loss,vector)[0].detach().cpu().numpy()
        self.assertEqual(float(loss.detach().cpu()),results[0][0])
        np.testing.assert_allclose(gradient,results[0][1],rtol=2e-5,atol=1e-10)
