"""使用量化显示色差和过渡门槛微调整数网格。"""
import time
import hashlib

import numpy as np

from perceptual import de2000, to_lab


SATURATION_AXES = ('saturation', 'native-saturation')
PROBE_AXES = tuple(prefix+axis for prefix in ('', 'native-')
                   for axis in ('dark-exposure', 'full-exposure', 'hue', 'saturation'))
AXIS_METRICS = {'p95': 'chroma_second_difference_p95',
                'max': 'chroma_second_difference_max', 'over': 'over_allowance'}
TRANSITION_LIMITS = tuple(f'{axis}_{metric}' for axis in PROBE_AXES for metric in AXIS_METRICS)
SATURATION_LIMITS = tuple(name for name in TRANSITION_LIMITS if 'saturation' in name)


def transition_metrics(bank, rgb, strength):
    report = bank.report(rgb, strength)
    transitions = {f'{axis}_{metric}': report['axes'][axis][field]
                   for axis in PROBE_AXES for metric, field in AXIS_METRICS.items()}
    return dict(continuity_cost=report['objective_cost_8bit_squared'], **transitions)


def guard_failures(metrics, limits):
    return [name for name in ('gray_rmse', 'continuity_cost', *TRANSITION_LIMITS)
            if metrics[name] > limits[name]+1e-10]


def repair_grid(grid, gray_base, gray_target, probe_base, response, bank, strength, limits):
    """局部修正违反过渡门槛的网格，最终颜色验收由完整 BIN 筛选完成。"""
    from measured_response import get

    model = get(response)
    base = np.concatenate((probe_base, gray_base))
    _, nodes, weights = model.stencil(base)
    mixing = model.response(base)
    table = grid.copy()
    raw = model.predict_cpu(base, table, clip=False)
    probe_count = len(probe_base)
    gray_target = np.floor(np.clip(gray_target, 0, 1)*255+.5)
    group_slices = {}
    offset = 0
    for axis, count in bank.groups:
        group_slices[axis] = slice(offset, offset+count)
        offset += count

    def violations():
        clipped = np.clip(raw, 0, 1)
        probes = clipped[:probe_count]
        gray = np.floor(clipped[probe_count:]*255+.5)
        gray_rmse = float(np.sqrt(np.mean((gray-gray_target)**2)))
        ab = bank.curvature(to_lab(probes*255))[:, 1:]
        jump = np.linalg.norm(ab, axis=1)
        over = jump-bank.allowance
        loss = 0.
        active = np.zeros(len(jump))
        for axis, section in group_slices.items():
            values = jump[section]
            ceiling = limits[f'{axis}_max']
            excess = np.maximum(values-ceiling, 0)/max(ceiling, .1)
            loss += float(excess @ excess)
            active[section] += excess
            ceiling = limits[f'{axis}_p95']
            percentile = np.percentile(values, 95)
            if percentile > ceiling:
                excess = (percentile-ceiling)/max(ceiling, .1)
                loss += excess**2
                nearby = np.argsort(np.abs(values-percentile), kind='stable')[:16]
                active[section.start+nearby] += excess
            allowance = over[section]
            count = int(np.count_nonzero(allowance > 0))
            excess_count = count-limits[f'{axis}_over']
            if excess_count > 0:
                nearest = np.flatnonzero(allowance > 0)
                nearest = nearest[np.argsort(allowance[nearest], kind='stable')[:excess_count]]
                margin = allowance[nearest]
                loss += float(margin @ margin)+.0001*excess_count
                active[section.start+nearest] += margin+.01
        continuity_excess = max(0., bank.cost(probes, strength)-limits['continuity_cost'])
        if continuity_excess > 0:
            loss += (continuity_excess/max(limits['continuity_cost'], .1))**2
            active += np.maximum(over, 0)*continuity_excess/max(len(over), 1)
        gray_excess = max(0., gray_rmse-limits['gray_rmse'])
        loss += (gray_excess/max(limits['gray_rmse'], .1))**2
        return loss, active, gray_excess

    moves = 0
    for _ in range(18):
        loss, active, gray_excess = violations()
        if loss == 0:
            break
        probe_mass = np.zeros(len(base))
        np.add.at(probe_mass, bank.triplets.ravel(), np.repeat(active, 3))
        if gray_excess:
            probe_mass[probe_count:] = gray_excess/len(gray_base)
        priority = np.bincount(nodes.ravel(), (weights*probe_mass[:, None]).ravel(), minlength=405)
        ranked = np.argsort(-priority, kind='stable')
        active_triplets = active > 0
        active_rows, triplets = np.unique(bank.triplets[active_triplets], return_inverse=True)
        triplets = triplets.reshape(-1, 3)
        mix = bank.mix[active_triplets]

        def local_loss():
            lab = to_lab(np.clip(raw[active_rows], 0, 1)*255)
            a, b, c = lab[triplets,1:].transpose(1,0,2)
            bend = np.linalg.norm(2*(b-a*(1-mix)-c*mix), axis=1)
            gray = np.floor(np.clip(raw[probe_count:], 0, 1)*255+.5)
            error = np.sqrt(np.mean((gray-gray_target)**2))
            return float(active[active_triplets] @ bend)+gray_excess*error

        shortlist = []
        for node in ranked[:8]:
            if priority[node] <= 0:
                break
            rows, corners = np.nonzero((nodes==node)&(weights>0))
            previous = raw[rows].copy()
            for channel in range(3):
                adjustment = weights[rows,corners,None]*mixing[rows,channel]
                for step in (-8, -4, -2, -1, 1, 2, 4, 8):
                    if -64 <= int(table[node,channel])+step <= 63:
                        raw[rows] = previous+step*adjustment
                        shortlist.append((local_loss(), abs(step), node, channel, step))
                raw[rows] = previous
        best = loss
        update = None
        for _, _, node, channel, step in sorted(shortlist)[:16]:
            rows, corners = np.nonzero((nodes==node)&(weights>0))
            previous = raw[rows].copy()
            raw[rows] = previous+step*weights[rows,corners,None]*mixing[rows,channel]
            trial, _, _ = violations()
            if trial < best-1e-12:
                best, update = trial, (node, channel, step, rows, raw[rows].copy())
            raw[rows] = previous
        if update is None:
            break
        node, channel, step, rows, updated = update
        table[node,channel] += step
        raw[rows] = updated
        moves += 1
    return table, moves


def polish_grid(grid, source, desired, gray_mask, probe_base,
                response, bank, strength, limits, proposal_target=None, proposal_table=None,
                deadline=None, *, validation_data=None, step_sizes=(1,), proposal_only=False):
    """全训练集逐项计算整数改动的色差，只重算受影响的样本。"""
    from scipy.sparse import coo_matrix
    from measured_response import get

    model = get(response)
    if proposal_only and proposal_table is None:
        raise ValueError('仅应用候选改动时必须提供候选网格')
    color_rows, color_target = source, desired
    if validation_data is not None:
        validation_base, validation_target = validation_data
        color_rows = np.concatenate((source, validation_base))
        color_target = np.concatenate((desired, validation_target))
    x = np.concatenate((color_rows, probe_base))
    _, nodes, interpolation = model.stencil(x)
    design = coo_matrix((interpolation.ravel(),
                         (np.repeat(np.arange(len(x)), nodes.shape[1]), nodes.ravel())),
                        shape=(len(x), 405)).tocsc()
    design.eliminate_zeros()
    mixing = model.response(x)
    table = grid.copy()
    raw = model.predict_cpu(x, table, clip=False)
    count = len(source)
    color_count = len(color_rows)
    target = np.floor(np.clip(color_target, 0, 1)*255+.5)
    target_lab = to_lab(target)

    def errors(rows):
        rgb = np.floor(np.clip(raw[rows], 0, 1)*255+.5)
        return np.mean((rgb-target[rows])**2, axis=1), de2000(to_lab(rgb), target_lab[rows])

    mse, delta = errors(np.arange(color_count))
    gray_sum = float(mse[:count][gray_mask].sum())
    gray_count = int(gray_mask.sum())
    ranking_target = desired if proposal_target is None else proposal_target
    error = np.clip(raw[:count], 0, 1)-ranking_target
    gradient = design[:count].T @ np.einsum('no,nco->nc', error, mixing[:count])
    priority = np.abs(gradient)
    if proposal_table is not None:
        predicted_update = proposal_table.astype(int)-table
        priority = priority*(1+np.abs(predicted_update))
    ordered = np.argsort(-priority.ravel(), kind='stable')
    if proposal_only:
        ordered = ordered[predicted_update.ravel()[ordered] != 0]
    accepted = 0
    for parameter in ordered[:512]:
        if deadline is not None and time.perf_counter() >= deadline:
            break
        node, channel = divmod(int(parameter), 3)
        lo, hi = design.indptr[node:node+2]
        rows = design.indices[lo:hi]
        touched = rows[rows<count]
        if not len(touched):
            continue
        gray_touched = gray_mask[touched]
        previous = raw[rows].copy()
        adjustment = design.data[lo:hi,None]*mixing[rows,channel]
        direction = -1 if gradient[node,channel] > 0 else 1
        if proposal_table is not None and predicted_update[node,channel]:
            direction = int(np.sign(predicted_update[node,channel]))
        validation_rows = rows[(rows>=count)&(rows<color_count)]
        signs = (direction,) if proposal_only else (direction, -direction)
        for step in (size*sign for size in step_sizes for sign in signs):
            if proposal_only and abs(step) > abs(predicted_update[node, channel]):
                continue
            if not -64 <= int(table[node,channel])+step <= 63:
                continue
            raw[rows] = previous + step*adjustment
            new_mse, new_delta = errors(touched)
            diff = new_mse-mse[touched]
            new_gray_sum = gray_sum + float(diff[gray_touched].sum())
            gray = float(np.sqrt(max(new_gray_sum, 0)/gray_count))
            if diff.sum() >= -1e-10 or (new_delta-delta[touched]).sum() >= -1e-10 or gray > limits['gray_rmse']+1e-10:
                continue
            if validation_data is not None:
                validation_mse, validation_delta = errors(validation_rows)
                if ((validation_mse-mse[validation_rows]).sum() >= -1e-10 or
                        (validation_delta-delta[validation_rows]).sum() >= -1e-10):
                    continue
            metrics = transition_metrics(bank, np.clip(raw[color_count:],0,1), strength)
            if guard_failures(dict(gray_rmse=gray, **metrics), limits):
                continue
            table[node,channel] += step
            mse[touched], delta[touched] = new_mse, new_delta
            if validation_data is not None:
                mse[validation_rows], delta[validation_rows] = validation_mse, validation_delta
            gray_sum = new_gray_sum
            accepted += 1
            break
        else:
            raw[rows] = previous
    return table, accepted


def selection_failures(metrics, limits, best_color):
    failures = guard_failures(metrics, limits)
    for name in ('rgb_rmse', 'delta_e00_mean'):
        if metrics[name] >= limits[name]-1e-10:
            failures.append(name)
    if metrics['color_score'] >= best_color-1e-10:
        failures.append('validation_color_score')
    return failures


def candidate_metrics(gray_target, validation_target, response, bank, strength, perceptual):
    """对原生参数和网格的任意组合使用相同的量化验收口径。"""
    from measured_response import get

    model = get(response)
    validation_target = np.floor(np.clip(validation_target, 0, 1)*255+.5)
    validation_lab = to_lab(validation_target)
    gray_target = np.floor(np.clip(gray_target, 0, 1)*255+.5)

    def measure(table, gray_base, validation_base, probe_base):
        gray = np.floor(model.predict_cpu(gray_base, table)*255+.5)
        rgb = np.floor(model.predict_cpu(validation_base, table)*255+.5)
        mse = np.mean((rgb-validation_target)**2)
        delta = de2000(to_lab(rgb), validation_lab)
        return dict(rgb_rmse=float(np.sqrt(mse)), delta_e00_mean=float(delta.mean()),
            color_score=float(mse+perceptual*np.mean((2.55*delta)**2)),
            gray_rmse=float(np.sqrt(np.mean((gray-gray_target)**2))),
            **transition_metrics(bank, model.predict_cpu(probe_base, table), strength))

    return measure


def refine(grid, base, target, train, gray_mask, validation, response, probes, perceptual,
           progress=None, *, strategy="standard"):
    """以原网格为门槛，按验证集选择符合约束的整数量化结果。"""
    from residual_grid import pack, unpack

    bank, probe_base, strength = probes
    grid = unpack(pack(grid))
    metrics_for = candidate_metrics(target[gray_mask], target[validation],
        response, bank, strength, perceptual)
    gray_base, validation_base = base[gray_mask], base[validation]

    def measure(table):
        return metrics_for(table, gray_base, validation_base, probe_base)

    baseline = selected = measure(grid)
    baseline_sha = hashlib.sha256(pack(grid)).hexdigest()
    searches = {
        'standard': ('standard',),
        'validation': ('validation',),
        'extended': ('standard', 'validation'),
    }[strategy]
    train_base, train_target, train_gray = base[train], target[train], gray_mask[train]
    history = []
    stage_baselines = {}
    sweeps = 5*len(searches)
    for search in searches:
        stage_limits = selected
        stage_baselines[search] = stage_limits
        search_options = {}
        stage = '纯整数网格微调与过渡验收'
        if search == 'validation':
            search_options = dict(validation_data=(base[validation], target[validation]), step_sizes=(1, 2))
            stage = '验证集引导的整数网格微调'
        for _ in range(5):
            sweep = len(history)+1
            if progress:
                progress(stage=stage, sweep=sweep, total_sweeps=sweeps,
                         state='running', point=None)
            proposal, moves = polish_grid(grid, train_base, train_target, train_gray,
                probe_base, response, bank, strength, stage_limits, **search_options)
            trials = []
            start = grid
            if moves:
                change = proposal.astype(int)-start
                for fraction in (1., .75, .5, .25):
                    candidate = np.rint(start+fraction*change).astype(np.int8)
                    metrics = measure(candidate)
                    failures = selection_failures(metrics, stage_limits, selected['color_score'])
                    trials.append(dict(fraction=fraction, metrics=metrics, rejected_by=failures))
                    if not failures:
                        grid, selected = candidate, metrics
            failures = guard_failures(selected, stage_limits)
            round_result = dict(sweep=sweep, proposed_moves=moves,
                applied_moves=int(np.count_nonzero(grid != start)), metrics=selected,
                gray_passed='gray_rmse' not in failures,
                saturation_passed=not any(key in SATURATION_LIMITS for key in failures),
                gray_rejections=sum('gray_rmse' in trial['rejected_by'] for trial in trials),
                saturation_rejections=sum(any(key in SATURATION_LIMITS for key in trial['rejected_by'])
                                          for trial in trials),
                rejected_candidates=sum(bool(trial['rejected_by']) for trial in trials))
            history.append(dict(sweep=sweep, search=search, moves=moves, candidates=trials))
            if progress:
                progress(state='round_done', integer_round=round_result)
            if grid is start:
                break
    return grid, dict(enabled=True, mode='integer-only', strategy=strategy,
        validation_before=baseline, stage_baselines=stage_baselines,
        validation_after=selected, baseline_grid_sha256=baseline_sha, sweeps=history,
        accepted=selected is not baseline, validation_samples=int(validation.sum()),
        gray_anchors=int(gray_mask.sum()), continuity_strength=strength, test_used_for_selection=False)
