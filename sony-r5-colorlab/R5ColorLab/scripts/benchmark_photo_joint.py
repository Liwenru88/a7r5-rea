"""复测四组联合拟合，独立照片参与最终整数配方验收。"""
import argparse
from copy import deepcopy
import json
from pathlib import Path
import sys
from time import perf_counter

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'web'), str(ROOT/'scripts')]

import core
from benchmark_calibrated_fit import native_rgb, photo_samples, polish_limits, render, train, write_bin
from benchmark_joint import inputs_for, save
from benchmark_teacher import measure
from calibrated_guard import RampBank, chroma_jumps, metric_failures, ramp_report
from fit_bin_joint import blend_entries, grid_from
from gpu_runtime import available, policy
from integer_blocks import Directions, grid_entry, native_moves
from integer_grid import polish_grid
from native_scoring import RecipeScorer, color_metrics


COLOR = ('rgb_rmse', 'delta_e00_mean')
NATIVE = ('gamma_native_129', 'cc1_delta', 'block13')
FIELDS = (*NATIVE, 'grid_5x9x9')
TARGET_AXES = {3: ('native-full-exposure',), 5: ('hue', 'native-hue')}


def photo_failures(rows, tolerance, *, strict=True):
    if len(rows) != 3 or len({row['scene'] for row in rows}) != 3:
        return ['photo-set-incomplete']
    failures = []
    improved = set()
    for row in rows:
        baseline, candidate = row['baseline'], row['candidate']
        for key in (*COLOR, 'delta_e00_p95'):
            before, after = baseline[key], candidate[key]
            if key in COLOR:
                if after < before-1e-10:
                    improved.add(key)
                failed = after >= before-1e-10 if strict else after > before+1e-10
            else:
                failed = after > before+tolerance+1e-10
            if not np.isfinite((before, after)).all() or failed:
                failures.append(f'{row["scene"]}:{key}')
    if not strict:
        failures.extend(f'calibration-no-improvement:{key}' for key in COLOR if key not in improved)
    return failures


def photos_report(model, reference_model, response, entry, seed, samples):
    rows = []
    for scene, inputs, target in samples:
        before = color_metrics(render(reference_model, inputs, response, seed), target)
        after = before if entry == seed else color_metrics(render(model, inputs, response, entry), target)
        rows.append(dict(scene=scene, samples=len(target), baseline=before, candidate=after))
    return rows


def make_scorer(config, data):
    keys = ('context', 'inputs', 'target', 'train', 'gray', 'validation', 'response', 'bank', 'strength', 'perceptual')
    return RecipeScorer(config, **{key:data[key] for key in keys})


def choose(seed, scorer, data, calibration, margins, banks, args, *, focus=None, warm=None):
    if focus:
        # 筛选阶段预留量化和采样相位的余量。最终复验仍使用已冻结的完整容差。
        margins = deepcopy(margins)
        for axis in focus[1]:
            margins['axes'][axis]['p95'] *= .5
    start = scorer.score(seed, 'reference')
    reference_model, _ = scorer.native(seed)
    response = scorer.response
    ramp_inputs = [bank.inputs(data['context'].base) for bank in banks]
    ramp_base = [bank.jumps(render(reference_model, inputs, response, seed)) for bank, inputs in zip(banks, ramp_inputs)]
    sweep = []
    if args.exposure_sweep:
        axis = 'native-full-exposure'
        for phase in (.07, .23, .37, .47, .59, .79, .97):
            bank = RampBank(phase)
            span, shape = bank.span(axis)
            inputs = bank.inputs(data['context'].base)[span]
            before = render(reference_model, inputs, response, seed).reshape(*shape, 3)
            limit = np.percentile(chroma_jumps(before), 95) + margins['axes'][axis]['p95']*.5
            sweep.append((phase, bank.sha256, shape, float(limit)))
            ramp_inputs.append(inputs)
    ramp_splits = np.cumsum([len(rows) for rows in ramp_inputs])[:-1]
    photo_start = photos_report(reference_model, reference_model, response, seed, seed, calibration)
    best, best_rank = start, 4.
    native_starts = []
    examined = {}

    def ramp_errors(pixels):
        failures = []
        outputs = np.split(pixels, ramp_splits)
        for index, (bank, base, values) in enumerate(zip(banks, ramp_base, outputs), 1):
            _, rejected = ramp_report(base, bank.jumps(values), margins)
            failures.extend(f'screen{index}:{name}' for name in rejected)
        for (phase, _, shape, limit), values in zip(sweep, outputs[len(banks):]):
            if np.percentile(chroma_jumps(values.reshape(*shape, 3)), 95) > limit+1e-10:
                failures.append(f'exposure-phase-{phase:g}:p95')
        return failures

    def consider(recipe):
        nonlocal best, best_rank
        if recipe.sha256 in examined:
            return
        failures = metric_failures(recipe.metrics, start.metrics, margins)
        rows = []
        if not failures:
            model, _ = scorer.native(recipe.entry)
            pixels = render(model, np.concatenate(ramp_inputs), response, recipe.entry)
            failures = ramp_errors(pixels)
        if not failures:
            for known, (_, inputs, target) in zip(photo_start, calibration):
                score = color_metrics(render(model, inputs, response, recipe.entry), target)
                rows.append(dict(known, candidate=score))
            chart = sum(recipe.metrics[key]/max(start.metrics[key], 1e-10) for key in COLOR)
            photo = sum(row['candidate'][key]/max(row['baseline'][key], 1e-10)
                        for row in rows for key in COLOR)/len(rows)
            rank = chart+photo
            if any(recipe.entry[key] != seed[key] for key in NATIVE):
                native_starts.append((rank, recipe))
            failures = photo_failures(rows, margins['delta_e00_p95'], strict=not args.exposure_sweep)
            if not failures and rank < best_rank:
                best, best_rank = recipe, rank
        examined[recipe.sha256] = dict(label=recipe.label, sha256=recipe.sha256,
            failures=failures, validation=recipe.metrics, calibration=rows)

    chart_choice, training = train(seed, data, scorer, start, margins, banks[0], ramp_inputs[0], ramp_base[0], args,
        proposal_hook=consider, gamma_controls=args.gamma_controls, finish_polish=False, focus=focus)

    if warm is not None:
        # 上轮未通过的配方只提供合法整数方向。独立照片和复验渐变仍在锁定后读取。
        for fraction in (.875, .75, .5, .25):
            scaled = blend_entries(seed, warm, fraction)
            consider(scorer.score(scaled, f'previous:{fraction:g}'))
            for tone in (0., .5):
                trial = dict(scaled, gamma_native_129=blend_entries(seed, scaled, tone)['gamma_native_129'])
                consider(scorer.score(trial, f'previous:{fraction:g}:gamma:{tone:g}'))

    # 在已通过校准照片的起点上，再试各原生参数族的合法整数步。
    parent = best
    directions = Directions(scorer, data['response'], data['strength'], data['perceptual'], start)
    native_gradient, _, _ = directions.gradient(parent)
    for entry, label in native_moves(parent.entry, native_gradient, 1, count=10 if focus else 5):
        consider(scorer.score(entry, f'native-integer:{label}'))

    parents = {row.sha256:row for row in (start, best)}
    if native_starts:
        joint = min(native_starts, key=lambda row:row[0])[1]
        parents[joint.sha256] = joint
    moves = []
    began = perf_counter()
    for parent in parents.values():
        model, full = scorer.native(parent.entry)
        train_base, valid_base, probes = np.split(full, (scorer.ntrain, scorer.ntrain+scorer.nvalid))
        guards = tuple((native_rgb(model, inputs), target) for _, inputs, target in calibration)
        independent = native_rgb(model, np.concatenate(ramp_inputs))
        table, count = polish_grid(grid_from(parent.entry), train_base, data['target'][data['train']],
            data['gray'][data['train']], probes, data['response'], data['bank'], data['strength'],
            polish_limits(start, margins, data['bank']), proposal_table=grid_from(chart_choice.entry),
            deadline=perf_counter()+args.polish_seconds,
            validation_data=(valid_base, data['target'][data['validation']]), protect_color_p95=True,
            ramp_screen=(independent, lambda pixels:not ramp_errors(pixels)), color_guards=guards,
            color_guard_priority=args.exposure_sweep)
        moves.append(dict(parent=parent.label, moves=count))
        if count:
            candidate = grid_entry(parent.entry, table)
            fractions = (1., .75, .5, .25, .125) if focus else (1., .5, .25)
            for fraction in fractions:
                trial = blend_entries(parent.entry, candidate, fraction)
                consider(scorer.score(trial, f'photo-polish:{parent.label}:{fraction:g}'))
    return best, dict(training=training, selected=best.label, calibration=examined.get(best.sha256),
        screened=list(examined.values()), integer_moves=moves, integer_seconds=perf_counter()-began,
        focused_screen_p95={axis:margins['axes'][axis]['p95'] for axis in focus[1]} if focus else {},
        exposure_sweep=[dict(phase=phase, sha256=sha, absolute_p95_limit=limit) for phase, sha, _, limit in sweep])


def load_case(frozen, previous, number, receipt, latest, case):
    folder = frozen/f'{number:02d}'
    old = core.compiler.unpack((folder/'legacy.BIN').read_bytes())
    seed, = old['entries']
    margins = json.loads((previous/f'{number:02d}'/'calibration.json').read_text())
    # 上轮已经通过三张照片的配方作为更强对照，其他槽位以冻结原配方为准。
    photo_passed = receipt['accepted'] and len(receipt['blind_photo_delta']) == 3 and all(
        all(row['delta'][key] < -1e-10 for key in COLOR)
        and row['delta']['delta_e00_p95'] <= margins['delta_e00_p95']+1e-10
        for row in receipt['blind_photo_delta'])
    if photo_passed:
        seed = latest[seed['number']]
        if seed['full_name'] != receipt['name'] or seed['full_name'] != case['name']:
            raise ValueError('上轮验收配方和色卡不对应')
        gray_used = receipt['final']['gray_rmse']-receipt['baseline']['gray_rmse']
        margins['gray_rmse'] = min(margins['gray_rmse'], max(0., margins['gray_rmse']-gray_used))
    config = core.compiler.config([seed], core.compiler.format_version(old))
    data = inputs_for(folder/'job', config, json.loads((folder/'response.json').read_text()))
    data['perceptual'] = .35
    digest = core.sha(data['inputs'][data['test']].tobytes())
    if (digest, int(data['test'].sum())) != (case['holdout_sha256'], case['test_samples']):
        raise ValueError('本轮与上轮留出集不一致')
    return config, seed, data, margins, digest, 'previous-photo-passed' if photo_passed else 'frozen-original'


def final_check(config, candidate, data, margins, banks, samples):
    seed, = config['entries']
    entry, = candidate['entries']
    context = data['context']
    original_model, model = [context.build(**core.slot_native_parameters(context, row)) for row in (seed, entry)]
    response = make_scorer(config, data).response
    before, after = [measure(value, data, 'test') for value in (config, candidate)]
    failures = metric_failures(after, before, margins)
    ramps = []
    for index, bank in enumerate(banks, 1):
        inputs = bank.inputs(context.base)
        start = bank.jumps(render(original_model, inputs, response, seed))
        end = bank.jumps(render(model, inputs, response, entry))
        metrics, failed = ramp_report(start, end, margins)
        failures.extend(f'blind-ramp{index}:{name}' for name in failed)
        ramps.append(dict(sha256=bank.sha256, metrics=metrics, failures=failed))
    photos = photos_report(model, original_model, response, entry, seed, samples)
    failed_photos = photo_failures(photos, margins['delta_e00_p95'])
    failures.extend(f'blind-photo:{name}' for name in failed_photos)
    accepted = entry != seed and not failures
    return dict(accepted=accepted, baseline=before, candidate=after, final=after if accepted else before,
        failures=failures, blind_ramps=ramps, blind_photos=photos, photo_failures=failed_photos,
        candidate_changed_fields=[key for key in FIELDS if seed[key] != entry[key]],
        final_changed_fields=[key for key in FIELDS if accepted and seed[key] != entry[key]])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for field in ('frozen', 'previous', 'photos', 'output'):
        parser.add_argument(field, type=Path)
    parser.add_argument('--steps', type=int, default=600)
    parser.add_argument('--checkpoint', type=int, default=25)
    parser.add_argument('--lr', type=float, default=.006)
    parser.add_argument('--gamma-controls', type=int, default=33)
    parser.add_argument('--polish-seconds', type=float, default=20.)
    parser.add_argument('--cases', type=int, nargs='+')
    parser.add_argument('--focus-prior', type=Path, help='沿用上轮五槽 BIN，只针对指定过渡轴复测 Vision3 和 Portra')
    parser.add_argument('--exposure-sweep', action='store_true', help='对 Vision3 的原生域曝光加密筛选相位')
    args = parser.parse_args()
    if not available() or min(args.steps, args.checkpoint, args.lr, args.polish_seconds) <= 0:
        parser.error('需要可用的 Apple Metal/MPS 和正的训练预算')
    prior = json.loads((args.previous/'comparison.json').read_text())['cases']
    verified = json.loads((args.previous/'verified/verification.json').read_text())
    prior_blob = (args.previous/'verified/R5NATIVE.BIN').read_bytes()
    if core.sha(prior_blob) != verified['binary_sha256']:
        raise ValueError('上轮验收 BIN 散列不一致')
    latest = {entry['number']:entry for entry in core.compiler.unpack(prior_blob)['entries']}
    manifest = json.loads((args.photos/'manifest.json').read_text())
    if manifest['filters'] != [case['name'] for case in prior] or len(prior) != 5:
        raise ValueError('照片和色卡套数或顺序不一致')
    names = {part:{row['raw'] for row in manifest['scenes'] if row['split'] == part} for part in ('calibration', 'blind')}
    if any(len(value) != 3 for value in names.values()) or names['calibration'] & names['blind']:
        raise ValueError('照片筛选集和最终复验集必须互斥，各三张')
    args.cases = args.cases or (list(TARGET_AXES) if args.focus_prior else [1, 2, 3, 4, 5])
    if len(set(args.cases)) != len(args.cases) or not set(args.cases) <= set(TARGET_AXES if args.focus_prior else range(1, 6)):
        parser.error('槽位必须合法且唯一')
    if args.exposure_sweep and (not args.focus_prior or args.cases != [3]):
        parser.error('加密曝光复测只用于 Vision3 定向模式')
    frozen_entries = []
    focus_reference = None
    if args.focus_prior:
        focus_reference = json.loads((args.focus_prior/'verification.json').read_text())
        previous_blob = (args.focus_prior/'R5NATIVE.BIN').read_bytes()
        if core.sha(previous_blob) != focus_reference['sha256']:
            raise ValueError('定向复测的上轮 BIN 散列不一致')
        frozen_entries = core.compiler.unpack(previous_blob)['entries']
        if len(frozen_entries) != 5 or len(focus_reference['cases']) != 5:
            raise ValueError('定向复测需要完整的上轮五槽记录')
    args.output.mkdir(parents=True, exist_ok=False)
    screen = [RampBank(phase) for phase in (.53, .31)]
    blind = [RampBank(phase) for phase in (.87, .91)]
    focus_banks = []
    if focus_reference is not None:
        screen.append(RampBank(.67))
        blind.append(RampBank(.43))
        focus_banks = [RampBank(phase) for phase in (.19, .71)]
    if args.exposure_sweep:
        focus_banks.extend(RampBank(phase) for phase in (.11, .61))
        blind.append(RampBank(.83))
    results, loaded = [], []
    for number in args.cases:
        config, seed, data, margins, heldout, reference = load_case(
            args.frozen, args.previous, number, verified['cases'][number-1], latest, prior[number-1])
        scorer = make_scorer(config, data)
        focus, warm = None, None
        if focus_reference is not None:
            previous = focus_reference['cases'][number-1]
            if previous['accepted'] or previous['holdout_sha256'] != heldout or previous['name'] != seed['full_name']:
                raise ValueError('目标槽位必须对应上轮未采用的候选和同一留出集')
            previous_slot = args.focus_prior/f'{number:02d}'
            if core.compiler.pack(config) != (previous_slot/'reference.BIN').read_bytes():
                raise ValueError('定向复测的参考配方发生变化')
            warm_blob = (previous_slot/'candidate.BIN').read_bytes()
            if core.sha(warm_blob) != previous['candidate_sha256']:
                raise ValueError('上轮候选散列不一致')
            warm, = core.compiler.unpack(warm_blob)['entries']
            focus = (focus_banks, TARGET_AXES[number])
        print(seed['full_name'], reference, f'{len(data["train"])} 个色块整批训练', flush=True)
        selected, audit = choose(seed, scorer, data, list(photo_samples(args.photos, manifest, number, 'calibration')),
                                 margins, screen, args, focus=focus, warm=warm)
        folder = args.output/f'{number:02d}'
        folder.mkdir()
        version = core.compiler.format_version(config)
        _, original_sha = write_bin(folder/'reference.BIN', seed, version)
        _, digest = write_bin(folder/'candidate.BIN', selected.entry, version)
        if digest != selected.sha256:
            raise ValueError('候选文件与已锁定配方散列不同')
        audit.update(name=seed['full_name'], reference=reference, reference_sha256=original_sha,
            candidate_sha256=digest, margins=margins, holdout_sha256=heldout,
            training_samples=len(data['train']), test_samples=int(data['test'].sum()))
        save(folder/'selection.json', audit)
        loaded.append((number, folder, config, data, audit))
        print('锁定候选', seed['full_name'], selected.label, flush=True)
    save(args.output/'locked.json', [dict(name=row[-1]['name'], sha256=row[-1]['candidate_sha256']) for row in loaded])

    # 完成所有候选的锁定后才读取独立照片和留出集指标。
    updated_entries = []
    for number, folder, config, data, audit in loaded:
        blob = (folder/'candidate.BIN').read_bytes()
        if core.sha(blob) != audit['candidate_sha256']:
            raise ValueError('最终验收前候选文件被改变')
        candidate = core.compiler.unpack(blob)
        outcome = final_check(config, candidate, data, audit['margins'], blind,
            list(photo_samples(args.photos, manifest, number, 'blind')))
        kept = candidate if outcome['accepted'] else config
        updated_entries.extend(kept['entries'])
        _, sha = write_bin(folder/'R5NATIVE.BIN', kept['entries'][0], core.compiler.format_version(config))
        results.append(dict(outcome, name=audit['name'], reference=audit['reference'], selected=audit['selected'],
            holdout_sha256=audit['holdout_sha256'], training_samples=audit['training_samples'],
            test_samples=audit['test_samples'], candidate_sha256=audit['candidate_sha256'], final_sha256=sha,
            gray_tolerance=audit['margins']['gray_rmse'], color_p95_tolerance=audit['margins']['delta_e00_p95']))
        save(folder/'verification.json', results[-1])
        print(audit['name'], '验收通过' if outcome['accepted'] else '回退', outcome['failures'], flush=True)
    updated_slots = {entry['number'] for entry in updated_entries}
    preserved = [entry for entry in frozen_entries if entry['number'] not in updated_slots]
    final_entries = sorted(preserved+updated_entries, key=lambda entry:entry['number'])
    blob = core.compiler.pack(core.compiler.config(final_entries, 5))
    destination = args.output/'R5NATIVE.BIN'
    destination.write_bytes(blob)
    if core.compiler.unpack(destination.read_bytes())['entries'] != final_entries:
        raise ValueError('最终合并 BIN 回读不一致')
    save(args.output/'verification.json', dict(backend=policy(), steps=args.steps, gamma_controls=args.gamma_controls,
        optimizer='Adam', learning_rate_peak=args.lr, full_batch=True, chart_holdout_used_for_selection=False,
        blind_photos_used_for_selection=False, calibration_photos_used_for_gradient=False,
        calibration_photos_used_for_candidate_selection=True, scenes=manifest['scenes'],
        calibration_photos_allow_ties=args.exposure_sweep,
        ramp_hashes=dict(screen=[bank.sha256 for bank in screen], blind=[bank.sha256 for bank in blind]),
        preserved_slots=[dict(number=entry['number'], name=entry['full_name']) for entry in preserved],
        focus_reference_sha256=focus_reference['sha256'] if focus_reference is not None else None,
        sha256=core.sha(blob), accepted=sum(row['accepted'] for row in results), cases=results))


if __name__ == '__main__':
    main()
