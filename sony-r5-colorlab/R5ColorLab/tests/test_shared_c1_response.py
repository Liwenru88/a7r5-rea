"""Published no-expert model matches calibration inference and tensor rendering."""
import hashlib
import importlib.util
from pathlib import Path
import sys
import unittest
import numpy as np
import measured_response as measured
from grid_models import default_response


class SharedC1Tests(unittest.TestCase):
    def test_default_and_calibrator_inference(self):
        identity = default_response()
        self.assertEqual(identity, measured.shared_response())
        model = measured.get(identity)
        self.assertTrue(model.shared_c1)
        self.assertFalse(model.hue_experts)
        path = Path(measured.__file__).parent/'data/r5/paired-20261102-shared-c1-c50.json'
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), identity['sha256'])
        calibrator = Path(__file__).resolve().parents[2]/'R5GridCalibrator'
        spec = importlib.util.spec_from_file_location('shared_calibration_oracle', calibrator/'model.py')
        reference = importlib.util.module_from_spec(spec)
        sys.path.insert(0, str(calibrator))
        try:
            spec.loader.exec_module(reference)
            options = reference.optimization_options()
            self.assertFalse(options['hue_experts'])
            self.assertTrue(options['structured_response'])
            self.assertEqual(options['curvature_scale'], .5)
            rng = np.random.default_rng(743)
            rgb = np.r_[rng.random((1024, 3)), np.zeros((1, 3)), np.ones((1, 3)),
                        np.repeat(np.linspace(0, 1, 257)[:, None], 3, axis=1)]
            grid = rng.integers(-64, 64, (405, 3))
            np.testing.assert_allclose(model.predict_cpu(rgb, grid),
                reference.predict(rgb, grid, model.value), atol=1e-12, rtol=0)
            np.testing.assert_array_equal(model.predict_cpu(rgb, np.zeros_like(grid)), rgb)
        finally:
            sys.path.remove(str(calibrator))

    def test_tensor_prediction_and_gradient(self):
        try:
            import torch
        except ImportError:
            self.skipTest('optional torch dependency unavailable')
        from gpu_tensor import TensorTools
        from gpu_color import paired_tensor
        identity = default_response()
        model = measured.get(identity)
        rng = np.random.default_rng(45)
        rgb = rng.uniform(.05, .95, (512, 3))
        grid = rng.integers(-32, 32, (405, 3))
        tools = TensorTools(device='cpu')
        tensor = tools.tensor(rgb).requires_grad_(True)
        result = paired_tensor(tools, tensor, tools.tensor(grid), identity)
        np.testing.assert_allclose(result.detach().numpy(), model.predict_cpu(rgb, grid),
                                   atol=2e-6, rtol=0)
        result.square().mean().backward()
        self.assertTrue(torch.isfinite(tensor.grad).all())
