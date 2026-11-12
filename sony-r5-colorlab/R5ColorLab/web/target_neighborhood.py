"""Optional train-only suppression of extra local RGB ringing.

Only four consecutive measured chart colors define a colored neighborhood.
The loss suppresses alternating +,-,+ / -,+,- differences beyond the target's
own local pattern. Monotone curves, unequal slopes and one sustained turn are
unpenalized. Neutral inputs retain target tint with a separate monotonic gate.
"""
from collections import defaultdict
import hashlib
from numbers import Real
import numpy as np
from perceptual import to_lab

POLICY = 'train-target-neighborhood-antiringing/2'


def _backsteps(windows, positive, minimum, stack):
    a,b,c=windows[...,1,:]-windows[...,0,:],windows[...,2,:]-windows[...,1,:],windows[...,3,:]-windows[...,2,:]
    plus=minimum(minimum(positive(a),positive(-b)),positive(c))
    minus=minimum(minimum(positive(-a),positive(b)),positive(-c))
    return stack([plus,minus],axis=-2)


def isolated_backsteps(windows):
    """Actual encoded-RGB amplitude of isolated +,-,+ / -,+,- patterns."""
    return _backsteps(np.asarray(windows),lambda x:np.maximum(x,0),np.minimum,lambda a,axis:np.stack(a,axis=axis))


def _vector_backsteps(windows,positive,minimum,norm,quantum):
    a,b,c=windows[:,1]-windows[:,0],windows[:,2]-windows[:,1],windows[:,3]-windows[:,2]
    axis=a+c
    length=norm(axis,axis=1)
    if isinstance(windows,np.ndarray):den=np.maximum(length,quantum)
    else:den=length.clamp(min=quantum)
    direction=axis/den[:,None]
    along=lambda v:(v*direction).sum(axis=1)
    alignment=positive((a*c).sum(axis=1))/(norm(a,axis=1)*norm(c,axis=1)+quantum**2)
    return minimum(minimum(positive(along(a)),positive(-along(b))),positive(along(c)))*alignment


def vector_backsteps(windows,quantum=1/16383):
    return _vector_backsteps(np.asarray(windows),lambda x:np.maximum(x,0),np.minimum,np.linalg.norm,quantum)


def _strength(value):
    if isinstance(value, (bool, np.bool_)) or not isinstance(value, Real) or not np.isfinite(value) or not 0 <= value <= 100:
        raise ValueError('Neighborhood strength must be a finite real number in 0..100')
    return float(value)


class TargetNeighborhoodBank:
    """Frozen exact RGB-axis and neutral-line neighborhoods within train.

    ``source_indices`` indexes the original arrays; ``rows`` and ``tensor_loss``
    accept predictions in precisely that order. Duplicate design colors are
    averaged for neighborhood evaluation. Targets of duplicates must agree within
    an explicit tolerance, or construction fails instead of hiding a conflict.
    Euclidean design-RGB distances select and weight actual neighbors only.
    Isolated colored patches supply no shape information.
    """
    def __init__(self, design, target, split, train=None, *, max_step=.125,
                 max_step_ratio=4., duplicate_tolerance=1/255,
                 first_rate=1e-5, second_rate=1e-8, perceptual_mix=1.,
                 backstep_rate=8., gray_axis_rate=.02, prediction_quantum=1/16383):
        design, target, split = np.asarray(design), np.asarray(target), np.asarray(split)
        if design.ndim != 2 or design.shape[1] != 3 or target.shape != design.shape or split.shape != (len(design),):
            raise ValueError('Expected matching design/target Nx3 and split N')
        indices = np.flatnonzero(split == 'train') if train is None else np.asarray(train)
        if (indices.ndim != 1 or indices.dtype.kind not in 'iu' or len(np.unique(indices)) != len(indices)
                or np.any(indices < 0) or np.any(indices >= len(split)) or not np.all(split[indices] == 'train')):
            raise ValueError('Neighborhood indices must be unique training rows')
        self.source_indices = indices.astype(np.int64)
        # Slice first: non-train colors/targets never construct or validate the bank.
        x, y = np.asarray(design[indices], float), np.asarray(target[indices], float)
        if (not len(x) or not np.isfinite(x).all() or not np.isfinite(y).all()
                or np.any((x < 0) | (x > 1)) or np.any((y < 0) | (y > 1))):
            raise ValueError('Training design/target must be finite RGB in 0..1')
        settings = np.asarray([max_step, max_step_ratio, duplicate_tolerance,
                               first_rate, second_rate, perceptual_mix, backstep_rate, gray_axis_rate, prediction_quantum], float)
        if (not np.isfinite(settings).all() or max_step <= 0 or max_step_ratio < 1
                or min(duplicate_tolerance, first_rate, second_rate, perceptual_mix, backstep_rate, gray_axis_rate) < 0 or prediction_quantum <= 0):
            raise ValueError('Invalid target-neighborhood geometry or rates')
        self.design, self.inverse, self.counts = np.unique(x, axis=0, return_inverse=True, return_counts=True)
        n = len(self.design)
        self.target = np.zeros((n, 3)); np.add.at(self.target, self.inverse, y)
        self.target /= self.counts[:, None]
        low, high = np.full((n, 3), np.inf), np.full((n, 3), -np.inf)
        np.minimum.at(low, self.inverse, y); np.maximum.at(high, self.inverse, y)
        if np.max(high-low) > duplicate_tolerance + 1e-12:
            raise ValueError('Duplicate design colors have inconsistent training targets')
        self.target_lab = to_lab(self.target*255)/100
        self.first_rate, self.second_rate, self.perceptual_mix = first_rate, second_rate, perceptual_mix
        lines = []
        for axis in range(3):
            other = [i for i in range(3) if i != axis]
            groups = defaultdict(list)
            for i, color in enumerate(self.design):
                groups[tuple(color[other])].append(i)
            for key in sorted(groups):
                line = sorted(groups[key], key=lambda i: self.design[i, axis])
                if len(line) > 1: lines.append(('rgb-axis-'+str(axis), np.asarray(line)))
        gray = np.flatnonzero(np.all(self.design == self.design[:, [0]], axis=1))
        if len(gray) > 1: lines.append(('neutral', gray))
        edges, trips, first_weight, second_weight = [], [], [], []
        quads, quad_weight, quad_names = [], [], []
        first_names, second_names = [], []
        for line_number, (name, line) in enumerate(lines):
            steps = np.linalg.norm(np.diff(self.design[line], axis=0), axis=1)
            for i in range(max(0,len(line)-3)):
                segment=steps[i:i+3]
                if np.all(segment>0) and segment.max()<=max_step and segment.max()/segment.min()<=max_step_ratio:
                    quads.append(line[i:i+4]);quad_weight.append(segment.mean());quad_names.append((name,line_number))
            for i, step in enumerate(steps):
                if 0 < step <= max_step:
                    edges.append(line[i:i+2]); first_weight.append(step); first_names.append((name, line_number))
            for i, (left, right) in enumerate(zip(steps[:-1], steps[1:])):
                if 0 < min(left, right) and max(left, right) <= max_step and max(left, right)/min(left, right) <= max_step_ratio:
                    trips.append(line[i:i+3]); second_weight.append((left+right)/2); second_names.append((name, line_number))
        self.edges = np.asarray(edges, dtype=np.int64).reshape(-1, 2)
        self.triplets = np.asarray(trips, dtype=np.int64).reshape(-1, 3)
        self.edge_distance = np.linalg.norm(self.design[self.edges[:, 1]]-self.design[self.edges[:, 0]], axis=1)
        self.triplet_distance = np.linalg.norm(np.diff(self.design[self.triplets], axis=1), axis=2)
        # Equal family and line masses, arc quadrature within a line, equal RGB
        # output mass. Dense gray tracks cannot crowd out colored directions.
        def mass(values, names):
            a = np.asarray(values, float)
            if not len(a): return a
            lines_by_family = defaultdict(set)
            line_mass = defaultdict(float)
            for value, (family, line) in zip(a, names):
                lines_by_family[family].add(line); line_mass[line] += value
            return np.asarray([value/line_mass[line]/len(lines_by_family[family])/len(lines_by_family)/3
                for value, (family, line) in zip(a, names)])
        self.first_scale = np.sqrt(first_rate*mass(first_weight, first_names))
        self.second_scale = np.sqrt(second_rate*mass(second_weight, second_names))
        self.quads=np.asarray(quads,dtype=np.int64).reshape(-1,4)
        self.backstep_scale=np.sqrt(backstep_rate*mass(quad_weight,quad_names))
        self.gray_indices=gray.astype(np.int64)
        neutral=np.all(self.design==self.design[:,[0]],axis=1)
        self.gray_edges=self.edges[np.all(neutral[self.edges],axis=1)]
        self.prediction_quantum=float(prediction_quantum)
        self.gray_axis_rate=float(gray_axis_rate)
        self.boundary_channels=np.any((self.target[self.quads]<=prediction_quantum)|(self.target[self.quads]>=1-prediction_quantum),axis=1)
        # One known native prediction-output LSB; target retains its original
        # 16-bit/ICC floating precision and is NOT assumed quantized to 14 bits.
        self.backstep_allowance=prediction_quantum*np.where(self.boundary_channels,4.,1.)
        self.target_backsteps=isolated_backsteps(self.target[self.quads])
        self.target_vector_backsteps=vector_backsteps(self.target[self.quads],prediction_quantum)
        self.gray_negative=np.maximum(-np.diff(self.target[self.gray_edges],axis=1)[:,0],0)
        self.backstep_rate=float(backstep_rate)
        self._tensor_cache = {}
        supported = bool(len(quads) or len(gray))
        enabled = bool((len(quads) and backstep_rate) or (len(self.gray_edges) and backstep_rate) or (len(gray) and gray_axis_rate))
        reason = None if enabled else ('no supported training neighborhoods' if not supported else 'all available shape rates are zero')
        self.metadata = dict(policy=POLICY, training_only=True, default_enabled=False,
            enabled=enabled, disabled_reason=reason, high_frequency_windows=len(quads),
            shape='isolated +,-,+ or -,+,- per RGB channel plus vector fold; no absolute slope/curvature penalty',
            prediction_quantum=prediction_quantum,target_assumed_quantized=False,
            boundary_policy='frozen target clips only, per-channel 4 prediction LSB allowance; interior 1 LSB',
            gray_policy='monotone within target reversal plus one LSB; target gray chroma axis preserved',
            backstep_rate=backstep_rate,gray_axis_rate=gray_axis_rate,
            source_rows=len(indices), unique_colors=n, duplicate_rows=len(x)-n,
            duplicate_max_target_range=float(np.max(high-low)), duplicate_tolerance=duplicate_tolerance,
            first_rows=len(edges), second_rows=len(trips), max_step=max_step,
            max_step_ratio=max_step_ratio, exact_other_coordinates=True,
            weighting='equal direction family and line masses; within-line RGB arc quadrature',
            target_interpolation=False, global_hue_monotonicity=False,
            first_rate=first_rate, second_rate=second_rate, perceptual_mix=perceptual_mix,
            units='encoded RGB backstep amplitude; squared weighted RGB rows',
            diagnostic_only=['first_rows','second_rows','first_rate','second_rate','rgb_derivative_residual_rms','rgb_curvature_residual_rms'],
            design_sha256=hashlib.sha256(x.tobytes()).hexdigest(),
            target_sha256=hashlib.sha256(y.tobytes()).hexdigest(),
            source_indices_sha256=hashlib.sha256(self.source_indices.tobytes()).hexdigest(),
            unsupported='No derivative claim for isolated colors, large gaps, or other unmeasured directions')

    def _values(self, predictions):
        p = np.asarray(predictions, float)
        if p.shape != (len(self.source_indices), 3) or not np.isfinite(p).all():
            raise ValueError('Predictions must match source_indices order and be finite Nx3')
        result = np.zeros_like(self.target); np.add.at(result, self.inverse, p)
        return result/self.counts[:, None]

    def validate_source_indices(self, indices):
        """Call when binding a training stage; rebuild if its row order changes."""
        if not np.array_equal(np.asarray(indices), self.source_indices):
            raise ValueError('Training row order changed; rebuild the target neighborhood bank')

    def _derivatives(self, error):
        first = np.diff(error[self.edges], axis=1)[:, 0]/self.edge_distance[:, None]
        a, b, c = error[self.triplets].transpose(1, 0, 2)
        left, right = self.triplet_distance.T
        second = 2*((c-b)/right[:, None]-(b-a)/left[:, None])/(left+right)[:, None]
        return first, second

    def _shape_rows(self, values, op, constants=None):
        # Broad curves, slope magnitude, curvature and one sustained turn are
        # deliberately absent from this objective.
        pos, minimum, norm, stack = op
        c = self.__dict__ if constants is None else constants
        windows = values[c['quads']]
        back = _backsteps(windows, pos, minimum, stack)
        vector = _vector_backsteps(windows, pos, minimum, norm, self.prediction_quantum)
        allowance, scale = c['backstep_allowance'], c['backstep_scale']
        channel = pos(back-c['target_backsteps']-allowance[:,None,:])*scale[:,None,None]
        # Each channel has its own frozen boundary allowance; clipping another
        # channel or clipping the prediction cannot turn off this gate.
        vector = pos(vector-c['target_vector_backsteps']-norm(allowance,axis=1))*scale*(self.perceptual_mix**.5)
        gray = values[c['gray_indices']]-c['target'][c['gray_indices']]
        luma = gray@c['luma'] if constants is not None else gray@np.array([.2126,.7152,.0722])
        chroma = (gray-luma[:,None])*np.sqrt(self.gray_axis_rate/max(1,len(self.gray_indices)*3))
        edges = c['gray_edges']
        delta = values[edges[:,1]]-values[edges[:,0]]
        monotone = pos(-delta-c['gray_negative']-self.prediction_quantum)*np.sqrt(self.backstep_rate/max(1,len(self.gray_edges)*3))
        return [channel.reshape(-1),vector.reshape(-1),chroma.reshape(-1),monotone.reshape(-1)]

    def _tensor_constants(self, tools, predictions):
        # Materialize each frozen target/index bank once per device and dtype.
        # Native device indices avoid implicit CPU advanced-index transfers on MPS.
        key = (str(predictions.device), str(predictions.dtype))
        if key not in self._tensor_cache:
            t = tools.torch
            integer = ('inverse','quads','gray_indices','gray_edges')
            floating = ('counts','target','backstep_allowance','backstep_scale',
                        'target_backsteps','target_vector_backsteps','gray_negative')
            cache = {name:t.as_tensor(np.array(getattr(self,name),copy=True),
                device=predictions.device,dtype=t.int64) for name in integer}
            cache.update({name:predictions.new_tensor(getattr(self,name)) for name in floating})
            cache['luma'] = predictions.new_tensor([.2126,.7152,.0722])
            self._tensor_cache[key] = cache
        return self._tensor_cache[key]

    def rows(self, predictions, strength):
        strength=_strength(strength)
        if not strength:return np.empty(0)
        rows=self._shape_rows(self._values(predictions),(lambda x:np.maximum(x,0),np.minimum,np.linalg.norm,lambda a,axis:np.stack(a,axis=axis)))
        return np.concatenate(rows)*np.sqrt(strength/100)

    def cost(self, predictions, strength):
        rows=self.rows(predictions,strength)
        return float(rows@rows)*255**2

    def tensor_loss(self, tools, predictions, strength):
        strength=_strength(strength)
        if tuple(predictions.shape)!=(len(self.source_indices),3):raise ValueError('Predictions must match source_indices order')
        t=tools.torch
        if not strength:return predictions.sum()*0
        cache=self._tensor_constants(tools,predictions)
        values=t.zeros((len(self.design),3),dtype=predictions.dtype,device=predictions.device).index_add(0,cache['inverse'],predictions)/cache['counts'][:,None]
        op=(lambda x:x.clamp(min=0),t.minimum,lambda x,axis:t.linalg.vector_norm(x,dim=axis),lambda a,axis:t.stack(a,dim=axis))
        rows=self._shape_rows(values,op,cache)
        return sum((r*r).sum() for r in rows)*strength/100

    def report(self, predictions, strength):
        strength = _strength(strength)
        values = self._values(predictions)
        first, second = self._derivatives(values-self.target)
        enabled = bool(self.metadata['enabled'] and strength)
        reason = self.metadata['disabled_reason'] if not self.metadata['enabled'] else None if strength else 'strength is zero'
        backsteps = isolated_backsteps(values[self.quads])
        excess = np.maximum(backsteps-self.target_backsteps-self.backstep_allowance[:,None,:],0)
        return dict(self.metadata, enabled=enabled, disabled_reason=reason,
            strength=strength, objective_cost_8bit_squared=self.cost(predictions,strength),
            extra_channel_backsteps=int(np.count_nonzero(excess)),
            max_extra_backstep_8bit=float(np.max(excess)*255) if excess.size else 0.,
            rgb_derivative_residual_rms=float(np.sqrt(np.mean(first**2))) if first.size else None,
            rgb_curvature_residual_rms=float(np.sqrt(np.mean(second**2))) if second.size else None)
