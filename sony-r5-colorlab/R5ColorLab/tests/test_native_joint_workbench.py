"""新标准profile与唯一终检回退，不依赖真实长训练。"""
import copy,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
import core
import training_profile as tp


class WorkbenchTests(unittest.TestCase):
    def test_cancel_joint_stage_without_subprocess_preserves_stop_request(self):
        from native_joint_workbench import request_cancel,check_cancel
        job={}
        request_cancel(job,{})
        self.assertTrue(job['cancel_requested'])
        with self.assertRaisesRegex(RuntimeError,'取消'):check_cancel(job)

    def test_adapter_keeps_job_running_until_joint_publication(self):
        self.check_publication(False)

    def test_cancel_during_final_acceptance_prevents_publication(self):
        self.check_publication(True)

    def check_publication(self,late_cancel):
        import json,numpy as np
        import server,baseline
        from native_joint_workbench import work
        from native_solver import blob
        old=copy.deepcopy(core.presets()[0][0]);old['number']=24
        new=copy.deepcopy(old);new['gamma_native_129'][1]+=1
        config=core.compiler.config([old],5);published=core.compiler.config([new],5);events=[]
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);identifier='f'*32;(root/identifier).mkdir()
            options=tp.bind(dict(training_profile='native-joint/1',target_kind='chart-image',number=24))
            def native(baseid,body,**kwargs):
                events.append('baseline');server.JOBS[baseid].update(status='done',result={})
                (root/baseid/'grid_training.json').write_text(json.dumps(dict(key='base')))
            def artifact(job,source,state,callback,settings,**kwargs):
                self.assertEqual(settings['rounds'],0)
                self.assertEqual(server.JOBS[identifier]['status'],'running')
                events.append('artifact')
                np.savez(job/'pairs.npz',input=np.full((6,9,3),6000,np.uint16),split=np.array(['train','train','train','valid','test','test']),
                    anchor_index=np.array([4,5,-1,-1,-1,-1]),design_srgb=np.zeros((6,3)),sample_kind=np.full(6,'random'),**{'0_target':np.full((6,3),6000)})
                (job/'input_audit.json').write_text(json.dumps(dict(dataset_id=baseline.V45_ID)))
                state.update(status='done',result=dict(grid_key='artifact'))
            def joint(data,reference,folder,**kwargs):
                self.assertEqual(server.JOBS[identifier]['status'],'running')
                events.append('joint')
                row=dict(entry=new,sha256=core.sha(blob(new)),label='C/200',metrics={'weighted_loss':1.},fully_evaluated=True,failures=[])
                def assess(*a,**k):
                    if late_cancel:server.JOBS[identifier]['cancel_requested']=True
                    return dict(failures=[])
                gate=SimpleNamespace(baseline=dict(row,entry=old,sha256=core.sha(blob(old))),data=data,assess=assess)
                return new,dict(selected=row),gate
            def publish(job,state,chosen,quality):
                events.append('publish');self.assertEqual(server.JOBS[identifier]['status'],'running')
                state['result'].update(grid_key='published',config=published)
            with patch.object(server,'RUNS',root),patch.dict(server.JOBS,{identifier:dict(id=identifier,status='queued')},clear=True), \
                 patch('gpu_runtime.available',return_value=True),patch.object(tp,'train',side_effect=artifact), \
                 patch('native_joint.fit',side_effect=joint),patch('quality_data.load',return_value=()), \
                 patch('packed_training.attach_result',side_effect=publish),patch('grid_distillation.firmware_config',side_effect=lambda path,*a:config if path.name!=identifier else published):
                work(server,native,identifier,options)
                self.assertEqual(server.JOBS[identifier]['status'],'error' if late_cancel else 'done',server.JOBS[identifier].get('error',''))
                if late_cancel:self.assertIn('取消',server.JOBS[identifier]['error'])
            self.assertEqual(events,['baseline','artifact','joint']+([] if late_cancel else ['publish']))

    def test_joint_cache_signature_changes_with_bound_profile_revision(self):
        import server
        with tempfile.TemporaryDirectory() as tmp,patch.object(server,'RUNS',Path(tmp)), \
             patch.dict(server.JOBS,{},clear=True),patch.object(server,'POOL'), \
             patch.object(server,'validate_fit'),patch('packed_training.bind_context'):
            signatures=[]
            for revision in ('native-joint/1','native-joint/2'):
                body=dict(number=24,full_name='缓存验证',project_id='a'*32,target_kind='chart-image',
                    training_profile='native-joint/1',training_revision=revision)
                result=server.queue_fit(body);job=server.JOBS[result['id']]
                signatures.append(job['signature']);job['status']='error'
            self.assertNotEqual(*signatures)

    def test_joint_profile_is_bound_for_all_new_requests(self):
        body=tp.bind(dict(training_profile='native-joint/1',target_kind='chart-image',number=24))
        self.assertEqual(body['training_profile'],'native-joint/1')
        self.assertEqual(body['packed_selection_policy'],'native-packed-quality/1')
        self.assertGreater(body['joint_options']['steps'],0)
        self.assertEqual(tp.bind(dict(target_kind='chart-image'))['training_profile'],'native-joint/1')

    def test_server_routes_joint_training_to_shared_adapter(self):
        import server
        with patch('native_joint_workbench.work') as joint,patch.object(server,'native_work') as native:
            server.work('test',dict(training_profile='native-joint/1'))
            joint.assert_called_once();native.assert_not_called()

    def test_final_failure_retains_reference_without_retrying_candidates(self):
        from native_joint_workbench import accept
        old=copy.deepcopy(core.presets()[0][0]);new=dict(old,short_name='候选')
        baseline=dict(entry=old,sha256='old',metrics={'weighted_loss':2.},label='reference')
        selected=dict(entry=new,sha256='new',metrics={'weighted_loss':1.},label='candidate')
        gate=SimpleNamespace(assess=lambda *a,**k:dict(failures=['dense:final:max']),baseline=baseline)
        chosen,quality=accept(new,dict(selected=selected),gate)
        self.assertEqual(chosen,old);self.assertFalse(quality['adopted'])
        self.assertEqual(quality['independent_checks'],1)


if __name__=='__main__':unittest.main()
