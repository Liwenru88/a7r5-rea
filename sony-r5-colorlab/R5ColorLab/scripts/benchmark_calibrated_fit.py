"""五款色卡整批 GPU 联合训练，按冻结的双域容差回读整数 BIN。"""
import argparse
import json
from pathlib import Path
import sys
from time import perf_counter

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'web'), str(ROOT/'scripts')]

import core
from benchmark_joint import inputs_for, save
from benchmark_teacher import measure
from calibrated_guard import CalibratedTrainingGuard, FocusedRampLoss, RampBank, calibrate, metric_failures, phase_rgb, ramp_report
from compute_backend import render_native
from edit_parameter_context import ParameterContext
from fit_anchor_native import SmoothNative, vector_for
from fit_bin_joint import blend_entries, grid_from, projected
from gpu_runtime import available, cpu_reference, policy
from integer_blocks import grid_entry
from integer_grid import polish_grid
from joint_fit import JointObjective, native_basis
from measured_response import get
from native_scoring import RecipeScorer, adoption_failures, color_metrics
from patch_sampling import center_mean


FRACTIONS = (1., .25, .0625, .015625)
SCALES = (.1, .2, .5, .5, 32.)


def render(model, inputs, response, entry):
    return response.predict_cpu(native_rgb(model, inputs), grid_from(entry))


def native_rgb(model, inputs):
    with cpu_reference():
        return center_mean(render_native(model, inputs))/16383


def photo_samples(directory, manifest, number, split):
    for scene in manifest['scenes']:
        if scene['split'] == split:
            with np.load(directory/scene['cache'], allow_pickle=False) as value:
                yield Path(scene['raw']).name, value['inputs'], value[f'target_{number}']


def ramps_png(path, bank, before, after):
    from PIL import Image, ImageDraw

    axes = tuple(bank.jumps(before))
    canvas = Image.new('RGB', (865, len(axes)*62), 'white')
    draw = ImageDraw.Draw(canvas)
    for row, axis in enumerate(axes):
        left, right = (bank.lines(value, axis) for value in (before, after))
        # 展示变化最大的整条路径，原配方和候选采用完全相同的输入坐标。
        index = int(np.argmax(np.max(np.abs(left-right), axis=(1, 2))))
        y = row*62
        draw.text((8, y+4), f'{axis} | ramp {index+1} | baseline / selected', fill='black')
        for col, values in enumerate((left, right)):
            rgb = np.rint(phase_rgb(values[index])*255).astype(np.uint8)
            strip = Image.fromarray(rgb[None]).resize((410, 34), Image.Resampling.NEAREST)
            canvas.paste(strip, (8+col*430, y+20))
    canvas.save(path)


def polish_limits(start, margins, bank):
    limits = dict(start.metrics)
    limits['gray_rmse'] += margins['gray_rmse']
    limits['delta_e00_p95'] += margins['delta_e00_p95']
    for axis, count in bank.groups:
        limits[f'{axis}_p95'] += margins['axes'][axis]['p95']
        limits[f'{axis}_max'] += margins['axes'][axis]['peak']
        limits[f'{axis}_over'] = count
    return limits


def train(seed, data, scorer, start, margins, screen, screen_inputs, screen_start, args, *,
          proposal_hook=None, gamma_controls=None, finish_polish=True, focus=None):
    model, exact = scorer.native(seed)
    train_rows, gray, bank = data['train'], data['gray'], data['bank']
    selector = np.r_[np.arange(scorer.ntrain), np.arange(scorer.ntrain+scorer.nvalid, len(exact))]
    inputs = scorer.inputs[selector]
    fit_base = exact[selector]
    focus_inputs, focus_groups = None, []
    if focus:
        focus_banks, focus_axes = focus
        chunks = []
        for focus_bank in focus_banks:
            bank_inputs = focus_bank.inputs(data['context'].base)
            for axis in focus_axes:
                span, shape = focus_bank.span(axis)
                chunks.append(bank_inputs[span])
                focus_groups.append((axis, shape))
        focus_inputs = np.concatenate(chunks)
        inputs = np.concatenate((inputs, focus_inputs))
        fit_base = np.concatenate((fit_base, native_rgb(model, focus_inputs)))
    context = ParameterContext(model)
    smooth = SmoothNative(context, inputs)
    original_grid = grid_from(seed)
    objective = JointObjective(smooth, vector_for(context), fit_base, data['target'][train_rows],
        data['weights'], np.flatnonzero(gray[train_rows]), bank, original_grid, data['response'],
        .35, data['smoothing'], data['strength'])
    tools, torch = objective.tools, objective.torch
    torch.manual_seed(42)
    response = scorer.response
    starting_rgb = response.predict_cpu(exact[selector], original_grid)
    objective.guard = CalibratedTrainingGuard(tools, bank, starting_rgb[scorer.ntrain:],
        starting_rgb[:scorer.ntrain][gray[train_rows]], data['target'][train_rows][gray[train_rows]], margins)
    focus_guard = None if focus_inputs is None else FocusedRampLoss(tools, focus_groups,
        response.predict_cpu(fit_base[-len(focus_inputs):], original_grid), margins)
    if gamma_controls is None:
        scales = np.repeat(SCALES[:4], [4, 4, 96, len(smooth.knots)])
        objective.basis = tools.tensor(np.diag(scales))
    else:
        objective.basis = tools.tensor(native_basis(smooth, gamma_controls))
    origin = tools.tensor(original_grid)
    vector_delta = tools.tensor(np.zeros(objective.basis.shape[1])).requires_grad_(True)
    grid_delta = torch.zeros_like(origin).requires_grad_(True)
    optimizer = torch.optim.Adam([vector_delta, grid_delta], lr=args.lr)
    records = []
    best = start
    evaluations = {}
    initial_loss = None
    started = perf_counter()

    def decode():
        return objective.vector(vector_delta), (origin+SCALES[-1]*grid_delta).clamp(-64, 63)

    def consider(entry, label):
        nonlocal best
        candidate = scorer.score(entry, label)
        if candidate.sha256 in evaluations:
            return evaluations[candidate.sha256]
        failures = metric_failures(candidate.metrics, start.metrics, margins)
        independent = None
        if not failures:
            candidate_model, _ = scorer.native(candidate.entry)
            pixels = render(candidate_model, screen_inputs, response, candidate.entry)
            independent, ramp_failures = ramp_report(screen_start, screen.jumps(pixels), margins)
            failures.extend(ramp_failures)
        row = dict(label=candidate.label, sha256=candidate.sha256, validation=candidate.metrics,
                   rejected_by=failures, strict_rejected_by=adoption_failures(candidate.metrics, start.metrics),
                   independent_ramps=independent)
        evaluations[candidate.sha256] = row
        if proposal_hook is not None and not failures:
            proposal_hook(candidate)
        if not failures and candidate.metrics['color_score'] < best.metrics['color_score']:
            best = candidate
        return row

    for step in range(1, args.steps+1):
        # 前 25 步逐渐升到目标学习率，末段缩小实际步长。
        optimizer.param_groups[0]['lr'] = args.lr * min(1., .2+step/25) * (1-.8*step/args.steps)
        optimizer.zero_grad(set_to_none=True)
        vector, table = decode()
        loss = objective.loss(objective.native(vector_delta), table, vector, 30., extra_guard=focus_guard)
        if step == 1:
            initial_loss = float(loss.detach().cpu())
        loss.backward()
        optimizer.step()
        with torch.no_grad():
            grid_delta.clamp_((-64-origin)/SCALES[-1], (63-origin)/SCALES[-1])
        checkpoint = step in (1, 5, 10, args.steps) or step % args.checkpoint == 0
        if not checkpoint:
            continue
        with torch.no_grad():
            vector, table = decode()
            value = float(objective.loss(objective.native(vector_delta), table, vector, 30., extra_guard=focus_guard).cpu())
            if not np.isfinite(value):
                raise ValueError(f'第 {step} 步出现非有限 Loss')
            entry = grid_entry(projected(seed, smooth.params(vector.cpu().numpy().astype(float))),
                               np.rint(table.cpu().numpy()).astype(int))
        trials = [consider(blend_entries(seed, entry, f), f'{step}:joint:{f:g}') for f in FRACTIONS]
        # 记录网格单独保留时的真实效果。联合更新和导出候选的筛选相互独立。
        grid_only = grid_entry(seed, grid_from(entry))
        trials.extend(consider(blend_entries(seed, grid_only, f), f'{step}:grid:{f:g}')
                      for f in (.25, .0625, .015625))
        if proposal_hook is not None and step % (args.checkpoint*2) == 0:
            # 分别试探原生块与网格的保留幅度，避免量化后仍强制两者同幅。
            for native_f, grid_f in ((.015625, .125), (.0625, .25)):
                native = blend_entries(seed, entry, native_f)
                table = grid_from(blend_entries(seed, grid_only, grid_f))
                trials.append(consider(grid_entry(native, table), f'{step}:mixed:{native_f:g}:{grid_f:g}'))
        records.append(dict(step=step, loss=value, trials=[row['sha256'] for row in trials]))
        if step % args.checkpoint == 0 or step == args.steps:
            # 用当前量化原生配方更新连续模型的局部偏移。验证行不参与 GPU 目标。
            anchor_model, anchor = scorer.native(entry)
            anchor = anchor[selector]
            if focus_inputs is not None:
                anchor = np.concatenate((anchor, native_rgb(anchor_model, focus_inputs)))
            with torch.no_grad():
                objective.offset = tools.tensor(anchor)-objective.gpu.render(vector)/16383
        if step % (args.checkpoint*2) == 0 or step == args.steps:
            print(f'{step}/{args.steps} loss={value:.8g} accepted={best.label} '
                  f'RGB={best.metrics["rgb_rmse"]:.5f} DE={best.metrics["delta_e00_mean"]:.5f}', flush=True)
    result = dict(initial_loss=initial_loss, seconds=perf_counter()-started, steps=args.steps,
        checkpoints=records, candidates=list(evaluations.values()))
    if focus:
        result['focused_ramps'] = dict(axes=list(focus_axes), rows=len(focus_inputs),
            sha256=[bank.sha256 for bank in focus_banks], p95_margin_fraction=.25)
    if not finish_polish:
        return best, result
    # 用 GPU 轨迹给整数量化微调排序，再走同一套独立渐变与 BIN 回读验收。
    # 从已验收候选或冻结基准起步，保留此次微调与 GPU 检查点的来源区别。
    _, polish_base = scorer.native(best.entry)
    train_base, valid_base, probes = np.split(polish_base, (scorer.ntrain, scorer.ntrain+scorer.nvalid))
    limits = polish_limits(start, margins, bank)
    polish_started = perf_counter()
    polish, moves = polish_grid(grid_from(best.entry), train_base, data['target'][train_rows],
        gray[train_rows], probes, data['response'], bank, data['strength'], limits,
        proposal_table=grid_from(entry), deadline=polish_started+args.polish_seconds,
        validation_data=(valid_base, data['target'][data['validation']]), protect_color_p95=True)
    if moves:
        consider(grid_entry(best.entry, polish), 'gpu-guided-integer-polish')
    result.update(seconds=perf_counter()-started, candidates=list(evaluations.values()),
                  integer_polish=dict(moves=moves, seconds=perf_counter()-polish_started))
    return best, result


def replay_polish(seed, saved, data, scorer, start, margins, banks, seconds):
    """保留原 GPU 轨迹，微调每一步都对两套独立渐变验收。"""
    context, bank, response = data['context'], data['bank'], scorer.response
    model, _ = scorer.native(seed)
    ramp_inputs = [ramp.inputs(context.base) for ramp in banks]
    references = [ramp.jumps(render(model, inputs, response, seed)) for ramp, inputs in zip(banks, ramp_inputs)]
    splits = np.cumsum([len(inputs) for inputs in ramp_inputs])[:-1]
    events = []
    best = start

    def inspect(pixels):
        outputs = np.split(pixels, splits)
        return [ramp_report(reference, ramp.jumps(value), margins)[1]
                for ramp, reference, value in zip(banks, references, outputs)]

    def consider(entry, label):
        nonlocal best
        candidate = scorer.score(entry, label)
        failures = metric_failures(candidate.metrics, start.metrics, margins)
        if not failures:
            candidate_model, _ = scorer.native(candidate.entry)
            pixels = render(candidate_model, np.concatenate(ramp_inputs), response, candidate.entry)
            failures.extend(f'screen{index+1}:{reason}' for index, results in enumerate(inspect(pixels))
                            for reason in results)
        events.append(dict(label=label, sha256=candidate.sha256, rejected_by=failures, validation=candidate.metrics))
        if not failures and candidate.metrics['color_score'] < best.metrics['color_score']:
            best = candidate

    for fraction in (1., .75, .5, .25):
        consider(blend_entries(seed, saved, fraction), f'previous-gpu:{fraction:g}')

    limits = polish_limits(start, margins, bank)
    began = perf_counter()
    moves = []
    # 同时给冻结基准和通过筛选的联合参数一次机会，防止一条路径吃完所有预算。
    parents = [start] if start.sha256 == best.sha256 else [start, best]
    for index, parent in enumerate(parents):
        parent_model, full = scorer.native(parent.entry)
        train, valid, probes = np.split(full, (scorer.ntrain, scorer.ntrain+scorer.nvalid))
        screen_base = native_rgb(parent_model, np.concatenate(ramp_inputs))
        table, count = polish_grid(grid_from(parent.entry), train, data['target'][data['train']],
            data['gray'][data['train']], probes, data['response'], bank, data['strength'], limits,
            proposal_table=grid_from(saved) if not np.array_equal(grid_from(parent.entry), grid_from(saved)) else None,
            deadline=began+seconds*(index+1)/len(parents),
            validation_data=(valid, data['target'][data['validation']]), protect_color_p95=True,
            ramp_screen=(screen_base, lambda pixels: not any(inspect(pixels))))
        moves.append(count)
        if count:
            consider(grid_entry(parent.entry, table), f'per-move-ramp-polish:{parent.label}')
    return best, dict(seconds=perf_counter()-began, moves=moves, events=events,
                      ramp_hashes=[ramp.sha256 for ramp in banks])


def write_bin(path, entry, version):
    blob = core.compiler.pack(core.compiler.config([entry], version))
    path.write_bytes(blob)
    readback = core.compiler.unpack(path.read_bytes())
    if core.compiler.pack(readback) != blob:
        raise ValueError('BIN 回读与落盘字节不一致')
    return readback, core.sha(blob)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('frozen', type=Path)
    parser.add_argument('previous', type=Path)
    parser.add_argument('photos', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--steps', type=int, default=600)
    parser.add_argument('--lr', type=float, default=.006)
    parser.add_argument('--checkpoint', type=int, default=25)
    parser.add_argument('--polish-seconds', type=float, default=15)
    parser.add_argument('--replay', type=Path, help='复用五款 GPU 训练记录，逐步约束整数微调')
    parser.add_argument('--cases', type=int, nargs='+', default=[1, 2, 3, 4, 5])
    args = parser.parse_args()
    if not available() or min(args.steps, args.lr, args.checkpoint, args.polish_seconds) <= 0:
        parser.error('需要可用的 Apple Metal/MPS 和正的训练预算')
    manifest = json.loads((args.photos/'manifest.json').read_text())
    frozen = json.loads(args.previous.read_text())['cases']
    if manifest['filters'] != [row['name'] for row in frozen]:
        parser.error('照片与冻结色卡的滤镜顺序不一致')
    args.output.mkdir(parents=True, exist_ok=False)
    calibration, screen, blind = [RampBank(phase) for phase in (.17, .53, .87)]
    extra_screen, extra_blind = (RampBank(.31), RampBank(.91)) if args.replay else (None, None)
    prior = json.loads((args.replay/'comparison.json').read_text()) if args.replay else None
    if prior and (len(prior['cases']) != 5 or prior['backend']['backend'] != 'Apple Metal/MPS'):
        raise ValueError('复验需要完整的五款 GPU 训练记录')
    report = dict(backend=policy(), full_batch=True, learning_rate_peak=args.lr, optimizer='Adam',
        steps=args.steps, group_scales=SCALES, checkpoint=args.checkpoint, candidate_fractions=FRACTIONS,
        integer_polish_seconds=args.polish_seconds,
        perceptual_weight=.35, ramp_hashes=dict(calibration=calibration.sha256, screen=screen.sha256, blind=blind.sha256),
        scenes=manifest['scenes'], long_edge=manifest['long_edge'], test_used_for_selection=False,
        validation_used_for_gradient=False, blind_photo_used_for_selection=False, cases=[])
    if prior:
        report.update(replay_source=str(args.replay.resolve()), steps=prior['steps'],
                      learning_rate_peak=prior['learning_rate_peak'], checkpoint=prior['checkpoint'])
        report['ramp_hashes'].update(extra_screen=extra_screen.sha256, extra_blind=extra_blind.sha256)
    entries, originals = [], []
    for number in args.cases:
        source = args.frozen/f'{number:02d}'
        original = core.compiler.unpack((source/'legacy.BIN').read_bytes())
        seed, = original['entries']
        response_spec = json.loads((source/'response.json').read_text())
        data = inputs_for(source/'job', original, response_spec)
        data['perceptual'] = .35
        heldout = core.sha(data['inputs'][data['test']].tobytes())
        expected = frozen[number-1]
        if (seed['full_name'], heldout, int(data['test'].sum())) != (
                expected['name'], expected['holdout_sha256'], expected['test_samples']):
            raise ValueError('留出集与上轮对照不一致')
        print(seed['full_name'], '回放整数微调' if prior else f'{len(data["train"])} 个色块全批训练', flush=True)
        context = data['context']
        model = context.build(**core.slot_native_parameters(context, seed))
        response = get(response_spec)
        if prior:
            cached = args.replay/f'{number:02d}'
            margins = json.loads((cached/'calibration.json').read_text())
            if margins['ramp_sha256'] != calibration.sha256:
                raise ValueError('校准渐变与原实验不一致')
        else:
            photo_rows = ((scene, render(model, inputs, response, seed), target)
                          for scene, inputs, target in photo_samples(args.photos, manifest, number, 'calibration'))
            margins = calibrate(calibration, render(model, calibration.inputs(context.base), response, seed), list(photo_rows))
        folder = args.output/f'{number:02d}'
        folder.mkdir()
        save(folder/'calibration.json', margins)
        score_keys = ('context', 'inputs', 'target', 'train', 'gray', 'validation', 'response', 'bank', 'strength')
        scorer = RecipeScorer(original, **{key: data[key] for key in score_keys}, perceptual=.35)
        start = scorer.score(seed, 'baseline')
        if prior:
            row = prior['cases'][number-1]
            saved_blob = (cached/'R5NATIVE.BIN').read_bytes()
            if (heldout != row['holdout_sha256'] or start.sha256 != row['baseline_sha256']
                    or core.sha(saved_blob) != row['selected_sha256']):
                raise ValueError('回放源与冻结配方、留出集或 GPU 候选不一致')
            saved, = core.compiler.unpack(saved_blob)['entries']
            selected, refinement = replay_polish(seed, saved, data, scorer, start, margins,
                                                   (screen, extra_screen), args.polish_seconds)
            audit = dict(row['training'], per_move_ramp_polish=refinement)
        else:
            screen_inputs = screen.inputs(context.base)
            screen_start = screen.jumps(render(model, screen_inputs, response, seed))
            selected, audit = train(seed, data, scorer, start, margins, screen, screen_inputs, screen_start, args)
        version = core.compiler.format_version(original)
        final, digest = write_bin(folder/'R5NATIVE.BIN', selected.entry, version)
        write_bin(folder/'legacy.BIN', seed, version)
        if digest != selected.sha256:
            raise ValueError('回读散列与评分候选不同')
        # 重建评分器独立确认已选 BIN。留出色卡、照片和最终渐变只做复验。
        final_scorer = RecipeScorer(original, **{key: data[key] for key in score_keys}, perceptual=.35)
        exact = final_scorer.score(final['entries'][0], 'readback')
        if selected.sha256 != start.sha256 and metric_failures(exact.metrics, start.metrics, margins):
            raise ValueError('候选回读未通过冻结色卡门槛')
        final_model, _ = final_scorer.native(exact.entry)
        blind_inputs = blind.inputs(context.base)
        before = render(model, blind_inputs, response, seed)
        after = render(final_model, blind_inputs, response, exact.entry)
        blind_ramps, blind_failures = ramp_report(blind.jumps(before), blind.jumps(after), margins)
        ramps_png(folder/'blind-ramps.png', blind, before, after)
        second_ramps = None
        if extra_blind is not None:
            extra_inputs = extra_blind.inputs(context.base)
            first = render(model, extra_inputs, response, seed)
            second = render(final_model, extra_inputs, response, exact.entry)
            second_ramps, second_failures = ramp_report(extra_blind.jumps(first), extra_blind.jumps(second), margins)
            blind_failures.extend(f'extra:{reason}' for reason in second_failures)
            ramps_png(folder/'extra-blind-ramps.png', extra_blind, first, second)
        photos = [dict(scene=scene, samples=len(target), baseline=color_metrics(render(model, inputs, response, seed), target),
                       selected=color_metrics(render(final_model, inputs, response, exact.entry), target))
                  for scene, inputs, target in photo_samples(args.photos, manifest, number, 'blind')]
        case = dict(name=seed['full_name'], training_samples=len(data['train']), test_samples=int(data['test'].sum()),
            holdout_sha256=heldout, baseline_sha256=start.sha256, selected_sha256=digest, selected=selected.label,
            baseline_validation=start.metrics, selected_validation=exact.metrics, blind_ramps=blind_ramps,
            blind_ramp_failures=blind_failures, extra_blind_ramps=second_ramps, baseline_test=measure(original, data, 'test'),
            selected_test=measure(final, data, 'test'), blind_photos=photos, training=audit)
        save(folder/'comparison.json', case)
        save(folder/'response.json', response_spec)
        report['cases'].append(case)
        entries.extend(final['entries'])
        originals.extend(original['entries'])
        for filename, values in (('R5NATIVE.BIN', entries), ('legacy.BIN', originals)):
            blob = core.compiler.pack(core.compiler.config(values, 5))
            if core.compiler.unpack(blob)['entries'] != values:
                raise ValueError('合并 BIN 的槽位回读失败')
            (args.output/filename).write_bytes(blob)
        save(args.output/'comparison.json', report)
        print(f'完成 {case["name"]} selected={selected.label} blind_ramp_failures={len(blind_failures)}', flush=True)


if __name__ == '__main__':
    main()
