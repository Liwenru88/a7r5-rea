"""开发照片辅助与统计过渡约束的定向契约。"""
import unittest
import numpy as np
import torch


class ResearchObjectiveTests(unittest.TestCase):
    def test_region_gate_activates_only_outside_frozen_quantization_envelope(self):
        from gpu_tensor import TensorTools
        from calibrated_guard import phase_rgb
        import native_objective_research as module
        tools=TensorTools('cpu',torch.float64)
        row=dict(scene='dev',role='development',inputs=np.zeros((81,9,3),np.uint16),
            target=np.full((81,3),.4),display=np.arange(81).reshape(9,9))
        bank=module.PhotoBank([row],per_region=8);bank.reference=np.full_like(bank.target,.42)
        gate=module.PhotoProtection(bank)
        for reference in (bank.reference,phase_rgb(bank.reference,np.array([.3,-.3,.1]))):
            loss,stats=gate.parts(tools,tools.tensor(reference))
            self.assertEqual(float(loss),0.);self.assertEqual(stats['photo_guard_active_regions'],0)
        changed=bank.reference.copy();changed[:8]=.58
        prediction=tools.tensor(changed).requires_grad_(True)
        loss,stats=gate.parts(tools,prediction);loss.backward()
        self.assertGreater(float(loss.detach()),0.)
        self.assertEqual(stats['photo_guard_active_regions'],1)
        self.assertTrue(torch.isfinite(prediction.grad).all())
        self.assertGreater(float(prediction.grad[:8].sum()),0.)
        self.assertEqual(float(prediction.grad[8:].abs().max()),0.)

    def test_photo_sampling_is_balanced_reproducible_and_excludes_holdout(self):
        import native_objective_research as module
        inputs=np.repeat(np.arange(81,dtype=np.uint16)[:,None,None],27,axis=1).reshape(81,9,3)
        row=dict(scene='dev',role='development',inputs=inputs,target=np.full((81,3),.4),display=np.arange(81).reshape(9,9))
        a=module.PhotoBank([row],per_region=2,seed=42);b=module.PhotoBank([row],per_region=2,seed=42)
        self.assertEqual(len(a.groups),9);self.assertEqual(len(a.inputs),18)
        self.assertEqual(a.groups,b.groups);np.testing.assert_array_equal(a.inputs,b.inputs)
        self.assertTrue(all(len(g['indices'])==2 for g in a.groups))
        with self.assertRaises(ValueError):module.PhotoBank([dict(row,role='holdout')],per_region=2)

    def test_photo_loss_reaches_target_and_keeps_finite_gradients(self):
        from gpu_tensor import TensorTools
        import native_objective_research as module
        row=dict(scene='dev',role='development',inputs=np.zeros((81,9,3),np.uint16),
            target=np.full((81,3),.4),display=np.arange(81).reshape(9,9))
        bank=module.PhotoBank([row],per_region=2);tools=TensorTools('cpu',torch.float64)
        exact=tools.tensor(bank.target).requires_grad_(True)
        self.assertLess(float(bank.tensor_loss(tools,exact,.0002).detach()),1e-7)
        changed=tools.tensor(bank.target+.03).requires_grad_(True)
        loss=bank.tensor_loss(tools,changed,.0002);loss.backward()
        self.assertGreater(float(loss.detach()),.0001);self.assertTrue(torch.isfinite(changed.grad).all())

    def test_statistical_transition_hinge_preserves_reference_and_detects_new_spike(self):
        from gpu_tensor import TensorTools
        from calibrated_guard import RampBank
        import native_objective_research as module
        tools=TensorTools('cpu',torch.float64);bank=RampBank(.17)
        reference=np.clip(bank.rgb**.7,0,1)
        penalty=module.TransitionPenalty(bank,reference)
        self.assertEqual(float(penalty.tensor_loss(tools,tools.tensor(reference))),0.)
        changed=reference.copy();changed[31]=[1.,0.,1.]
        prediction=tools.tensor(changed).requires_grad_(True)
        loss=penalty.tensor_loss(tools,prediction);loss.backward()
        self.assertGreater(float(loss.detach()),0.)
        self.assertTrue(torch.isfinite(prediction.grad).all())

    def test_photo_and_transition_auxiliary_paths_run_on_mps_with_bounded_gradients(self):
        import copy,colorsys,baseline,core
        from calibrated_guard import RampBank
        from edit_parameter_context import ParameterContext,RuntimeColor
        from grid_models import default_response
        from native_feasible_experiment import OriginalSpace,FlatRenderer
        from native_guard_policy import TargetToneBank,build_calibration
        import native_objective_research as module
        design=np.array([colorsys.hsv_to_rgb(h,.82,float(v)) for h in np.arange(24)/24 for v in np.linspace(.01,1,9)])
        target=design**.85;inputs=np.repeat(np.rint(design*15000).astype('uint16')[:,None],9,axis=1)
        context=ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID)),native_gamma=True)
        entry=copy.deepcopy(core.presets()[0][0]);entry['cc1_delta'][1:]=[[0]*8,[0]*8]
        entry['block13']=[copy.deepcopy(entry['block13'][0]) for _ in range(3)]
        space=OriginalSpace(context,entry,device='mps');bank=RampBank(.17);response=default_response()
        flat=FlatRenderer(space,np.concatenate((inputs,bank.inputs(context.base))),response)
        reference=flat.exact_entry(entry)[0];gray=np.arange(len(design))<9
        photo_inputs=inputs.copy();photo_inputs[:,2,0]+=35
        photos=module.PhotoBank([dict(scene='dev',role='development',inputs=photo_inputs,target=target,display=np.arange(len(design)).reshape(24,9))],per_region=2)
        renderer=module.MixedRenderer(flat,photos.inputs);photos.reference=renderer.photo.exact_entry(entry)[0]
        calibration=build_calibration(reference[:len(design)],target,gray,[('dev',reference[:len(design)],target,np.arange(len(design)).reshape(24,9))])
        tones=TargetToneBank(design,target,np.full(len(design),'train'),np.full(len(design),'hue24_tonal'),reference[:len(design)])
        for ratio,guard in ((.1,0.),(0.,.25),(.05,.1)):
            with self.subTest(photo_ratio=ratio,photo_guard_budget=guard):
                objective=module.ResearchObjective(space,target,gray,bank,reference,new_loss=True,response=response,
                    calibration=calibration,tone_bank=tones,tone_gradient_cap=.2,photo_bank=photos,
                    photo_ratio=ratio,transition_budget=.1,photo_guard_budget=guard)
                vector=space.tensor(space.initial).requires_grad_(True);prediction,_=renderer.evaluate(vector)
                if guard:
                    shifted=prediction.clone();shifted[-len(photos.inputs):]=shifted[-len(photos.inputs):]+.1
                    prediction=shifted
                loss,stats=objective.balanced(prediction,space.decode(vector),vector,space.tensor(space.legacy_scales))
                loss.backward();self.assertTrue(torch.isfinite(vector.grad).all())
                if ratio:self.assertGreater(stats['photo_loss'],0)
                if guard:self.assertGreater(stats['photo_guard_loss'],0)
                self.assertLessEqual(stats['photo_gradient_ratio'],.250001)
                self.assertLessEqual(stats['photo_guard_gradient_ratio'],guard+1e-6)
                self.assertLessEqual(stats['transition_gradient_ratio'],.100001)
                self.assertEqual(stats['photo_training_samples'],18)
