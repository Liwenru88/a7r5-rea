"""原配方起点、损失平衡和完整保护的定向回归。"""
import copy
import unittest

import numpy as np
import torch

import baseline
import core
from edit_parameter_context import ParameterContext, RuntimeColor
from grid_models import default_response


class FeasibleExperimentTests(unittest.TestCase):
    def fixture(self, device='cpu'):
        import native_feasible_experiment as module
        entry=copy.deepcopy(core.presets()[0][0])
        entry['cc1_delta'][1:]=[[0]*8,[0]*8]
        entry['block13']=[copy.deepcopy(entry['block13'][0]) for _ in range(3)]
        # 非凹Gamma和负矩阵的有效低位都必须原样保留。
        entry['gamma_native_129']=np.rint(np.linspace(0,100000,129)).astype(int).tolist()
        entry['gamma_native_129'][-2:]=[100000,131071]
        entry['block13'][0][0][0]=-101
        entry['block13']=[copy.deepcopy(entry['block13'][0]) for _ in range(3)]
        context=ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID)),native_gamma=True)
        space=module.OriginalSpace(context,entry,device=device)
        values=np.array([[1000,2000,4000],[12000,8000,6000]],dtype=np.uint16)
        return module,space,np.repeat(values[:,None],9,axis=1)

    def test_cpu_and_mps_start_with_original_bin_bytes(self):
        for device in ('cpu','mps'):
            with self.subTest(device=device):
                module,space,_=self.fixture(device)
                actual=space.entry(space.tensor(space.initial))
                pack=lambda e:core.compiler.pack(core.compiler.config([e],5))
                self.assertEqual(pack(actual),pack(space.seed))

    def test_flat_cpu_acceleration_matches_full_nine_pixel_reference(self):
        module,space,inputs=self.fixture()
        fast=module.FlatRenderer(space,inputs,default_response())
        from native_four_experiment import Renderer
        reference=Renderer(space,inputs,default_response())
        np.testing.assert_array_equal(fast.exact_entry(space.seed)[0],reference.exact_entry(space.seed)[0])

    def test_balance_caps_both_value_and_normalized_gradient(self):
        import native_feasible_experiment as module
        for penalty,gradient in ((0.,0.),(.184,100.),(1e-4,1e-5)):
            with self.subTest(penalty=penalty):
                weight=module.balance_weight(.001,penalty,.02,gradient,budget=.5)
                self.assertGreaterEqual(weight,0)
                self.assertLessEqual(weight*penalty,.0005+1e-12)
                self.assertLessEqual(weight*gradient,.01+1e-12)

    def test_integer_blend_preserves_monotonicity_and_exact_endpoints(self):
        module,space,_=self.fixture()
        changed=copy.deepcopy(space.seed)
        changed['gamma_native_129']=[v//2 for v in changed['gamma_native_129']]
        changed['grid_5x9x9']['coefficients'][0][0][0][0]=63
        self.assertEqual(module.blend_entry(space.seed,changed,0),space.seed)
        self.assertEqual(module.blend_entry(space.seed,changed,1),changed)
        entry=module.blend_entry(space.seed,changed,.125)
        self.assertTrue(np.all(np.diff(entry['gamma_native_129'])>=0))
        core.compiler.pack(core.compiler.config([entry],5))

    def test_original_is_feasible_and_actual_mps_loss_obeys_caps(self):
        from calibrated_guard import RampBank
        module,space,inputs=self.fixture('mps')
        bank=RampBank(.17)
        renderer=module.FlatRenderer(space,np.concatenate((inputs,bank.inputs(space.context.base))),default_response())
        reference=renderer.exact_entry(space.seed)[0]
        objective=module.BalancedObjective(space,np.clip(reference[:2]-.01,0,1),np.array([True,False]),
            bank,reference,new_loss=True,response=default_response())
        initial=space.tensor(space.initial).requires_grad_(True)
        prediction,_=renderer.evaluate(initial)
        _,penalty,_=objective.parts(prediction,space.decode(initial))
        self.assertEqual(float(penalty.detach().cpu()),0)
        vector=initial.detach().clone();vector[0]+=.8;vector.requires_grad_(True)
        prediction,_=renderer.evaluate(vector)
        loss,stats=objective.balanced(prediction,space.decode(vector),vector,space.tensor(space.legacy_scales))
        loss.backward()
        self.assertTrue(torch.isfinite(vector.grad).all())
        self.assertLessEqual(stats['value_ratio'],.500001)
        self.assertLessEqual(stats['gradient_ratio'],.500001)

    def test_repair_retains_all_training_feasible_fractions_without_validation(self):
        from benchmark_native_feasible import repair_candidates
        _,space,_=self.fixture()
        source=copy.deepcopy(space.seed);source['grid_5x9x9']['coefficients'][0][0][0][0]=0
        candidate=copy.deepcopy(source);candidate['grid_5x9x9']['coefficients'][0][0][0][0]=32
        def score(entry):
            value=entry['grid_5x9x9']['coefficients'][0][0][0][0]
            return dict(failures=['training_guard'] if value>4 else [],value=value)
        repaired,raw=repair_candidates(source,candidate,score)
        self.assertTrue(raw['failures'])
        values=[row[2]['value'] for row in repaired]
        self.assertIn(4,values);self.assertIn(2,values);self.assertIn(1,values)
        self.assertTrue(all(not row[2]['failures'] for row in repaired))

    def test_cli_accepts_selected_arms_before_gpu_preflight(self):
        import sys
        from unittest.mock import patch
        import benchmark_native_feasible as module
        for arms in (['C'], ['D'], ['C', 'D']):
            with self.subTest(arms=arms):
                argv=['benchmark_native_feasible', '--bin', 'unused.BIN',
                      '--manifest', 'unused.json', '--output', 'unused-output',
                      '--arms', *arms]
                with patch.object(sys, 'argv', argv), patch.object(
                        module.torch.backends.mps, 'is_available', return_value=False):
                    with self.assertRaisesRegex(RuntimeError, 'MPS不可用'):
                        module.main()

    def test_cli_accepts_frozen_normalization_before_gpu_preflight(self):
        import sys
        from unittest.mock import patch
        import benchmark_native_feasible as module
        argv=['benchmark_native_feasible', '--bin', 'unused.BIN',
              '--manifest', 'unused.json', '--output', 'unused-output',
              '--arms', 'D', '--normalization', 'frozen-normalization.json']
        with patch.object(sys, 'argv', argv), patch.object(
                module.torch.backends.mps, 'is_available', return_value=False):
            with self.assertRaisesRegex(RuntimeError, 'MPS不可用'):
                module.main()

    def test_frozen_scales_require_identical_start_and_valid_coordinates(self):
        import json
        import tempfile
        from pathlib import Path
        import benchmark_native_feasible as module
        initial=np.arange(1448,dtype=float)
        expected=np.linspace(.1,32768,1448)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'normalization.json'
            value=dict(initial=initial.tolist(),scales=expected.tolist())
            path.write_text(json.dumps(value))
            scales,metadata=module.load_frozen_scales(path,initial)
            np.testing.assert_array_equal(scales,expected)
            self.assertEqual(metadata['sha256'],module.digest(path))
            invalid=[dict(value,initial=(initial+1).tolist()),
                     dict(value,scales=[1.]*1447),dict(value,scales=[0.]*1448),
                     dict(value,scales=[float('nan')]*1448)]
            for index,payload in enumerate(invalid):
                with self.subTest(invalid=index):
                    path.write_text(json.dumps(payload))
                    with self.assertRaises(ValueError):
                        module.load_frozen_scales(path,initial)

    def test_short_trial_keeps_full_training_lr_horizon(self):
        import math
        import benchmark_native_feasible as module
        value=torch.nn.Parameter(torch.tensor([1.]))
        optimizer,scheduler=module.make_optimizer([value],steps=200,lr=.003,min_lr=.00006,schedule_steps=2000)
        for _ in range(200):
            optimizer.zero_grad(set_to_none=True);value.sum().backward()
            optimizer.step();scheduler.step()
        expected=.00006+(.003-.00006)*(1+math.cos(math.pi*200/2000))/2
        self.assertAlmostEqual(scheduler.get_last_lr()[0],expected,places=12)
        self.assertGreater(scheduler.get_last_lr()[0],.0029)
        for kwargs in (dict(lr=0.),dict(lr=float('nan')),dict(min_lr=.01),dict(schedule_steps=199)):
            with self.subTest(kwargs=kwargs):
                with self.assertRaises(ValueError):module.make_optimizer([value],steps=200,**kwargs)

    def test_rejected_update_restores_recipe_and_adam_state(self):
        import tempfile
        from pathlib import Path
        from types import SimpleNamespace
        from calibrated_guard import RampBank
        from benchmark_native_four import combined_metrics
        import benchmark_native_feasible as training
        module,space,inputs=self.fixture('mps');bank=RampBank(.17)
        renderer=module.FlatRenderer(space,np.concatenate((inputs,bank.inputs(space.context.base))),default_response())
        rgb=renderer.exact_entry(space.seed)[0];target=np.clip(rgb[:2]-.01,0,1);gray=np.array([True,False])
        objective=module.BalancedObjective(space,target,gray,bank,rgb,new_loss=True,response=default_response())
        reference=dict(metrics=combined_metrics(rgb[:2],target,rgb[:1],target[:1]))
        seen=[]
        def guard(entry):
            seen.append(training.blob(entry))
            return dict(failures=[] if len(seen)==1 else ['transition_limit'])
        def screen(entry):
            out=renderer.exact_entry(entry)[0][:2]
            metrics=combined_metrics(out,target,out[:1],target[:1])
            return dict(metrics=metrics,failures=[],score=metrics['rgb_rmse']+metrics['delta_e00_mean'])
        with tempfile.TemporaryDirectory() as directory:
            args=SimpleNamespace(output=Path(directory),steps=1,checkpoint=1,seed=42,
                guard_calibration=dict(chart=dict(gray_rmse=100.,delta_e00_p95=100.)),step_guard=guard)
            events=[];args.progress=lambda **row:events.append(row)
            entry,_=training.train('C',space,renderer,objective,space.legacy_scales,screen,reference,{},args)
            self.assertGreater(len(seen),1,'每次更新后必须调用真实过渡检查')
            self.assertEqual(training.blob(entry),training.blob(space.seed))
            state=torch.load(Path(directory)/'C/latest.pt',map_location='cpu',weights_only=True)
            self.assertEqual(state['optimizer']['state'],{},'完全回退后不能保留被拒绝更新的Adam状态')
            self.assertTrue(any(row.get('loss_sample') for row in events),'共享求解器必须输出真实训练Loss')


if __name__=='__main__':unittest.main()
