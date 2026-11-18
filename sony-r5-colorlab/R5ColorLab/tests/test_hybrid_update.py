"""新版默认模型、正式流程与历史资源的可观察契约。"""
import hashlib
import importlib.util
import unittest
import json
import tempfile
from unittest.mock import patch
from pathlib import Path

import numpy as np
import measured_response as measured
from grid_models import default_response

WEB = Path(measured.__file__).parent
HYBRID = dict(schema=measured.SCHEMA, model='ILCE-7RM5',
    preset='r5-paired-20261107-nonlinear-he3',
    sha256='936af0b27f3c5f1ff422c20dd7c1436f92458407d1dd492a4edca2e5ef45e677')


class HybridUpdateTests(unittest.TestCase):
    def test_data_only_grid_progress_reports_actual_stage_and_final_loss(self):
        from continuity_grid import constrain
        base=np.random.default_rng(9).uniform(.1,.8,(12,3))
        events=[]
        _,audit=constrain(np.zeros((405,3),np.int8),base,base+.01,np.ones(len(base)),
            np.eye(3),0,None,progress=lambda **v:events.append(v),evaluations=2,
            device='cpu',training_penalties=False)
        self.assertEqual(events[0]['stage'],'压缩网格真实目标数据微调')
        self.assertEqual(events[-1]['loss_sample'][1],audit['evaluations'])

    def test_parent_logs_are_mirrored_once_as_complete_lines(self):
        import training_profile
        self.assertTrue(callable(getattr(training_profile,'mirror_progress',None)))
        with tempfile.TemporaryDirectory() as directory:
            source=Path(directory)/'parent';source.mkdir()
            output=Path(directory)/'final';output.mkdir()
            path=source/'training_progress.jsonl'
            path.write_bytes(b'{"current":1}\n{"cur')
            positions={}
            training_profile.mirror_progress(source,output,positions)
            self.assertEqual((output/path.name).read_bytes(),b'{"current":1}\n')
            path.write_bytes(path.read_bytes()+b'rent":2}\n')
            training_profile.mirror_progress(source,output,positions)
            training_profile.mirror_progress(source,output,positions)
            self.assertEqual((output/path.name).read_bytes(),path.read_bytes())

    def test_deburr_parent_tamper_is_rejected(self):
        import core
        from grid_distillation import load_result
        from residual_grid import pack
        with tempfile.TemporaryDirectory() as directory:
            job=Path(directory)
            for name in ('pc_compensation.json','fit/recipe.json','pairs.npz'):
                p=job/name;p.parent.mkdir(exist_ok=True);p.write_bytes(b'fixture')
            identity=dict(teacher_sha256=core.sha(b'fixture'),recipe_sha256=core.sha(b'fixture'),
                pairs_sha256=core.sha(b'fixture'),response=HYBRID,
                response_implementation_sha256=core.sha(Path(measured.__file__).read_bytes()),
                response_runtime_sha256=measured.runtime_fingerprint(HYBRID),
                postfit_before_payload_sha256=core.sha(b'original'))
            key=core.sha(json.dumps(identity,sort_keys=True).encode())
            folder=job/'grid_distillation'/key;folder.mkdir(parents=True)
            (folder/'postfit-before.payload').write_bytes(b'tampered')
            (folder/'result.json').write_text(json.dumps(dict(identity=identity,camera_apply_allowed=False,
                fitting=dict(postfit_deburr=dict(original_payload_sha256=core.sha(b'original'))),
                payload_hex=pack(np.zeros((405,3))).hex())))
            with patch.object(core,'target_matches',return_value=True):
                with self.assertRaisesRegex(ValueError,'原表身份'):
                    load_result(job,key)

    def test_formal_gpu_absence_leaves_no_queued_parent(self):
        import server
        with tempfile.TemporaryDirectory() as directory, patch.object(server,'RUNS',Path(directory)), \
             patch.dict(server.JOBS,{},clear=True), patch('gpu_runtime.available',return_value=False):
            identifier='a'*32
            server.JOBS[identifier]=dict(id=identifier,status='queued')
            server.work(identifier,dict(training_profile='upstream-formal/1',short_name='测试'))
            self.assertEqual(server.JOBS[identifier]['status'],'error')
            self.assertIn('Metal/MPS',server.JOBS[identifier]['error'])
            self.assertFalse(any(v['status'] in ('queued','running') for v in server.JOBS.values()))

    def test_retained_runtime_bindings_remain_valid(self):
        path = Path(__file__).parent/'fixtures/response-provenance/pre-hybrid-bindings.json'
        for identity in json.loads(path.read_text()):
            with self.subTest(preset=identity['response']['preset']):
                measured.verify_saved_runtime(identity)

    def test_web_explains_formal_budget(self):
        html = (WEB/'static/index.html').read_text()
        script = (WEB/'static/app.js').read_text()
        self.assertIn('C · 原生四组联合训练', html)
        self.assertNotIn('value="custom"', html)
        self.assertNotIn('upstream-formal/1', script)

    def test_new_default_preserves_gray_axis(self):
        self.assertEqual(default_response(), HYBRID)
        model = measured.get(default_response())
        rgb = np.repeat(np.linspace(0, 1, 257)[:, None], 3, axis=1)
        grid = np.random.default_rng(8).integers(-64, 64, (405, 3))
        np.testing.assert_allclose(model.response(rgb), model.base.response(rgb), atol=0, rtol=0)
        np.testing.assert_array_equal(model.predict_cpu(rgb, np.zeros_like(grid)), rgb)

    def test_retained_model_resources_are_hash_bound(self):
        for identity in (measured.nonlinear_response(), measured.shared_response(), measured.default_response()):
            path = WEB/'data/r5'/(identity['preset'].replace('r5-', '', 1)+'.json')
            with self.subTest(preset=identity['preset']):
                self.assertTrue(path.is_file(), str(path))
                self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(), identity['sha256'])
                measured.get(identity)

    def test_formal_chart_defaults_keep_slot_identity(self):
        self.assertIsNotNone(importlib.util.find_spec('training_profile'))
        from training_profile import bind, PROFILE
        request = dict(target_kind='chart-image', target_id='a'*32, number=24,
            short_name='测试', full_name='正式更新测试', evaluations=7,
            pc_options=dict(response=measured.shared_response()))
        bound = bind(request)
        self.assertEqual(bound['number'], 24)
        self.assertEqual(bound['short_name'], '测试')
        self.assertEqual(bound['target_id'], 'a'*32)
        self.assertEqual(bound['evaluations'], 2000)
        self.assertEqual(bound['pc_options']['response'], HYBRID)
        self.assertEqual(bound['search_options']['starts'], 12)
        self.assertFalse(bound['search_options']['postfit_deburr'])
        self.assertEqual(PROFILE['settings']['rounds'], 3)
        self.assertEqual(bound['training_profile'], 'native-joint/1')
        self.assertEqual(request['evaluations'], 7)


if __name__ == '__main__':
    unittest.main()
