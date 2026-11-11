"""统一的整数配方评分与门槛；搜索缓存不能替代最终BIN独立复核。"""
from collections import OrderedDict
from dataclasses import dataclass
import json

import numpy as np

from integer_grid import TRANSITION_LIMITS, candidate_metrics, guard_failures
from perceptual import de2000, to_lab

PROTECTED = ('gray_rmse', 'continuity_cost', *TRANSITION_LIMITS, 'delta_e00_p95')
COLOR = ('rgb_rmse', 'delta_e00_mean')


def adoption_failures(metrics, baseline, best_color=None):
    """只按真实回读指标采用候选；非有限数不能借比较运算绕过保护。"""
    required = (*PROTECTED, *COLOR, 'color_score')
    if any(key not in metrics or not np.isfinite(metrics[key]) for key in required):
        return ['nonfinite_or_missing_metrics']
    if any(key not in baseline or not np.isfinite(baseline[key]) for key in required):
        raise ValueError('评分基准不完整或含非有限值')
    failures = guard_failures(metrics, baseline)
    if metrics['delta_e00_p95'] > baseline['delta_e00_p95'] + 1e-10:
        failures.append('delta_e00_p95')
    failures.extend(key for key in COLOR if metrics[key] >= baseline[key] - 1e-10)
    if best_color is not None and metrics['color_score'] >= best_color - 1e-10:
        failures.append('validation_color_score')
    return failures


def color_metrics(rgb, target):
    """实际8位指标与显示取整前指标分开记录，后者只处理搜索平台。"""
    p, t = [np.clip(np.asarray(value, float), 0, 1) for value in (rgb, target)]
    if p.shape != t.shape or not len(p) or not np.isfinite(p).all() or not np.isfinite(t).all():
        raise ValueError('颜色评分需要相同形状的有限非空数据')
    a, b = [np.floor(value * 255 + .5) for value in (p, t)]
    delta = de2000(to_lab(a), to_lab(b))
    tail = np.partition(delta, len(delta) - max(1, int(np.ceil(.05 * len(delta)))))[-max(1, int(np.ceil(.05 * len(delta)))):]
    return dict(rgb_rmse=float(np.sqrt(np.mean((a-b)**2))),
        delta_e00_mean=float(delta.mean()), delta_e00_p95=float(np.percentile(delta, 95)),
        delta_e00_tail_mean=float(tail.mean()),
        float_rgb_rmse=float(np.sqrt(np.mean((p-t)**2))*255),
        float_delta_e00_mean=float(de2000(to_lab(p*255), to_lab(t*255)).mean()))


def validate_splits(inputs, target, train, gray, validation):
    train, gray, validation = map(np.asarray, (train, gray, validation))
    if (inputs.ndim != 3 or inputs.shape[1:] != (9, 3) or target.shape != (len(inputs), 3)
            or not np.isfinite(inputs).all() or not np.isfinite(target).all()
            or np.any(inputs < 0) or np.any(inputs > 65535)
            or train.ndim != 1 or train.dtype.kind not in 'iu' or not len(train)
            or len(np.unique(train)) != len(train) or np.any(train < 0) or np.any(train >= len(inputs))
            or gray.dtype != bool or validation.dtype != bool
            or gray.shape != (len(inputs),) or validation.shape != gray.shape
            or not gray.any() or not validation.any() or validation[train].any()
            or not np.isin(np.flatnonzero(gray), train).all()):
        raise ValueError('训练、灰阶和验证集必须有效、分离且包含全部灰阶锚点')


@dataclass
class ScoredRecipe:
    entry: dict
    sha256: str
    metrics: dict
    training: dict
    label: str


class RecipeScorer:
    """只持有训练/验证/固定探针；不接收测试掩码，不读取照片。"""
    def __init__(self, config, context, inputs, target, train, gray, validation,
                 response, bank, strength, perceptual, *, native_cache_size=4):
        import core
        from measured_response import get

        validate_splits(inputs, target, train, gray, validation)
        self.context, self.bank = context, bank
        self.version = core.compiler.format_version(config)
        self.response = get(response)
        self.train_target = np.asarray(target[train], float).copy()
        self.valid_target = np.asarray(target[validation], float).copy()
        self.gray_train = np.asarray(gray[train], bool).copy()
        self.ntrain, self.nvalid = len(train), int(validation.sum())
        self.inputs = np.concatenate((inputs[train], inputs[validation], bank.inputs(context.base)))
        self.measure = candidate_metrics(target[gray], self.valid_target, response,
            bank, strength, perceptual, include_p95=True)
        # 灰阶顺序可以与训练索引不同，按原始灰阶行重排，保持同一评分口径。
        position = {int(row): i for i, row in enumerate(train)}
        self.gray_positions = np.array([position[int(i)] for i in np.flatnonzero(gray)])
        self.cache, self.scored = OrderedDict(), {}
        self.cache_size = native_cache_size
        self.counts = dict(native_renders=0, native_cache_hits=0, scored=0, score_cache_hits=0)

    def canonical(self, entry):
        import core
        blob = core.compiler.pack(core.compiler.config([entry], self.version))
        decoded, = core.compiler.unpack(blob)['entries']
        return decoded, core.sha(blob)

    def native(self, entry):
        import core
        from compute_backend import render_native
        from gpu_runtime import cpu_reference
        from patch_sampling import center_mean

        key = json.dumps({key: entry[key] for key in ('gamma_native_129', 'cc1_delta', 'block13')},
                         sort_keys=True, separators=(',', ':'))
        if key in self.cache:
            self.cache.move_to_end(key)
            self.counts['native_cache_hits'] += 1
            return self.cache[key]
        model = self.context.build(**core.slot_native_parameters(self.context, entry))
        with cpu_reference():
            base = center_mean(render_native(model, self.inputs))/16383
        self.counts['native_renders'] += 1
        self.cache[key] = (model, base)
        if len(self.cache) > self.cache_size:
            self.cache.popitem(last=False)
        return model, base

    def score(self, entry, label):
        from fit_bin_joint import grid_from

        entry, digest = self.canonical(entry)
        if digest in self.scored:
            self.counts['score_cache_hits'] += 1
            return self.scored[digest]
        _, base = self.native(entry)
        table = grid_from(entry)
        train, valid, probes = np.split(base, (self.ntrain, self.ntrain+self.nvalid))
        metrics = self.measure(table, train[self.gray_positions], valid, probes)
        # 所有搜索方向只用训练；验证的尾部统计只用于候选筛选。
        metrics.update(color_metrics(self.response.predict_cpu(valid, table), self.valid_target))
        training = color_metrics(self.response.predict_cpu(train, table), self.train_target)
        if not all(np.isfinite(value) for value in (*metrics.values(), *training.values())):
            raise ValueError('整数候选产生非有限评分')
        result = ScoredRecipe(entry, digest, metrics, training, label)
        self.scored[digest] = result
        self.counts['scored'] += 1
        return result
