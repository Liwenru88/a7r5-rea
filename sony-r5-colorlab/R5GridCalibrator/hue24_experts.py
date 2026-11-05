"""Twenty-four compact hue residuals over a frozen shared C1 response.

Each residual is a complete 3x3 response matrix with a quadratic Bernstein
dependence on input RGB luminance. All gates use baseline RGB only, including
neutral attenuation; the predictor remains linear in native lookup values.
NumPy inference imports no Torch. Native lookup and output clip are external.
"""
from numbers import Real
import numpy as np
import structured_response as sr

KIND = 'rgb-hue24-residual/1'
GATE = dict(kappa=12., s0=.04, c0=.04)
EXPERT_COUNT = 24
LUMA = np.array([.2126, .7152, .0722])
ANGLES = np.arange(EXPERT_COUNT)*2*np.pi/EXPERT_COUNT
DIRECTIONS = np.column_stack([np.cos(ANGLES), np.sin(ANGLES)])
PENALTY_RATES = dict(coarse_anchor=1e-5, detail=3e-5,
                     lum_curvature=1.5e-7, path_gradient=1e-7,
                     path_curvature=1.5e-5, overlap=3e-5,
                     ring_curvature=1.5e-7)


def validate_gate(gate=None):
    values = GATE.copy() if gate is None else gate
    if not isinstance(values, dict) or set(values) != set(GATE):
        raise ValueError('hue24 gate requires exactly kappa, s0 and c0')
    for value in values.values():
        if (isinstance(value, (bool, np.bool_)) or not isinstance(value, Real)
                or not np.isfinite(value) or value <= 0):
            raise ValueError('hue24 gate values must be finite positive numbers')
    return {key: float(value) for key, value in values.items()}


def _rgb(x):
    x = np.asarray(x, float)
    if (x.ndim != 2 or x.shape[1] != 3 or not np.isfinite(x).all()
            or np.any((x < 0) | (x > 1))):
        raise ValueError('hue24 input requires finite Nx3 RGB in 0..1')
    return x


def _shared(shared):
    shared = np.asarray(shared, float)
    if shared.shape != (81, 3) or not np.isfinite(shared).all():
        raise ValueError('shared C1 response requires finite 81x3 coefficients')
    return shared


def _experts(experts):
    experts = np.asarray(experts, float)
    if experts.shape != (24, 9, 3) or not np.isfinite(experts).all():
        raise ValueError('hue24 residuals require finite 24x9x3 coefficients')
    return experts


def weights(x, gate=None):
    """Nx24 smooth periodic gates; RGB-opponent directions are 15 degrees apart.

    The regularized norm is sqrt(q+s0^2), never sqrt(q) or atan2. Therefore
    finite concentration and all derivatives remain regular as chroma ->0.
    Alpha and its gradient vanish on the neutral axis, including black.
    """
    x = _rgb(x); gate = validate_gate(gate)
    z = np.column_stack([x[:, 0]-(x[:, 1]+x[:, 2])/2,
                         np.sqrt(3)/2*(x[:, 1]-x[:, 2])])
    q = np.sum(z*z, axis=1)
    logits = gate['kappa']*(z@DIRECTIONS.T)/np.sqrt(q+gate['s0']**2)[:, None]
    logits -= logits.max(axis=1, keepdims=True)
    p = np.exp(logits); p /= p.sum(axis=1, keepdims=True)
    return (q/(q+gate['c0']**2))[:, None]*p


def luminosity_basis(x):
    """Quadratic Bernstein basis of fixed input RGB luminance, Nx3."""
    x = _rgb(x); l = x@LUMA
    return np.column_stack([(1-l)**2, 2*l*(1-l), l*l])


def features(x, d, gate=None):
    """Nx216: expert-major, then lookup component, then luminance basis."""
    x = _rgb(x); d = np.asarray(d, float)
    if d.shape != x.shape or not np.isfinite(d).all():
        raise ValueError('hue24 grid delta requires finite Nx3 values')
    return np.einsum('ne,nc,nb->necb', weights(x, gate), d,
                     luminosity_basis(x)).reshape(len(x), 216)


def response_field(x, shared, experts, gate=None):
    """Nx3x3, full lookup-component-to-output response, before native lookup."""
    x = _rgb(x); shared = _shared(shared); experts = _experts(experts)
    base = np.einsum('nb,cbo->nco', sr.basis(x, sr.KIND_C1), shared.reshape(3, 27, 3))
    extra = np.einsum('nb,ecbo->neco', luminosity_basis(x), experts.reshape(24, 3, 3, 3))
    return base+np.einsum('ne,neco->nco', weights(x, gate), extra)


def predict_correction(x, d, shared, experts, gate=None):
    """Full shared-plus-residual correction, without output RGB clipping."""
    x = _rgb(x); shared = _shared(shared); experts = _experts(experts)
    return (sr.predict_correction(x, d, shared, sr.KIND_C1)
            + features(x, d, gate)@experts.reshape(216, 3))


def detail_support(x, sample_weights, gate=None):
    """Train-only mass of squared gated Bernstein basis, shape24x3."""
    x = _rgb(x); w = np.asarray(sample_weights, float)
    if (w.shape != (len(x),) or not np.isfinite(w).all()
            or np.any(w < 0) or w.sum() <= 0):
        raise ValueError('training weights must be finite nonnegative and nonzero')
    support = np.einsum('n,ne,nb->eb', w/w.sum(), weights(x, gate)**2,
                        luminosity_basis(x)**2)
    factors = np.empty_like(support)
    # One global reference retains relative support across experts as well as
    # brightness, so a rarely activated hue receives extra shrinkage.
    positive = support[support > 1e-12]
    reference = float(np.median(positive)) if len(positive) else 1.
    factors[:] = np.clip(np.sqrt(reference/np.maximum(support, reference/256)), 1, 16)
    return support, factors


def _paths(path_constraints):
    if path_constraints is None:
        return {key: np.empty((0, 216 if key in ('first','second') else 3))
                for key in ('first','second','base_first','base_second')}
    if (not isinstance(path_constraints, dict)
            or set(path_constraints) != {'first','second','base_first','base_second'}):
        raise ValueError('hue24 paths require first/second and base_first/base_second')
    paths = {}
    for order in ('first','second'):
        for key, width in ((order,216),('base_'+order,3)):
            value = np.asarray(path_constraints[key], float)
            if value.ndim != 2 or value.shape[1] != width or not np.isfinite(value).all():
                raise ValueError('invalid hue24 path matrix')
            paths[key] = value
        if len(paths[order]) != len(paths['base_'+order]):
            raise ValueError('hue24 shared and residual path rows must match')
    return paths


def regularization_terms(x, experts, support_factor=None, path_constraints=None, gate=None):
    """NumPy reference for all seven penalties, before clipping.

    Brightness curvature uses the exact Bernstein second derivative2*diff2.
    Ring curvature is unscaled cyclic second difference in expert index.
    Overlap averages the24 neighboring pairs and TRAIN colors, weighted by
    alpha^2*p_k*p_next and the full response-matrix Frobenius squared norm.
    """
    x = _rgb(x); experts = _experts(experts)
    sf = np.ones((24,3)) if support_factor is None else np.asarray(support_factor,float)
    if sf.shape != (24,3) or not np.isfinite(sf).all() or np.any(sf < 1):
        raise ValueError('hue24 support factors require finite24x3 values >=1')
    paths = _paths(path_constraints); c = experts.reshape(24,3,3,3)
    ring = np.roll(c,1,axis=0)-2*c+np.roll(c,-1,axis=0)
    terms = dict(coarse_anchor=float(np.mean(c*c)),
                 detail=float(np.mean(c*c*sf[:,None,:,None])),
                 lum_curvature=float(np.mean((2*np.diff(c,n=2,axis=2))**2)),
                 ring_curvature=float(np.mean(ring*ring)),path_gradient=0.,path_curvature=0.)
    for order,name in (('first','path_gradient'),('second','path_curvature')):
        if len(paths[order]):
            value = paths['base_'+order]+paths[order]@experts.reshape(216,3)
            terms[name] = float(np.mean(value*value))
    fields = np.einsum('nb,ecbo->neco',luminosity_basis(x),c)
    g = weights(x,gate)
    diff = fields-np.roll(fields,-1,axis=1)
    terms['overlap'] = float(np.mean(g*np.roll(g,-1,axis=1)*np.sum(diff*diff,axis=(2,3)))) if len(x) else 0.
    return terms


def solve(x,y,d,w,shared,device='mps',regularization=1.,iterations=400,
          gate=None,path_constraints=None,scale=3.,mix=1.):
    """Fit648 zero-initialized residual parameters; shared model stays fixed."""
    x = _rgb(x); y = _rgb(y); shared = _shared(shared); gate = validate_gate(gate)
    if y.shape != x.shape or not len(x):
        raise ValueError('hue24 training input and target shapes must match')
    if device not in ('cpu','mps') or type(iterations) is not int or not 1 <= iterations <= 2000:
        raise ValueError('hue24 device/iteration limit is invalid')
    for value in (regularization,scale,mix):
        if (isinstance(value,(bool,np.bool_)) or not isinstance(value,Real)
                or not np.isfinite(value) or value < 0):
            raise ValueError('hue24 loss settings must be finite nonnegative numbers')
    w = np.asarray(w,float); support,factor = detail_support(x,w,gate)
    paths = _paths(path_constraints)
    f = features(x,d,gate); b = luminosity_basis(x); g = weights(x,gate)
    base = sr.predict_correction(x,d,shared,sr.KIND_C1)
    try:
        import torch
    except ImportError as error:
        raise ValueError('hue24 training requires PyTorch') from error
    from perceptual import torch_oklab,joint_residual
    if device == 'mps' and not torch.backends.mps.is_available():
        raise ValueError('Apple MPS unavailable')
    dtype = torch.float32 if device == 'mps' else torch.float64
    t = lambda value: torch.as_tensor(value,dtype=dtype,device=device)
    tx,ty,tf,tb,tg,tbase,tw = map(t,(x,y,f,b,g,base,w/w.sum()))
    sf = t(factor)[:,None,:,None];tp = {key:t(v) for key,v in paths.items()}
    coef = t(np.zeros((24,9,3))).requires_grad_(True)

    def terms(value):
        c = value.reshape(24,3,3,3)
        ring = torch.roll(c,1,dims=0)-2*c+torch.roll(c,-1,dims=0)
        result = dict(coarse_anchor=c.square().mean(),detail=(c.square()*sf).mean(),
                      lum_curvature=(2*torch.diff(c,n=2,dim=2)).square().mean(),
                      ring_curvature=ring.square().mean(),path_gradient=t(0.),path_curvature=t(0.))
        for order,name in (('first','path_gradient'),('second','path_curvature')):
            if len(tp[order]):
                result[name] = (tp['base_'+order]+tp[order]@value.reshape(216,3)).square().mean()
        fields = torch.einsum('nb,ecbo->neco',tb,c)
        diff = fields-torch.roll(fields,-1,dims=1)
        result['overlap'] = (tg*torch.roll(tg,-1,dims=1)*diff.square().sum(dim=(2,3))).mean()
        return result

    def losses(value):
        pred = torch.clamp(tx+tbase+tf@value.reshape(216,3),0,1)
        def squash(error,threshold):
            return error*torch.sqrt(2/(torch.sqrt(1+(error/threshold)**2)+1)) if threshold else error
        er = squash(pred-ty,scale/255)
        comp = torch.cat([er,mix**.5*squash(torch_oklab(pred,torch)-torch_oklab(ty,torch),.03)],1) if mix else er
        data = comp.square().mean(1)@tw;parts = terms(value)
        penalty = regularization*sum(PENALTY_RATES[key]*v for key,v in parts.items())
        return data+penalty,data,penalty,parts,pred

    probe = np.sin(np.arange(648).reshape(24,9,3)+.3)*.001
    with torch.no_grad():
        pv = losses(t(probe));initial_values = losses(coef)
    cpu_pred = np.clip(x+predict_correction(x,d,shared,probe,gate),0,1)
    pred_error = float(np.max(abs(cpu_pred-pv[4].cpu().numpy())))
    cpu_terms = regularization_terms(x,probe,factor,paths,gate)
    term_errors = {key:abs(float(pv[3][key].cpu())-v)/max(1,abs(v)) for key,v in cpu_terms.items()}
    cpu_penalty = regularization*sum(PENALTY_RATES[key]*v for key,v in cpu_terms.items())
    penalty_error = abs(float(pv[2].cpu())-cpu_penalty)
    cpu_data = float(np.average(np.mean(joint_residual(cpu_pred,y,scale,mix)**2,axis=1),weights=w))
    data_error = abs(float(pv[1].cpu())-cpu_data)
    if (pred_error > 2e-5 or max(term_errors.values()) > 2e-5
            or penalty_error > max(2e-8,abs(cpu_penalty)*2e-4)
            or data_error > max(2e-8,abs(cpu_data)*2e-4)):
        raise ValueError(f'hue24 CPU/GPU preflight failed: RGB={pred_error}, terms={term_errors}, data={data_error}, penalty={penalty_error}')
    initial_loss = float(initial_values[0].detach().cpu())
    opt = torch.optim.LBFGS([coef],lr=.8,max_iter=iterations,max_eval=iterations*2,
                            tolerance_grad=1e-9,tolerance_change=1e-12,history_size=16,line_search_fn='strong_wolfe')
    calls = [0]
    def closure():
        opt.zero_grad();value = losses(coef)[0]*1e5
        if not torch.isfinite(value):raise ValueError('nonfinite hue24 objective')
        value.backward();calls[0] += 1;return value
    opt.step(closure)
    with torch.no_grad():
        end = losses(coef);final_loss = float(end[0].cpu())
    accepted = bool(np.isfinite(final_loss) and final_loss <= initial_loss+1e-12)
    returned = coef.detach().cpu().numpy().astype(float) if accepted else np.zeros((24,9,3))
    if not accepted:
        with torch.no_grad():coef.zero_();end = losses(coef)
    c = returned.reshape(24,3,3,3)
    note = dict(response_basis=KIND,gate=gate,shared_frozen=True,device=device,dtype=str(dtype),autograd=True,
                accepted=accepted,initial_objective=initial_loss,optimizer_final_objective=final_loss,
                final_objective=float(end[0].detach().cpu()),final_data_loss=float(end[1].detach().cpu()),
                final_regularization_loss=float(end[2].detach().cpu()),regularization_multiplier=float(regularization),
                penalty_rates=PENALTY_RATES.copy(),penalty_terms={key:float(v.detach().cpu()) for key,v in end[3].items()},
                closure_calls=calls[0],iterations=int(opt.state[coef].get('n_iter',0)),requested_iterations=iterations,max_evaluations=iterations*2,
                expert_count=24,parameters_per_expert=27,shared_parameter_count=243,trainable_parameter_count=648,
                training_samples=len(x),detail_support_mass=support.tolist(),detail_support_factor=factor.tolist(),
                expert_activation=dict(mean=g.mean(0).tolist(),weighted_mean=((w/w.sum())@g).tolist(),maximum=g.max(0).tolist(),neutral_count=int(np.sum(g.sum(1)==0))),
                roughness=dict(lum_second_derivative_rms=float(np.sqrt(np.mean((2*np.diff(c,n=2,axis=2))**2))),
                               ring_second_difference_rms=float(np.sqrt(np.mean((np.roll(c,1,axis=0)-2*c+np.roll(c,-1,axis=0))**2))),
                               residual_response_continuity='C-infinity; mixed with fixed shared C1; native lookup external'),
                preflight_max_rgb_error=pred_error,preflight_regularizer_relative_errors=term_errors,
                preflight_regularization_loss_error=penalty_error,preflight_data_loss_error=data_error,
                path_rows=dict(first=len(paths['first']),second=len(paths['second'])),
                gate_geometry='24 equally spaced RGB-opponent directions; not uniform perceptual hue angles',
                constraints_scope='648-parameter input-gated residual, cyclic hue and complete preclip path penalties; native lookup unchanged')
    return returned,note
