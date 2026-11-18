"""完整 BIN 曲线必须独立影响原生前向，不能被 RAW 的 128 点投影吞掉。"""
import copy
import unittest

import numpy as np

import baseline
import core
from edit_parameter_context import ParameterContext, RuntimeColor


class NativeGamma129Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.factory = RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID))
        cls.context = ParameterContext(cls.factory)

    def test_bin_terminal_node_changes_highlight_prediction(self):
        entry = copy.deepcopy(core.presets()[0][0])
        entry['gamma_native_129'] = np.rint(np.linspace(0, 100000, 129)).astype(int).tolist()
        entry['gamma_native_129'][-1] = 120000
        changed = copy.deepcopy(entry)
        changed['gamma_native_129'][-1] = 131071
        models = [self.context.build(**core.slot_native_parameters(self.context, value))
                  for value in (entry, changed)]
        inputs = np.repeat(np.array([14336, 15360, 15872, 16383])[:, None], 3, axis=1)
        before, after = [model.main_gamma(inputs) for model in models]
        np.testing.assert_array_equal(before[:2], after[:2])
        self.assertTrue(np.all(after[2:] > before[2:]), 'BIN 最后一节点未参与高光前向')

    def test_training_gpu_keeps_all_native_nodes(self):
        import torch
        from fit_anchor_native import SmoothNative, vector_for
        from apple_gpu import SmoothGPU
        context = ParameterContext(self.factory, native_gamma=True)
        inputs = np.repeat(np.array([14337, 15001, 15873, 16380])[:, None, None], 27, axis=1).reshape(4, 9, 3)
        smooth = SmoothNative(context, inputs)
        vector = vector_for(context)
        self.assertEqual(len(smooth.gamma(vector)), 129)
        for device, dtype in [('cpu', torch.float64), ('mps', torch.float32)]:
            with self.subTest(device=device):
                gpu = SmoothGPU(smooth, device=device, dtype=dtype)
                v = gpu.tensor(vector).requires_grad_(True)
                predicted = gpu.render(v)
                np.testing.assert_allclose(predicted.detach().cpu().numpy(), smooth.render(vector), atol=.04, rtol=1e-5)
                predicted.sum().backward()
                self.assertTrue(torch.isfinite(v.grad).all())
                self.assertGreater(float(v.grad[-1].abs().cpu()), 0.)

    def test_projected_bin_keeps_the_two_independent_tail_nodes(self):
        from fit_bin_joint import projected
        from native_gamma import parameter_fields, parameter_values
        entry = copy.deepcopy(core.presets()[0][0])
        parameters = core.slot_native_parameters(self.context, entry)
        parameters['gamma_y'] = np.rint(np.linspace(0, 220000, 129)/2).astype(int)*2
        fields = parameter_fields(parameters)
        restored = parameter_values(fields)
        candidate = projected(entry, restored)
        self.assertEqual(len(candidate['gamma_native_129']), 129)
        np.testing.assert_array_equal(candidate['gamma_native_129'], parameters['gamma_y']//2)

    def test_stack_decoder_has_the_same_complete_gamma_as_preview(self):
        from stack_training import decode_model
        entry = copy.deepcopy(core.presets()[0][0])
        entry['gamma_native_129'] = np.rint(np.linspace(0, 100000, 129)).astype(int).tolist()
        entry['gamma_native_129'][-1] = 131071
        actual = decode_model(entry, self.factory)
        expected = self.context.build(**core.slot_native_parameters(self.context, entry))
        np.testing.assert_array_equal(np.frombuffer(actual.runtime, '<u2', count=65536, offset=0x18f6),
                                      np.frombuffer(expected.runtime, '<u2', count=65536, offset=0x18f6))

    def test_gamma_diagnostic_includes_the_missing_physical_node(self):
        from gamma_diagnostics import compare
        entry = copy.deepcopy(core.presets()[0][0])
        model = self.context.build(**core.slot_native_parameters(self.context, entry))
        report = compare(self.factory, model)
        self.assertEqual(report['encoding']['stored_points'], 129)
        self.assertEqual(report['parameter_knots']['input_14bit'][127], 15360.)

    def test_independent_tail_cannot_be_silently_exported_as_raw128(self):
        from native_gamma import raw_projection
        q = np.rint(np.linspace(0, 110000, 129)).astype(int)
        q[-1] = 131071
        with self.assertRaisesRegex(ValueError, '不能无损'):
            raw_projection(q, require_exact=True)

    def test_mps_integer_gamma_table_matches_the_cpu_reference(self):
        from native_gamma import EDIT_AXIS, tensor_table
        from edit_native_model import expand_gamma
        curves = [np.rint(np.linspace(0, 100000, 129)).astype(int),
                  np.minimum(131071, np.rint(np.sqrt(np.linspace(0, 1, 129))*131071)).astype(int)]
        for q in curves:
            q[-1] = 131071
            for contrast in (None, self.context.contrast):
                with self.subTest(contrast=contrast is not None):
                    actual = tensor_table(q, contrast=contrast, device='mps').cpu().numpy()
                    expected = expand_gamma(EDIT_AXIS, 2*q, contrast)
                    np.testing.assert_array_equal(actual, expected)


if __name__ == '__main__':
    unittest.main()
