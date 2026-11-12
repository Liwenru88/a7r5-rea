"""Optional, train-only repair of an already fitted signed-7-bit grid.

This module never changes a native model, response calibration, or real target.
It interpolates *endpoint residuals* over real ordered target samples to propose
a small output repair, then projects that proposal back to the shared grid.
Only CPU float64 rendering of pack/unpack integers can accept a proposal.
Finite neighbourhood checks are diagnostics, not a continuous-domain proof.
"""
from collections import defaultdict
import hashlib
from numbers import Real

import numpy as np
from scipy import sparse
from scipy.optimize import minimize

from residual_grid import coefficients, coordinates, pack, response_matrix, stencil, unpack
from target_neighborhood import isolated_backsteps


POLICY = 'postfit-target-relative-deburr/1'
DEFAULTS = dict(max_step=.125, max_step_ratio=4., prediction_quantum=1/16383,
    duplicate_tolerance=1/255, max_coefficient_step=2, max_iterations=60,
    repair_weight=16., coefficient_ridge=.0001, max_output_repair_8bit=2.,
    rgb_rmse_budget_8bit=.02, mean_de00_budget=.01, max_error_budget_8bit=.1,
    gray_chroma_budget=.01, anchor_shift_lsb=1., severe_8bit=.5,
    guard_shift_8bit=.5, guard_side=17)


def options(value=None):
    result = dict(DEFAULTS)
    if value is not None:
        if not isinstance(value, dict) or set(value)-set(result):
            raise ValueError('Unknown post-fit deburr options')
        result.update(value)
    for name, v in result.items():
        if isinstance(v, (bool, np.bool_)) or not isinstance(v, Real) or not np.isfinite(v):
            raise ValueError('Post-fit deburr options must be finite real numbers')
        if v < 0 or (name in ('max_step', 'prediction_quantum', 'repair_weight') and not v):
            raise ValueError('Invalid post-fit deburr option: '+name)
    for name, lo, hi in [('max_coefficient_step', 1, 8), ('max_iterations', 1, 500), ('guard_side', 5, 33)]:
        if type(result[name]) is not int or not lo <= result[name] <= hi:
            raise ValueError('Invalid integer post-fit deburr option: '+name)
    if result['max_step_ratio'] < 1:
        raise ValueError('max_step_ratio must be at least one')
    return result


def _sha(value):
    return hashlib.sha256(np.ascontiguousarray(value).tobytes()).hexdigest()


class TrackBank:
    """Real train colours only; duplicate means are used for shape, never loss.

    RGB axes and neutral lines are exact. Known generated tonal families are
    grouped by a checked constant design-RGB ray, independent of row ordering.
    No nearest-neighbour path or interpolated Fuji target is invented.
    """
    def __init__(self, design, target, sample_kind=None, *, settings=None):
        self.settings = options(settings)
        self.design, self.inverse, self.counts = np.unique(design, axis=0, return_inverse=True, return_counts=True)
        self.target = self.mean(target)
        low, high = np.full_like(self.target, np.inf), np.full_like(self.target, -np.inf)
        np.minimum.at(low, self.inverse, target); np.maximum.at(high, self.inverse, target)
        if np.max(high-low, initial=0.) > self.settings['duplicate_tolerance']+1e-12:
            raise ValueError('Duplicate design colours have inconsistent real targets')
        self.duplicate_max_target_range = float(np.max(high-low, initial=0.))
        self.tracks = []
        for axis in range(3):
            groups = defaultdict(list)
            other = [i for i in range(3) if i != axis]
            for i, color in enumerate(self.design):
                groups[tuple(color[other])].append(i)
            for key in sorted(groups):
                line = np.asarray(sorted(groups[key], key=lambda i:self.design[i, axis]), dtype=int)
                if len(line) >= 4:
                    self.tracks.append(dict(family='rgb-axis-'+str(axis), indices=line))
        self.gray = np.flatnonzero(np.all(self.design == self.design[:, [0]], axis=1))
        self.gray = self.gray[np.argsort(self.design[self.gray, 0])]
        if len(self.gray) >= 4:
            self.tracks.append(dict(family='neutral', indices=self.gray))
        if sample_kind is not None:
            zero = np.flatnonzero(np.all(self.design == 0, axis=1))
            for family in ('hue24_tonal', 'hue16_tonal', 'primary_tonal'):
                original = np.flatnonzero(sample_kind == family)
                unique = np.unique(self.inverse[original])
                groups = defaultdict(list)
                for i in unique:
                    color = self.design[i]
                    if color.max() > 0:
                        groups[tuple(np.round(color/color.max(), 12))].append(i)
                for key in sorted(groups):
                    ids = np.asarray(groups[key], dtype=int)
                    endpoint = self.design[ids[np.argmax(np.linalg.norm(self.design[ids], axis=1))]]
                    norm = float(endpoint@endpoint)
                    distance = self.design[ids]@endpoint/norm
                    if np.max(np.abs(self.design[ids]-distance[:, None]*endpoint)) > 1e-10:
                        raise ValueError('Generated tonal family is not a constant design-RGB ray')
                    ids = ids[np.argsort(distance)]
                    # A real, shared black sample may anchor several real rays.
                    if len(zero) and zero[0] not in ids:
                        ids = np.r_[zero[0], ids]
                    if len(ids) >= 4:
                        self.tracks.append(dict(family=family, indices=ids))
        quads, contexts, seen = [], [], set()
        for track in self.tracks:
            ids = track['indices']
            steps = np.linalg.norm(np.diff(self.design[ids], axis=0), axis=1)
            for at in range(len(ids)-3):
                d = steps[at:at+3]
                if d.min() > 0 and d.max() <= self.settings['max_step'] and d.max()/d.min() <= self.settings['max_step_ratio']:
                    key = tuple(ids[at:at+4])
                    if key not in seen:
                        seen.add(key); quads.append(key); contexts.append((ids, at))
        self.quads = np.asarray(quads, dtype=int).reshape(-1, 4)
        self.quad_contexts = contexts
        self.target_backsteps = isolated_backsteps(self.target[self.quads])
        quantum = self.settings['prediction_quantum']
        boundary = np.any((self.target[self.quads] <= quantum) | (self.target[self.quads] >= 1-quantum), axis=1)
        self.allowance = quantum*np.where(boundary, 4., 1.)

    def mean(self, values):
        result = np.zeros((len(self.design), 3), dtype=float)
        np.add.at(result, self.inverse, values)
        return result/self.counts[:, None]

    def excess(self, values):
        return np.maximum(isolated_backsteps(values[self.quads])-self.target_backsteps-self.allowance[:, None, :], 0.)

    def report(self, values):
        excess = self.excess(values)
        return dict(windows=len(self.quads), extra_events=int(np.sum(excess > 1e-12)),
            severe_events=int(np.sum(excess*255 > self.settings['severe_8bit']+1e-10)),
            max_extra_8bit=float(np.max(excess, initial=0.)*255),
            extra_squared_8bit=float(np.sum((excess*255)**2)))


def repair_targets(bank, prediction, protected=None):
    """Propose local interior repairs while retaining the real target's shape.

    Fritsch--Carlson interpolation of neighbouring prediction-minus-target
    residuals preserves the real target's turns. The anomalous two interior
    samples never become interpolation controls. Two endpoints are the minimum;
    up to one valid real control beyond each side may supply shape information.
    No deterministic target measurement is replaced or discarded.
    """
    original = np.asarray(prediction, float)
    result = original.copy()
    protected = np.zeros(len(original), bool) if protected is None else np.asarray(protected, bool)
    limit = bank.settings['max_output_repair_8bit']/255
    applied, control_counts = 0, defaultdict(int)
    skipped_bad_endpoints = set()
    bad_interior = np.zeros_like(original, dtype=bool)
    initial = bank.excess(original)
    for window, channel in np.argwhere(np.max(initial, axis=1) > 1e-12):
        bad_interior[bank.quads[window, 1:3], channel] = True
    from shape_preserving import fritsch_carlson
    for _ in range(2):
        changed = False
        for window, ids in enumerate(bank.quads):
            old = np.maximum(isolated_backsteps(result[ids][None])-bank.target_backsteps[window]-bank.allowance[window][None, :], 0.)[0]
            for channel in np.flatnonzero(np.max(old, axis=0) > 1e-12):
                # Overlapping events can mark this window's endpoint as the
                # anomalous interior of another window. Such a point cannot
                # supply a supposedly valid FC control; retain this window.
                if np.any(bad_interior[ids[[0, -1]], channel]):
                    skipped_bad_endpoints.add((window, int(channel)))
                    continue
                track, at = bank.quad_contexts[window]
                arc = np.r_[0., np.cumsum(np.linalg.norm(np.diff(bank.design[track], axis=0), axis=1))]
                controls = [at, at+3]
                for position, neighbour in ((at-1, at), (at+4, at+3)):
                    if 0 <= position < len(track) and not bad_interior[track[position], channel]:
                        step = abs(arc[position]-arc[neighbour])
                        if 0 < step <= bank.settings['max_step']:
                            controls.append(position)
                controls = np.asarray(sorted(controls), dtype=int)
                residual = result[track[controls], channel]-bank.target[track[controls], channel]
                fitted = fritsch_carlson(arc[controls], residual[:, None], arc[at:at+4])[:, 0]
                interpolated = bank.target[ids, channel]+fitted
                trial = result[ids].copy()
                movable = ~protected[ids[1:3]]
                for offset in np.flatnonzero(movable)+1:
                    trial[offset, channel] = np.clip(interpolated[offset],
                        max(0., original[ids[offset], channel]-limit), min(1., original[ids[offset], channel]+limit))
                new = np.maximum(isolated_backsteps(trial[None])-bank.target_backsteps[window]-bank.allowance[window][None, :], 0.)[0]
                if np.sum(new[:, channel]**2) < np.sum(old[:, channel]**2)-1e-20 and np.all(new[:, channel] <= old[:, channel]+1e-12):
                    result[ids, channel] = trial[:, channel]
                    old[:, channel] = new[:, channel]
                    applied += 1; control_counts[len(controls)] += 1; changed = True
        if not changed:
            break
    return result, dict(method='real target plus Fritsch-Carlson interpolated neighbouring residuals; anomalous interior samples excluded from controls',
        local_channel_repairs=applied, changed_colours=int(np.sum(np.any(np.abs(result-original) > 1e-12, axis=1))),
        control_count_histogram={str(k):v for k,v in sorted(control_counts.items())},
        two_control_linear_fallback_repairs=control_counts[2],
        skipped_bad_endpoint_channel_windows=len(skipped_bad_endpoints),
        target_measurements_modified=False, synthetic_target_rows=0)


def _renderer(base, response):
    """Return the fixed CPU oracle and its sparse, pre-clip linear design."""
    response = response_matrix(response)
    if isinstance(response, dict):
        from measured_response import get
        model = get(response)
        if not all(hasattr(model, name) for name in ('stencil', 'response', 'predict_cpu')):
            raise ValueError('Post-fit deburr requires a fixed linear-in-grid paired response')
        _, ids, weights = model.stencil(base)
        mixing = model.response(base)
        render = lambda table:model.predict_cpu(base, coefficients(table))
    else:
        ids, weights = stencil(coordinates(base))
        mixing = np.broadcast_to(response.T/256, (len(base), 3, 3))
        def render(table):
            d = (coefficients(table)[ids]*weights[..., None]).sum(axis=1)
            return np.clip(base+np.einsum('nc,nco->no', d, mixing), 0, 1)
    rows, cols, data = [], [], []
    for channel in range(3):
        for output in range(3):
            rows.append(np.repeat(np.arange(len(base))*3+output, 8))
            cols.append((ids*3+channel).ravel())
            data.append((weights*mixing[:, channel, output, None]).ravel())
    design = sparse.coo_matrix((np.concatenate(data), (np.concatenate(rows), np.concatenate(cols))), shape=(len(base)*3, 1215)).tocsr()
    return render, design, ids, weights, mixing


def _metrics(prediction, target, weights=None):
    from perceptual import de2000, to_lab
    if not len(prediction):
        return None
    mass = np.ones(len(prediction)) if weights is None else np.asarray(weights, float)
    mass = mass/mass.sum()
    delta = prediction-target
    pl, tl = to_lab(prediction*255), to_lab(target*255)
    return dict(samples=len(prediction), rgb_rmse_8bit=float(np.sqrt(np.sum(np.mean(delta**2, axis=1)*mass))*255),
        mean_de00=float(np.sum(de2000(pl, tl)*mass)), max_error_8bit=float(np.max(np.abs(delta))*255),
        gray_chroma_rmse=float(np.sqrt(np.sum(np.mean((pl[:, 1:]-tl[:, 1:])**2, axis=1)*mass))))


def _budget_reasons(before, after, settings, label):
    if before is None:
        return []
    result = []
    for metric, budget in [('rgb_rmse_8bit', 'rgb_rmse_budget_8bit'), ('mean_de00', 'mean_de00_budget'), ('max_error_8bit', 'max_error_budget_8bit')]:
        if after[metric] > before[metric]+settings[budget]+1e-10:
            result.append(label+'_'+metric+'_budget')
    return result


def _solve(original, base, desired, mass, design, ids, stencil_weights, mixing, active, settings, device):
    """MPS may propose a continuous move; CPU always scores exported integers."""
    fixed = base.ravel()+design@original.astype(float).ravel()
    local = design[:, active].tocsr()
    original_active = original.ravel()[active].astype(float)
    bounds = np.c_[np.maximum(-settings['max_coefficient_step'], -64-original_active),
                   np.minimum(settings['max_coefficient_step'], 63-original_active)]
    row_mass = np.repeat(mass, 3)/3
    ridge = settings['coefficient_ridge']/max(1, len(active))/256**2
    desired_flat = desired.ravel()
    def cpu(delta):
        raw = fixed+local@delta
        error = np.clip(raw, 0, 1)-desired_flat
        value = float(np.sum(error**2*row_mass)+ridge*(delta@delta))
        gradient = 2*np.asarray(local.T@(error*row_mass*((raw > 0) & (raw < 1)))).ravel()+2*ridge*delta
        return value, gradient
    used, fallback = 'cpu', None
    if device not in (None, 'cpu', 'mps'):
        raise ValueError('Post-fit deburr device must be cpu or mps')
    function = cpu
    if device != 'cpu':
        try:
            import torch
            if not torch.backends.mps.is_available():
                raise RuntimeError('MPS unavailable')
            def tensor(x, integer=False):
                return torch.as_tensor(np.array(x, copy=True), device='mps', dtype=torch.int64 if integer else torch.float32)
            g0, source, goal = tensor(original.astype(float)), tensor(base), tensor(desired)
            tid, tw, mix, ta = tensor(ids, True), tensor(stencil_weights), tensor(mixing), tensor(active, True)
            wm = tensor(mass)
            def metal(delta):
                move = tensor(delta).requires_grad_(True)
                table = (g0.ravel().index_add(0, ta, move)).reshape(405, 3)
                d = (table[tid]*tw[..., None]).sum(dim=1)
                prediction = (source+torch.einsum('nc,nco->no', d, mix)).clamp(0, 1)
                loss = (((prediction-goal)**2).mean(dim=1)*wm).sum()+ridge*(move*move).sum()
                loss.backward()
                return float(loss.detach().cpu()), move.grad.detach().cpu().numpy().astype(float)
            reference, _ = cpu(np.zeros(len(active)))
            accelerated, _ = metal(np.zeros(len(active)))
            if abs(reference-accelerated) > max(1e-9, abs(reference)*1e-4):
                raise RuntimeError('MPS/CPU post-fit objective gate failed')
            function, used = metal, 'mps'
        except (ImportError, RuntimeError, AttributeError) as error:
            fallback = str(error)
    # scipy's relative objective test uses max(1, |f|): normalized RGB losses
    # near 1e-8 otherwise terminate after effectively no movement. Scale value
    # AND gradient together; preflight and audit remain in original units.
    objective_scale = 1e8
    def optimizer_objective(delta):
        value, gradient = function(delta)
        return value*objective_scale, gradient*objective_scale
    fit = minimize(optimizer_objective, np.zeros(len(active)), jac=True, method='L-BFGS-B', bounds=bounds,
        options=dict(maxiter=settings['max_iterations'], maxfun=settings['max_iterations']*2, maxls=16, ftol=1e-12, gtol=1e-10))
    if not np.isfinite(fit.x).all():
        raise ValueError('Nonfinite post-fit projection result')
    return fit.x, dict(backend=used, fallback_reason=fallback, evaluations=int(fit.nfev),
        converged=bool(fit.success), message=str(fit.message), continuous_objective_before=cpu(np.zeros(len(active)))[0],
        continuous_objective_after=cpu(fit.x)[0], active_coefficients=len(active), optimizer_objective_scale=objective_scale)


def deburr(grid, base, target, response, *, design_srgb, split, sample_kind=None,
           anchor_index=None, weights=None, anchor_mask=None, options=None, device=None, progress=None):
    """Return ``(grid, audit)``; unsafe or unhelpful repairs return original bytes.

    All row arrays use the original complete dataset order. Only ``split`` is
    read before slicing; validation/test values never construct geometry,
    targets, constraints, budgets, candidate selection, or acceptance. Optional
    weights have the complete dataset length. ``anchor_mask`` adds explicit
    train anchors; it does not replace ColorChecker24 or real hue-ray endpoints.
    Native output ``base`` and the calibrated ``response`` remain fixed.
    """
    settings = globals()['options'](options)
    if device not in (None, 'cpu', 'mps'):
        raise ValueError('Post-fit deburr device must be cpu or mps')
    original = unpack(pack(grid))
    payload = pack(original)
    split = np.asarray(split)
    if split.ndim != 1:
        raise ValueError('Expected one split value per row')
    train = np.flatnonzero(split == 'train')
    audit = dict(policy=POLICY, enabled=True, accepted=False, reason=None, training_only=True,
        native_parameters_frozen=True, response_frozen=True, target_measurements_modified=False,
        selected_rows=len(train), heldout_rows_used=0, settings=settings,
        original_payload_sha256=hashlib.sha256(payload).hexdigest(), integer_cpu_acceptance=True,
        neighbourhood_scope='finite real train tracks plus fixed synthetic RGB lattice; no continuous-domain guarantee')
    def unchanged(reason):
        audit['reason'] = reason
        audit['final_payload_sha256'] = audit['original_payload_sha256']
        audit['changed_coefficients'] = 0
        return original.copy(), audit
    if len(train) < 4:
        return unchanged('insufficient_train_rows')
    def select(value, shape, label, dtype=None):
        array = np.asarray(value)
        if array.shape != shape:
            raise ValueError('Invalid '+label+' shape')
        return np.asarray(array[train], dtype=dtype)
    n = len(split)
    base = select(base, (n, 3), 'native base', float)
    target = select(target, (n, 3), 'real target', float)
    design = select(design_srgb, (n, 3), 'design RGB', float)
    for value in (base, target, design):
        if not np.isfinite(value).all() or np.any((value < 0) | (value > 1)):
            raise ValueError('Train RGB arrays must be finite and in [0,1]')
    mass = np.ones(len(train)) if weights is None else select(weights, (n,), 'weights', float)
    if not np.isfinite(mass).all() or np.any(mass <= 0):
        raise ValueError('Train weights must be finite and positive')
    mass = mass/mass.sum()
    kind = None if sample_kind is None else select(sample_kind, (n,), 'sample kind')
    anchors = np.zeros(len(train), bool) if anchor_mask is None else select(anchor_mask, (n,), 'anchor mask', bool)
    explicit_anchor_count = int(anchors.sum())
    cc24 = np.zeros(len(train), bool)
    if anchor_index is not None:
        anchor_ids = select(anchor_index, (n,), 'anchor index')
        cc24 = (anchor_ids >= 260) & (anchor_ids < 284)
        if cc24.any() and len(np.unique(anchor_ids[cc24])) != 24:
            return unchanged('incomplete_colorchecker24_anchors')
        anchors |= cc24
    audit['train_identity'] = dict(source_indices_sha256=_sha(train), base_sha256=_sha(base),
        target_sha256=_sha(target), design_sha256=_sha(design))
    try:
        bank = TrackBank(design, target, kind, settings=settings)
    except ValueError as error:
        audit['rejection_detail'] = str(error)
        return unchanged('unsupported_train_geometry')
    hue_tracks = [track for track in bank.tracks if track['family'] == 'hue24_tonal']
    if hue_tracks and len(hue_tracks) != 24:
        return unchanged('incomplete_24_hue_rays')
    if len(hue_tracks) != 24 and explicit_anchor_count < 24:
        return unchanged('missing_24_hue_anchor_evidence')
    endpoints = np.asarray([track['indices'][-1] for track in hue_tracks], dtype=int)
    hue_anchors = np.isin(bank.inverse, endpoints)
    anchors |= hue_anchors
    audit['anchors'] = dict(colorchecker24_rows=int(cc24.sum()), real_hue24_rays=len(hue_tracks),
        real_hue24_endpoint_rows=int(hue_anchors.sum()), explicit_rows=explicit_anchor_count,
        protected_rows=int(anchors.sum()), output_shift_allowance_native_lsb=settings['anchor_shift_lsb'])
    audit['geometry'] = dict(unique_train_colours=len(bank.design), duplicate_rows=len(train)-len(bank.design),
        duplicate_max_target_range=bank.duplicate_max_target_range, windows=len(bank.quads),
        track_families={family:sum(t['family'] == family for t in bank.tracks) for family in sorted({t['family'] for t in bank.tracks})},
        target_interpolation=False, global_hue_monotonicity=False)
    if not len(bank.quads):
        return unchanged('no_supported_real_train_windows')
    try:
        render, design_matrix, ids, stencil_weights, mixing = _renderer(base, response)
    except ValueError as error:
        audit['rejection_detail'] = str(error)
        return unchanged('unsupported_response_model')
    baseline = render(original)
    raw = (base.ravel()+design_matrix@original.astype(float).ravel()).reshape(-1, 3)
    if not np.allclose(np.clip(raw, 0, 1), baseline, atol=2e-12, rtol=0):
        return unchanged('fixed_response_linear_design_gate_failed')
    baseline_mean = bank.mean(baseline)
    before = bank.report(baseline_mean)
    audit['before'] = dict(shape=before, fidelity=_metrics(baseline, target, mass))
    if not before['extra_events']:
        return unchanged('no_extra_train_backsteps')
    protected = np.zeros(len(bank.design), bool)
    protected[np.unique(bank.inverse[anchors])] = True
    desired_mean, repair_audit = repair_targets(bank, baseline_mean, protected)
    audit['repair'] = repair_audit
    changed_rows = np.any(np.abs(desired_mean[bank.inverse]-baseline_mean[bank.inverse]) > 1e-12, axis=1)
    if not changed_rows.any():
        return unchanged('no_local_repair_preserving_target_turns_and_anchors')
    # Duplicate shape means do not erase per-row native output differences.
    desired = np.clip(baseline+desired_mean[bank.inverse]-baseline_mean[bank.inverse], 0, 1)
    node_ids = ids[changed_rows][stencil_weights[changed_rows] > 0]
    active = np.unique((np.unique(node_ids)[:, None]*3+np.arange(3)).ravel())
    solve_mass = mass*np.where(changed_rows, settings['repair_weight'], 1.)
    solve_mass *= np.where(anchors, 64., 1.)
    gray_rows = np.all(design == design[:, [0]], axis=1)
    solve_mass *= np.where(gray_rows, 4., 1.)
    solve_mass /= solve_mass.sum()
    if progress:
        progress(stage='拟合后局部网格去毛刺', state='running', active_coefficients=len(active))
    try:
        delta, audit['solver'] = _solve(original, base, desired, solve_mass, design_matrix,
            ids, stencil_weights, mixing, active, settings, device)
    except (ValueError, RuntimeError, FloatingPointError) as error:
        audit['rejection_detail'] = str(error)
        return unchanged('projection_solver_failed')
    candidates, seen = [], {payload}
    for alpha in (1., .75, .5, .25):
        value = original.astype(float).ravel()
        value[active] += alpha*delta
        candidate = np.clip(np.rint(value), -64, 63).astype(np.int8).reshape(405, 3)
        packed = pack(candidate)
        if packed not in seen:
            seen.add(packed); candidates.append(('projection-'+str(alpha), unpack(packed)))
    # Explore a few neighbouring integer moves if rounding erased a small solve.
    for at in np.argsort(-np.abs(delta))[:4]:
        if abs(delta[at]) < 1e-9:
            continue
        value = original.copy().ravel(); index = active[at]
        proposed = int(value[index])+(1 if delta[at] > 0 else -1)
        if -64 <= proposed <= 63:
            value[index] = proposed
            candidate = value.reshape(405, 3); packed = pack(candidate)
            if packed not in seen:
                seen.add(packed); candidates.append(('integer-neighbour-'+str(index), unpack(packed)))
    if not candidates:
        return unchanged('continuous_projection_has_no_changed_integer_candidate')
    # Fixed probes have no Fuji target: they preserve the old mapping and only
    # reject new folds. They never become additional fitting targets.
    axis = np.linspace(0, 1, settings['guard_side'])
    guards = np.stack(np.meshgrid(axis, axis, axis, indexing='ij'), axis=-1).reshape(-1, 3)
    affected_rows = np.any(np.isin(ids, np.unique(node_ids)) & (stencil_weights > 0), axis=1)
    # A coarse RGB lattice can miss an entire odd-index grid hat. All affected
    # real train inputs therefore join the guard set, even when they were not
    # themselves selected for repair. These old-output guards never fit a move.
    guards = np.unique(np.r_[guards, base[affected_rows]], axis=0)
    guard_render, _, _, _, _ = _renderer(guards, response)
    guard_old = guard_render(original)
    guard_bank = TrackBank(guards, guard_old, settings=settings)
    guard_old_mean = guard_bank.mean(guard_old)
    old_guard_excess = guard_bank.excess(guard_old_mean)
    old_excess = bank.excess(baseline_mean)
    old_severe = old_excess*255 > settings['severe_8bit']+1e-10
    quantum = settings['prediction_quantum']
    gray_before = _metrics(baseline[gray_rows], target[gray_rows])
    # Shape uses duplicate-colour means; fidelity must retain every real row.
    # Shared black/overlap colours remain in every affected real ray's check.
    hue_rows = [np.isin(bank.inverse, track['indices']) & (kind == 'hue24_tonal') for track in hue_tracks]
    track_before = [_metrics(baseline[mask], target[mask]) for mask in hue_rows]
    audit['before']['gray'] = gray_before
    audit['before']['hue24_full_tracks'] = track_before
    audit['finite_guard'] = dict(samples=len(guards), windows=len(guard_bank.quads),
        target='original packed output only; no claimed Fuji target or camera evidence',
        affected_stencil_nodes=len(np.unique(node_ids)), affected_train_rows=int(affected_rows.sum()),
        full_continuous_domain_proven=False)
    choices, audit['candidates'] = [], []
    for name, candidate in candidates:
        candidate = unpack(pack(candidate))
        prediction = render(candidate)
        mean = bank.mean(prediction)
        shape = bank.report(mean)
        metrics = _metrics(prediction, target, mass)
        reasons = _budget_reasons(audit['before']['fidelity'], metrics, settings, 'train')
        excess = bank.excess(mean)
        if shape['extra_squared_8bit'] >= before['extra_squared_8bit']-1e-12:
            reasons.append('train_backsteps_not_reduced')
        if np.any((excess*255 > settings['severe_8bit']+1e-10) & ~old_severe):
            reasons.append('new_severe_train_backstep')
        if shape['max_extra_8bit'] > before['max_extra_8bit']+quantum*255+1e-10:
            reasons.append('maximum_train_backstep_increased')
        anchor_shift = float(np.max(np.abs(prediction[anchors]-baseline[anchors]), initial=0.))
        if anchor_shift > settings['anchor_shift_lsb']*quantum+1e-12:
            reasons.append('protected_anchor_output_shift')
        if np.any(np.abs(prediction[anchors]-target[anchors]) > np.abs(baseline[anchors]-target[anchors])+settings['anchor_shift_lsb']*quantum+1e-12):
            reasons.append('protected_anchor_target_error')
        gray_after = _metrics(prediction[gray_rows], target[gray_rows])
        reasons += _budget_reasons(gray_before, gray_after, settings, 'gray')
        if gray_before is not None and gray_after['gray_chroma_rmse'] > gray_before['gray_chroma_rmse']+settings['gray_chroma_budget']+1e-10:
            reasons.append('gray_target_chroma_budget')
        if len(bank.gray) >= 2:
            def gray_reverse(p):
                return np.maximum(-np.diff(p[bank.gray], axis=0)-np.maximum(-np.diff(bank.target[bank.gray], axis=0), 0)-quantum, 0)
            if np.any(gray_reverse(mean) > gray_reverse(baseline_mean)+quantum+1e-12):
                reasons.append('new_gray_reverse_step')
        track_after = []
        for i, mask in enumerate(hue_rows):
            value = _metrics(prediction[mask], target[mask])
            track_after.append(value)
            reasons += _budget_reasons(track_before[i], value, settings, 'hue24_track_'+str(i))
        guard_new = guard_render(candidate)
        guard_excess = guard_bank.excess(guard_bank.mean(guard_new))
        if np.any((guard_excess*255 > settings['severe_8bit']+1e-10) & ~(old_guard_excess*255 > settings['severe_8bit']+1e-10)):
            reasons.append('new_severe_synthetic_neighbourhood_backstep')
        guard_shift = float(np.max(np.abs(guard_new-guard_old))*255)
        if guard_shift > settings['guard_shift_8bit']+1e-10:
            reasons.append('synthetic_neighbourhood_output_shift')
        entry = dict(name=name, accepted=not reasons, rejection_reasons=reasons, shape=shape,
            fidelity=metrics, gray=gray_after, hue24_full_tracks=track_after,
            max_anchor_shift_8bit=anchor_shift*255, synthetic_max_shift_8bit=guard_shift,
            changed_coefficients=int(np.sum(candidate != original)))
        audit['candidates'].append(entry)
        if not reasons:
            choices.append((shape['extra_squared_8bit'], np.sum((candidate.astype(float)-original)**2), candidate, entry))
    if not choices:
        return unchanged('all_integer_candidates_rejected')
    _, _, chosen, report = min(choices, key=lambda v:(v[0], v[1]))
    audit.update(accepted=True, reason='accepted_integer_local_repair', selected_candidate=report['name'],
        after=report, changed_coefficients=report['changed_coefficients'],
        final_payload_sha256=hashlib.sha256(pack(chosen)).hexdigest())
    return unpack(pack(chosen)), audit
