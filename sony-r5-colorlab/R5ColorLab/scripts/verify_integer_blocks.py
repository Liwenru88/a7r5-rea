"""独立回读新旧BIN并复算指标，可回放生产编排的采用、回退与拒绝边界。"""
import argparse
import copy
import io
import json
from pathlib import Path
import sys
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'web'),str(ROOT/'scripts')]

import numpy as np

import core
from benchmark_joint import inputs_for,save
from benchmark_teacher import measure
from fit_bin_joint import grid_from
from integer_blocks import fingerprint
from native_scoring import adoption_failures


def compare_metrics(selected,reference):
    return dict(passed=not adoption_failures(selected,reference),
                rejected_by=adoption_failures(selected,reference),
                changes={key:selected[key]-reference[key] for key in reference})


def pipeline(root,frozen):
    import grid_distillation
    integration = root/'integration'
    integration.mkdir(exist_ok=False)
    old = core.compiler.unpack((root/'01/legacy.BIN').read_bytes())
    selected = core.compiler.unpack((root/'01/R5NATIVE.BIN').read_bytes())
    response = json.loads((root/'01/response.json').read_text())
    audit = json.loads((root/'01/comparison.json').read_text())['audit']
    baseline = (frozen/'01/job').resolve()
    receipts = []
    for mode in ('adopt','fallback','no-candidate','mismatched-grid'):
        job = integration/mode
        job.mkdir();(job/'fit').mkdir()
        for name in ('pairs.npz','target-image.bin','input_audit.json','pc_compensation.json','chart_target.json'):
            (job/name).symlink_to(baseline/name)
        (job/'fit/recipe.json').symlink_to(baseline/'fit/recipe.json')
        (job/'native_config.json').write_text(json.dumps(old,ensure_ascii=False))
        candidate = copy.deepcopy(old if mode in ('fallback','no-candidate') else selected)
        table = grid_from(candidate['entries'][0]).copy()
        if mode in ('mismatched-grid','no-candidate'):
            table[0,0] += 1 if table[0,0] < 63 else -1
        with patch('grid_distillation.fit_target',return_value=(grid_from(old['entries'][0]),dict(objective='fuji-target'))), \
             patch('integer_grid.refine',return_value=(grid_from(old['entries'][0]),dict(enabled=True))), \
             patch('adaptive_color.refine',return_value=(copy.deepcopy(old),grid_from(old['entries'][0]),dict(policy='fixture',seconds=0))), \
             patch('integer_blocks.refine',return_value=(None if mode=='no-candidate' else candidate,table,copy.deepcopy(audit))):
            try:
                result = grid_distillation.generate(job,response,objective='fuji-target',adaptive_color=True,joint_native=True)
            except ValueError as error:
                assert mode=='mismatched-grid' and '返回值不一致' in str(error),str(error)
                assert not list((job/'grid_distillation').glob('*/result.json'))
                receipts.append(dict(mode=mode,rejected=True,error=str(error)))
                continue
        assert mode!='mismatched-grid'
        expected = selected if mode=='adopt' else old
        actual = grid_distillation.firmware_config(job,result['key'],configuration_only=True)
        assert core.compiler.pack(actual)==core.compiler.pack(expected)
        with zipfile.ZipFile(io.BytesIO(grid_distillation.firmware_config(job,result['key']))) as archive:
            assert archive.read('R5NATIVE.BIN')==core.compiler.pack(expected)
        proof = result['fitting']['joint_native']
        assert proof['independent_bin_recheck']
        assert proof['selected']==('joint' if mode=='adopt' else 'legacy')
        assert proof['validation_after']==(proof['independent_candidate_validation'] if mode=='adopt' else proof['legacy_validation'])
        receipts.append(dict(mode=mode,selected=proof['selected'],
            bin_sha256=core.sha(core.compiler.pack(actual)),independent_recheck=True))
    save(integration/'verification.json',dict(numerical_solver_replayed=True,
        production_scoring_and_export_real=True,cases=receipts))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('benchmark',type=Path)
    parser.add_argument('frozen',type=Path)
    parser.add_argument('current',type=Path)
    parser.add_argument('--pipeline',action='store_true')
    args = parser.parse_args()
    root = args.benchmark
    sources = json.loads((root/'source_bundle/manifest.json').read_text())
    assert sources==fingerprint()
    for name,digest in sources.items():
        assert core.sha((root/'source_bundle'/name).read_bytes())==digest
    comparison = json.loads((root/'comparison.json').read_text())
    assert len(comparison['cases'])==5
    records = []
    for number,case in enumerate(comparison['cases'],1):
        folder = root/f'{number:02d}'
        old_blob,current_blob,selected_blob = [(folder/name).read_bytes() for name in
                                              ('legacy.BIN','current.BIN','R5NATIVE.BIN')]
        assert old_blob==(args.frozen/f'{number:02d}/legacy.BIN').read_bytes()
        assert current_blob==(args.current/f'{number:02d}/R5NATIVE.BIN').read_bytes()
        old,current,selected = map(core.compiler.unpack,(old_blob,current_blob,selected_blob))
        assert core.compiler.pack(selected)==selected_blob
        response = json.loads((folder/'response.json').read_text())
        data = inputs_for(args.frozen/f'{number:02d}/job',old,response)
        scores = {name:{split:measure(config,data,split) for split in ('validation','test')}
                  for name,config in [('legacy',old),('current',current),('selected',selected)]}
        for arm,prefix in [('legacy','baseline'),('current','current'),('selected','selected')]:
            for split in ('validation','test'):
                for key,value in scores[arm][split].items():
                    assert abs(value-case[f'{prefix}_{split}'][key]) < 1e-10,(number,arm,split,key)
        assert case['audit']['sources']==sources
        if case['audit']['accepted']:
            initial = scores[case['initialization']]['validation'] if case['initialization']!='legacy' else scores['legacy']['validation']
            assert not adoption_failures(scores['selected']['validation'],initial)
        else:
            assert selected_blob==(old_blob if case['initialization']=='legacy' else current_blob)
        assert core.sha(data['inputs'][data['test']].tobytes())==case['holdout_sha256']=='ddbd2e8f43ffefb91d6701743f4ed17b52b887648fbfb49543ac448d0f47870e'
        changed = {}
        for arm,config in [('legacy',old),('current',current)]:
            a,b = config['entries'][0],selected['entries'][0]
            changed[arm] = {key:int(np.count_nonzero(np.asarray(a[key])!=np.asarray(b[key])))
                           for key in ('gamma_native_129','cc1_delta','block13')}
            changed[arm]['grid'] = int(np.count_nonzero(grid_from(a)!=grid_from(b)))
        records.append(dict(name=case['name'],scores=scores,changed_fields=changed,
            versus_legacy={split:compare_metrics(scores['selected'][split],scores['legacy'][split]) for split in ('validation','test')},
            versus_current={split:compare_metrics(scores['selected'][split],scores['current'][split]) for split in ('validation','test')},
            bin_sha256=core.sha(selected_blob)))
    binary = (root/'R5NATIVE.BIN').read_bytes()
    config = core.compiler.unpack(binary)
    assert [entry['number'] for entry in config['entries']]==list(range(1,6))
    assert len(binary)==128+2452*5 and core.compiler.pack(config)==binary
    for version in (4,5):
        assert core.compiler.unpack(core.compiler.pack(core.compiler.config(config['entries'],version)))['entries']==config['entries']
    save(root/'native_config.json',config)
    save(root/'verification.json',dict(cases=records,sources=sources,
        bin_sha256=core.sha(binary),bin_bytes=len(binary),format_versions=[4,5],
        configured_slots=list(range(1,6)),empty_slots=list(range(6,25)),
        test_used_for_selection=False,photos_used_for_selection=False,camera_connected=False))
    if args.pipeline:
        pipeline(root,args.frozen)
    print(json.dumps(dict(bin_sha256=core.sha(binary),cases=[dict(name=row['name'],
        legacy_test_passed=row['versus_legacy']['test']['passed'],
        current_test_passed=row['versus_current']['test']['passed']) for row in records]),ensure_ascii=False,indent=2))


if __name__=='__main__':
    main()
