"""固定五款数据：比较纯整数分块求解与当前冻结配方，测试集只在训练后评分。"""
import argparse
import copy
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'web'),str(ROOT/'scripts')]

import core
from benchmark_joint import inputs_for,save
from benchmark_teacher import measure
from fit_bin_joint import grid_from
from gpu_runtime import available,policy
from integer_blocks import refine,fingerprint
from training_progress import TrainingProgress


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('frozen',type=Path)
    parser.add_argument('current',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--seconds',type=float,default=180)
    parser.add_argument('--rounds',type=int,default=24)
    parser.add_argument('--start',choices=('legacy','current'),default='legacy')
    parser.add_argument('--proposals',type=Path,help='可选的冻结候选目录，作为全部目标统一的额外起点')
    parser.add_argument('--cases',type=int,nargs='+',default=[1,2,3,4,5])
    args = parser.parse_args()
    if not available():
        parser.error('需要R5_GPU_TRAINING=1与可用MPS')
    args.output.mkdir(parents=True,exist_ok=False)
    snapshot = args.output/'source_bundle'
    snapshot.mkdir()
    for name in fingerprint():
        destination = snapshot/name
        destination.parent.mkdir(parents=True,exist_ok=True)
        destination.write_bytes((ROOT/name).read_bytes())
    save(snapshot/'manifest.json',fingerprint())
    reports,entries,old_entries,current_entries = [],[],[],[]
    for number in args.cases:
        source,control = args.frozen/f'{number:02d}',args.current/f'{number:02d}'
        folder = args.output/f'{number:02d}'
        folder.mkdir()
        old_blob = (source/'legacy.BIN').read_bytes()
        current_blob = (control/'R5NATIVE.BIN').read_bytes()
        old,current = map(core.compiler.unpack,(old_blob,current_blob))
        response = json.loads((source/'response.json').read_text())
        initial = old if args.start == 'legacy' else current
        data = inputs_for(source/'job',initial,response)
        tracker = TrainingProgress(folder/'progress.json')
        extra = () if args.proposals is None else core.compiler.unpack(
            (args.proposals/f'{number:02d}/R5NATIVE.BIN').read_bytes())['entries']
        print('开始纯整数分块',current['entries'][0]['full_name'],flush=True)
        candidate,table,audit = refine(initial,grid_from(initial['entries'][0]),
            **{key:value for key,value in data.items() if key!='test'},progress=tracker.update,
            seconds=args.seconds,max_rounds=args.rounds,extra_starts=extra)
        selected = copy.deepcopy(candidate or initial)
        if not (grid_from(selected['entries'][0]) == table).all():
            raise ValueError('最终配方与网格不一致')
        for name,blob in [('legacy.BIN',old_blob),('current.BIN',current_blob),
                          ('R5NATIVE.BIN',core.compiler.pack(selected))]:
            (folder/name).write_bytes(blob)
        report = dict(name=current['entries'][0]['full_name'],audit=audit,gpu_policy=policy(),
            initialization=args.start,current_used_as_start=args.start=='current',
            extra_proposals=None if args.proposals is None else str(args.proposals),
            baseline_validation=measure(old,data,'validation'),
            current_validation=measure(current,data,'validation'),
            selected_validation=measure(selected,data,'validation'),
            baseline_test=measure(old,data,'test'),current_test=measure(current,data,'test'),
            selected_test=measure(selected,data,'test'),
            holdout_sha256=core.sha(data['inputs'][data['test']].tobytes()),
            test_samples=int(data['test'].sum()),test_used_for_selection=False,
            current_bin_sha256=core.sha(current_blob),legacy_bin_sha256=core.sha(old_blob),
            binary_sha256=core.sha(core.compiler.pack(selected)))
        save(folder/'comparison.json',report)
        save(folder/'response.json',response)
        reports.append(report)
        entries.extend(selected['entries']);old_entries.extend(old['entries']);current_entries.extend(current['entries'])
        for name,values in [('R5NATIVE.BIN',entries),('legacy.BIN',old_entries),('current.BIN',current_entries)]:
            (args.output/name).write_bytes(core.compiler.pack(core.compiler.config(values,5)))
        save(args.output/'comparison.json',dict(cases=reports))
        tracker.update(stage='整数分块BIN独立回读完成',state='done')
        print('完成',report['name'],'accepted',audit['accepted'],'seconds',audit['seconds'],
            'current',report['current_test']['rgb_rmse'],report['current_test']['delta_e00_mean'],
            'new',report['selected_test']['rgb_rmse'],report['selected_test']['delta_e00_mean'],flush=True)


if __name__ == '__main__':
    main()
