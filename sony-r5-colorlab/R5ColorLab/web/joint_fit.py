"""在最终网格后联合优化原生配方，使用量化回读和固定过渡门槛选优。"""
import copy
import time

import numpy as np
from scipy.optimize import minimize

from apple_gpu import SmoothGPU
from gpu_tensor import TensorTools

POLICY = 'native-grid-joint/1'


def delta_e_squared(tools, first, second):
    """连续的 ΔE00 平方，在相同颜色及中性色处保留有限梯度。"""
    t = tools.torch
    l1, a1, b1 = first.unbind(1)
    l2, a2, b2 = second.unbind(1)
    c1 = (a1.square() + b1.square()).clamp(min=1e-12).sqrt()
    c2 = (a2.square() + b2.square()).clamp(min=1e-12).sqrt()
    average = (c1 + c2) / 2
    g = .5 * (1 - (average**7 / (average**7 + 25**7)).clamp(min=1e-24).sqrt())
    ap1, ap2 = (1 + g) * a1, (1 + g) * a2
    cp1 = (ap1.square() + b1.square()).clamp(min=1e-12).sqrt()
    cp2 = (ap2.square() + b2.square()).clamp(min=1e-12).sqrt()
    # atan2 的零点采用微小偏移，避免黑白锚点产生 NaN 梯度。
    hp1 = t.remainder(t.atan2(b1, ap1 + 1e-8) * (180 / np.pi), 360)
    hp2 = t.remainder(t.atan2(b2, ap2 + 1e-8) * (180 / np.pi), 360)
    neutral = (c1 <= 1e-6) | (c2 <= 1e-6)
    dh = hp2 - hp1
    dh = t.where(dh > 180, dh - 360, t.where(dh < -180, dh + 360, dh))
    dh = t.where(neutral, 0, dh)
    dl, dc = l2 - l1, cp2 - cp1
    d_h = 2 * (cp1 * cp2).sqrt() * t.sin(dh * (np.pi / 360))
    lm, cm = (l1 + l2) / 2, (cp1 + cp2) / 2
    hm = t.where(t.abs(hp1 - hp2) <= 180, (hp1 + hp2) / 2,
        t.where(hp1 + hp2 < 360, (hp1 + hp2 + 360) / 2, (hp1 + hp2 - 360) / 2))
    hm = t.where(neutral, hp1 + hp2, hm)
    radians = np.pi / 180
    term = 1 - .17 * t.cos((hm - 30) * radians) + .24 * t.cos(2 * hm * radians)
    term = term + .32 * t.cos((3 * hm + 6) * radians) - .20 * t.cos((4 * hm - 63) * radians)
    sl = 1 + .015 * (lm - 50).square() / (20 + (lm - 50).square()).sqrt()
    sc, sh = 1 + .045 * cm, 1 + .015 * cm * term
    rt = -2 * (cm**7 / (cm**7 + 25**7)).clamp(min=1e-24).sqrt() * t.sin(
        60 * t.exp(-((hm - 275) / 25).square()) * radians)
    return ((dl / sl).square() + (dc / sc).square() + (d_h / sh).square()
            + rt * (dc / sc) * (d_h / sh)).clamp(min=0)


def native_basis(smooth, controls=17):
    """用平滑 Gamma 增量修正减少搜索维数，输出仍使用全部原生节点。"""
    size = len(smooth.knots)
    positions = smooth.axis / smooth.axis[-1]
    knots = np.linspace(0, 1, controls)
    hats = np.stack([np.interp(positions, knots, row) for row in np.eye(controls)], axis=1)
    hats -= hats.mean(axis=0)
    basis = np.zeros((104 + size, 104 + controls))
    basis[:104, :104] = np.diag(np.r_[np.full(4, .1), np.full(4, .2), np.full(96, .5)])
    basis[104:, 104:] = hats * .5
    return basis


class JointObjective:
    def __init__(self, smooth, initial, exact_base, target, weights, gray_rows, bank,
                 grid, response, perceptual, smoothing, strength, *, device='mps', dtype=None):
        from adaptive_gpu import FitGuard
        from grid_regularization import get_penalty
        from measured_response import get
        from output_continuity import TensorPenalty
        from parameter_smoothing import multiplier

        self.tools = TensorTools(device, dtype)
        flat = np.array_equal(smooth.x, np.broadcast_to(smooth.x[:,4:5], smooth.x.shape))
        self.gpu = SmoothGPU(smooth, device, dtype, compact_flat=flat)
        self.torch = self.tools.torch
        tensor = self.tools.tensor
        self.response = response
        self.ntrain = len(target)
        self.gray_rows = tensor(gray_rows, True)
        self.target = tensor(target)
        self.target_lab = self.tools.lab(self.target)
        self.weights = tensor(weights / weights.sum())
        self.initial = tensor(initial)
        self.basis = tensor(native_basis(smooth))
        self.smoothing = smoothing
        self.config = smooth.ctx.base.config
        self.perceptual = perceptual
        self.penalty = get_penalty(response)
        self.gram = tensor(self.penalty.dense_gram * (.001 * multiplier(smoothing)))
        model = get(response)
        baseline = model.predict_cpu(exact_base, grid)
        self.guard = FitGuard(self.tools, bank, baseline[self.ntrain:],
            baseline[:self.ntrain][gray_rows], target[gray_rows])
        self.continuity = TensorPenalty(bank, self.tools, strength)
        with self.torch.no_grad():
            origin = tensor(np.zeros(self.basis.shape[1]))
            self.offset = tensor(exact_base) - self.gpu.render(self.vector(origin)) / 16383
            self.continuity_limit = self.continuity.loss(tensor(baseline[self.ntrain:]))

    def vector(self, values):
        vector = self.initial + self.basis @ values
        lower = vector.new_tensor(np.r_[np.full(4, -.999), np.full(4, .05),
            np.full(96, -6), np.full(len(vector) - 104, -14)])
        upper = vector.new_tensor(np.r_[np.full(4, .996), np.full(4, 3.98),
            np.full(96, 6), np.full(len(vector) - 104, 15)])
        return self.torch.minimum(self.torch.maximum(vector, lower), upper)

    def native(self, values):
        return (self.gpu.render(self.vector(values)) / 16383 + self.offset).clamp(0, 1)

    def loss(self, native, table, vector, guard_scale, *, extra_guard=None):
        from gpu_color import paired_tensor
        from parameter_smoothing import native_rows_tensor

        predicted = paired_tensor(self.tools, native, table, self.response)
        color = predicted[:self.ntrain]
        error = (color - self.target).square().mean(dim=1)
        if self.perceptual:
            error = error + self.perceptual * .0001 * delta_e_squared(
                self.tools, self.tools.lab(color), self.target_lab)
        flat = table.reshape(-1)
        loss = self.weights @ error + flat @ self.gram @ flat
        native_rows = native_rows_tensor(self.gpu, vector[8:104], self.gpu.gamma(vector) * 16,
            self.gpu.axis, self.smoothing, cc1=vector[:8], config=self.config)
        loss = loss + native_rows.square().sum()
        gray = color[self.gray_rows]
        probes = predicted[self.ntrain:]
        constraint = self.guard.loss(gray, probes)
        gray_error = (gray - self.guard.gray_target).square().mean()
        constraint = constraint + 10 * (gray_error - self.guard.gray_limit).clamp(min=0)
        constraint = constraint + (self.continuity.loss(probes) - self.continuity_limit).clamp(min=0)
        if extra_guard is not None:
            loss = loss + extra_guard(predicted)
        return loss + guard_scale * constraint


class BudgetReached(Exception):
    pass


def grouped_candidates(grid, desired, base, target, weights, response, perceptual, deadline):
    """同时移动相邻节点，以完整训练损失筛掉无效组合。"""
    from measured_response import get
    from optimizer_policy import display_cost_rows

    model = get(response)
    _, nodes, interpolation = model.stencil(base)
    mixing = model.response(base)
    raw = model.predict_cpu(base, grid, clip=False)
    before = float(np.average(display_cost_rows(np.clip(raw, 0, 1), target, perceptual), weights=weights))
    change = desired - grid.astype(float)
    seen = set()
    for parameter in np.argsort(-np.abs(change).ravel(), kind='stable')[:12]:
        node, channel = divmod(int(parameter), 3)
        position = np.unravel_index(node, (5, 9, 9))
        for axis, stride in enumerate((81, 9, 1)):
            if time.perf_counter() >= deadline:
                return
            neighbor = node + stride if position[axis] < (4, 8, 8)[axis] else node - stride
            key = (min(node, neighbor), max(node, neighbor), channel)
            if key in seen:
                continue
            seen.add(key)
            steps = np.sign(change[[node, neighbor], channel]).astype(int)
            if not steps[0]:
                continue
            if not steps[1]:
                steps[1] = -steps[0]
            trial = grid.astype(int)
            trial[[node, neighbor], channel] += steps
            if trial.min() < -64 or trial.max() > 63:
                continue
            influence = sum(step * (interpolation * (nodes == at)).sum(axis=1)
                            for at, step in zip((node, neighbor), steps))
            prediction = np.clip(raw + influence[:, None] * mixing[:, channel], 0, 1)
            score = float(np.average(display_cost_rows(prediction, target, perceptual), weights=weights))
            if score < before - 1e-10:
                yield trial.astype(np.int8)


def solve(objective, initial, bounds, deadline, evaluations, progress, stage):
    """保存预算内最佳训练损失，所有梯度由 GPU 自动求导提供。"""
    best = np.asarray(initial, float).copy()
    best_loss = float('inf')
    calls = 0

    def value_gradient(values):
        nonlocal best, best_loss, calls
        if time.perf_counter() >= deadline or calls >= evaluations:
            raise BudgetReached()
        tensor = objective[0].tensor(values).requires_grad_(True)
        loss = objective[1](tensor)
        gradient, = objective[0].torch.autograd.grad(loss, tensor)
        score = float(loss.detach().cpu())
        derivative = gradient.detach().cpu().numpy().astype(float)
        calls += 1
        if not np.isfinite(score) or not np.isfinite(derivative).all():
            raise ValueError('联合求解产生非有限损失或梯度')
        if time.perf_counter() >= deadline:
            raise BudgetReached()
        if score < best_loss:
            best, best_loss = values.copy(), score
        if progress and (calls == 1 or calls % 10 == 0):
            progress(stage=stage, state='running', evaluations=calls,
                loss_sample=('MPS joint L-BFGS-B', calls, score, best_loss))
        return score, derivative

    try:
        minimize(value_gradient, best, jac=True, method='L-BFGS-B', bounds=bounds,
                 options=dict(maxiter=evaluations, maxfun=evaluations, maxls=12, ftol=1e-10, gtol=1e-8))
    except BudgetReached:
        pass
    return best, dict(evaluations=calls, training_loss=best_loss if np.isfinite(best_loss) else None)


def refine(config, grid, context, inputs, target, train, weights, eligible, gray, validation,
           response, bank, probe_base, bin_base, strength, perceptual, smoothing, progress=None,
           *, seconds=60):
    """整批训练更新四组参数，验证集仅用于量化候选选择。"""
    import core
    from adaptive_color import focus_weights
    from compute_backend import render_native
    from edit_parameter_context import ParameterContext
    from fit_anchor_native import SmoothNative, vector_for
    from fit_bin_joint import blend_entries, grid_from, projected
    from gpu_runtime import available, cpu_reference
    from integer_grid import candidate_metrics, guard_failures, polish_grid, repair_grid, selection_failures
    from measured_response import get
    from optimizer_policy import display_cost_rows
    from patch_sampling import center_mean

    if not np.isfinite(seconds) or seconds <= 0:
        raise ValueError('联合求解时间预算必须为正数')
    if not available():
        raise RuntimeError('联合求解需要可用的 Metal/MPS')
    train = np.asarray(train)
    if (train.ndim != 1 or train.dtype.kind not in 'iu' or len(np.unique(train)) != len(train)
            or np.any(train < 0) or np.any(train >= len(inputs))
            or validation.dtype != bool or gray.dtype != bool
            or validation.shape != (len(inputs),) or gray.shape != (len(inputs),)
            or not validation.any() or not gray.any() or validation[train].any()
            or not np.isin(np.flatnonzero(gray), train).all()):
        raise ValueError('训练、灰阶和验证数据的分组不一致')
    selected_config = core.compiler.unpack(core.compiler.pack(config))
    entry, = selected_config['entries']
    if any(any(row) for row in entry['cc1_delta'][1:]) or any(m != entry['block13'][0] for m in entry['block13'][1:]):
        raise ValueError('联合求解首版要求三个照明端点共享原生参数')
    entry['grid_5x9x9'] = dict(coefficients=grid.T.reshape(3, 5, 9, 9).tolist())
    started = time.perf_counter()
    deadline = started + seconds
    search_deadline = deadline - min(8., seconds / 3)
    response_model = get(response)
    scores = display_cost_rows(response_model.predict_cpu(bin_base[train], grid), target[train], perceptual)
    # 原生初始化已使用各色组总权重；末段按完整训练人口降低最终显示色差，
    # 灰阶由独立的固定门槛保护，避免少量锚点再次主导整个颜色目标。
    population_weights = np.ones(len(train))
    if eligible.any():
        population_weights[eligible] = weights[eligible] / weights[eligible].mean()
    weights, groups = focus_weights(target[train], scores, population_weights, eligible)
    measure = candidate_metrics(target[gray], target[validation], response, bank, strength, perceptual)
    baseline = best_metrics = measure(grid, bin_base[gray], bin_base[validation], probe_base)
    audit = dict(policy=POLICY, backend='Apple Metal/MPS', full_batch=True,
        training_samples=len(train), validation_samples=int(validation.sum()), groups=groups,
        validation_before=baseline, rounds=[], candidates=[], accepted=False,
        time_budget_seconds=seconds, validation_used_for_gradient=False, test_used_for_selection=False)
    audit['color_weighting'] = 'full-training-population; gray protected by fixed constraints'
    original = copy.deepcopy(entry)
    best_entry = entry
    current_base, current_probes = bin_base, probe_base
    validation_inputs = np.concatenate((inputs[gray], inputs[validation], bank.inputs(context.base)))
    ngray, nvalid = int(gray.sum()), int(validation.sum())
    repairable = []

    def consider(candidate, label):
        nonlocal best_entry, best_metrics
        if time.perf_counter() >= deadline:
            return
        candidate_config = copy.deepcopy(selected_config)
        candidate_config['entries'] = [candidate]
        blob = core.compiler.pack(candidate_config)
        quantized, = core.compiler.unpack(blob)['entries']
        native = context.build(**core.slot_native_parameters(context, quantized))
        with cpu_reference():
            rendered = center_mean(render_native(native, validation_inputs)) / 16383
        metrics = measure(grid_from(quantized), *np.split(rendered, (ngray, ngray + nvalid)))
        failures = selection_failures(metrics, baseline, best_metrics['color_score'])
        in_budget = time.perf_counter() <= deadline
        audit['candidates'].append(dict(label=label, bin_sha256=core.sha(blob), metrics=metrics,
                                       rejected_by=failures, in_budget=in_budget))
        if not failures and in_budget:
            best_entry, best_metrics = quantized, metrics
        elif in_budget and failures == guard_failures(metrics, baseline):
            excess = sum((metrics[key] - baseline[key]) / max(baseline[key], .1) for key in failures)
            repairable.append((excess, quantized, rendered))

    # 单一训练任务中复用初始化，交替消除网格残差与原生参数误差。
    for round_index in range(3):
        if time.perf_counter() >= search_deadline - 2:
            break
        warm = context.build(**core.slot_native_parameters(context, best_entry))
        vector = vector_for(ParameterContext(warm))
        probes = bank.inputs(warm)
        smooth = SmoothNative(ParameterContext(warm), np.concatenate((inputs[train], probes)))
        objective = JointObjective(smooth, vector, np.concatenate((current_base[train], current_probes)),
            target[train], weights, np.flatnonzero(gray[train]), bank, grid_from(best_entry),
            response, perceptual, smoothing, strength)
        tools = objective.tools
        n_native = objective.basis.shape[1]
        initial = np.r_[np.zeros(n_native), grid_from(best_entry).ravel() / 32]
        guard_scale = 10. ** (round_index + 1)
        seed_table = tools.tensor(grid_from(best_entry))
        native_values, native_audit = solve((tools, lambda values: objective.loss(
            objective.native(values), seed_table, objective.vector(values), guard_scale)),
            initial[:n_native], [(-2., 2.)] * n_native,
            min(search_deadline - 1, time.perf_counter() + seconds / 8), 50, progress,
            '联合拟合：固定网格优化全部原生参数')
        with tools.torch.no_grad():
            native_tensor = tools.tensor(native_values)
            fixed_native = objective.native(native_tensor)
            fixed_vector = objective.vector(native_tensor)
        initial[:n_native] = native_values
        table, inner = solve((tools, lambda values: objective.loss(fixed_native,
            values.reshape(405, 3) * 32, fixed_vector, guard_scale)),
            initial[n_native:], [(-2., 63 / 32)] * 1215,
            min(search_deadline - 1, time.perf_counter() + seconds / 6), 50, progress, '联合拟合：固定原生参数重解网格')
        initial[n_native:] = table

        def joint_loss(values):
            native_values = values[:n_native]
            return objective.loss(objective.native(native_values),
                values[n_native:].reshape(405, 3) * 32, objective.vector(native_values), guard_scale)

        proposal, outer = solve((tools, joint_loss), initial,
            [(-2., 2.)] * n_native + [(-2., 63 / 32)] * 1215,
            min(search_deadline - 1, time.perf_counter() + seconds / 3), 100, progress,
            '联合拟合：Gamma、CC1、色相矩阵与网格')
        fitted_vector = objective.vector(tools.tensor(proposal[:n_native])).detach().cpu().numpy().astype(float)
        floating_grid = proposal[n_native:].reshape(405, 3) * 32
        candidate = projected(best_entry, smooth.params(fitted_vector))
        candidate['grid_5x9x9'] = dict(coefficients=np.clip(np.rint(floating_grid), -64, 63)
                                     .astype(int).T.reshape(3, 5, 9, 9).tolist())
        incumbent = best_entry
        native_only = projected(incumbent, smooth.params(fixed_vector.detach().cpu().numpy().astype(float)))
        for fraction in (1., .25, .0625):
            consider(blend_entries(incumbent, native_only, fraction), f'native-{round_index + 1}-{fraction}')
        for fraction in (1., .5, .25, .125, .0625, .03125):
            consider(blend_entries(incumbent, candidate, fraction), f'joint-{round_index + 1}-{fraction}')
        # 固定原生参数的内层结果也参与验收，避免一次原生步幅掩盖网格收益。
        grid_only = copy.deepcopy(native_only)
        grid_only['grid_5x9x9'] = dict(coefficients=np.clip(np.rint(table.reshape(405, 3) * 32), -64, 63)
                                     .astype(int).T.reshape(3, 5, 9, 9).tolist())
        for fraction in (1., .25, .0625):
            consider(blend_entries(incumbent, grid_only, fraction), f'inner-{round_index + 1}-{fraction}')
        audit['rounds'].append(dict(round=round_index + 1, grid=inner, joint=outer,
                                    native=native_audit, guard_scale=guard_scale, native_controls=n_native))
        del objective
        if best_entry is not incumbent:
            native = context.build(**core.slot_native_parameters(context, best_entry))
            with cpu_reference():
                current_base = center_mean(render_native(native, inputs)) / 16383
                current_probes = center_mean(render_native(native, bank.inputs(native))) / 16383
        if time.perf_counter() < search_deadline - 2:
            for group_index, table in enumerate(grouped_candidates(grid_from(best_entry), floating_grid,
                    current_base[train], target[train], weights, response, perceptual, search_deadline - 1)):
                candidate = copy.deepcopy(best_entry)
                candidate['grid_5x9x9'] = dict(coefficients=table.T.reshape(3, 5, 9, 9).tolist())
                consider(candidate, f'grouped-integer-{round_index + 1}-{group_index}')
                if group_index >= 7:
                    break
            polished, moves = polish_grid(grid_from(best_entry), current_base[train], target[train],
                gray[train], current_probes, response, bank, strength, best_metrics,
                deadline=search_deadline - 1, step_sizes=(1, 2))
            if moves:
                candidate = copy.deepcopy(best_entry)
                candidate['grid_5x9x9'] = dict(coefficients=polished.T.reshape(3, 5, 9, 9).tolist())
                consider(candidate, f'integer-{round_index + 1}')
    audit['constraint_repairs'] = []
    for _, candidate, rendered in sorted(repairable, key=lambda item: item[0])[:2]:
        if time.perf_counter() >= deadline - 2:
            break
        gray_base, _, probes = np.split(rendered, (ngray, ngray + nvalid))
        repaired, moves = repair_grid(grid_from(candidate), gray_base, target[gray], probes,
            response, bank, strength, baseline, deadline=deadline - 1)
        audit['constraint_repairs'].append(dict(moves=moves))
        if moves:
            candidate = copy.deepcopy(candidate)
            candidate['grid_5x9x9'] = dict(coefficients=repaired.T.reshape(3, 5, 9, 9).tolist())
            consider(candidate, 'constraint-repair')
    audit.update(accepted=best_entry != original, validation_after=best_metrics,
                 seconds=time.perf_counter() - started)
    selected_config['entries'] = [best_entry]
    selected = core.compiler.unpack(core.compiler.pack(selected_config))
    return selected if audit['accepted'] else None, grid_from(best_entry), audit
