"""按本次目标的训练残差补拟合色相矩阵，并验收配对的整数网格。"""
import time

import numpy as np

from perceptual import to_lab

POLICY = 'target-hue-tone/2'


def focus_weights(target, costs, weights, eligible):
    """只重新分配有色随机样本的权重，保留中性色和全部锚点。"""
    lab = to_lab(target*255)
    hue = np.arctan2(lab[:, 2], lab[:, 1]) % (2*np.pi)
    sectors = np.floor(hue*12/(2*np.pi)).astype(int)
    tones = np.digitize(lab[:, 0], (33.3, 66.7))
    groups = tones*12+sectors
    active = eligible & (np.linalg.norm(lab[:, 1:], axis=1) >= 12)
    updated = weights.copy()
    if not active.any():
        return updated, []
    reference = max(float(np.average(costs[active], weights=weights[active])), 1.)
    audit = []
    for group in np.unique(groups[active]):
        rows = active & (groups == group)
        count = int(rows.sum())
        loss = float(np.average(costs[rows], weights=weights[rows]))
        # 样本不足时向全局均值收缩，避免被孤立色块牵引。
        shrunk = (count*loss+64*reference)/(count+64)
        factor = float(np.clip(np.sqrt(shrunk/reference), .75, 2.5))
        updated[rows] *= factor
        audit.append(dict(hue_sector=int(group%12), lightness_band=int(group//12),
                          samples=count, residual_rmse=float(np.sqrt(loss)), multiplier=factor))
    updated[active] *= weights[active].sum()/updated[active].sum()
    return updated, audit


def refine(config, grid, context, inputs, target, train, weights, eligible, gray, validation,
           response, bank, probe_base, bin_base, strength, perceptual, smoothing, progress=None):
    """在同一配方上连续求解，用已验收候选作为保护基准。"""
    import core
    from compute_backend import render_native
    from gpu_runtime import cpu_reference
    from patch_sampling import center_mean

    started = time.perf_counter()
    data = (context, inputs, target, train, weights, eligible, gray, validation, response, bank)
    settings = (strength, perceptual, smoothing, progress)
    reference, reference_grid, reference_audit = _refine_once(
        config, grid, *data, probe_base, bin_base, *settings, constrained=False)
    if reference is not None:
        native = context.build(**core.slot_native_parameters(context, reference['entries'][0]))
        with cpu_reference():
            bin_base = center_mean(render_native(native, inputs))/16383
            probe_base = center_mean(render_native(native, bank.inputs(native)))/16383
    selected, selected_grid, audit = _refine_once(
        reference or config, reference_grid, *data, probe_base, bin_base, *settings, constrained=True)
    audit.update(reference=reference_audit, protected_accepted=selected is not None,
                 reference_bin_sha256=core.sha(core.compiler.pack(reference)) if reference else None,
                 accepted=selected is not None or reference is not None,
                 seconds=time.perf_counter()-started)
    return selected or reference, selected_grid, audit


def _refine_once(config, grid, context, inputs, target, train, weights, eligible, gray, validation,
                 response, bank, probe_base, bin_base, strength, perceptual, smoothing, progress,
                 *, constrained):
    from scipy.optimize import minimize

    import core
    from adaptive_gpu import GuardedMatrixObjective, fit_grid
    from compressed_alternation import CompressedGridObjective
    from compute_backend import render_native
    from edit_parameter_context import ParameterContext
    from fit_anchor_native import SmoothNative, vector_for
    from fit_bin_joint import blend_entries, projected
    from gpu_runtime import cpu_reference
    from integer_grid import candidate_metrics, guard_failures, polish_grid, repair_grid, selection_failures
    from measured_response import get
    from optimizer_policy import display_cost_rows
    from parameter_smoothing import multiplier
    from patch_sampling import center_mean
    from pc_stages import fit_response_grid
    from residual_grid import pack, unpack

    started = time.perf_counter()
    seed, = config['entries']
    seed = {**seed, 'grid_5x9x9': dict(coefficients=grid.T.reshape(3, 5, 9, 9).tolist())}
    model = get(response)
    desired = target[train]
    costs = display_cost_rows(model.predict(bin_base[train], grid), desired, perceptual)
    focused, groups = focus_weights(desired, costs, weights, eligible)
    audit = dict(policy=POLICY, constrained=constrained, accepted=False, training_samples=len(train), grid_fits=[],
                 groups=groups, candidates=[], test_used_for_selection=False, backend='Apple Metal/MPS')
    if not groups or np.allclose(focused, weights):
        return None, grid, {**audit, 'reason': 'no-distinct-chromatic-cohorts'}

    smooth = SmoothNative(context, inputs[train])
    warm = context.build(**core.slot_native_parameters(context, seed))
    initial = vector_for(ParameterContext(warm))
    probes = bank.inputs(warm)
    gray_rows = np.flatnonzero(gray[train])
    baseline_gray = model.predict_cpu(bin_base[train[gray_rows]], grid)
    baseline_probes = model.predict_cpu(probe_base, grid)
    block = slice(8, 104)
    # 在当前导出网格后计算色差，冻结 Gamma 和 CC1，仅更新十六色相矩阵。
    objective_args = (smooth, desired*16383, focused/focused.mean(), initial, grid,
                      response, perceptual, smoothing)
    if constrained:
        objective = GuardedMatrixObjective(*objective_args, bank=bank,
            probe_smooth=SmoothNative(context, probes), gray_rows=gray_rows,
            baseline_gray=baseline_gray, baseline_probes=baseline_probes)
    else:
        objective = CompressedGridObjective(*objective_args)
    best_loss = float('inf')
    calls = 0

    def value_gradient(matrix):
        nonlocal best_loss, calls
        vector = initial.copy()
        vector[block] = matrix
        loss, gradient = objective.value_gradient(vector, block)
        calls += 1
        best_loss = min(loss, best_loss)
        if progress:
            stage = '含灰阶和双域饱和度约束的矩阵拟合' if constrained else '按目标色相与亮度补拟合原生矩阵'
            progress(stage=stage, state='running',
                     evaluations=calls, loss_sample=('adaptive-hue-mps', calls, loss, best_loss))
        return loss, gradient

    start_loss, _ = value_gradient(initial[block])
    result = minimize(value_gradient, initial[block], jac=True, method='L-BFGS-B',
                      bounds=[(-6., 6.)]*96, options=dict(maxiter=36, maxfun=42, ftol=1e-10))
    vector = initial.copy()
    vector[block] = result.x
    estimate = {**seed, 'block13': projected(seed, smooth.params(vector))['block13']}
    del objective
    audit.update(evaluations=calls, loss_before=start_loss, loss_after=float(result.fun))
    if result.fun >= start_loss:
        estimate = seed
    if not constrained and estimate['block13'] == seed['block13']:
        return None, grid, {**audit, 'reason': 'no-quantized-matrix-update'}

    measure = candidate_metrics(target[gray], target[validation], response, bank, strength, perceptual)
    limits = measure(grid, bin_base[gray], bin_base[validation], probe_base)
    best = limits
    selected, selected_grid = None, grid
    validation_inputs = np.concatenate((inputs[gray], inputs[validation], probes))
    ngray, nvalid = int(gray.sum()), int(validation.sum())
    repairable = []

    def refit_grid(train_base, rendered_probes, fraction):
        if not constrained:
            table, _ = fit_response_grid(train_base, desired, focused, response,
                                        strength=.001*multiplier(smoothing))
            return table
        if progress:
            progress(stage='含灰阶和双域饱和度约束的网格拟合', state='running', evaluations=0)
        table, details = fit_grid(train_base, desired, focused, grid, response,
            .001*multiplier(smoothing), perceptual, bank=bank, gray_rows=gray_rows,
            probes=rendered_probes, baseline_gray=baseline_gray, baseline_probes=baseline_probes)
        audit['grid_fits'].append(dict(matrix_fraction=fraction, **details))
        return table

    def consider(entry, table, rendered, fraction, grid_fraction, stage='joint'):
        nonlocal best, selected, selected_grid
        candidate = {**entry, 'grid_5x9x9': dict(coefficients=table.T.reshape(3, 5, 9, 9).tolist())}
        binary = core.compiler.pack({**config, 'entries': [candidate]})
        quantized = core.compiler.unpack(binary)
        table = unpack(pack(table))
        metrics = measure(table, *rendered)
        failures = selection_failures(metrics, limits, best['color_score'])
        audit['candidates'].append(dict(stage=stage, matrix_fraction=fraction, grid_fraction=grid_fraction,
                                        metrics=metrics, rejected_by=failures))
        if not failures:
            selected, selected_grid, best = quantized, table, metrics
        elif stage == 'joint' and failures == guard_failures(metrics, limits):
            excess = sum((metrics[k]-limits[k])/max(limits[k], .1) for k in failures)
            repairable.append((excess, entry, table, rendered, fraction, grid_fraction))

    # 网格重拟合只看训练数据。缩小矩阵和网格步幅，由量化验收决定是否发布。
    seen = set()
    for fraction in (.015625, .0625, .25, 1.):
        entry = blend_entries(seed, estimate, fraction)
        key = np.asarray(entry['block13']).tobytes()
        if key in seen or entry['block13'] == seed['block13']:
            continue
        seen.add(key)
        entry = core.compiler.unpack(core.compiler.pack({**config, 'entries': [entry]}))['entries'][0]
        native = context.build(**core.slot_native_parameters(context, entry))
        with cpu_reference():
            trial_base = center_mean(render_native(native, validation_inputs))/16383
        rendered = np.split(trial_base, (ngray, ngray+nvalid))
        consider(entry, grid, rendered, fraction, 0.)
        if progress:
            progress(stage='按新色相矩阵重拟合网格', state='running', evaluations=0)
        train_base = center_mean(render_native(native, inputs[train]))/16383
        refitted = refit_grid(train_base, rendered[2], fraction)
        change = refitted.astype(int)-grid
        for step in (.125, .5, 1.):
            table = np.rint(grid+step*change).astype(np.int8)
            if not np.array_equal(table, grid):
                consider(entry, table, rendered, fraction, step)

    if repairable:
        _, entry, table, rendered, fraction, step = min(repairable, key=lambda trial: trial[0])
        if progress:
            progress(stage='整数网格过渡修正与验收', state='running')
        repaired, moves = repair_grid(table, rendered[0], target[gray], rendered[2],
                                       response, bank, strength, limits)
        if moves:
            consider(entry, repaired, rendered, fraction, step, 'transition-repair')

    # 从已通过门槛的组合继续搜索整数台阶；没有矩阵候选时自然从基准开始。
    incumbent = selected['entries'][0] if selected is not None else seed
    if incumbent is seed:
        train_base = bin_base[train]
        rendered = (bin_base[gray], bin_base[validation], probe_base)
    else:
        native = context.build(**core.slot_native_parameters(context, incumbent))
        train_base = center_mean(render_native(native, inputs[train]))/16383
        with cpu_reference():
            rendered = np.split(center_mean(render_native(native, validation_inputs))/16383,
                                (ngray, ngray+nvalid))
    if constrained or selected is None:
        refitted = refit_grid(train_base, rendered[2], None)
        for _ in range(3 if constrained else 1):
            if progress and constrained:
                progress(stage='保护约束下逐步微调整数网格', state='running')
            table, moves = polish_grid(selected_grid, train_base, desired, gray[train], rendered[2],
                response, bank, strength, best, proposal_table=refitted,
                validation_data=(rendered[1], target[validation]),
                step_sizes=(1, 2, 4, 8) if constrained else (1, 2))
            if not moves:
                break
            previous = best
            consider(incumbent, table, rendered, None, None,
                     'integer-grid-polish' if constrained else 'integer-grid-only')
            if best is previous:
                break

    audit.update(accepted=selected is not None, validation_before=limits, validation_after=best,
                 seconds=time.perf_counter()-started)
    return selected, selected_grid, audit
