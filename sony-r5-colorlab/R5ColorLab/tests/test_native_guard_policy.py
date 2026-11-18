"""新保护规则区分数值误差、真实目标变化和待复核异常。"""
import unittest
import numpy as np

from calibrated_guard import RampBank,phase_rgb
from native_scoring import color_metrics


class GuardPolicyTests(unittest.TestCase):
    def test_quantization_envelope_covers_unseen_rounding_phases(self):
        from native_guard_policy import quality_envelope
        rng=np.random.default_rng(91)
        source=rng.uniform(0,1,(120,3));target=rng.uniform(0,1,(120,3))
        envelope=quality_envelope(source,target)
        for phase in rng.uniform(-.499,.499,(20,3)):
            actual=color_metrics(phase_rgb(source,phase),target)
            for name in ('rgb_rmse','delta_e00_mean','delta_e00_p95'):
                self.assertLessEqual(actual[name],envelope['upper'][name]+1e-9)

    def test_color_gate_uses_calibrated_tolerance_and_still_rejects_nan(self):
        from native_guard_policy import quality_failures
        base=dict(rgb_rmse=6.,delta_e00_mean=3.,delta_e00_p95=7.,gray_rmse=2.)
        candidate=dict(base,rgb_rmse=5.,delta_e00_mean=2.5,gray_rmse=2.08,delta_e00_p95=7.12)
        margins=dict(gray_rmse=.1,delta_e00_p95=.2)
        self.assertEqual(quality_failures(candidate,base,margins),[])
        self.assertIn('gray_rmse',quality_failures(dict(candidate,gray_rmse=2.11),base,margins))
        self.assertTrue(quality_failures(dict(candidate,delta_e00_p95=float('nan')),base,margins))

    def test_target_turn_is_rewarded_instead_of_old_curve_shape(self):
        from native_guard_policy import TargetToneBank
        import torch
        from gpu_tensor import TensorTools
        colors=[]
        import colorsys
        for hue in np.arange(24)/24:
            colors.extend(colorsys.hsv_to_rgb(hue,.82,float(v)) for v in np.linspace(.01,1,17))
        design=np.asarray(colors);target=design**.6;original=design.copy()
        bank=TargetToneBank(design,target,np.full(len(design),'train'),np.full(len(design),'hue24_tonal'),original)
        tools=TensorTools('cpu',torch.float64)
        perfect=tools.tensor(target).requires_grad_(True)
        self.assertLess(float(bank.tensor_loss(tools,perfect).detach()),1e-12)
        self.assertGreater(float(bank.tensor_loss(tools,tools.tensor(original))),0)
        bank.tensor_loss(tools,perfect).backward()
        self.assertTrue(torch.isfinite(perfect.grad).all())

    def test_unconfirmed_transition_issue_requests_review_not_automatic_pass(self):
        from native_guard_policy import decision
        self.assertEqual(decision([],['native-saturation']), 'review_required')
        self.assertEqual(decision(['gamma_not_monotone'],[]),'rejected')
        self.assertEqual(decision([],[]),'eligible_offline')

    def test_multiscale_intervals_cover_all_valid_quantized_ramps(self):
        from native_guard_policy import multiscale_report
        bank=RampBank(.53);base=np.clip(bank.rgb**.6,0,1)
        result=multiscale_report(bank,base,base)
        for axis,scales in result['axes'].items():
            for row in scales.values():
                self.assertLessEqual(row['baseline_quantized']['max'],row['quantization_upper']['max']+1e-8)
        self.assertFalse(result['exceedances'])

    def test_scene_tiles_cannot_hide_a_local_tail_inside_better_whole_photo(self):
        from native_guard_policy import photo_failures
        target=np.full((81,3),.4);reference=target+[.1,0,0]
        candidate=target.copy();candidate[0,0]+=.35
        limits={name:dict.fromkeys(('rgb_rmse','delta_e00_mean','delta_e00_p95'),0.) for name in ('whole','tile')}
        failures,regions=photo_failures(reference,candidate,target,np.arange(81).reshape(9,9),limits)
        self.assertLess(regions['whole']['candidate']['rgb_rmse'],regions['whole']['baseline']['rgb_rmse'])
        self.assertLess(regions['whole']['candidate']['delta_e00_p95'],regions['whole']['baseline']['delta_e00_p95'])
        self.assertTrue(any(reason.startswith('tile-0-0:') for reason in failures))

    def test_invalid_gamma_and_crc_remain_hard_failures(self):
        import struct,zlib,core
        from native_guard_policy import legality_failures,decision
        entry=core.presets()[0][0];data=core.compiler.pack(core.compiler.config([entry],5))
        self.assertFalse(legality_failures(data))
        for gamma in (False,True):
            with self.subTest(gamma=gamma):
                modified=bytearray(data)
                if gamma:
                    struct.pack_into('<I',modified,128+716,1)
                    modified[112:116]=b'\0'*4;struct.pack_into('<I',modified,112,zlib.crc32(modified))
                else:modified[-1]^=1
                self.assertEqual(decision(legality_failures(bytes(modified)),[]),'rejected')

    def test_real_target_gradient_gpu_path_is_finite_and_has_no_old_shape_penalty(self):
        import torch,colorsys,core,baseline
        from edit_parameter_context import ParameterContext,RuntimeColor
        from grid_models import default_response
        from native_feasible_experiment import OriginalSpace,FlatRenderer
        from native_guard_policy import TargetToneBank,build_calibration,ReviewedObjective
        design=np.array([colorsys.hsv_to_rgb(h,.82,float(v)) for h in np.arange(24)/24 for v in np.linspace(.01,1,17)])
        target=design**.85;inputs=np.repeat(np.rint(design*15000).astype('uint16')[:,None],9,axis=1)
        context=ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID)),native_gamma=True)
        import copy
        entry=copy.deepcopy(core.presets()[0][0]);entry['cc1_delta'][1:]=[[0]*8,[0]*8]
        entry['block13']=[copy.deepcopy(entry['block13'][0]) for _ in range(3)]
        space=OriginalSpace(context,entry,device='mps');bank=RampBank(.17)
        renderer=FlatRenderer(space,np.concatenate((inputs,bank.inputs(context.base))),default_response())
        ref=renderer.exact_entry(entry)[0];gray=np.arange(len(design))<17
        calibration=build_calibration(ref[:len(design)],target,gray,
            [('development',ref[:len(design)],target,np.arange(len(design)).reshape(24,17))])
        tones=TargetToneBank(design,target,np.full(len(design),'train'),np.full(len(design),'hue24_tonal'),ref[:len(design)])
        objective=ReviewedObjective(space,target,gray,bank,ref,new_loss=True,response=default_response(),calibration=calibration,tone_bank=tones)
        vector=space.tensor(space.initial).requires_grad_(True);pred,_=renderer.evaluate(vector)
        loss,stats=objective.balanced(pred,space.decode(vector),vector,space.tensor(space.legacy_scales))
        loss.backward();self.assertTrue(torch.isfinite(vector.grad).all())
        self.assertGreater(stats['target_gradient_loss'],0)
        self.assertFalse(stats['synthetic_transition_penalty_enabled'])
        self.assertEqual(stats['raw_penalty'],0.)

    def test_dense_evidence_preserves_original_probe_input_points(self):
        import baseline
        from edit_parameter_context import RuntimeColor
        from native_guard_policy import dense_probe_inputs
        from integer_grid import PROBE_AXES
        model=RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID))
        bank=RampBank(.53);original=bank.inputs(model)
        for axis in PROBE_AXES:
            with self.subTest(axis=axis):
                span,shape=bank.span(axis)
                _,dense=dense_probe_inputs(bank,axis,0,model,factor=2)
                expected=original[span].reshape(*shape,9,3)[0]
                np.testing.assert_array_equal(dense[::2],expected)


if __name__=='__main__':unittest.main()
