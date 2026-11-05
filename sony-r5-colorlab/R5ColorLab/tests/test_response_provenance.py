"""Provenance gates plus preserved pre-expert inference, never retrains a job."""
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / 'scripts'))
import numpy as np
import measured_response as mr

WEB = Path(mr.__file__).resolve().parent

def preserved_source(workspace_name, fixture_name):
    original = ROOT / workspace_name
    return original if original.is_file() else HERE / 'fixtures/response-provenance' / fixture_name


class ResponseProvenanceTests(unittest.TestCase):
    def test_preserved_registry_sources(self):
        sources = [
            ('analysis/fuj_v45_nonlinear_formal_20261102/before/measured_response.py', 'old-registry-v2.py',
             'ac25d665dde7fc285affb4be1a862a647c767e339cea0aa4b756e77693199428'),
            ('analysis/fuj_v45_three_expert_formal_20261102/before/measured_response.py', 'old-registry-nonlinear.py',
             '2ee8128f87491ac15e1885e32594620aa04c92aa7a4acd8bf15977fa5ce27ac5'),
        ]
        for name, fixture_name, digest in sources:
            with self.subTest(source=name):
                self.assertEqual(hashlib.sha256(preserved_source(name, fixture_name).read_bytes()).hexdigest(), digest)

    def test_all_old_models_preserve_original_class_outputs(self):
        path = preserved_source('analysis/fuj_v45_three_expert_formal_20261102/before/paired_response.py', 'old-paired.py')
        # This original class supports all three retained old R5 identities.
        self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),
                         'c5d74177d5466149e7d7cb86214d4ca3e152d6e9ba7ad87a3227fb45bdba5940')
        spec = importlib.util.spec_from_file_location('preserved_paired_oracle', path)
        original = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(original)
        rng = np.random.default_rng(20261102)
        rgb = np.r_[rng.random((4096, 3)),
                    np.repeat(np.linspace(0, 1, 257)[:, None], 3, axis=1),
                    np.array(list(__import__('itertools').product([0., .5, 1.], repeat=3)))]
        tables = [np.zeros((405, 3), np.int8), np.full((405, 3), -64, np.int8),
                  np.full((405, 3), 63, np.int8)]
        tables += [rng.integers(-64, 64, (405, 3), dtype=np.int8) for _ in range(4)]
        for identity in (mr.previous_r5_response(), mr.v2_response(), mr.nonlinear_response()):
            with self.subTest(preset=identity['preset']):
                model = mr.get(identity)
                oracle = original.PairedModel(model.value, model.sha256, identity=identity)
                np.testing.assert_array_equal(model.coordinates(rgb), oracle.coordinates(rgb))
                np.testing.assert_array_equal(model.response(rgb), oracle.response(rgb))
                for table in tables:
                    for clip in (False, True):
                        np.testing.assert_array_equal(model.predict_cpu(rgb, table, clip),
                                                      oracle.predict_cpu(rgb, table, clip))

    def test_verified_legacy_fingerprint_is_current(self):
        sources = mr.inference_sources(mr.nonlinear_response())
        digest = hashlib.sha256(json.dumps(sources, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
        self.assertEqual(digest, mr._LEGACY_VERIFIED_INFERENCE_SHA256)

    def test_known_old_binding_accepted_and_unknown_rejected(self):
        for response in (mr.v2_response(), mr.nonlinear_response()):
            known = next(iter(mr._LEGACY_RESPONSE_IMPLEMENTATIONS[response['preset']]))
            identity = dict(response=response, response_implementation_sha256=known)
            mr.verify_saved_runtime(identity)
            with self.assertRaises(ValueError):
                mr.verify_saved_runtime(dict(identity, response_implementation_sha256='0' * 64))
            sources = mr.inference_sources(response)
            sources['paired_response.py'] = '0' * 64
            with patch.object(mr, 'inference_sources', return_value=sources):
                with self.assertRaises(ValueError):
                    mr.verify_saved_runtime(identity)

    def test_new_binding_requires_both_registry_and_actual_runtime(self):
        response = mr.default_response()
        identity = dict(response=response,
            response_implementation_sha256=hashlib.sha256(Path(mr.__file__).read_bytes()).hexdigest(),
            response_runtime_sha256=mr.runtime_fingerprint(response))
        mr.verify_saved_runtime(identity)
        for field in ('response_implementation_sha256', 'response_runtime_sha256'):
            with self.subTest(field=field), self.assertRaises(ValueError):
                mr.verify_saved_runtime(dict(identity, **{field: '0' * 64}))
        sources = mr.inference_sources(response)
        sources['paired_coordinates.py'] = '0' * 64
        with patch.object(mr, 'inference_sources', return_value=sources):
            with self.assertRaises(ValueError):
                mr.verify_saved_runtime(identity)
        wrong_response = dict(response, sha256='0' * 64)
        with self.assertRaises(ValueError):
            mr.runtime_fingerprint(wrong_response)

    def test_training_method_change_does_not_change_inference_fingerprint(self):
        import ast
        actual = WEB / 'paired_response.py'
        before = mr._inference_ast(actual, ('PairedModel.response', 'PairedModel.predict_cpu'))
        source = actual.read_text()
        # Reading an alternate source is enough: no workspace file is changed.
        class Alternate:
            def read_text(self):
                return source.replace('def fit(self,base,target,weights,strength=.01):',
                                      'def fit(self,base,target,weights,strength=.02):')
        after = mr._inference_ast(Alternate(), ('PairedModel.response', 'PairedModel.predict_cpu'))
        self.assertEqual(before, after)
        class Changed:
            def read_text(self):
                return source.replace('return r/256', 'return r/255')
        self.assertNotEqual(before, mr._inference_ast(Changed(), ('PairedModel.response', 'PairedModel.predict_cpu')))


if __name__ == '__main__':
    unittest.main()
