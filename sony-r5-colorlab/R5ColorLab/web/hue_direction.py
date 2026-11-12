"""Train-only target-relative hue-offset direction constraint.

For each measured hue24 tonal ray, adjacent target colours define the trusted
direction of dH(V). Predictions are penalized only when their adjacent hue
step runs against that direction. Target turns, plateaus and unreliable dark
or low-chroma samples do not create a constraint.
"""
from collections import defaultdict
import hashlib
from numbers import Real

import numpy as np
from perceptual import to_lab

POLICY = 'target-hue-offset-direction/1'


def strength(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or not np.isfinite(value) or not 0 <= value <= 100:
        raise ValueError('Hue direction strength must be a finite real number in 0..100')
    return float(value)


def _hue(rgb, module=np):
    x = rgb
    high = module.max(x, axis=1) if module is np else module.amax(x, dim=1)
    low = module.min(x, axis=1) if module is np else module.amin(x, dim=1)
    delta = high - low
    denominator = module.maximum(delta, 1e-12) if module is np else delta.clamp(min=1e-12)
    r, g, b = x[:, 0], x[:, 1], x[:, 2]
    red = module.remainder((g-b)/denominator, 6)
    green = (b-r)/denominator + 2
    blue = (r-g)/denominator + 4
    if module is np:
        sector = np.where(high == r, red, np.where(high == g, green, blue))
        return np.where(delta > 1e-12, sector*np.pi/3, 0.)
    sector = module.where(high == r, red, module.where(high == g, green, blue))
    return module.where(delta > 1e-12, sector*np.pi/3, module.zeros_like(sector))


def _wrapped_step(angle, module=np):
    delta = angle[1:] - angle[:-1]
    return module.atan2(module.sin(delta), module.cos(delta))


class HueDirectionBank:
    def __init__(self, design, target, split, sample_kind, *,
                 minimum_saturation=.10, minimum_lightness=5.,
                 minimum_target_step_degrees=.05, allowance_degrees=.05):
        design, target = np.asarray(design, float), np.asarray(target, float)
        split, sample_kind = np.asarray(split).astype(str), np.asarray(sample_kind).astype(str)
        if (design.ndim != 2 or design.shape[1] != 3 or target.shape != design.shape
                or split.shape != (len(design),) or sample_kind.shape != (len(design),)
                or not np.isfinite(design).all() or not np.isfinite(target).all()):
            raise ValueError('Hue direction requires finite matching chart arrays')
        chosen = np.flatnonzero((split == 'train') & (sample_kind == 'hue24_tonal'))
        groups = defaultdict(list)
        for row in chosen:
            color = design[row]
            if color.max() > 0:
                groups[tuple(np.round(color/color.max(), 12))].append(row)
        if len(groups) != 24:
            raise ValueError('Hue direction requires exactly 24 real TRAIN tonal rays')
        source, edges, track_ids = [], [], []
        for track, key in enumerate(sorted(groups)):
            rows = np.asarray(groups[key], int)
            rows = rows[np.argsort(np.max(design[rows], axis=1))]
            start = len(source); source.extend(rows.tolist())
            edges.extend((start+i, start+i+1) for i in range(len(rows)-1))
            track_ids.extend([track]*(len(rows)-1))
        self.source_indices = np.asarray(source, dtype=np.int64)
        self.edges = np.asarray(edges, dtype=np.int64)
        self.edge_tracks = np.asarray(track_ids, dtype=np.int64)
        values = target[self.source_indices]
        high, low = values.max(axis=1), values.min(axis=1)
        saturation = np.where(high > 0, (high-low)/high, 0.)
        lightness = to_lab(np.clip(values, 0, 1)*255)[:, 0]
        target_step = np.empty(len(self.edges))
        for edge in range(len(self.edges)):
            a, b = self.edges[edge]
            target_step[edge] = _wrapped_step(_hue(values[[a, b]]))[0]
        reliable = ((saturation[self.edges] >= minimum_saturation).all(axis=1)
                    & (lightness[self.edges] >= minimum_lightness).all(axis=1)
                    & (np.abs(np.degrees(target_step)) >= minimum_target_step_degrees))
        self.edges = self.edges[reliable]
        self.edge_tracks = self.edge_tracks[reliable]
        self.target_step = target_step[reliable]
        self.direction = np.sign(self.target_step)
        self.allowance = np.radians(float(allowance_degrees))
        counts = np.bincount(self.edge_tracks, minlength=24)
        self.mass = np.asarray([1/(24*counts[t]) for t in self.edge_tracks], float)
        self.settings = dict(minimum_saturation=float(minimum_saturation),
            minimum_lightness=float(minimum_lightness),
            minimum_target_step_degrees=float(minimum_target_step_degrees),
            allowance_degrees=float(allowance_degrees))
        self.input_sha256 = hashlib.sha256(np.ascontiguousarray(design[self.source_indices]).tobytes()).hexdigest()
        self.target_sha256 = hashlib.sha256(np.ascontiguousarray(values).tobytes()).hexdigest()
        self._tensor_cache = {}

    def _steps(self, prediction):
        p = np.asarray(prediction, float)
        if p.shape != (len(self.source_indices), 3) or not np.isfinite(p).all():
            raise ValueError('Hue direction predictions must match the frozen TRAIN rays')
        angle = _hue(np.clip(p, 0, 1))
        return np.arctan2(np.sin(angle[self.edges[:, 1]]-angle[self.edges[:, 0]]),
                          np.cos(angle[self.edges[:, 1]]-angle[self.edges[:, 0]]))

    def rows(self, prediction, amount):
        amount = strength(amount)
        if not amount:return np.empty(0)
        reverse = np.maximum(-self.direction*self._steps(prediction)-self.allowance, 0.)/np.pi
        return reverse*np.sqrt(self.mass*amount/100*8)

    def cost(self, prediction, amount):
        rows = self.rows(prediction, amount)
        return float(rows@rows)*255**2

    def tensor_loss(self, tools, prediction, amount):
        amount = strength(amount)
        if not amount:return prediction.sum()*0
        key = (str(prediction.device), str(prediction.dtype))
        if key not in self._tensor_cache:
            self._tensor_cache[key] = dict(edges=tools.tensor(self.edges, integer=True),
                direction=tools.tensor(self.direction), mass=tools.tensor(self.mass))
        c = self._tensor_cache[key]; t = tools.torch
        angle = _hue(prediction.clamp(0, 1), t)
        step = t.atan2(t.sin(angle[c['edges'][:, 1]]-angle[c['edges'][:, 0]]),
                       t.cos(angle[c['edges'][:, 1]]-angle[c['edges'][:, 0]]))
        reverse = (-c['direction']*step-self.allowance).clamp(min=0)/np.pi
        return (reverse.square()*c['mass']).sum()*amount/100*8

    def report(self, prediction, amount):
        amount = strength(amount); step = self._steps(prediction)
        opposite = self.direction*step < -self.allowance
        reverse = np.maximum(-self.direction*step, 0.)
        target_degrees, predicted_degrees = np.degrees(self.target_step), np.degrees(step)
        tracks = []
        for track in range(24):
            at = self.edge_tracks == track
            tracks.append(dict(index=track, constrained_edges=int(at.sum()),
                opposite_edges=int(np.sum(opposite & at)),
                agreement_rate=float(np.mean(~opposite[at])) if at.any() else None,
                maximum_reverse_degrees=float(np.max(np.degrees(reverse[at]), initial=0.))))
        circular_error=np.degrees(np.arctan2(np.sin(step-self.target_step),
                                              np.cos(step-self.target_step)))
        return dict(policy=POLICY, enabled=bool(amount), strength=amount,
            training_only=True, target_relative=True, global_monotonicity=False,
            target_turns_preserved=True, reliable_edges=len(self.edges), tonal_rays=24,
            opposite_edges=int(opposite.sum()), agreement_rate=float(np.mean(~opposite)),
            maximum_reverse_degrees=float(np.max(np.degrees(reverse), initial=0.)),
            mean_circular_step_error_degrees=float(np.mean(np.abs(circular_error))),
            objective_cost_8bit_squared=self.cost(prediction, amount), settings=self.settings,
            input_sha256=self.input_sha256, target_sha256=self.target_sha256,
            target_step_degrees=target_degrees.tolist(), predicted_step_degrees=predicted_degrees.tolist(),
            tracks=tracks)
