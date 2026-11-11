"""从原厂与训练灰阶启动核心条件网格拟合，对照冻结的旧方案。"""
import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'web'), str(ROOT / 'scripts')]

import core
from benchmark_joint import inputs_for, measure, save
from profiled_fit import fit
from training_progress import TrainingProgress


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--seconds', type=float, default=90)
    parser.add_argument('--cases', type=int, nargs='+', default=[1, 2, 3, 4, 5])
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    reports, entries = [], []
    for number in args.cases:
        source = args.baseline / f'{number:02d}'
        case = args.output / f'{number:02d}'
        case.mkdir()
        reference = core.compiler.unpack((source / 'legacy.BIN').read_bytes())
        response = json.loads((source / 'response.json').read_text())
        data = inputs_for(source / 'job', reference, response)
        inputs_sha = core.sha(data['inputs'][data['test']].tobytes())
        fit_data = {key: value for key, value in data.items() if key != 'test'}
        print('开始核心重构对照', reference['entries'][0]['full_name'], flush=True)
        tracker = TrainingProgress(case / 'profiled_progress.json')
        selected, candidate, audit = fit(reference, fit_data, seconds=args.seconds, progress=tracker.update)
        tracker.update(stage='核心求解与量化验收完成', state='done')
        for name, config in [('candidate.BIN', candidate), ('R5NATIVE.BIN', selected), ('legacy.BIN', reference)]:
            (case / name).write_bytes(core.compiler.pack(config))
        report = dict(name=reference['entries'][0]['full_name'], holdout_sha256=inputs_sha,
            test_samples=int(data['test'].sum()), audit=audit,
            baseline_test=measure(reference, data, 'test'), candidate_test=measure(candidate, data, 'test'),
            selected_test=measure(selected, data, 'test'),
            implementation_sha256=core.sha((ROOT / 'web/profiled_fit.py').read_bytes()))
        save(case / 'comparison.json', report)
        reports.append(report)
        entries.extend(selected['entries'])
        save(args.output / 'comparison.json', dict(cases=reports, test_used_for_selection=False))
        (args.output / 'R5NATIVE.BIN').write_bytes(core.compiler.pack(core.compiler.config(entries, 5)))
        print('完成核心重构对照', report['name'], audit['selected'], audit['rejected_by'], flush=True)


if __name__ == '__main__':
    main()
