"""One-job native/PC pipeline contracts; the real numerical runs are separate."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import server


class IntegratedTrainingTests(unittest.TestCase):
    def test_full_pipeline_fits_once_and_requires_compression_success(self):
        # 验证真实任务编排与落盘，数值求解边界使用替身，避免重复长时间训练。
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);identifier='unified';order=[]
                job={'id':identifier,'status':'queued'}
                body=dict(number=24,short_name='F24',full_name='统一入口',
                          pc_compensation=True,compression_training=True,guarded_adam=True,
                          pc_options=dict(response=[[1,0,0],[0,1,0],[0,0,1]]))
                def native(*args):order.append('native')
                def finish(*args):return dict(config=dict(entries=[dict(number=24)]))
                def pc(output):
                    order.append('pc');(output/'pc_compensation.json').write_text('{}')
                    return dict(metrics={})
                def grid(*args,**kwargs):
                    self.assertTrue(kwargs['adaptive_color'])
                    order.append('grid')
                    if failure:raise ValueError('压缩失败')
                    return dict(key='compressed-key')
                with patch.object(server,'RUNS',root),patch.dict(server.JOBS,{identifier:job},clear=True), \
                     patch.object(server,'fit_native',side_effect=native) as fit, \
                     patch.object(server.core,'finish_fit',side_effect=finish), \
                     patch('pc_compensation.generate',side_effect=pc), \
                     patch('grid_distillation.generate',side_effect=grid):
                    server.work(identifier,body)
                self.assertEqual(fit.call_count,1)
                self.assertEqual(order,['native','pc','grid'])
                saved=json.loads((root/identifier/'job.json').read_text())
                state=json.loads((root/identifier/'grid_training.json').read_text())
                self.assertEqual(saved['status'],'error' if failure else 'done')
                self.assertEqual(state['status'],saved['status'])
                if failure:self.assertNotIn('result',saved)
                else:self.assertEqual(saved['result']['grid_key'],'compressed-key')

    def test_ui_has_one_training_switch_and_no_separate_fitting_module(self):
        from html.parser import HTMLParser
        class Elements(HTMLParser):
            def __init__(self):super().__init__();self.ids=[]
            def handle_starttag(self,tag,attrs):
                value=dict(attrs).get('id')
                if value:self.ids.append(value)
        html=(server.STATIC/'index.html').read_text();elements=Elements();elements.feed(html)
        self.assertEqual(len(elements.ids),len(set(elements.ids)))
        self.assertLess(html.index('id="lut"'),html.index('id="pcTraining"'))
        self.assertLess(html.index('id="pcTraining"'),html.index('id="gamut"'))
        self.assertNotIn('pcFit',elements.ids)
        self.assertIn('resultMode',elements.ids)
        self.assertIn('nativeStages',elements.ids)

    def test_option_controls_solver_and_persisted_final_artifact(self):
        for enabled in [False, True]:
            with self.subTest(enabled=enabled), tempfile.TemporaryDirectory() as directory:
                root=Path(directory);identifier='fixture'
                commands=[]
                class Process:
                    def __init__(self, cmd, **kwargs):commands.append(cmd)
                    def wait(self, **kwargs):return 0
                def finish(output,*args):return {'config':{},'heldout':{}}
                def pc(output):
                    (output/'pc_compensation.json').write_text('{"schema":"fixture"}')
                    return {'metrics':{'test':{'compensated':{'rmse':1}}}}
                def prepare(lut,gamut,output,dataset_id=None):
                    import chart_datasets
                    (output/'input_audit.json').write_text(json.dumps(dict(dataset_id=chart_datasets.get(dataset_id).DATASET_ID)))
                job={'id':identifier,'status':'queued'}
                with patch.object(server,'RUNS',root),patch.dict(server.JOBS,{identifier:job},clear=True), \
                     patch.object(server.core,'prepare_target',side_effect=prepare),patch.object(server.core,'finish_fit',side_effect=finish), \
                     patch.object(server.subprocess,'Popen',Process),patch('pc_compensation.generate',side_effect=pc) as generate:
                    server.work(identifier,dict(lut='fixture',gamut='S-Gamut3',evaluations=1,number=1,short_name='ST',full_name='ST',white_balance=enabled,pc_compensation=enabled,pc_options=dict(curve_mode='qaq-grid',grid_enabled=True,response=[[1,0,0],[0,1,0],[0,0,1]]),group_weights=dict(random=1,primaries=2,gray=3,colorchecker24=4),search_options=dict(starts=3,adaptive_rounds=1,perceptual_weight=.4,quantization_sweeps=2,parameter_smoothing=0,gamma_color_rounds=0,**({"adam_learning_rate":.0075,"adam_steps":1200} if enabled else {}))))
                    self.assertEqual(job['status'],'done',job.get('error'))
                    self.assertEqual('--pc-compensation' in commands[0],enabled)
                    self.assertEqual('--white-balance' in commands[0],enabled)
                    self.assertEqual(json.loads(commands[0][commands[0].index('--pc-options')+1]),dict(curve_mode='qaq-grid',grid_enabled=True,response=[[1,0,0],[0,1,0],[0,0,1]]))
                    self.assertEqual(json.loads(commands[0][commands[0].index('--group-weights')+1]),dict(random=1,primaries=2,gray=3,colorchecker24=4))
                    self.assertEqual(json.loads(commands[0][commands[0].index('--search-options')+1]),dict(starts=3,adaptive_rounds=1,perceptual_weight=.4,quantization_sweeps=2,parameter_smoothing=0,gamma_color_rounds=0,output_continuity=0,primary_tonal_weight=1.0,hue24_tonal_weight=1.0,adam_learning_rate=.0075 if enabled else .015,adam_steps=1200 if enabled else 2000))
                    self.assertEqual(generate.call_count,int(enabled))
                    saved=json.loads((root/identifier/'job.json').read_text())
                    self.assertEqual(saved['result']['pc_compensation']['enabled'],enabled)
                    self.assertNotIn('process',saved)
                    self.assertIn('finished',saved)


if __name__=='__main__':unittest.main()
