"""五款固定数据的教师→原生联合拟合→舍入→实际BIN回读对照。"""
import argparse
import copy
import json
from pathlib import Path
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'web'),str(ROOT/'scripts')]
import core
from benchmark_joint import inputs_for, save
from compute_backend import render_native
from fit_bin_joint import grid_from
from gpu_runtime import available, cpu_reference
from integer_grid import candidate_metrics
from patch_sampling import center_mean
from teacher_joint import refine
from training_progress import TrainingProgress


def measure(config,data,split):
    model=data['context'].build(**core.slot_native_parameters(data['context'],config['entries'][0]))
    with cpu_reference():
        base=[center_mean(render_native(model,x))/16383 for x in
              (data['inputs'][data['gray']],data['inputs'][data[split]],data['bank'].inputs(model))]
    return candidate_metrics(data['target'][data['gray']],data['target'][data[split]],data['response'],
        data['bank'],data['strength'],data['perceptual'],include_p95=True)(grid_from(config['entries'][0]),*base)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--seconds',type=float,default=180)
    parser.add_argument('--cases',type=int,nargs='+',default=[1,2,3,4,5])
    parser.add_argument('--teacher-steps',type=int,default=2000)
    parser.add_argument('--guard-steps',type=int,default=1000)
    parser.add_argument('--evaluations',type=int,default=240)
    parser.add_argument('--rounding-steps',type=int,default=300)
    args=parser.parse_args()
    if not available():
        parser.error('需要R5_GPU_TRAINING=1与Metal/MPS')
    args.output.mkdir(parents=True,exist_ok=False)
    reports,selected_entries,old_entries=[],[],[]
    for number in args.cases:
        source=args.baseline/f'{number:02d}'
        case=args.output/f'{number:02d}'
        case.mkdir()
        reference=core.compiler.unpack((source/'legacy.BIN').read_bytes())
        response=json.loads((source/'response.json').read_text())
        data=inputs_for(source/'job',reference,response)
        tracker=TrainingProgress(case/'progress.json')
        print('开始完整教师联合链路',reference['entries'][0]['full_name'],flush=True)
        selected,table,audit=refine(reference,grid_from(reference['entries'][0]),
            **{key:value for key,value in data.items() if key!='test'},progress=tracker.update,
            seconds=args.seconds,teacher_steps=args.teacher_steps,guard_steps=args.guard_steps,
            evaluations=args.evaluations,rounding_steps=args.rounding_steps)
        chosen=copy.deepcopy(selected or reference)
        chosen['entries'][0]['grid_5x9x9']=dict(coefficients=table.T.reshape(3,5,9,9).tolist())
        for name,config in [('legacy.BIN',reference),('R5NATIVE.BIN',chosen)]:
            (case/name).write_bytes(core.compiler.pack(config))
        report=dict(name=reference['entries'][0]['full_name'],audit=audit,
            holdout_sha256=core.sha(data['inputs'][data['test']].tobytes()),
            test_samples=int(data['test'].sum()),baseline_test=measure(reference,data,'test'),
            selected_test=measure(chosen,data,'test'),test_used_for_selection=False,
            binary_sha256=core.sha((case/'R5NATIVE.BIN').read_bytes()))
        save(case/'comparison.json',report)
        save(case/'response.json',response)
        reports.append(report)
        selected_entries.extend(chosen['entries'])
        old_entries.extend(reference['entries'])
        save(args.output/'comparison.json',dict(cases=reports))
        for filename,entries in [('R5NATIVE.BIN',selected_entries),('legacy.BIN',old_entries)]:
            (args.output/filename).write_bytes(core.compiler.pack(core.compiler.config(entries,5)))
        tracker.update(stage='完整BIN回读对照完成',state='done')
        print('完成',report['name'],'accepted',audit['accepted'],'test',report['selected_test']['rgb_rmse'],report['selected_test']['delta_e00_mean'],flush=True)


if __name__=='__main__':
    main()
