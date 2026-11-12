"""正式训练应按实际整数配方筛选，并有明确的旧配方回退。"""
import unittest
from training_profile import bind


class PackedSelectionTests(unittest.TestCase):
    def test_formal_training_enables_packed_candidate_quality_gate(self):
        body=bind(dict(target_kind='chart-image',number=24))
        self.assertEqual(body.get('packed_selection_policy'),'native-packed-quality/1')


class QualityChoiceTests(unittest.TestCase):
    def policy(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('packed_training'),'缺少最终整数配方筛选器')
        return __import__('packed_training')

    def test_better_weighted_loss_cannot_hide_worse_rgb(self):
        policy=self.policy()
        baseline=dict(label='old',metrics=dict(rgb_rmse=5.,delta_e00_mean=2.,delta_e00_p95=4.,gray_rmse=1.,weighted_loss=50.))
        proposal=dict(label='new',metrics=dict(rgb_rmse=6.,delta_e00_mean=1.,delta_e00_p95=3.,gray_rmse=.9,weighted_loss=40.),failures=[])
        self.assertEqual(policy.quality_choice(baseline,[proposal])['label'],'old')

    def test_transition_failure_keeps_baseline_despite_better_colors(self):
        policy=self.policy()
        old=dict(label='old',metrics=dict(rgb_rmse=5.,delta_e00_mean=2.,delta_e00_p95=4.,gray_rmse=1.,weighted_loss=50.))
        new=dict(label='new',metrics=dict(rgb_rmse=4.,delta_e00_mean=1.,delta_e00_p95=3.,gray_rmse=.9,weighted_loss=20.),failures=['ramp:native-saturation:peak'])
        self.assertIs(policy.quality_choice(old,[new]),old)

    def test_missing_protected_metrics_fail_closed(self):
        policy=self.policy()
        old=dict(label='old',metrics=dict(rgb_rmse=5.,delta_e00_mean=2.,delta_e00_p95=4.,gray_rmse=1.,weighted_loss=50.))
        good=dict(rgb_rmse=4.,delta_e00_mean=1.,delta_e00_p95=3.,gray_rmse=.9,weighted_loss=20.)
        for field in good:
            with self.subTest(field=field):
                newer=dict(good);newer[field]=float('nan')
                self.assertIs(policy.quality_choice(old,[dict(label='bad',metrics=newer,failures=[])]),old)
        self.assertIs(policy.quality_choice(old,[dict(label='missing',metrics=good)]),old)

    def test_qualified_candidate_is_selected_without_mutating_baseline(self):
        import copy
        policy=self.policy()
        old=dict(label='old',metrics=dict(rgb_rmse=5.,delta_e00_mean=2.,delta_e00_p95=4.,gray_rmse=1.,weighted_loss=50.))
        before=copy.deepcopy(old)
        good=dict(label='good',metrics=dict(rgb_rmse=4.,delta_e00_mean=1.,delta_e00_p95=3.,gray_rmse=.9,weighted_loss=20.),failures=[])
        self.assertIs(policy.quality_choice(old,[good]),good)
        self.assertEqual(old,before)

class WorkflowTests(unittest.TestCase):
    def test_packed_selection_precedes_stack_and_final_gate_follows_it(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        import training_profile as tp
        import server
        order=[];seed={'number':24}
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);identifier='b'*32
            def native(key,body,**kwargs):
                order.append('native');server.JOBS[key].update(status='done',continuation={'done':True})
            def prepare(*args,**kwargs):order.append('prepare');return seed,None,None,[]
            def train(job,source,state,*args,**kwargs):order.append('train');self.assertEqual(kwargs.get('seed_entry'),seed);state.update(status='done',result={})
            def finalize(*args):order.append('finalize');return dict(adopted=False)
            options=tp.bind(dict(target_kind='chart-image',number=24,short_name='测试',full_name='测试滤镜'))
            with patch.object(server,'RUNS',root),patch.dict(server.JOBS,{},clear=True),patch('gpu_runtime.available',return_value=True),patch('packed_training.prepare',side_effect=prepare),patch('packed_training.finalize',side_effect=finalize),patch.object(tp,'train',side_effect=train),patch.object(tp,'completed',return_value=True):
                server.reserve_job(identifier,options)
                tp.work(server,native,identifier,options)
                self.assertEqual(server.JOBS[identifier]['status'],'done')
        self.assertEqual(order,['native','prepare','train','finalize'])

    def test_reserving_job_freezes_saved_slot_for_retry(self):
        import tempfile,json,copy
        from pathlib import Path
        from unittest.mock import patch
        import projects,core,server
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=projects.Store(root);project=projects.empty('保底测试')
            entry=copy.deepcopy(core.presets()[0][0]);entry['number']=24
            project['entries']=[copy.deepcopy(entry)];project['format']=5;store.write(project)
            body=bind(dict(target_kind='chart-image',number=24,short_name='测试',full_name='测试滤镜',project_id=project['id']))
            with patch.object(server,'RUNS',root),patch.dict(server.JOBS,{},clear=True):
                server.reserve_job('c'*32,body)
                saved=json.loads((root/('c'*32)/'request.json').read_text())
                self.assertEqual(saved.get('packed_baseline',{}).get('entry'),entry)
                project['entries'][0]['short_name']='已修改';store.write(project)
                from packed_training import bind_context
                bind_context(saved,root)
                self.assertEqual(saved['packed_baseline']['entry'],entry)

class ArtifactTests(unittest.TestCase):
    def test_mutated_quality_receipt_is_rejected_by_preview_and_export_loader(self):
        import tempfile,json,copy
        from pathlib import Path
        from unittest.mock import patch
        import core
        from residual_grid import pack
        import numpy as np
        from grid_distillation import load_result
        with tempfile.TemporaryDirectory() as tmp:
            job=Path(tmp)
            for name in ('pc_compensation.json','fit/recipe.json','pairs.npz'):
                p=job/name;p.parent.mkdir(exist_ok=True);p.write_bytes(b'fixture')
            quality=dict(policy='native-packed-quality/1',adopted=False)
            identity=dict(teacher_sha256=core.sha(b'fixture'),recipe_sha256=core.sha(b'fixture'),pairs_sha256=core.sha(b'fixture'),response=np.eye(3).tolist(),quality_policy='native-packed-quality/1',quality_audit_sha256=core.sha(json.dumps(quality,sort_keys=True).encode()))
            key=core.sha(json.dumps(identity,sort_keys=True).encode());folder=job/'grid_distillation'/key;folder.mkdir(parents=True)
            changed=dict(quality,adopted=True)
            report=dict(identity=identity,camera_apply_allowed=False,fitting=dict(quality_selection=changed),payload_hex=pack(np.zeros((405,3))).hex())
            (folder/'result.json').write_text(json.dumps(report))
            with patch.object(core,'target_matches',return_value=True):
                with self.assertRaisesRegex(ValueError,'品质验收'):
                    load_result(job,key)

class BatchBaselineTests(unittest.TestCase):
    def test_batch_enqueue_freezes_each_saved_slot_before_worker_runs(self):
        import tempfile,copy,json
        from pathlib import Path
        from unittest.mock import patch
        import core,projects,server,batch_training
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);store=projects.Store(root);project=projects.empty('批量保底')
            entry=copy.deepcopy(core.presets()[0][0]);entry['number']=24
            project['entries']=[entry];project['format']=5;store.write(project)
            options=bind(dict(target_kind='chart-image',number=24,project_id=project['id']))
            item=dict(id='d'*32,name='测试',filename='测试.tif',options=options)
            with patch.object(server,'RUNS',root),patch.dict(server.JOBS,{},clear=True),patch.object(server.POOL,'submit'),patch('batch_training.directory',return_value=root/'batches'):
                result=batch_training.enqueue([item],1,server)
                state=json.loads((root/'batches'/result['id']/'batch.json').read_text())
                self.assertEqual(state['jobs'][0]['options'].get('packed_baseline',{}).get('entry'),entry)

class GateIsolationTests(unittest.TestCase):
    def test_screen_does_not_read_test_targets(self):
        import tempfile,json
        from pathlib import Path
        import numpy as np
        import core,baseline
        from packed_training import QualityGate
        from grid_models import default_response
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            (root/'input_audit.json').write_text(json.dumps(dict(dataset_id=baseline.V45_ID)))
            inputs=np.full((6,9,3),6000,np.uint16)
            target=np.full((6,3),.4*16383);target[-2:]=np.nan
            np.savez(root/'pairs.npz',input=inputs,split=np.array(['train','train','valid','valid','test','test']),anchor_index=np.array([4,5,-1,-1,-1,-1]),**{'0_target':target})
            entry=core.presets()[0][0]
            gate=QualityGate(root,entry,default_response())
            screen=gate.assess(entry,'baseline')
            self.assertEqual(screen['failures'],[])
            self.assertEqual(screen['split'],'valid')
            self.assertEqual(screen['ramp_phase'],.53)
            self.assertFalse(screen['photos_verified'])
            self.assertEqual(gate.margins['delta_e00_p95'],0)
            with self.assertRaisesRegex(ValueError,'有限'):
                gate.assess(entry,'baseline',final=True)

    def test_failed_independent_verification_falls_back_without_trying_runner_up(self):
        import tempfile,copy
        from pathlib import Path
        from types import SimpleNamespace
        from unittest.mock import patch
        import core
        from packed_training import finalize,canonical
        old=copy.deepcopy(core.presets()[0][0]);new=dict(old,short_name='候选')
        b=dict(rgb_rmse=5.,delta_e00_mean=2.,delta_e00_p95=4.,gray_rmse=1.,weighted_loss=50.)
        m=dict(rgb_rmse=4.,delta_e00_mean=1.,delta_e00_p95=3.,gray_rmse=.9,weighted_loss=20.)
        reference=dict(label='old',entry=old,sha256=canonical(old)[1],metrics=b,failures=[])
        first=dict(label='qualified',entry=new,sha256=canonical(new)[1],metrics=m,failures=[])
        seen=[]
        def assess(entry,label,**kwargs):
            seen.append((label,kwargs.get('final',False)))
            return dict(first,failures=['ramp:native-saturation:peak']) if kwargs.get('final') else dict(reference,label='stack-proposal',failures=['rgb_rmse'])
        gate=SimpleNamespace(assess=assess,margins={},photos=[],response=SimpleNamespace(identity={}))
        with tempfile.TemporaryDirectory() as tmp,patch('packed_training.attach_result') as publish:
            job=Path(tmp);(job/'R5NATIVE.BIN').write_bytes(core.compiler.pack(core.config([new])))
            quality=finalize(job,{},gate,reference,[first])
            self.assertFalse(quality['adopted']);self.assertEqual(quality['accepted'],'old')
            self.assertEqual(seen,[('stack-proposal',False),('qualified',True)])
            self.assertEqual(publish.call_args.args[2],old)


class CandidateArchiveTests(unittest.TestCase):
    def test_roundtrip_keeps_parameters_and_selects_diverse_native_gray_seed(self):
        import tempfile
        from pathlib import Path
        import numpy as np
        from native_candidates import append,shortlist
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'pool.json'
            for i in range(7):
                params=dict(matrix_payload=b'color',cc1=np.full(8,i),gamma_y=np.arange(128))
                append(p,params,np.full(232,i),str(i),i,10-i,'a'*64)
            values=shortlist(p,limit=4,expected_pairs_sha256='a'*64)
            self.assertEqual(len(values),4)
            self.assertEqual({values[0]['label'],values[1]['label']},{'0','6'})
            self.assertEqual(values[0]['parameters']['gamma_7806_y'],list(range(128)))
            with self.assertRaisesRegex(ValueError,'身份'):
                shortlist(p,expected_pairs_sha256='b'*64)


class CustomBudgetTests(unittest.TestCase):
    def test_custom_budget_does_not_inherit_formal_only_policy(self):
        body=bind(dict(target_kind='chart-image',training_profile='custom',number=24,
                       packed_selection_policy='native-packed-quality/1',packed_baseline={'old':'data'},quality_set='a'*64))
        self.assertNotIn('packed_selection_policy',body)
        self.assertNotIn('packed_baseline',body)
        self.assertNotIn('quality_set',body)


if __name__=='__main__':unittest.main()
