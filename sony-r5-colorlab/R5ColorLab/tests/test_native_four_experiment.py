"""单款实验的精确前向、梯度及保护门禁使用可执行契约。"""
import copy
import importlib.util
import unittest

import numpy as np
import torch

import baseline
import core
from edit_parameter_context import ParameterContext, RuntimeColor
from grid_models import default_response


class ExperimentTests(unittest.TestCase):
    def module(self):
        self.assertIsNotNone(importlib.util.find_spec('native_four_experiment'), '缺少四组离线实验内核')
        return __import__('native_four_experiment')

    def fixture(self, kind='monotone', device='cpu'):
        module=self.module()
        context=ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID)),native_gamma=True)
        entry=copy.deepcopy(core.presets()[0][0])
        entry['cc1_delta'][1:]=[[0]*8,[0]*8]
        entry['block13']=[copy.deepcopy(entry['block13'][0]) for _ in range(3)]
        dtype=torch.float32 if device=='mps' else torch.float64
        space=module.Space(context,entry,kind=kind,device=device,dtype=dtype)
        values=np.array([[1200,1900,600],[8000,6000,4000],[16000,15000,12000]])
        inputs=np.repeat(values[:,None,:],9,axis=1)
        return module,space,inputs

    def test_corrected_forward_equals_complete_integer_bin(self):
        module,space,inputs=self.fixture()
        renderer=module.Renderer(space,inputs,default_response())
        vector=space.tensor(space.initial).requires_grad_(True)
        predicted,audit=renderer.evaluate(vector,corrected=True,dynamic=True)
        expected=renderer.exact_entry(space.entry(vector))[0]
        np.testing.assert_allclose(predicted.detach().numpy(),expected,atol=1e-12,rtol=0)
        predicted.square().sum().backward()
        self.assertTrue(torch.isfinite(vector.grad).all())
        self.assertGreater(float(vector.grad.abs().sum()),0)
        self.assertTrue(audit['exact_corrected'])

    def test_nonflat_photo_patches_require_opt_in_and_preserve_exact_bin_forward(self):
        module,space,inputs=self.fixture(device='mps')
        inputs=inputs.copy();inputs[:,2,0]+=311;inputs[:,6,2]-=127
        with self.assertRaises(ValueError):module.Renderer(space,inputs,default_response())
        renderer=module.Renderer(space,inputs,default_response(),allow_nonflat=True)
        self.assertEqual(tuple(renderer.gpu.x.shape),tuple(inputs.shape))
        for offset in (0.,.3):
            with self.subTest(offset=offset):
                vector=space.tensor(space.initial).detach().clone();vector[8]+=offset;vector.requires_grad_(True)
                predicted,_=renderer.evaluate(vector,corrected=True,dynamic=True)
                expected=renderer.exact_entry(space.entry(vector))[0]
                np.testing.assert_allclose(predicted.detach().cpu().numpy(),expected,atol=1e-7,rtol=0)
                predicted.square().sum().backward()
                self.assertTrue(torch.isfinite(vector.grad).all())
                self.assertGreater(float(vector.grad.abs().sum().cpu()),0)

    def test_gamma_update_rebuilds_dynamic_chroma_cutoff(self):
        module,space,inputs=self.fixture()
        renderer=module.Renderer(space,inputs,default_response())
        vector=space.tensor(space.initial).requires_grad_(True)
        changed=vector.detach().clone();changed[232]*=.85;changed.requires_grad_(True)
        _,before=renderer.evaluate(vector,corrected=True,dynamic=True)
        prediction,after=renderer.evaluate(changed,corrected=True,dynamic=True)
        self.assertNotEqual(before['controls']['high_cutoff'],after['controls']['high_cutoff'])
        self.assertAlmostEqual(after['controls']['high_cutoff'],after['surrogate_high_cutoff'],places=8)
        prediction.sum().backward()
        self.assertTrue(torch.isfinite(changed.grad).all())

    def test_neural_heads_start_from_identical_parameter_vector(self):
        module,space,_=self.fixture()
        scales=np.ones(len(space.initial))
        heads=module.FourHeads(len(space.initial),device='cpu',dtype=torch.float64,seed=42)
        result=heads()
        np.testing.assert_array_equal(result.detach().numpy(),np.zeros(len(space.initial)))
        result.sum().backward()
        self.assertTrue(all(p.grad is None or torch.isfinite(p.grad).all() for p in heads.parameters()))
        self.assertGreater(sum(p.numel() for p in heads.parameters()),len(space.initial))

    def test_bin_projection_keeps_native_ranges(self):
        for kind in ('concave','monotone'):
            with self.subTest(kind=kind):
                module,space,_=self.fixture(kind)
                entry=space.entry(space.tensor(space.initial))
                blob=core.compiler.pack(core.compiler.config([entry],5))
                self.assertEqual(core.compiler.pack(core.compiler.unpack(blob)),blob)
                self.assertEqual(len(entry['gamma_native_129']),129)
                self.assertEqual(entry['gamma_native_129'][0],0)
                self.assertTrue(np.all(np.diff(entry['gamma_native_129'])>=0))

    def test_gate_cannot_trade_gray_or_transition_for_lower_color_loss(self):
        module=self.module()
        before=dict(rgb_rmse=8.,delta_e00_mean=3.,delta_e00_p95=7.,gray_rmse=2.)
        good=dict(rgb_rmse=7.,delta_e00_mean=2.8,delta_e00_p95=6.9,gray_rmse=2.)
        self.assertEqual(module.metric_failures(good,before),[])
        for field in ('gray_rmse','delta_e00_p95'):
            with self.subTest(field=field):
                self.assertIn(field,module.metric_failures(dict(good,**{field:before[field]+.001}),before))
        self.assertTrue(module.metric_failures(dict(good,delta_e00_mean=float('nan')),before))

    def test_transition_gate_retains_zero_regression_on_global_statistics(self):
        module=self.module()
        self.assertTrue(callable(getattr(module,'transition_failures',None)), '缺少双域严格保护')
        before={'native-saturation':np.array([[1.,2.,1.,3.]])}
        after={'native-saturation':np.array([[1.,2.,1.,3.01]])}
        margins={'axes':{'native-saturation':dict(p95=1.,peak=1.,local=1.)}}
        self.assertTrue(module.transition_failures(before,after,margins))
        self.assertFalse(module.transition_failures(before,before,margins))

    def test_mps_forward_and_parameter_decode_match_cpu_bin(self):
        from fit_anchor_native import vector_for
        for kind in ('concave','monotone'):
            with self.subTest(kind=kind):
                module,space,inputs=self.fixture(kind,device='mps')
                vector=space.tensor(space.initial).requires_grad_(True)
                entry=space.entry(vector)
                model=space.context.build(**core.slot_native_parameters(space.context,entry))
                actual=space.decode(vector)['vector'][:104].detach().cpu().numpy()
                expected=vector_for(ParameterContext(model))[:104]
                np.testing.assert_allclose(actual,expected,atol=1e-7,rtol=0)
                renderer=module.Renderer(space,inputs,default_response())
                predicted,_=renderer.evaluate(vector,corrected=True,dynamic=True)
                expected=renderer.exact_entry(entry)[0]
                np.testing.assert_allclose(predicted.detach().cpu().numpy(),expected,atol=1e-7,rtol=0)
                predicted.square().sum().backward()
                self.assertTrue(torch.isfinite(vector.grad).all())

    def test_sensitivity_scales_are_finite_and_bounded(self):
        module,space,inputs=self.fixture()
        renderer=module.Renderer(space,inputs,default_response())
        scales,audit=module.sensitivity_scales(space,renderer,probes=2)
        self.assertEqual(scales.shape,(1448,))
        self.assertTrue(np.isfinite(scales).all())
        self.assertTrue((scales>0).all())
        self.assertLessEqual(float(scales[233:].max()),64.)
        self.assertEqual(audit['probes'],2)

    def test_local_training_penalty_detects_spike_and_run_without_global_increase(self):
        module=self.module()
        reference=torch.tensor([[5.,1.,1.,1.,1.]],dtype=torch.float64)
        candidate=torch.tensor([[4.,1.1,1.1,1.1,1.]],dtype=torch.float64,requires_grad=True)
        peak,cluster=module.local_violations(candidate,reference,.05,.05)
        self.assertGreater(float(peak.detach()),0)
        self.assertGreater(float(cluster.detach()),0)
        (peak+cluster).backward()
        self.assertTrue(torch.isfinite(candidate.grad).all())
        self.assertEqual(float(sum(module.local_violations(reference,reference,.05,.05))),0)

    def test_objective_uses_only_provided_training_rows_and_has_finite_gradient(self):
        from calibrated_guard import RampBank
        module,space,inputs=self.fixture()
        bank=RampBank(.17)
        probes=bank.inputs(space.context.base)
        renderer=module.Renderer(space,np.concatenate((inputs,probes)),default_response())
        reference=renderer.exact_entry(space.seed)[0]
        objective=module.Objective(space,reference[:3],np.array([True,False,False]),
            bank,reference,new_loss=True,response=default_response())
        vector=space.tensor(space.initial).requires_grad_(True)
        prediction,_=renderer.evaluate(vector,corrected=True)
        loss,stats=objective(prediction,space.decode(vector))
        loss.backward()
        self.assertTrue(torch.isfinite(vector.grad).all())
        self.assertEqual(stats['training_samples'],3)
        self.assertGreaterEqual(stats['constraint'],0)


if __name__=='__main__':
    unittest.main()
