"""在固定色卡留出集上检查已量化网格的局部退化。"""
import numpy as np

from integer_grid import transition_metrics
from perceptual import de2000, to_lab
from residual_grid import evaluate, pack

POLICY = 'chart-grid-holdout/1'
MIN_GROUP = 16
TOLERANCE = 1e-10


def rgb8(values):
    if not np.isfinite(values).all():
        raise ValueError('色卡保护需要有限的 RGB 数据')
    return np.floor(np.clip(values, 0, 1) * 255 + .5)


def shadow_masks(lab):
    dark = lab[:, 0] <= 25
    return dark, dark & (np.linalg.norm(lab[:, 1:], axis=1) <= 8)


def focused_weights(target, prediction, mass):
    """用基准网格的训练残差做一次有界重加权。"""
    lab_target = to_lab(rgb8(target))
    dark, neutral = shadow_masks(lab_target)
    delta = de2000(to_lab(rgb8(prediction)), lab_target)
    tail = delta > np.percentile(delta, 95)
    weights = mass * (1 + .25 * dark + .25 * neutral + .5 * tail)
    return weights / weights.sum(), dict(shadows=int(dark.sum()),
        dark_neutral=int(neutral.sum()), tail=int(tail.sum()))


def select(candidates, baseline, response, validation, gray, continuity=None):
    """从训练集提出的候选中选优，所有门槛固定在同一个原候选。"""
    validation_base, validation_target = validation
    gray_base, gray_target = gray
    target = rgb8(validation_target)
    gray_target = rgb8(gray_target)
    lab_target = to_lab(target)
    dark, dark_neutral = shadow_masks(lab_target)
    coverage = dict(validation=len(target), gray=len(gray_target),
                    shadows=int(dark.sum()), dark_neutral=int(dark_neutral.sum()))
    tail_count = max(1, int(np.ceil(.05 * len(target))))
    before, rows, chosen = None, [], baseline
    seen = set()
    # 优先测原流程的选择，重复网格无需重新计算。
    for candidate in (baseline, *candidates):
        _, table, audit = candidate
        payload = pack(table)
        if payload in seen:
            continue
        seen.add(payload)
        prediction = rgb8(evaluate(validation_base, table, response))
        lab = to_lab(prediction)
        delta = de2000(lab, lab_target)
        gray_prediction = rgb8(evaluate(gray_base, table, response))
        metrics = dict(rgb_rmse=float(np.sqrt(np.mean((prediction - target)**2))),
                       delta_e00_mean=float(delta.mean()), delta_e00_p95=float(np.percentile(delta, 95)),
                       delta_e00_tail_mean=float(np.partition(delta, len(delta) - tail_count)[-tail_count:].mean()),
                       gray_rmse=float(np.sqrt(np.mean((gray_prediction - gray_target)**2))))
        if coverage['shadows'] >= MIN_GROUP:
            metrics['shadows_p95'] = float(np.percentile(delta[dark], 95))
        if coverage['dark_neutral'] >= MIN_GROUP:
            error = lab[dark_neutral, 1:] - lab_target[dark_neutral, 1:]
            metrics['dark_neutral_ab_rmse'] = float(np.sqrt(np.mean(np.sum(error**2, axis=1))))
        if continuity is not None:
            bank, probes, strength = continuity
            metrics.update(transition_metrics(bank, evaluate(probes, table, response), strength))
        if not all(np.isfinite(value) for value in metrics.values()):
            raise ValueError('色卡留出复核产生非有限指标')
        if before is None:
            before = after = metrics
        else:
            rejected = [name for name, value in metrics.items() if value > before[name] + TOLERANCE]
            # 总体误差须有实际改善，局部和连续性指标只作保护门槛。
            if all(metrics[name] >= before[name] - TOLERANCE for name in ('rgb_rmse', 'delta_e00_mean')):
                rejected.append('no_global_improvement')
            if not rejected and (metrics['delta_e00_mean'], metrics['rgb_rmse']) < (after['delta_e00_mean'], after['rgb_rmse']):
                chosen, after = candidate, metrics
            rows.append(dict(smoothness=audit['smoothness'], kind=audit.get('kind', 'smoothness'),
                             metrics=metrics, rejected_by=rejected))
    return chosen, dict(policy=POLICY, coverage=coverage, minimum_group_samples=MIN_GROUP,
        adopted=chosen is not baseline, baseline_smoothness=baseline[2]['smoothness'],
        selected_smoothness=chosen[2]['smoothness'], selected_kind=chosen[2].get('kind', 'smoothness'),
        before=before, after=after, candidates=rows,
        test_used_for_selection=False)
