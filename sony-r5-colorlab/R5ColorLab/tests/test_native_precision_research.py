"""高覆盖照片、密集局部窗口及辅助梯度投影的行为契约。"""
import tempfile
from pathlib import Path
import unittest

import numpy as np
import torch


class PrecisionTests(unittest.TestCase):
    def test_projection_keeps_loss_value_and_removes_opposing_gradient(self):
        import native_precision_research as module
        vector=torch.tensor([.3,.2],dtype=torch.float64,requires_grad=True)
        scales=torch.tensor([2.,3.],dtype=torch.float64)
        loss=(-vector[0]+vector[1])/3
        main=torch.tensor([1.,0.],dtype=torch.float64)
        updated,stats=module.project_auxiliary(loss,vector,scales,main)
        self.assertEqual(float(updated.detach()),float(loss.detach()))
        grad=torch.autograd.grad(updated,vector)[0]*scales
        self.assertGreaterEqual(float(grad@main),-1e-12)
        self.assertLessEqual(float(grad.norm()),float(torch.tensor([-2/3,1.]).norm()))
        self.assertTrue(stats['projected'])

    def test_dense_windows_are_true_inputs_covering_both_domains(self):
        import baseline
        from calibrated_guard import RampBank
        from edit_parameter_context import ParameterContext,RuntimeColor
        import native_precision_research as module
        context=ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID)),native_gamma=True)
        base=RampBank(.17)
        render=lambda x:np.clip(x[:,4].astype(float)/16383,0,1)
        bank=module.WindowRampBank(base,context.base,render,uniform=4,peaks=2,rays_per_axis=2)
        self.assertEqual(bank.window_shape,(4,6,3))
        self.assertEqual(set(x['axis'] for x in bank.groups),{'saturation','native-saturation'})
        np.testing.assert_array_equal(bank.inputs(context.base)[:len(base.rgb)],base.inputs(context.base))
        inputs=bank.inputs(context.base)
        self.assertEqual(inputs.shape,(len(bank.rgb),9,3))
        np.testing.assert_array_equal(inputs,np.broadcast_to(inputs[:,4:5],inputs.shape))
        reference=render(inputs);penalty=module.DenseWindowPenalty(bank,reference)
        from gpu_tensor import TensorTools
        tools=TensorTools('cpu',torch.float64)
        self.assertLess(float(penalty.tensor_loss(tools,tools.tensor(reference))),1e-15)
        changed=reference.copy();changed[bank.dense_offset+1]=[1.,0.,1.]
        value=tools.tensor(changed).requires_grad_(True)
        loss=penalty.tensor_loss(tools,value);loss.backward()
        self.assertGreater(float(loss.detach()),0.)
        self.assertTrue(torch.isfinite(value.grad).all())

    def test_precision_plan_predeclares_equal_short_and_long_budgets(self):
        import benchmark_native_precision as module
        plan=module.screen_plan()
        self.assertEqual(len(plan),4)
        self.assertTrue(all(x['photo_samples']==256 for x in plan))
        self.assertEqual([x['dense_budget'] for x in plan],[0.,.1,.25,.25])
        self.assertEqual([x['project_conflicts'] for x in plan],[False,False,False,True])

    def test_precision_loss_runs_full_corrected_mps_forward_and_backward(self):
        import colorsys,copy,baseline,core
        from calibrated_guard import RampBank
        from edit_parameter_context import ParameterContext,RuntimeColor
        from grid_models import default_response
        from native_feasible_experiment import OriginalSpace,FlatRenderer
        from native_guard_policy import TargetToneBank,build_calibration
        from native_objective_research import PhotoBank,MixedRenderer
        import native_precision_research as module
        design=np.array([colorsys.hsv_to_rgb(h,.82,float(v)) for h in np.arange(24)/24 for v in np.linspace(.01,1,9)])
        target=design**.85;inputs=np.repeat(np.rint(design*15000).astype('uint16')[:,None],9,axis=1)
        context=ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID)),native_gamma=True)
        entry=copy.deepcopy(core.presets()[0][0]);entry['cc1_delta'][1:]=[[0]*8,[0]*8]
        entry['block13']=[copy.deepcopy(entry['block13'][0]) for _ in range(3)]
        space=OriginalSpace(context,entry,device='mps');response=default_response()
        from benchmark_native_four import predict
        bank=module.WindowRampBank(RampBank(.17),context.base,lambda x:predict(context,entry,x,response),uniform=4,peaks=2,rays_per_axis=2)
        flat=FlatRenderer(space,np.concatenate((inputs,bank.inputs(context.base))),response);reference=flat.exact_entry(entry)[0]
        gray=np.arange(len(design))<9
        photos=PhotoBank([dict(scene='dev',role='development',inputs=inputs,target=target,display=np.arange(len(design)).reshape(24,9))],per_region=2)
        renderer=MixedRenderer(flat,photos.inputs);photos.reference=renderer.photo.exact_entry(entry)[0]
        calibration=build_calibration(reference[:len(design)],target,gray,[('dev',reference[:len(design)],target,np.arange(len(design)).reshape(24,9))])
        tones=TargetToneBank(design,target,np.full(len(design),'train'),np.full(len(design),'hue24_tonal'),reference[:len(design)])
        objective=module.PrecisionObjective(space,target,gray,bank,reference,new_loss=True,response=response,
            calibration=calibration,tone_bank=tones,tone_gradient_cap=.2,photo_bank=photos,photo_ratio=.05,
            photo_guard_budget=.25,dense_budget=.25,project_conflicts=True)
        vector=space.tensor(space.initial).requires_grad_(True);prediction,_=renderer.evaluate(vector)
        shifted=prediction.clone();shifted[len(design)+bank.dense_offset+1]+=prediction.new_tensor([.1,-.1,.05])
        loss,stats=objective.balanced(shifted,space.decode(vector),vector,space.tensor(space.legacy_scales))
        loss.backward();self.assertTrue(torch.isfinite(vector.grad).all())
        self.assertGreater(stats['dense_loss'],0.)
        self.assertLessEqual(stats['dense_gradient_ratio'],.250001)

    def test_optional_checkpoints_preserve_bin_and_optimizer_state(self):
        import baseline,core
        import benchmark_native_feasible as module
        with tempfile.TemporaryDirectory() as folder:
            entry=core.presets()[0][0];state=dict(step=50,vector=torch.tensor([1.,2.]))
            module.save_research_checkpoint(Path(folder),50,state,entry)
            path=Path(folder)/'checkpoints/000050.BIN'
            self.assertEqual(core.compiler.unpack(path.read_bytes())['entries'][0],entry)
            saved=torch.load(path.with_suffix('.pt'),weights_only=True)
            self.assertEqual(saved['step'],50)
