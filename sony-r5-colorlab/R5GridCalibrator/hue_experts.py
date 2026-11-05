"""Input-gated C1 response residuals; NumPy inference and optional GPU fit.

The supplied shared 81x3 response is fixed. Each of three experts adds a full
3x3 response field in the existing C1 basis, never a single output channel.
Gates depend only on baseline RGB. This preserves zero-grid identity and the
preclip predictor's linearity in native lookup values. The response is C1;
native lookup boundaries and final clipping retain their own derivative kinks.
"""
from numbers import Real
import numpy as np
import structured_response as sr

KIND = 'rgb-hue-experts-c1/1'
GATE = dict(kappa=2., s0=.25, c0=.04)
DIRECTIONS = np.array([[1., 0.], [-.5, np.sqrt(3)/2], [-.5, -np.sqrt(3)/2]])
PAIRS = ((0, 1), (0, 2), (1, 2))
PENALTY_RATES = dict(coarse_anchor=1e-5, detail=3e-5,
                     gradient_delta=3e-7, gradient_absolute=1e-8,
                     curvature=1.5e-7, path_gradient=1e-7,
                     path_curvature=1.5e-5, overlap=3e-5)


def validate_gate(gate=None):
    """Validate a serialized fixed gate; no training of gate hyperparameters."""
    result = GATE.copy() if gate is None else gate
    if not isinstance(result, dict) or set(result) != set(GATE):
        raise ValueError('hue gate requires exactly kappa, s0 and c0')
    for key, value in result.items():
        if (isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
                or not np.isfinite(value) or value <= 0):
            raise ValueError('hue gate values must be finite positive numbers')
    return {key: float(value) for key, value in result.items()}


def _rgb(x):
    x = np.asarray(x, float)
    if (x.ndim != 2 or x.shape[1] != 3 or not np.isfinite(x).all()
            or np.any((x < 0) | (x > 1))):
        raise ValueError('hue expert input must be finite Nx3 RGB in 0..1')
    return x


def _shared(value):
    value = np.asarray(value, float)
    if value.shape != (81, 3) or not np.isfinite(value).all():
        raise ValueError('shared C1 response requires finite 81x3 coefficients')
    return value


def _experts(value):
    value = np.asarray(value, float)
    if value.shape != (3, 81, 3) or not np.isfinite(value).all():
        raise ValueError('hue experts require finite 3x81x3 coefficients')
    return value


def weights(x, gate=None):
    """Return alpha*softmax logits, Nx3, with an exact neutral fallback.

    The unnormalized opponent vector needs neither atan2 nor division by
    chroma. All denominators are fixed positive constants or q+c0^2; gates
    and their first derivatives vanish on the neutral axis, including black.
    """
    x = _rgb(x); gate = validate_gate(gate)
    z = np.column_stack([x[:, 0]-(x[:, 1]+x[:, 2])/2,
                         np.sqrt(3)/2*(x[:, 1]-x[:, 2])])
    q = np.sum(z*z, axis=1)
    logits = gate['kappa']*(z@DIRECTIONS.T)/gate['s0']
    logits -= logits.max(axis=1, keepdims=True)
    p = np.exp(logits); p /= p.sum(axis=1, keepdims=True)
    return (q/(q+gate['c0']**2))[:, None]*p


def features(x, d, gate=None):
    """N x 243; expert-major order, each expert has 81 response features."""
    x = _rgb(x)
    base = sr.features(x, d, sr.KIND_C1)
    return (weights(x, gate)[:, :, None]*base[:, None, :]).reshape(len(x), 243)


def response_field(x, shared, experts, gate=None):
    """N x lookup-component x RGB-output response before native lookup."""
    x = _rgb(x); shared = _shared(shared); experts = _experts(experts)
    b = sr.basis(x, sr.KIND_C1)
    base = np.einsum('nb,cbo->nco', b, shared.reshape(3, 27, 3))
    extra = np.einsum('nb,ecbo->neco', b, experts.reshape(3, 3, 27, 3))
    return base + np.einsum('ne,neco->nco', weights(x, gate), extra)


def predict_correction(x, d, shared, experts, gate=None):
    """Full shared-plus-expert correction, with no final RGB clipping."""
    x = _rgb(x); shared = _shared(shared); experts = _experts(experts)
    return (sr.predict_correction(x, d, shared, sr.KIND_C1)
            + features(x, d, gate)@experts.reshape(243, 3))


def detail_support(x, sample_weights, gate=None):
    """Training-only gated residual support and capped inverse support factor."""
    x = _rgb(x); w = np.asarray(sample_weights, float)
    if (w.shape != (len(x),) or not np.isfinite(w).all()
            or np.any(w < 0) or w.sum() <= 0):
        raise ValueError('training weights must be finite nonnegative and nonzero')
    b = sr.basis(x, sr.KIND_C1)[:, 8:]
    support = np.einsum('n,ne,nb->eb', w/w.sum(), weights(x, gate)**2, b*b)
    factors = np.empty_like(support)
    for expert, values in enumerate(support):
        positive = values[values > 1e-12]
        reference = float(np.median(positive)) if len(positive) else 1.
        factors[expert] = np.clip(np.sqrt(reference/np.maximum(values, reference/256)), 1, 16)
    return support, factors


def _paths(path_constraints):
    if path_constraints is None:
        return {key: np.empty((0, 243 if key in ('first', 'second') else 3))
                for key in ('first', 'second', 'base_first', 'base_second')}
    if (not isinstance(path_constraints, dict)
            or set(path_constraints) != {'first', 'second', 'base_first', 'base_second'}):
        raise ValueError('expert paths require first/second and base_first/base_second')
    result = {}
    for order in ('first', 'second'):
        for key, width in ((order, 243), ('base_'+order, 3)):
            v = np.asarray(path_constraints[key], float)
            if v.ndim != 2 or v.shape[1] != width or not np.isfinite(v).all():
                raise ValueError('invalid hue expert path matrix')
            result[key] = v
        if len(result[order]) != len(result['base_'+order]):
            raise ValueError('shared and expert path row counts must match')
    return result


def regularization_terms(x, experts, support_factor=None, path_constraints=None, gate=None):
    """Independent NumPy reference, including actual mixed preclip path cost.

    Overlap is the unweighted mean over TRAIN colors and the three expert
    pairs of alpha^2*p_i*p_j times the squared full-response Frobenius norm.
    """
    x = _rgb(x); experts = _experts(experts)
    sf = np.ones((3, 19)) if support_factor is None else np.asarray(support_factor, float)
    if sf.shape != (3, 19) or not np.isfinite(sf).all() or np.any(sf < 1):
        raise ValueError('expert support factors require finite 3x19 values >=1')
    paths = _paths(path_constraints)
    terms = {key: 0. for key in PENALTY_RATES}
    for e in range(3):
        local = sr.regularization_terms(experts[e], support_factor=sf[e], kind=sr.KIND_C1)
        for key in ('coarse_anchor', 'detail', 'gradient_delta', 'gradient_absolute', 'curvature'):
            terms[key] += local[key]/3
    for order, name in (('first', 'path_gradient'), ('second', 'path_curvature')):
        if len(paths[order]):
            value = paths['base_'+order]+paths[order]@experts.reshape(243, 3)
            terms[name] = float(np.mean(value*value))
    b = sr.basis(x, sr.KIND_C1)
    f = np.einsum('nb,ecbo->neco', b, experts.reshape(3, 3, 27, 3))
    g = weights(x, gate)
    overlaps = [g[:, i]*g[:, j]*np.sum((f[:, i]-f[:, j])**2, axis=(1, 2)) for i, j in PAIRS]
    terms['overlap'] = float(np.mean(overlaps)) if len(x) else 0.
    return terms


def solve(x, y, d, w, shared, device='mps', regularization=1., iterations=400,
          gate=None, path_constraints=None, scale=3., mix=1.):
    """Fit only 729 zero-initialized residual coefficients; shared stays fixed.

    Data use clipped floating RGB/OKLab soft-L1. Regularizers use unclipped
    response/path values. Validation and model selection are caller-owned.
    """
    x = _rgb(x); y = _rgb(y); shared = _shared(shared); gate = validate_gate(gate)
    if y.shape != x.shape or not len(x):
        raise ValueError('hue expert training inputs and targets must match')
    if device not in ('cpu', 'mps') or type(iterations) is not int or not 1 <= iterations <= 2000:
        raise ValueError('hue expert device/iteration limit is invalid')
    for value in (regularization, scale, mix):
        if (isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
                or not np.isfinite(value) or value < 0):
            raise ValueError('loss settings must be finite nonnegative numbers')
    w = np.asarray(w, float)
    support, factor = detail_support(x, w, gate)
    paths = _paths(path_constraints)
    f = features(x, d, gate)
    base = sr.predict_correction(x, d, shared, sr.KIND_C1)
    b = sr.basis(x, sr.KIND_C1); g = weights(x, gate)
    try:
        import torch
    except ImportError as error:
        raise ValueError('hue expert training requires PyTorch') from error
    from perceptual import torch_oklab, joint_residual
    if device == 'mps' and not torch.backends.mps.is_available():
        raise ValueError('Apple MPS unavailable')
    dtype = torch.float32 if device == 'mps' else torch.float64
    t = lambda value: torch.as_tensor(value, dtype=dtype, device=device)
    tx, ty, tf, tb, tg, tbase, tw = map(t, (x, y, f, b, g, base, w/w.sum()))
    nodes_basis = t(sr.basis(sr.NODES, sr.KIND_C1))
    sf = t(factor)[:, None, :, None]
    tp = {key: t(value) for key, value in paths.items()}
    coef = t(np.zeros((3, 81, 3))).requires_grad_(True)

    def terms(value):
        c = value.reshape(3, 3, 27, 3)
        nodes = torch.einsum('nb,ecbo->enco', nodes_basis, c).reshape(3, 3, 3, 3, 3, 3)
        gradient = sum((2*torch.diff(nodes, dim=i)).square().mean() for i in (1, 2, 3))
        curvature = sum((4*torch.diff(nodes, n=2, dim=i)).square().mean() for i in (1, 2, 3))
        curvature += .25*sum((4*torch.diff(torch.diff(nodes, dim=i), dim=j)).square().mean()
                              for i in (1, 2, 3) for j in range(i+1, 4))
        result = dict(coarse_anchor=c[:, :, :8].square().mean(),
                      detail=(c[:, :, 8:].square()*sf).mean(),
                      gradient_delta=gradient, gradient_absolute=gradient,
                      curvature=curvature, path_gradient=t(0.), path_curvature=t(0.))
        flat = value.reshape(243, 3)
        for order, name in (('first', 'path_gradient'), ('second', 'path_curvature')):
            if len(tp[order]):
                result[name] = (tp['base_'+order]+tp[order]@flat).square().mean()
        fields = torch.einsum('nb,ecbo->neco', tb, c)
        result['overlap'] = torch.stack([tg[:, i]*tg[:, j]*(fields[:, i]-fields[:, j]).square().sum(dim=(1, 2))
                                         for i, j in PAIRS]).mean()
        return result

    def losses(value):
        pred = torch.clamp(tx+tbase+tf@value.reshape(243, 3), 0, 1)
        def squash(error, threshold):
            return error*torch.sqrt(2/(torch.sqrt(1+(error/threshold)**2)+1)) if threshold else error
        er = squash(pred-ty, scale/255)
        components = torch.cat([er, mix**.5*squash(torch_oklab(pred, torch)-torch_oklab(ty, torch), .03)], 1) if mix else er
        data = components.square().mean(1)@tw
        parts = terms(value)
        penalty = regularization*sum(PENALTY_RATES[key]*value for key, value in parts.items())
        return data+penalty, data, penalty, parts, pred

    # A nonzero deterministic probe exercises every regularizer, including
    # expert overlap: a zero initialization alone cannot validate those terms.
    probe = np.sin(np.arange(729).reshape(3, 81, 3)+.3)*.001
    with torch.no_grad():
        pv = losses(t(probe)); initial_values = losses(coef)
    cpu_pred = np.clip(x+predict_correction(x, d, shared, probe, gate), 0, 1)
    pred_error = float(np.max(abs(cpu_pred-pv[4].cpu().numpy())))
    cpu_terms = regularization_terms(x, probe, factor, paths, gate)
    term_errors = {key: abs(float(pv[3][key].cpu())-value)/max(1, abs(value)) for key, value in cpu_terms.items()}
    cpu_penalty = regularization*sum(PENALTY_RATES[key]*value for key, value in cpu_terms.items())
    penalty_error = abs(float(pv[2].cpu())-cpu_penalty)
    cpu_data = float(np.average(np.mean(joint_residual(cpu_pred, y, scale, mix)**2, axis=1), weights=w))
    data_error = abs(float(pv[1].cpu())-cpu_data)
    if (pred_error > 2e-5 or max(term_errors.values()) > 2e-5
            or penalty_error > max(2e-8, abs(cpu_penalty)*2e-4)
            or data_error > max(2e-8, abs(cpu_data)*2e-4)):
        raise ValueError(f'hue expert CPU/GPU preflight failed: RGB={pred_error}, terms={term_errors}, loss={data_error}, penalty={penalty_error}')
    initial_loss = float(initial_values[0].detach().cpu())
    opt = torch.optim.LBFGS([coef], lr=.8, max_iter=iterations, max_eval=iterations*2,
                            tolerance_grad=1e-9, tolerance_change=1e-12, history_size=16,
                            line_search_fn='strong_wolfe')
    calls = [0]
    def closure():
        opt.zero_grad(); value = losses(coef)[0]*1e5
        if not torch.isfinite(value):
            raise ValueError('nonfinite hue expert objective')
        value.backward(); calls[0] += 1
        return value
    opt.step(closure)
    with torch.no_grad():
        end = losses(coef); final_loss = float(end[0].cpu())
    accepted = bool(np.isfinite(final_loss) and final_loss <= initial_loss+1e-12)
    returned = coef.detach().cpu().numpy().astype(float) if accepted else np.zeros((3, 81, 3))
    if not accepted:
        with torch.no_grad():
            coef.zero_(); end = losses(coef)
    note = dict(response_basis=KIND, gate=gate, shared_frozen=True,
                device=device, dtype=str(dtype), autograd=True, accepted=accepted,
                initial_objective=initial_loss, optimizer_final_objective=final_loss,
                final_objective=float(end[0].detach().cpu()),
                final_data_loss=float(end[1].detach().cpu()), final_regularization_loss=float(end[2].detach().cpu()),
                regularization_multiplier=float(regularization), penalty_rates=PENALTY_RATES.copy(),
                penalty_terms={key: float(value.detach().cpu()) for key, value in end[3].items()},
                closure_calls=calls[0], iterations=int(opt.state[coef].get('n_iter', 0)),
                requested_iterations=iterations, max_evaluations=iterations*2,
                expert_count=3, shared_parameter_count=243, trainable_parameter_count=729,
                training_samples=len(x), detail_support_mass=support.tolist(), detail_support_factor=factor.tolist(),
                expert_activation=dict(mean=g.mean(0).tolist(), weighted_mean=((w/w.sum())@g).tolist(),
                                       maximum=g.max(0).tolist(), neutral_count=int(np.sum(g.sum(1)==0))),
                roughness=[sr.roughness(c, sr.KIND_C1) for c in returned],
                preflight_max_rgb_error=pred_error, preflight_regularizer_relative_errors=term_errors,
                preflight_regularization_loss_error=penalty_error, preflight_data_loss_error=data_error,
                path_rows=dict(first=len(paths['first']), second=len(paths['second'])),
                constraints_scope='C1 input-gated response residuals and full preclip correction paths; native lookup unchanged; not global monotone hue')
    return returned, note
