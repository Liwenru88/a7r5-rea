"""用固定目标、共同初始化和相同预算比较联合求解与旧方案。"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'web'), str(ROOT / 'scripts')]

import numpy as np

import baseline
import core
import grid_distillation
from compute_backend import render_native
from edit_parameter_context import ParameterContext, RuntimeColor
from fit_anchor_native import training_plan
from fit_bin_joint import grid_from
from gpu_runtime import available, cpu_reference
from integer_grid import candidate_metrics, guard_failures
from output_continuity import ProbeBank
from patch_sampling import center_mean


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def prepare(folder, job, number):
    import chart_target
    import pc_compensation
    import server
    from optimizer_policy import pc_options, search_options
    from training_policy import group_importance
    from v45_dataset import DATASET_ID

    targets = sorted(p for p in folder.iterdir() if p.suffix.lower() in ('.tif', '.tiff'))
    if len(targets) != 1:
        raise ValueError('每款滤镜需要一张目标色卡')
    target, = targets
    with target.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    options = search_options(dict(parameter_smoothing=30, output_continuity=30,
                                  gamma_color_rounds=1))
    body = dict(number=number, short_name=f'J{number:02d}', full_name=folder.name,
        target_kind='chart-image', dataset_id=DATASET_ID, target_sha256=digest,
        evaluations=80, group_weights=group_importance(), search_options=options,
        pc_options=pc_options(), pc_compensation=True, compression_training=True,
        white_balance=False, speed_priority=False, gamma_endpoint128=131071)
    request = job / 'request.json'
    if request.exists() and json.loads(request.read_text()) != body:
        raise ValueError('基准任务的来源或训练设置发生变化')
    if not request.exists():
        job.mkdir(parents=True, exist_ok=False)
        save(request, body)
    if not (job / 'pairs.npz').exists():
        chart_target.prepare(target.read_bytes(), job, source_path=target, dataset_id=DATASET_ID)
    if not (job / 'fit/recipe.json').exists():
        server.solve_native(body, job, {})
    if not (job / 'native_config.json').exists():
        core.finish_fit(job, number, body['short_name'], folder.name, 131071)
    if not (job / 'pc_compensation.json').exists():
        pc_compensation.generate(job)
    key = grid_distillation.latest(job)
    if key is None:
        key = grid_distillation.generate(job, body['pc_options']['response'],
            objective='fuji-target', adaptive_color=False)['key']
    config = grid_distillation.firmware_config(job, key, configuration_only=True)
    return config, grid_distillation.load_result(job, key)[0]['identity']['response']


def inputs_for(job, config, response):
    recipe, _ = baseline.read_job(job)
    with np.load(job / 'pairs.npz', allow_pickle=False) as p:
        arrays = {key: p[key] for key in p.files}
    split, ids = arrays['split'], arrays['anchor_index']
    sectors = arrays['sector16_index']
    options = recipe['fitting']['search_options']
    train, _, _, weights = training_plan(split, ids,
        recipe['fitting']['group_total_weights'], sectors, arrays['baseline_tonal_index'],
        np.flatnonzero((split == 'train') & (ids < 0) & (sectors < 0)),
        arrays['sample_kind'], options)
    context = ParameterContext(RuntimeColor.from_capture(*baseline.for_job(job)))
    bank = ProbeBank()
    model = context.build(**core.slot_native_parameters(context, config['entries'][0]))
    with cpu_reference():
        base = center_mean(render_native(model, arrays['input'])) / 16383
        probes = center_mean(render_native(model, bank.inputs(model))) / 16383
    return dict(context=context, inputs=arrays['input'], target=arrays['0_target'] / 16383,
        train=train, weights=weights, eligible=(ids[train] < 0) & (sectors[train] < 0),
        gray=(ids >= 4) & (ids < 260) & (split == 'train'), validation=split == 'valid',
        test=split == 'test', response=response, bank=bank, probe_base=probes, bin_base=base,
        strength=options['output_continuity'] or 30,
        perceptual=options['perceptual_weight'], smoothing=options['parameter_smoothing'])


def measure(config, data, split):
    entry, = core.compiler.unpack(core.compiler.pack(config))['entries']
    model = data['context'].build(**core.slot_native_parameters(data['context'], entry))
    mask = data[split]
    with cpu_reference():
        bases = [center_mean(render_native(model, values)) / 16383 for values in
            (data['inputs'][data['gray']], data['inputs'][mask], data['bank'].inputs(model))]
    score = candidate_metrics(data['target'][data['gray']], data['target'][mask],
        data['response'], data['bank'], data['strength'], data['perceptual'])
    return score(grid_from(entry), *bases)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('data', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--mode', choices=('baseline', 'joint', 'all'), default='all')
    parser.add_argument('--seconds', type=float, default=60)
    args = parser.parse_args()
    if args.seconds <= 0:
        parser.error('时间预算必须为正数')
    if not available():
        parser.error('此对照需要 R5_GPU_TRAINING=1 和可用的 Metal/MPS')
    args.output.mkdir(parents=True, exist_ok=True)
    folders = sorted(p for p in (args.data / '滤镜').iterdir() if p.is_dir() and p.name != '王家卫')
    if len(folders) != 5:
        parser.error('本次对照需要完整的五款 SpektraLab 目标')
    results = []
    selected_entries = []
    legacy_entries = []
    for index, folder in enumerate(folders, 1):
        case = args.output / f'{index:02d}'
        job = case / 'job'
        print('开始', folder.name, args.mode, flush=True)
        if args.mode in ('baseline', 'all'):
            config, response = prepare(folder, job, index)
            save(case / 'seed.json', config)
            save(case / 'response.json', response)
        else:
            config = json.loads((case / 'seed.json').read_text())
            response = json.loads((case / 'response.json').read_text())
        data = inputs_for(job, config, response)
        grid = grid_from(config['entries'][0])
        common = {key: value for key, value in data.items() if key != 'test'}
        if args.mode in ('baseline', 'all') and not (case / 'legacy.json').exists():
            from adaptive_color import refine
            started = time.perf_counter()
            selected, table, audit = refine(config, grid, **common)
            chosen = copy.deepcopy(selected or config)
            chosen['entries'][0]['grid_5x9x9'] = dict(coefficients=table.T.reshape(3, 5, 9, 9).tolist())
            blob = core.compiler.pack(chosen)
            (case / 'legacy.BIN').write_bytes(blob)
            save(case / 'legacy.json', dict(seconds=time.perf_counter() - started,
                audit=audit, validation=measure(chosen, data, 'validation')))
        legacy = core.compiler.unpack((case / 'legacy.BIN').read_bytes())
        legacy_report = json.loads((case / 'legacy.json').read_text())
        if args.mode in ('joint', 'all'):
            from joint_fit import refine
            from training_progress import TrainingProgress
            budget = max(args.seconds, legacy_report['seconds'] + 15)
            common = {key: value for key, value in inputs_for(job, legacy, response).items() if key != 'test'}
            tracker = TrainingProgress(case / 'joint_progress.json')
            selected, table, audit = refine(legacy, grid_from(legacy['entries'][0]), **common,
                seconds=budget - legacy_report['seconds'], progress=tracker.update)
            tracker.update(stage='联合候选量化验收完成', state='done')
            candidate = copy.deepcopy(selected or legacy)
            candidate['entries'][0]['grid_5x9x9'] = dict(coefficients=table.T.reshape(3, 5, 9, 9).tolist())
            candidate_validation = measure(candidate, data, 'validation')
            legacy_validation = legacy_report['validation']
            failures = guard_failures(candidate_validation, legacy_validation)
            failures += [key for key in ('rgb_rmse', 'delta_e00_mean')
                         if candidate_validation[key] >= legacy_validation[key] - 1e-10]
            chosen = legacy if failures else candidate
            blob = core.compiler.pack(chosen)
            assert core.compiler.pack(core.compiler.unpack(blob)) == blob
            (case / 'candidate.BIN').write_bytes(core.compiler.pack(candidate))
            (case / 'R5NATIVE.BIN').write_bytes(blob)
            report = dict(name=folder.name, budget_seconds=budget,
                shared_initialization=True, test_used_for_selection=False,
                holdout_sha256=core.sha(data['inputs'][data['test']].tobytes()),
                test_samples=int(data['test'].sum()), legacy=legacy_report,
                candidate=dict(audit=audit, validation=candidate_validation),
                selected='legacy' if failures else 'joint', rejected_by=failures,
                total_joint_seconds=legacy_report['seconds'] + audit['seconds'],
                baseline_test=measure(legacy, data, 'test'), candidate_test=measure(candidate, data, 'test'),
                selected_test=measure(chosen, data, 'test'), binary_sha256=core.sha(blob))
            save(case / 'comparison.json', report)
            results.append(report)
            selected_entries.extend(core.compiler.unpack(blob)['entries'])
            legacy_entries.extend(legacy['entries'])
            merged = core.compiler.pack(core.compiler.config(selected_entries, 5))
            assert core.compiler.pack(core.compiler.unpack(merged)) == merged
            (args.output / 'R5NATIVE.BIN').write_bytes(merged)
            (args.output / 'legacy.BIN').write_bytes(core.compiler.pack(core.compiler.config(legacy_entries, 5)))
            save(args.output / 'comparison.json', dict(cases=results, format_version=5,
                binary_sha256=core.sha(merged), shared_initialization=True,
                refinement_budget_seconds=args.seconds, source=str(args.data),
                validation_selection=True, test_used_for_selection=False,
                implementation_sha256=core.sha((ROOT/'web/joint_fit.py').read_bytes())))
            print('完成', folder.name, report['selected'], report['baseline_test']['rgb_rmse'],
                  report['selected_test']['rgb_rmse'], flush=True)
        else:
            print('基准完成', folder.name, legacy_report['seconds'], flush=True)


if __name__ == '__main__':
    main()
