"""Hierarchical continuous piecewise RGB response field for grid calibration.

The native 5x9x9 grid lookup remains external. This module only models the
color-dependent response to the three lookup components. Eight coarse corner
functions describe the broad response; nineteen fine-grid hats add local
residual freedom. The default linear hats are C0 at RGB half-step planes.
Optional smoothstep hats are C1 there; neither variant guarantees monotonicity.

Inference imports NumPy only. Torch is imported lazily by ``solve``.
"""
from itertools import product
from numbers import Real
import numpy as np

KIND = 'rgb-hierarchical-hat-3x3x3'
KIND_C1 = 'rgb-hierarchical-c1-3x3x3'
NODES = np.asarray(list(product((0., .5, 1.), repeat=3)))
CORNERS = tuple(product((0, 2), repeat=3))
DETAILS = tuple(p for p in product(range(3), repeat=3) if p not in CORNERS)
CORNER_INDICES = np.asarray([a * 9 + b * 3 + c for a, b, c in CORNERS])
DETAIL_INDICES = np.asarray([a * 9 + b * 3 + c for a, b, c in DETAILS])
PENALTY_RATES = dict(coarse_anchor=1e-6, detail=3e-5,
                     gradient_delta=3e-7, gradient_absolute=1e-8,
                     curvature=3e-7, path_gradient=1e-8,
                     path_curvature=3e-8)
PENALTY_RATES_C1 = dict(PENALTY_RATES, path_gradient=1e-7,
                       path_curvature=3e-5)


def penalty_rates(kind=KIND, curvature_scale=1.0):
    """Return independent rates, relaxing only the two curvature penalties."""
    if kind not in (KIND, KIND_C1):
        raise ValueError('unsupported structured response basis')
    if (isinstance(curvature_scale, (bool, np.bool_))
            or not isinstance(curvature_scale, Real)
            or not np.isfinite(curvature_scale)
            or not 0 <= curvature_scale <= 1):
        raise ValueError('curvature_scale must be a finite number in 0..1, not bool')
    rates = (PENALTY_RATES_C1 if kind == KIND_C1 else PENALTY_RATES).copy()
    for key in ('curvature', 'path_curvature'):
        rates[key] *= float(curvature_scale)
    return rates


def _rgb(rgb):
    x = np.asarray(rgb, dtype=float)
    if x.ndim != 2 or x.shape[1] != 3 or not np.isfinite(x).all():
        raise ValueError('structured response RGB must be finite Nx3')
    if np.any((x < 0) | (x > 1)):
        raise ValueError('structured response RGB must be in 0..1')
    return x


def _coefficients(value):
    c = np.asarray(value, dtype=float)
    if c.shape != (81, 3) or not np.isfinite(c).all():
        raise ValueError('structured response needs finite 81x3 coefficients')
    return c


def basis(rgb, kind=KIND):
    """Return N x (8 coarse + 19 local residual) hierarchical functions.

    The eight coarse functions sum to one. The complete hierarchical basis
    does not: fine hats express additive residuals, not extra convex weights.
    """
    if kind not in (KIND, KIND_C1):
        raise ValueError('unsupported structured response basis')
    x = _rgb(rgb)
    coarse = np.stack([np.prod(np.where(np.asarray(c) == 2, x, 1-x), axis=1)
                       for c in CORNERS], axis=1)
    hats = np.maximum(1-np.abs(2*x[:, :, None]-np.arange(3)), 0)
    if kind == KIND_C1:
        # S(0)=0, S(1)=1, S'(0)=S'(1)=0. Transforming each
        # compact hat by cubic smoothstep makes both sides meet with zero
        # slope. Tensor residuals remain local; the coarse trilinear part
        # retains the broad linear response and is already C-infinity.
        hats = hats*hats*(3-2*hats)
    fine = np.stack([hats[:, 0, a]*hats[:, 1, b]*hats[:, 2, c]
                     for a, b, c in DETAILS], axis=1)
    return np.concatenate([coarse, fine], axis=1)


def features(rgb, delta, kind=KIND):
    x = _rgb(rgb)
    d = np.asarray(delta, dtype=float)
    if d.shape != x.shape or not np.isfinite(d).all():
        raise ValueError('structured response delta must be finite Nx3')
    return np.einsum('nc,nb->ncb', d, basis(x, kind)).reshape(len(x), 81)


def predict_correction(rgb, delta, coefficients, kind=KIND):
    """Unclipped RGB correction; a zero grid delta is identically zero."""
    return features(rgb, delta, kind) @ _coefficients(coefficients)


def field_nodes(coefficients, kind=KIND):
    """Return response at RGB nodes, shape 3x3x3 x component x output."""
    c = _coefficients(coefficients).reshape(3, 27, 3)
    return np.einsum('nb,cbo->nco', basis(NODES, kind), c).reshape(3, 3, 3, 3, 3)


def from_nodes(nodes, kind=KIND):
    """Exact nodal-to-hierarchical decomposition of a 3x3x3 response field."""
    field = np.asarray(nodes, dtype=float)
    if field.shape != (3, 3, 3, 3, 3) or not np.isfinite(field).all():
        raise ValueError('response nodes must be finite 3x3x3x3x3')
    flat = field.reshape(27, 3, 3)
    c = np.zeros((3, 27, 3))
    c[:, :8, :] = flat[CORNER_INDICES].transpose(1, 0, 2)
    coarse = np.einsum('nb,cbo->nco', basis(NODES, kind)[:, :8], c[:, :8])
    c[:, 8:, :] = (flat-coarse)[DETAIL_INDICES].transpose(1, 0, 2)
    return c.reshape(81, 3)


def from_quadratic(old_coefficients, kind=KIND):
    """Match all 27 nodes of the existing 30x3 quadratic response.

    This is an initialization, not an assertion that a piecewise linear
    response equals the original quadratic between the nodes.
    """
    old = np.asarray(old_coefficients, dtype=float)
    if old.shape != (30, 3) or not np.isfinite(old).all():
        raise ValueError('quadratic response needs finite 30x3 coefficients')
    z = NODES-.5
    q = np.column_stack([z[:, 0]**2, z[:, 1]**2, z[:, 2]**2,
                         z[:, 0]*z[:, 1], z[:, 0]*z[:, 2], z[:, 1]*z[:, 2]])
    field = (old[:3][None]
             + np.einsum('nj,cjo->nco', z, old[3:12].reshape(3, 3, 3))
             + np.einsum('nj,cjo->nco', q, old[12:].reshape(3, 6, 3)))
    return from_nodes(field.reshape(3, 3, 3, 3, 3), kind)


def detail_support(rgb, weights, kind=KIND):
    x = _rgb(rgb)
    w = np.asarray(weights, dtype=float)
    if w.shape != (len(x),) or not np.isfinite(w).all() or np.any(w < 0) or w.sum() <= 0:
        raise ValueError('training weights must be finite, nonnegative, nonzero')
    support = (basis(x, kind)[:, 8:]**2).T @ (w/w.sum())
    positive = support[support > 1e-12]
    reference = float(np.median(positive)) if len(positive) else 1.
    # Unsupported residuals receive stronger shrinkage, rather than additional
    # freedom inferred from held-out or synthetic target colors.
    factor = np.clip(np.sqrt(reference/np.maximum(support, reference/256)), 1, 16)
    return support, factor


def regularization_terms(coefficients, initial=None, support_factor=None,
                         path_constraints=None, kind=KIND):
    """Unweighted NumPy penalty terms, independent of targets and clipping."""
    coef = _coefficients(coefficients)
    anchor = np.zeros_like(coef) if initial is None else _coefficients(initial)
    c, a = coef.reshape(3, 27, 3), anchor.reshape(3, 27, 3)
    f, old = field_nodes(coef, kind), field_nodes(anchor, kind)
    factor = np.ones(19) if support_factor is None else np.asarray(support_factor, float)
    if factor.shape != (19,) or not np.isfinite(factor).all() or np.any(factor < 1):
        raise ValueError('invalid detail support factors')
    curvature = sum(np.mean((4*np.diff(f, n=2, axis=i))**2) for i in range(3))
    curvature += .25*sum(np.mean((4*np.diff(np.diff(f, axis=i), axis=j))**2)
                          for i in range(3) for j in range(i+1, 3))
    terms = dict(coarse_anchor=float(np.mean((c[:, :8]-a[:, :8])**2)),
                 detail=float(np.mean(c[:, 8:]**2*factor[None, :, None])),
                 gradient_delta=float(sum(np.mean((2*np.diff(f-old, axis=i))**2) for i in range(3))),
                 gradient_absolute=float(sum(np.mean((2*np.diff(f, axis=i))**2) for i in range(3))),
                 curvature=float(curvature), path_gradient=0., path_curvature=0.)
    if path_constraints is not None:
        for key, term in [('first', 'path_gradient'), ('second', 'path_curvature')]:
            mat = np.asarray(path_constraints.get(key, np.empty((0, 81))), float)
            if mat.ndim != 2 or mat.shape[1] != 81 or not np.isfinite(mat).all():
                raise ValueError('path constraint must be finite Mx81')
            if len(mat):
                terms[term] = float(np.mean((mat@coef)**2))
    return terms


def roughness(coefficients, kind=KIND):
    """Finite-node surrogates and basis-specific exact half-step kink size.

    Nodal second differences measure the linear-hat derivative jump exactly.
    For smoothstep hats they are curvature surrogates, not derivative jumps.
    C1 smoothstep continuity does not eliminate the native lookup's kinks.
    """
    field = field_nodes(coefficients, kind)
    jumps = np.concatenate([(2*np.diff(field, n=2, axis=i)).ravel() for i in range(3)])
    if kind == KIND_C1:
        return dict(knot_gradient_jump_rms=0., knot_gradient_jump_max=0.,
                    exact_knot_gradient_jump=0.,
                    nodal_curvature_surrogate_rms=float(np.sqrt(np.mean(jumps*jumps))),
                    nodal_curvature_surrogate_max=float(np.max(np.abs(jumps))),
                    curvature_penalty=regularization_terms(coefficients, kind=kind)['curvature'],
                    continuity='C1 piecewise smoothstep residual field; not C2; not the native lookup',
                    knot_planes=[.5])
    return dict(knot_gradient_jump_rms=float(np.sqrt(np.mean(jumps*jumps))),
                knot_gradient_jump_max=float(np.max(np.abs(jumps))),
                curvature_penalty=regularization_terms(coefficients, kind=kind)['curvature'],
                continuity='C0 piecewise trilinear; not C1',
                knot_planes=[.5])


def solve(x, y, d, weights, initial, regularization=1., device='mps',
          iterations=300, scale=3, mix=1, path_constraints=None, kind=KIND,
          curvature_scale=1.0):
    """Fit train-only response coefficients with an optional Apple GPU backend.

    Caller supplies training arrays only. Model selection and all held-out
    evaluation deliberately remain outside this function. Optional path
    matrices encode physical-step differences of *unclipped correction*
    features, built from training probes or a predefined RGB test lattice.
    ``curvature_scale`` relaxes only nodal and path second-difference rates;
    first differences, residual shrinkage and coarse anchoring are unchanged.
    """
    x = _rgb(x); y = _rgb(y)
    if y.shape != x.shape or not len(x):
        raise ValueError('training RGB and target shape mismatch')
    f = features(x, d, kind); initial = _coefficients(initial)
    actual_rates = penalty_rates(kind, curvature_scale)
    w = np.asarray(weights, float)
    support, factor = detail_support(x, w, kind)
    if device not in ('cpu', 'mps'):
        raise ValueError('structured response device must be cpu or mps')
    if type(iterations) is not int or not 1 <= iterations <= 2000:
        raise ValueError('iterations must be 1..2000')
    if not np.isfinite([regularization, scale, mix]).all() or min(regularization, scale, mix) < 0:
        raise ValueError('regularization, scale and mix must be finite and nonnegative')
    # Validate optional matrices before allocating GPU objects.
    regularization_terms(initial, initial, factor, path_constraints, kind)
    try:
        import torch
    except ImportError as error:
        raise ValueError('分段结构训练需PyTorch，请安装requirements-gpu.txt；或关闭分段响应选项') from error
    from perceptual import torch_oklab, joint_residual
    if device == 'mps' and not torch.backends.mps.is_available():
        raise ValueError('Apple MPS unavailable')
    dtype = torch.float32 if device == 'mps' else torch.float64
    tensor = lambda value: torch.as_tensor(value, dtype=dtype, device=device)
    tx, ty, tf, tw = tensor(x), tensor(y), tensor(f), tensor(w/w.sum())
    nb = tensor(basis(NODES, kind)); start = tensor(initial)
    coef = start.clone().requires_grad_(True)
    sf = tensor(factor)[None, :, None]
    paths = {key: tensor(path_constraints.get(key, np.empty((0, 81))))
             for key in ('first', 'second')} if path_constraints is not None else {}
    field = lambda value: torch.einsum('nb,cbo->nco', nb, value.reshape(3, 27, 3)).reshape(3, 3, 3, 3, 3)
    old = field(start)
    def terms(value):
        c, a = value.reshape(3, 27, 3), start.reshape(3, 27, 3)
        nodes = field(value)
        curvature = sum((4*torch.diff(nodes, n=2, dim=i)).square().mean() for i in range(3))
        curvature = curvature + .25*sum((4*torch.diff(torch.diff(nodes, dim=i), dim=j)).square().mean()
                                         for i in range(3) for j in range(i+1, 3))
        result = dict(coarse_anchor=(c[:, :8]-a[:, :8]).square().mean(),
                      detail=(c[:, 8:].square()*sf).mean(),
                      gradient_delta=sum((2*torch.diff(nodes-old, dim=i)).square().mean() for i in range(3)),
                      gradient_absolute=sum((2*torch.diff(nodes, dim=i)).square().mean() for i in range(3)),
                      curvature=curvature,
                      path_gradient=tensor(0.), path_curvature=tensor(0.))
        for key, name in [('first', 'path_gradient'), ('second', 'path_curvature')]:
            if key in paths and len(paths[key]):
                result[name] = (paths[key]@value).square().mean()
        return result
    def losses():
        pred = torch.clamp(tx+tf@coef, 0, 1)
        def squash(error, threshold):
            return error*torch.sqrt(2/(torch.sqrt(1+(error/threshold)**2)+1)) if threshold else error
        er = squash(pred-ty, scale/255)
        components = torch.cat([er, mix**.5*squash(torch_oklab(pred, torch)-torch_oklab(ty, torch), .03)], dim=1) if mix else er
        data = components.square().mean(1)@tw
        parts = terms(coef)
        penalty = regularization*sum(actual_rates[key]*value for key, value in parts.items())
        return data+penalty, data, penalty, parts
    with torch.no_grad():
        pred0 = torch.clamp(tx+tf@coef, 0, 1).cpu().numpy()
        initial_values = losses()
    cpu0 = np.clip(x+f@initial, 0, 1)
    preflight = float(np.max(np.abs(pred0-cpu0)))
    cpu_parts = regularization_terms(initial, initial, factor, path_constraints, kind)
    term_error = max(abs(float(initial_values[3][key].detach().cpu())-cpu_parts[key])
                     / max(1, abs(cpu_parts[key])) for key in cpu_parts)
    cpu_penalty = regularization*sum(actual_rates[key]*value for key, value in cpu_parts.items())
    penalty_error = abs(float(initial_values[2].detach().cpu())-cpu_penalty)
    if (preflight > 2e-5 or term_error > 2e-5
            or penalty_error > max(2e-8, abs(cpu_penalty)*2e-4)):
        raise ValueError(f'structured GPU/CPU preflight failed: RGB={preflight}, regularizer={term_error}, weighted_penalty={penalty_error}')
    cpu_data = float(np.average(np.mean(joint_residual(cpu0, y, scale, mix)**2, axis=1), weights=w))
    gpu_data = float(initial_values[1].detach().cpu())
    if abs(cpu_data-gpu_data) > max(2e-8, abs(cpu_data)*2e-4):
        raise ValueError('structured GPU/CPU perceptual loss preflight failed')
    initial_loss = float(initial_values[0].detach().cpu())
    optimizer = torch.optim.LBFGS([coef], lr=.8, max_iter=iterations,
                                  max_eval=iterations*2, history_size=16,
                                  tolerance_grad=1e-9, tolerance_change=1e-12,
                                  line_search_fn='strong_wolfe')
    calls = [0]
    def closure():
        optimizer.zero_grad()
        value = losses()[0]*1e5
        if not torch.isfinite(value):
            raise ValueError('nonfinite structured response objective')
        value.backward(); calls[0] += 1
        return value
    optimizer.step(closure)
    with torch.no_grad():
        end = losses(); final_loss = float(end[0].cpu())
    accepted = np.isfinite(final_loss) and final_loss <= initial_loss+1e-12
    returned = coef.detach().cpu().numpy().astype(float) if accepted else initial.copy()
    if not accepted:
        with torch.no_grad():
            coef.copy_(start); end = losses()
    note = dict(device=device, autograd=True, dtype=str(dtype),
                closure_calls=calls[0], iterations=int(optimizer.state[coef].get('n_iter', 0)),
                accepted=bool(accepted), initial_objective=initial_loss,
                optimizer_final_objective=final_loss,
                final_objective=float(end[0].detach().cpu()),
                final_data_loss=float(end[1].detach().cpu()),
                final_regularization_loss=float(end[2].detach().cpu()),
                regularization_multiplier=float(regularization),
                curvature_scale=float(curvature_scale),
                penalty_rates=actual_rates.copy(),
                penalty_terms={key: float(value.detach().cpu()) for key, value in end[3].items()},
                training_samples=len(x), response_basis=kind,
                coarse_basis_count=8, detail_basis_count=19, coefficient_count=243,
                detail_support_mass=support.tolist(), detail_support_factor=factor.tolist(),
                preflight_max_rgb_error=preflight,
                preflight_regularizer_relative_error=term_error,
                preflight_regularization_loss_error=penalty_error,
                preflight_data_loss_error=abs(cpu_data-gpu_data),
                initial_roughness=roughness(initial, kind), final_roughness=roughness(returned, kind),
                constraints_scope='response field and unclipped correction differences; no forced hue monotonicity or unique ISP claim')
    return returned, note
