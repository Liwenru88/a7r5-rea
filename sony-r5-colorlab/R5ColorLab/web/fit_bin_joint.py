"""在测量色彩模型上交替拟合 BIN 原生参数与整数网格。"""
import argparse
import copy
import json
from pathlib import Path
import time
import struct

import numpy as np

import baseline
import core
import grid_distillation
from compute_backend import render_native
from continuity_grid import constrain
from edit_parameter_context import ParameterContext, RuntimeColor
from fit_anchor_native import SmoothNative, training_plan, vector_for
from gpu_runtime import available, cpu_reference
from integer_grid import (SATURATION_AXES, SATURATION_LIMITS, TRANSITION_LIMITS,
                          guard_failures, polish_grid, repair_grid, selection_failures, transition_metrics)
from optimizer_policy import display_cost_rows
from output_continuity import ProbeBank
from parameter_smoothing import grid_cost, native_cost
from patch_sampling import center_mean
from perceptual import de2000, to_lab
from precision_sampling import coarse
from residual_grid import evaluate
from training_policy import group_importance


def grid_from(entry):
    return np.asarray(entry['grid_5x9x9']['coefficients'], dtype=np.int8).reshape(3, 405).T


def projected(seed, parameters):
    """把浮点求解器的候选投影到 BIN 的 B 端点及整数精度。"""
    entry = copy.deepcopy(seed)
    cc = parameters['cc1']
    base = [int(cc[i]) for i in (1, 2, 3, 0)]
    base += [min(1023, (int(cc[i])+1)//2) for i in (5, 6, 7, 4)]
    payload = parameters['matrix_payload']
    matrix = [[struct.unpack_from('<h', payload, 24+2*(16*k+(s^1)))[0] >> 2
               for k in range(6)] for s in range(16)]
    end = entry['gamma_native_129'][-1]
    entry['gamma_native_129'] = [min(end, (int(v)+1)//2) for v in parameters['gamma_y']] + [end]
    entry['cc1_delta'][0] = base
    entry['block13'] = [copy.deepcopy(matrix) for _ in range(3)]
    return entry


def refine_entry(entry, score, gamma_step):
    """在合法 BIN 字段上逐项搜索，保留零起点、单调性和 Gamma 端点。"""
    entry = copy.deepcopy(entry)
    gamma, cc, matrix = entry['gamma_native_129'], entry['cc1_delta'][0], entry['block13']
    before = best = score(entry)
    accepted = dict(gamma=0, cc1=0, matrix=0)

    def search(kind, arrays, index, step, lower, upper):
        nonlocal best
        previous = winner = arrays[0][index]
        for value in (previous-step, previous+step):
            if not lower <= value <= upper:
                continue
            for array in arrays:
                array[index] = value
            cost = score(entry)
            if cost < best-1e-10:
                best, winner = cost, value
        for array in arrays:
            array[index] = winner
        accepted[kind] += int(winner != previous)

    for index in range(8):
        search('cc1', [cc], index, 4, -1024 if index < 4 else 0, 1023)
    for sector in range(16):
        for index in range(6):
            search('matrix', [m[sector] for m in matrix], index, 1, -8192, 8191)
    for index in range(1, 128):
        search('gamma', [gamma], index, gamma_step, gamma[index-1], gamma[index+1])
    return entry, dict(before=before, after=best, accepted=accepted)


def blend_entries(seed, proposal, fraction):
    """沿两份合法配方的连线取整，保持 Gamma 单调和各字段边界。"""
    entry = copy.deepcopy(seed)
    for field in ('gamma_native_129', 'cc1_delta', 'block13'):
        base = np.asarray(seed[field])
        entry[field] = np.rint(base + fraction*(np.asarray(proposal[field])-base)).astype(int).tolist()
    base = grid_from(seed).astype(int)
    grid = np.rint(base + fraction*(grid_from(proposal)-base)).astype(np.int8)
    entry['grid_5x9x9']['coefficients'] = grid.T.reshape(3,5,9,9).tolist()
    return entry


def fit(job, key, output, rounds=2, evaluations=24, neural_start=None, neural_grid=False,
        seconds=None, *, integer_start=None, candidate_source=None):
    job, output = Path(job), Path(output)
    if output.exists():
        raise FileExistsError(output)
    if rounds < 1 or evaluations < 2:
        raise ValueError('至少需要一轮交替和两次浮点评估')
    if integer_start is not None and neural_start is not None:
        raise ValueError('--integer-start 和 --neural-start 互斥')
    if candidate_source is not None and (integer_start is not None or neural_start is not None):
        raise ValueError('--candidate 与整数或神经网络起点互斥')
    if neural_grid and neural_start is None:
        raise ValueError('--neural-grid 需要 --neural-start')
    if seconds is not None and (not (integer_start is not None or neural_grid)
                                or not np.isfinite(seconds) or seconds <= 0):
        raise ValueError('--seconds 需要 --integer-start 或 --neural-grid，以及正数秒数')
    # 用已经完成的分阶段任务作共同起点，并校验原始配方与响应的身份。
    source, _, _ = grid_distillation.load_result(job, key)
    seed_config = grid_distillation.firmware_config(job, key, configuration_only=True)
    version = core.compiler.format_version(seed_config)
    seed = seed_config['entries'][0]
    recipe, _ = baseline.read_job(job)
    if (recipe.get('white_balance', {}).get('enabled') or any(any(row) for row in seed['cc1_delta'][1:])
            or any(m != seed['block13'][0] for m in seed['block13'][1:])):
        raise ValueError('联合拟合要求关闭实验白平衡，且三个照明端点共享参数')
    response = source['identity']['response']
    if not isinstance(response, dict):
        raise ValueError('请选择使用实测网格响应的任务')
    capture, context_id = baseline.for_job(job)
    context = ParameterContext(RuntimeColor.from_capture(capture, context_id))
    fitting = recipe['fitting']
    options = fitting['search_options']
    smoothing, continuity_strength = options['parameter_smoothing'], options['output_continuity']
    perceptual = options['perceptual_weight']
    importance = group_importance(fitting['group_total_weights'])
    pairs_path = job/'pairs.npz'
    with np.load(pairs_path, allow_pickle=False) as data:
        arrays = {name: data[name] for name in data.files}
    split = arrays['split']
    inputs, target = arrays['input'], arrays['0_target']/16383
    validation, test = split == 'valid', split == 'test'
    if not validation.any() or not test.any():
        raise ValueError('需要独立的验证集和测试集')
    sector = arrays['sector16_index']
    full_random = np.flatnonzero((split == 'train') & (arrays['anchor_index'] < 0) & (sector < 0))
    # 原生搜索保留全部锚点，普通样本在训练色域分层后均匀抽样。
    sample = coarse(arrays, per_bin=1)
    sample = sample[np.linspace(0, len(sample)-1, min(1024, len(sample)), dtype=int)]

    def plan(random_rows):
        train, _, _, weights = training_plan(split, arrays['anchor_index'], importance, sector,
            arrays.get('baseline_tonal_index'), random_rows, arrays.get('sample_kind'), options)
        return train, weights

    train, train_weights = plan(full_random)
    search_rows, search_weights = plan(sample)
    bank = ProbeBank()
    probes = bank.inputs(context.base)
    # 提高饱和度探针的训练权重，基线与候选的验收仍用原探针权重。
    saturation_bank = copy.copy(bank)
    saturation_bank.mass = bank.mass.copy()
    offset = 0
    for axis, count in bank.groups:
        if axis in SATURATION_AXES:
            saturation_bank.mass[offset:offset+count] *= 4
        offset += count
    gray_ids = arrays['anchor_index']
    gray_rows = np.flatnonzero((gray_ids >= 4) & (gray_ids < 260))
    gray_rows = gray_rows[np.argsort(gray_ids[gray_rows])]
    if len(gray_rows) != 256 or not np.all(split[gray_rows] == 'train'):
        raise ValueError('缺少完整的训练灰阶锚点')
    gray_train = np.isin(train, gray_rows)
    # 即使旧任务未启用连续性损失，对照仍使用正强度测量过渡。
    continuity_strength = continuity_strength or 30
    gray_target = np.floor(np.clip(target[gray_rows], 0, 1)*255+.5)
    validation_target = np.floor(np.clip(target[validation], 0, 1)*255+.5)
    validation_lab = to_lab(validation_target)


    def native(entry, x):
        parameters = core.slot_native_parameters(context, entry)
        model = context.build(**parameters)
        return center_mean(render_native(model, x))/16383

    def render(entry, x):
        return evaluate(native(entry, x), grid_from(entry), response)

    def score(entry, indices, weights=None, include_continuity=False):
        with cpu_reference():
            prediction = render(entry, inputs[indices])
            loss = np.average(display_cost_rows(prediction, target[indices], perceptual), weights=weights)
            loss += native_cost(core.slot_native_parameters(context, entry), context.axis, smoothing)
            loss += grid_cost(grid_from(entry), smoothing, response)
            if include_continuity:
                loss += bank.cost(render(entry, probes), continuity_strength)
        return float(loss)

    def roundtrip(entry):
        payload = core.compiler.pack(core.compiler.config([entry], version))
        return core.compiler.unpack(payload)['entries'][0], payload

    def selection_metrics(entry, render_fixed=None):
        with cpu_reference():
            if render_fixed is None:
                outputs = (render(entry, inputs[gray_rows]), render(entry, inputs[validation]), render(entry, probes))
            else:
                outputs = render_fixed(grid_from(entry))
            gray_rgb, validation_rgb, probe_rgb = outputs
            gray = np.floor(gray_rgb*255+.5)
            predicted = np.floor(validation_rgb*255+.5)
            mse = float(np.mean((predicted-validation_target)**2))
            de = de2000(to_lab(predicted), validation_lab)
            transition = transition_metrics(bank, probe_rgb, continuity_strength)
            return dict(color_score=mse+perceptual*float(np.mean((2.55*de)**2)),
                rgb_rmse=float(np.sqrt(mse)), delta_e00_mean=float(de.mean()),
                gray_rmse=float(np.sqrt(np.mean((gray-gray_target)**2))),
                **transition)

    seed, baseline_binary = roundtrip(seed)
    current = seed
    baseline_metrics = selected_metrics = selection_metrics(seed)
    audit = []
    candidate = seed
    refinement = {}
    pairs_sha = source['identity']['pairs_sha256']
    guarded_candidate = None
    if candidate_source is not None:
        candidate_job, candidate_key = candidate_source
        candidate_report, _, _ = grid_distillation.load_result(candidate_job, candidate_key)
        identity = candidate_report['identity']
        for field in ('pairs_sha256', 'response', 'response_runtime_sha256', 'target_source'):
            if identity[field] != source['identity'][field]:
                raise ValueError('量化候选与基线的训练数据、目标或响应不一致')
        if baseline.for_job(candidate_job) != (capture, context_id):
            raise ValueError('量化候选与基线的原生前端不一致')
        config = grid_distillation.firmware_config(candidate_job, candidate_key, configuration_only=True)
        proposal, = config['entries']
        if core.compiler.format_version(config) != version:
            raise ValueError('量化候选与基线的 BIN 格式不一致')
        mutable_fields = {'gamma_native_129', 'cc1_delta', 'block13', 'grid_5x9x9'}
        if ({k: v for k, v in proposal.items() if k not in mutable_fields}
                != {k: v for k, v in seed.items() if k not in mutable_fields}
                or proposal['gamma_native_129'][-1] != seed['gamma_native_129'][-1]):
            raise ValueError('量化候选与基线的槽位、端点或其他固定参数不一致')

        from measured_response import get
        response_model = get(response)
        candidate, raw_binary = roundtrip(proposal)
        trials, seen = [], {baseline_binary}
        winner = None
        repairable = []
        prior_metrics = None

        def consider(label, entry, render_fixed=None, **details):
            nonlocal current, selected_metrics, winner
            entry, payload = roundtrip(entry)
            if payload in seen:
                return
            seen.add(payload)
            metrics = selection_metrics(entry, render_fixed)
            failures = selection_failures(metrics, baseline_metrics, selected_metrics['color_score'])
            if prior_metrics is not None:
                for name in ('rgb_rmse', 'delta_e00_mean'):
                    if metrics[name] >= prior_metrics[name]-1e-10:
                        failures.append('prior_selection_'+name)
            trial = dict(stage=label, bin_sha256=core.sha(payload), metrics=metrics,
                         rejected_by=failures, **details)
            trials.append(trial)
            if label in ('candidate-blend', 'candidate-recombined'):
                violations = guard_failures(metrics, baseline_metrics)
                if violations and all(metrics[k]<baseline_metrics[k] for k in ('rgb_rmse','delta_e00_mean')):
                    distance = sum((metrics[k]-baseline_metrics[k])/max(baseline_metrics[k], .1)
                                   for k in violations)
                    repairable.append((entry, trial, len(violations), distance))
            if not failures:
                current, selected_metrics, winner = entry, metrics, trial

        def with_grid(entry, table):
            return {**entry, 'grid_5x9x9': {'coefficients': table.T.reshape(3, 5, 9, 9).tolist()}}

        # 原生参数和整数网格分别试探，避免两者必须以同一比例回退。
        fractions = (1., .875, .75, .625, .5, .375, .25, .125, .0625, 0.)
        seed_grid = grid_from(seed).astype(int)
        change = grid_from(candidate).astype(int)-seed_grid
        for native_fraction in fractions:
            entry = blend_entries(seed, candidate, native_fraction)
            with cpu_reference():
                bases = [native(entry, x) for x in (inputs[gray_rows], inputs[validation], probes)]

            def render_fixed(table):
                return [response_model.predict_cpu(base, table) for base in bases]

            for grid_fraction in fractions:
                table = np.rint(seed_grid+grid_fraction*change).astype(np.int8)
                consider('candidate-blend', with_grid(entry, table), render_fixed,
                         native_fraction=native_fraction, grid_fraction=grid_fraction)
        blend_winner = winner
        # 整体混合未通过时，按参数块吸收候选改动。每步仍验收整份 BIN。
        if winner is None:
            for field, blocks in (
                ('cc1_delta', [slice(0, 1)]),
                ('block13', [(slice(None), slice(sector, sector+1)) for sector in range(16)]),
                ('gamma_native_129', [slice(i, min(i+8, 128)) for i in range(1, 128, 8)]),
            ):
                goal = np.asarray(candidate[field])
                for block in blocks:
                    entry = current
                    start_values = np.asarray(entry[field])
                    for fraction in (.125, .25, .5, 1.):
                        values = start_values.copy()
                        values[block] = np.rint(start_values[block]+fraction*(goal[block]-start_values[block]))
                        if field == 'gamma_native_129' and np.any(np.diff(values) < 0):
                            continue
                        consider('candidate-native-block', {**entry, field: values.tolist()},
                                 field=field, fraction=fraction)
        # 只尝试朝 2000 步候选的系数移动，逐项检查固定门槛。
        with cpu_reference():
            source_train = native(current, inputs[train])
            source_validation = native(current, inputs[validation])
            source_probes = native(current, probes)
            for index in range(rounds):
                table, moves = polish_grid(grid_from(current), source_train, target[train],
                    gray_train, source_probes, response, bank, continuity_strength, baseline_metrics,
                    proposal_table=grid_from(candidate), proposal_only=True,
                    validation_data=(source_validation, target[validation]), step_sizes=(1, 2))
                previous = winner
                if moves:
                    consider('guarded-integer-polish', with_grid(current, table), sweep=index+1,
                             proposed_moves=moves)
                if winner is previous:
                    break
        before_targeted = winner
        prior_entry, prior_metrics = current, selected_metrics
        # 超限可能来自单一原生模块。先分别回调原生参数块，保留候选网格。
        by_color = sorted(repairable, key=lambda item: item[1]['metrics']['color_score'])
        by_guard = sorted(repairable, key=lambda item: (item[2], item[1]['metrics']['color_score']))
        recombined = set()
        for entry, trial, _, _ in by_color[:1]+by_guard[:1]:
            digest = trial['bin_sha256']
            if digest in recombined:
                continue
            recombined.add(digest)
            for fraction in (0., .25, .5, .75):
                native_part = blend_entries(seed, entry, fraction)
                for field in ('cc1_delta', 'block13', 'gamma_native_129'):
                    consider('candidate-recombined', {**entry, field: native_part[field]},
                             source_bin_sha256=digest, field=field, fraction=fraction)
        before_repair = winner
        # 同时尝试色差收益最大的配方和最接近过渡门槛的配方。
        by_color = sorted(repairable, key=lambda item: item[1]['metrics']['color_score'])
        by_guard = sorted(repairable, key=lambda item: (item[2], item[3]))
        repair_attempts = []
        repair_seen = set()
        for entry, trial, _, _ in by_color[:2]+by_guard[:2]:
            digest = trial['bin_sha256']
            if digest in repair_seen or trial['metrics']['color_score'] >= selected_metrics['color_score']:
                continue
            repair_seen.add(digest)
            with cpu_reference():
                table, moves = repair_grid(grid_from(entry), native(entry, inputs[gray_rows]),
                    target[gray_rows], native(entry, probes), response, bank, continuity_strength, baseline_metrics)
            repair_attempts.append(dict(source_bin_sha256=digest, moves=moves))
            if moves:
                consider('candidate-transition-repair', with_grid(entry, table),
                         source_bin_sha256=digest, proposed_moves=moves)
        # 以已通过验收的配方为起点，允许用反方向或邻近系数补偿局部色差。
        if winner is not None:
            with cpu_reference():
                source_train = native(current, inputs[train])
                source_validation = native(current, inputs[validation])
                source_probes = native(current, probes)
                for index in range(min(rounds, 3)):
                    table, moves = polish_grid(grid_from(current), source_train, target[train],
                        gray_train, source_probes, response, bank, continuity_strength, baseline_metrics,
                        proposal_table=grid_from(candidate),
                        validation_data=(source_validation, target[validation]), step_sizes=(1, 2))
                    previous = winner
                    if moves:
                        consider('candidate-color-polish', with_grid(current, table), sweep=index+1,
                                 proposed_moves=moves)
                    if winner is previous:
                        break
        # 最终直接回读整份 BIN，复核缓存筛选的结果，再渲染独立测试集。
        exact = selection_metrics(current)
        if exact != selected_metrics:
            raise ValueError('量化候选缓存与整份 BIN 的 CPU 参考验收结果不一致')
        guarded_candidate = dict(source_key=candidate_key, source_bin_sha256=core.sha(raw_binary),
                                 blend_selected=blend_winner, before_targeted=before_targeted,
                                 before_repair=before_repair,
                                 repair_attempts=repair_attempts, selected=winner, candidates=trials)

    start = integer_start if integer_start is not None else neural_start
    if start is not None:
        folder = Path(start)
        saved = json.loads((folder/'comparison.json').read_bytes())
        incumbent_binary = (folder/'R5NATIVE.BIN').read_bytes()
        if (saved['pairs_sha256'] != pairs_sha or saved['grid_source'] != key
                or saved['baseline_bin_sha256'] != core.sha(baseline_binary)
                or saved['joint_bin_sha256'] != core.sha(incumbent_binary)):
            raise ValueError('微调起点与色卡、基线或配方摘要不一致')
        config = core.compiler.unpack(incumbent_binary)
        if (len(config['entries']) != 1 or core.compiler.format_version(config) != version
                or config['entries'][0]['number'] != seed['number']):
            raise ValueError('微调需要同一版本和槽号的单槽 BIN')
        incumbent = config['entries'][0]
        limits = selection_metrics(incumbent)
        if selection_failures(limits, baseline_metrics, baseline_metrics['color_score']):
            raise ValueError('实验起点必须优于原方案，并通过灰阶和连续性门槛')
        current, selected_metrics = incumbent, limits
        source_train, source_probes = native(incumbent, inputs[train]), native(incumbent, probes)
        render_fixed = None
        if seconds is not None:
            from measured_response import get
            model = get(response)
            with cpu_reference():
                bases = [native(incumbent, x) for x in (inputs[gray_rows], inputs[validation], probes)]
            stencils = [(base, *model.stencil(base)[1:], model.response(base)) for base in bases]

            def render_fixed(table):
                return [np.clip(base + np.einsum('nc,nco->no',
                        (table[ids]*weights[..., None]).sum(axis=1), mixing), 0, 1)
                        for base, ids, weights, mixing in stencils]

            if selection_metrics(incumbent, render_fixed) != limits:
                raise ValueError('固定网格验收缓存与 CPU 参考结果不一致')
        if neural_grid:
            saturation_rows = np.repeat([axis in SATURATION_AXES for axis, _ in bank.groups],
                                        [count for _, count in bank.groups])
            probe_rows, triplets = np.unique(bank.triplets[saturation_rows], return_inverse=True)
            saturation_probes = source_probes[probe_rows], triplets.reshape(-1, 3), bank.allowance[saturation_rows]
        arms = ('control',) if integer_start is not None else ('control', 'mlp')
        if neural_start is not None:
            from neural_residual import fit_grid_update, fit_residual
        for arm in arms:
            entry, best_metrics = incumbent, limits
            records = []
            started = time.perf_counter()
            deadline = None if seconds is None else started+seconds
            # 给最后一次 BIN 量化和验收预留时间，两路使用相同余量。
            polish_deadline = None if deadline is None else deadline-.16
            for index in range(rounds):
                if deadline is not None and time.perf_counter() >= polish_deadline-.05:
                    break
                print(f'{arm} {index+1}/{rounds}：训练集整数网格搜索', flush=True)
                hint = teacher = predicted_table = None
                trials = []
                neural_seconds = 0.

                def consider(stage, start, proposal):
                    nonlocal entry, best_metrics
                    fractions = (.5, .375, .25, .1875) if stage == 'mlp-grid' else (1., .75, .5, .25)
                    for fraction in fractions:
                        if deadline is not None and time.perf_counter() >= deadline:
                            break
                        trial, _ = roundtrip(blend_entries(start, proposal, fraction))
                        metrics = selection_metrics(trial, render_fixed)
                        if deadline is not None and time.perf_counter() > deadline:
                            break
                        failures = selection_failures(metrics, limits, best_metrics['color_score'])
                        trials.append(dict(stage=stage, fraction=fraction, **metrics, rejected_by=failures))
                        if not failures:
                            entry, best_metrics = trial, metrics

                def with_table(table):
                    return {**entry, 'grid_5x9x9': {'coefficients': table.T.reshape(3,5,9,9).tolist()}}

                if arm == 'mlp':
                    if neural_grid:
                        neural_started = time.perf_counter()
                        if deadline is None or neural_started < deadline-1.2:
                            predicted_table, teacher = fit_grid_update(
                                source_train, target[train], grid_from(entry), response,
                                gray_train, saturation_probes, seed=42+index,
                                deadline=None if deadline is None else deadline-.8)
                            neural_seconds = time.perf_counter()-neural_started
                            consider('mlp-grid', entry, with_table(predicted_table))
                    else:
                        with cpu_reference():
                            rendered = evaluate(source_train, grid_from(entry), response)
                        predicted, teacher = fit_residual(source_train, rendered, target[train], seed=42+index)
                        hint = .5*predicted+.5*target[train]
                moves = 0
                if deadline is None or time.perf_counter() < polish_deadline-.05:
                    table, moves = polish_grid(grid_from(entry), source_train, target[train], gray_train,
                        source_probes, response, bank, continuity_strength, limits,
                        proposal_target=hint, proposal_table=predicted_table, deadline=polish_deadline)
                    consider('integer-polish', entry, with_table(table))
                records.append(dict(round=index+1, teacher=teacher, neural_seconds=neural_seconds,
                                    moves=moves, candidates=trials))
                print(f'  {arm} 验证评分 {best_metrics["color_score"]:.6f}，整数搜索接受 {moves} 步', flush=True)
            refinement[arm] = dict(entry=entry, validation=best_metrics, rounds=records, seconds=time.perf_counter()-started)
            if best_metrics['color_score'] < selected_metrics['color_score']:
                current, selected_metrics = entry, best_metrics
        refinement['incumbent'] = dict(entry=incumbent, validation=limits)
        candidate = current

    for index in range(0 if refinement or guarded_candidate is not None else rounds):
        print(f'联合拟合 {index+1}/{rounds}：固定整数网格，优化原生参数', flush=True)
        candidate = current
        gpu_audit = None
        if available():
            from compressed_alternation import optimize_native
            warm = ParameterContext(context.build(**core.slot_native_parameters(context, current)))
            vector = vector_for(warm)
            smooth = SmoothNative(context, inputs[search_rows])
            lower = np.r_[np.full(4,-.999), np.full(4,.05), np.full(96,-6), np.full(len(vector)-104,-14)]
            upper = np.r_[np.full(4,.996), np.full(4,3.98), np.full(96,6), np.full(len(vector)-104,15)]
            updated, gpu_audit = optimize_native(smooth, target[search_rows]*16383, search_weights,
                vector, grid_from(current), response, vector, lower, upper, evaluations, index+1,
                perceptual_weight=perceptual, parameter_smoothing=smoothing)
            proposal, _ = roundtrip(projected(current, smooth.params(updated)))
            if score(proposal, train, train_weights, True) < score(current, train, train_weights, True):
                candidate = proposal
        candidate, integer_audit = refine_entry(candidate,
            lambda entry: score(entry, search_rows, search_weights), gamma_step=8 if index == 0 else 2)
        candidate, _ = roundtrip(candidate)
        print(f'联合拟合 {index+1}/{rounds}：重拟合网格并筛选量化候选', flush=True)
        base = native(candidate, inputs[train])
        probe_base = native(candidate, probes)
        grid, grid_audit = grid_distillation.fit_target(base, target[train], train_weights, response,
            parameter_smoothing=smoothing, continuity=(bank, probe_base, continuity_strength))

        trial_reports = []
        seen = set()
        best_entry, best_metrics = current, selected_metrics

        def consider(label, proposal):
            nonlocal best_entry, best_metrics
            entry, payload = roundtrip(proposal)
            if payload in seen:
                return
            seen.add(payload)
            metrics = selection_metrics(entry)
            failures = selection_failures(metrics, baseline_metrics, best_metrics['color_score'])
            trial_reports.append(dict(candidate=label, bin_sha256=core.sha(payload), **metrics, rejected_by=failures))
            if not failures:
                best_entry, best_metrics = entry, metrics
                print(f'  {label}：达到灰阶和连续性门槛，验证色差评分 {metrics["color_score"]:.5f}', flush=True)

        def with_grid(entry, table):
            return {**entry, 'grid_5x9x9': {'coefficients': table.T.reshape(3,5,9,9).tolist()}}

        def consider_steps(label, proposal):
            consider(label, proposal)
            for step in (2, 4, 6, 8, 10, 12, 14):
                fraction = step/16
                consider(f'{label}-blend-{fraction:g}', blend_entries(current, proposal, fraction))

        consider_steps('native-only', candidate)
        unprotected = with_grid(candidate, grid)
        consider_steps('direct-grid', unprotected)
        for label, entry, initial, native_base, continuity_base in (
            ('joint', candidate, grid, base, probe_base),
            ('current', current, grid_from(current), native(current, inputs[train]), native(current, probes)),
        ):
            for factor in (2, 4):
                weights = train_weights.copy()
                weights[gray_train] *= factor
                protected_grid, _ = constrain(initial, native_base, target[train], weights, response,
                    smoothing, (saturation_bank, continuity_base, continuity_strength*factor))
                consider_steps(f'{label}-saturation-{factor}x', with_grid(entry, protected_grid))

        print(f'联合拟合 {index+1}/{rounds}：按饱和度门槛微调整数网格', flush=True)
        polished, polish_moves = polish_grid(grid_from(best_entry), native(best_entry, inputs[train]),
            target[train], gray_train, native(best_entry, probes),
            response, bank, continuity_strength, baseline_metrics)
        consider_steps('guarded-integer-polish', with_grid(best_entry, polished))

        accepted = best_entry != current
        audit.append(dict(round=index+1, validation_before=selected_metrics,
                          validation_after=best_metrics, accepted=accepted, floating=gpu_audit,
                          integer=integer_audit, guarded_grid_moves=polish_moves,
                          grid_objective=grid_audit['objective'], candidates=trial_reports))
        current, selected_metrics = best_entry, best_metrics
        candidate = unprotected
        print(f'第 {index+1} 轮采用候选={accepted}', flush=True)

    selected, binary = roundtrip(current)
    last_candidate, candidate_binary = roundtrip(candidate)
    # 独立测试样本只在选优结束后渲染，两路都从各自 BIN 回读。
    def report(entry):
        with cpu_reference():
            actual = render(entry, inputs[test])
            gray = render(entry, inputs[gray_rows])
            # 同一组探针比较暗部、色相、饱和度的局部变化。
            transition = bank.report(render(entry, probes), continuity_strength)
        gray_error = core.tonal_comparison(target[gray_rows], gray)['groups']['all']['metrics']
        return dict(test=core.tonal_comparison(target[test], actual)['groups'],
                    gray_training=gray_error, transitions=transition)

    result = dict(dataset=recipe['source'].get('dataset_id'), pairs_sha256=core.sha(pairs_path.read_bytes()),
        grid_source=key, response=response, samples=dict(train=len(train), search=len(search_rows),
            validation=int(validation.sum()), test=int(test.sum())),
        test_used_for_selection=False, camera_tested=False,
        selection=dict(gray_anchor_rmse_ceiling=baseline_metrics['gray_rmse'],
            continuity_cost_ceiling=baseline_metrics['continuity_cost'],
            transition_ceilings={name:baseline_metrics[name] for name in TRANSITION_LIMITS},
            saturation_ceilings={name:baseline_metrics[name] for name in SATURATION_LIMITS},
            validation_requires_lower=['rgb_rmse','delta_e00_mean'],
            continuity_strength=continuity_strength, color_rank='validation 8-bit RGB MSE plus weighted DE00 squared'),
        validation_baseline=baseline_metrics, validation_selected=selected_metrics, rounds=audit,
        baseline=report(seed), joint=report(selected),
        baseline_bin_sha256=core.sha(baseline_binary), joint_bin_sha256=core.sha(binary))
    if refinement:
        refinement_report = {}
        for arm, item in refinement.items():
            entry, payload = roundtrip(item['entry'])
            refinement_report[arm] = dict(
                validation=item['validation'], bin_sha256=core.sha(payload), **report(entry))
            if 'rounds' in item:
                refinement_report[arm]['rounds'] = item['rounds']
                refinement_report[arm]['seconds'] = item['seconds']
        if seconds is None:
            refinement_report['integer_parameter_budget'] = 512*rounds
        else:
            refinement_report['wall_time_budget_seconds'] = seconds
        refinement_report['selected'] = next(
            arm for arm in ('incumbent', *arms) if refinement[arm]['entry'] == selected)
        if integer_start is not None:
            refinement_report['mode'] = 'integer-only'
            result['integer_refinement'] = refinement_report
        else:
            refinement_report['mode'] = 'direct-grid' if neural_grid else 'rgb-residual-ranking'
            result['neural_experiment'] = refinement_report
    if guarded_candidate is not None:
        if prior_entry == selected:
            prior_test = result['joint']['test']
        elif prior_entry == seed:
            prior_test = result['baseline']['test']
        else:
            prior_test = report(prior_entry)['test']
        guarded_candidate['prior_policy_test'] = prior_test
        result['guarded_candidate'] = guarded_candidate
    output.mkdir(parents=True, exist_ok=False)
    for arm, item in refinement.items():
        (output/f'{arm}.BIN').write_bytes(roundtrip(item['entry'])[1])
    if last_candidate != selected:
        result['last_trial'] = report(last_candidate)
        result['last_trial_kind'] = ('unfiltered quantized input candidate' if guarded_candidate is not None
                                     else 'unprotected direct grid from final round')
        (output/'last-trial.BIN').write_bytes(candidate_binary)
    (output/'baseline.BIN').write_bytes(baseline_binary)
    (output/'R5NATIVE.BIN').write_bytes(binary)
    (output/'native_config.json').write_text(json.dumps(core.compiler.unpack(binary), ensure_ascii=False, indent=2)+'\n')
    (output/'comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('job', type=Path, help='已完成的分阶段训练任务目录')
    parser.add_argument('key', help='该任务的整数网格标识')
    parser.add_argument('output', type=Path, help='新建的对比输出目录')
    parser.add_argument('--rounds', type=int, default=2)
    parser.add_argument('--evaluations', type=int, default=24, help='每个浮点块的求解预算')
    start = parser.add_mutually_exclusive_group()
    start.add_argument('--integer-start', type=Path, help='使用上一轮联合结果做纯整数网格微调')
    start.add_argument('--neural-start', type=Path, help='使用上一轮联合结果做同预算 MLP 对照')
    start.add_argument('--candidate', nargs=2, metavar=('JOB', 'KEY'), help='按基线门槛筛选另一训练任务的量化候选')
    parser.add_argument('--neural-grid', action='store_true', help='MLP 直接预测网格更新')
    parser.add_argument('--seconds', type=float, help='每条路径的搜索和验证时间上限')
    args = parser.parse_args()
    if args.neural_grid and args.neural_start is None:
        parser.error('--neural-grid 需要 --neural-start')
    if args.seconds is not None and (not (args.integer_start is not None or args.neural_grid)
                                     or not np.isfinite(args.seconds) or args.seconds <= 0):
        parser.error('--seconds 需要 --integer-start 或 --neural-grid，以及正数秒数')
    if not 1 <= args.rounds <= 8 or not 2 <= args.evaluations <= 2000:
        parser.error('交替轮数须为 1–8，求解预算须为 2–2000')
    fit(args.job, args.key, args.output, args.rounds, args.evaluations,
        args.neural_start, args.neural_grid, args.seconds, integer_start=args.integer_start,
        candidate_source=args.candidate)


if __name__ == '__main__':
    main()
