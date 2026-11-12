"""PC display-RGB tone/tint separation; no camera or DCP algorithm claim.

The gray locus is the measured synthetic sensor-gray trajectory, not a claim
that equal sensor channels are a colorimetrically neutral photographed object.
"""
import numpy as np
from pathlib import Path
import sys
from scipy.optimize import lsq_linear
from scipy import sparse
from residual_grid import stencil, coordinates, coefficients

LUMA = np.array([.2126, .7152, .0722])


def fit_training(base, target, gray_mask, weights, strategy="direct", quantization_sweeps=0, perceptual_weight=0, curve_mode="tone-tint", response=None, parameter_smoothing=0, target_neighborhood=0, training_penalties=True):
    """Fit one compensation block from training arrays only.

    ``training_penalties=False`` fits data alone; native range/monotonic
    projections and tiny numerical solver stabilization remain.
    """
    from parameter_smoothing import multiplier
    if type(training_penalties) is not bool:
        raise ValueError('training_penalties must be a boolean')
    if not training_penalties:
        parameter_smoothing=0
        target_neighborhood=0
    factor=multiplier(parameter_smoothing) if training_penalties else 0.
    if target_neighborhood:factor=0.
    curve = fit_curves(base[gray_mask], target[gray_mask],strength=.002*factor,target_neighborhood=target_neighborhood)
    if curve_mode == 'qaq-grid':
        from residual_grid import response_matrix
        response=response_matrix(np.eye(3) if response is None else response)
        curve=dict(mode='qaq-grid',response=(response if isinstance(response,dict) else response.tolist()),reference=('Pinned empirical grid response; see saved response identity and scope' if isinstance(response,dict) else 'legacy provisional predictor'))
    elif curve_mode != 'tone-tint':
        raise ValueError('Unknown PC curve mode')
    validate(curve)
    _, tinted, gate = curves(base, curve)
    if curve_mode=='qaq-grid':
        if strategy!='direct':raise ValueError('QAQ model uses direct 5x9x9 fitting')
        grid,audit=fit_response_grid(base,target,weights,response,strength=.01*factor)
    elif strategy == 'none':
        grid=np.zeros((405,3),dtype=np.int8)
        audit=dict(training_only=True,objective='RGB curves only; no color grid')
    elif strategy == "dense-compressed":
        grid, audit = fit_compressed(base, target, curve, weights, smooth_factor=factor,target_neighborhood=target_neighborhood,training_penalties=training_penalties)
    elif strategy == "direct":
        grid, audit = fit_grid(tinted, target, gate, weights,strength=.01*factor)
    else:
        raise ValueError("Unknown PC grid strategy")
    audit["parameter_smoothing"] = parameter_smoothing
    audit["strategy"] = strategy
    if quantization_sweeps and strategy != 'none':
        from optimizer_policy import refine_grid
        grid, refinement = refine_grid(grid, tinted, target, gate, weights, quantization_sweeps, perceptual_weight,response=curve.get('response'),parameter_smoothing=0 if target_neighborhood else parameter_smoothing)
        audit["quantization_refinement"] = refinement
    audit["quantization_sweeps"] = quantization_sweeps
    audit["perceptual_weight"] = perceptual_weight
    audit['curve_mode']=curve_mode
    if not training_penalties:
        audit['training_penalties']=False
        audit['legacy_grid_neighbor_regularization']=0.
        audit['curve_shape_regularization']=0.
        audit['target_neighborhood_strength']=0.
        audit['numerical_stabilization']='1e-10 ridge only; no shape, antiringing or neighbor penalty'
    if target_neighborhood:
        audit['curve_target_neighborhood']=curve.get('target_neighborhood',dict(enabled=False,reason='curve mode has no tone/tint curves'))
        audit['legacy_grid_neighbor_regularization']=0.
    return curve, grid, audit


def isotonic(values):
    blocks = []
    for value in values:
        blocks.append([float(value), 1])
        while len(blocks) > 1 and blocks[-2][0] > blocks[-1][0]:
            right = blocks.pop(); left = blocks.pop()
            count = left[1]+right[1]
            blocks.append([(left[0]*left[1]+right[0]*right[1])/count, count])
    return np.concatenate([np.repeat(v, n) for v, n in blocks])


def curve_neighborhood_design(x, weights=None, target_neighborhood=0):
    """Legacy derivative rows; the enabled backstep policy never calls this.

    Equal x values cannot define an interval: their residuals are averaged
    using the same weights as the data fit before differentiation. The data
    loss still retains every observation. Targets are never interpolated.
    """
    from parameter_smoothing import strength as checked_strength
    amount=checked_strength(target_neighborhood)
    x=np.asarray(x,float)
    mass=np.ones(len(x)) if weights is None else np.asarray(weights,float)
    if (x.ndim!=1 or not len(x) or mass.shape!=x.shape or not np.isfinite(x).all()
            or not np.isfinite(mass).all() or np.any(mass<0) or mass.sum()<=0
            or np.any((x<0)|(x>1))):
        raise ValueError('Curve neighborhoods need finite gray-luma samples and nonnegative weights')
    # Zero-weight observations do not create target derivative information.
    active=np.flatnonzero(mass>0)
    unique,inverse=np.unique(x[active],return_inverse=True)
    total=np.bincount(inverse,weights=mass[active],minlength=len(unique))
    average=sparse.coo_matrix((mass[active]/total[inverse],(inverse,active)),shape=(len(unique),len(x))).tocsr()
    step=np.diff(unique)
    edge=np.flatnonzero((step>0)&(step<=.125))
    trip=np.flatnonzero((step[:-1]>0)&(step[1:]>0)&(np.maximum(step[:-1],step[1:])<=.125)
        &(np.maximum(step[:-1],step[1:])<=4*np.minimum(step[:-1],step[1:])))
    first_rate,second_rate=1e-5,1e-8
    if len(edge):
        h=step[edge];scale=np.sqrt(amount/100*first_rate*h/h.sum())/h
        first=sparse.coo_matrix((np.column_stack([-scale,scale]).ravel(),
            (np.repeat(np.arange(len(edge)),2),np.column_stack([edge,edge+1]).ravel())),shape=(len(edge),len(unique))).tocsr()
    else:first=sparse.csr_matrix((0,len(unique)))
    if len(trip):
        left,right=step[trip],step[trip+1];width=(left+right)/2
        scale=np.sqrt(amount/100*second_rate*width/width.sum())*2/(left+right)
        second=sparse.coo_matrix((np.column_stack([scale/left,-scale*(1/left+1/right),scale/right]).ravel(),
            (np.repeat(np.arange(len(trip)),3),np.column_stack([trip,trip+1,trip+2]).ravel())),shape=(len(trip),len(unique))).tocsr()
    else:second=sparse.csr_matrix((0,len(unique)))
    enabled=bool(amount and (len(edge) or len(trip)))
    report=dict(policy='train-gray-curve-target-differences/1',enabled=enabled,strength=amount,
        training_only=True,samples=len(x),positive_weight_samples=len(active),unique_lumas=len(unique),
        duplicate_lumas=len(active)-len(unique),first_rows=len(edge),second_rows=len(trip),
        duplicate_policy='weighted average residual at identical x; no derivative across duplicates',
        first_rate=first_rate,second_rate=second_rate,max_gap=.125,max_step_ratio=4,
        target_interpolation=False,derivative_units='encoded gray-luma arc length',
        preserves='target derivatives; tone isotonic, zero-luma tint and weak node d2 remain',
        disabled_reason=None if enabled else 'strength is zero' if not amount else 'no supported gray-luma neighborhoods')
    return sparse.vstack([first,second],format='csr')@average,report


def curve_fit(x, values, strength=.002, nodes=129, weights=None, target_neighborhood=0):
    """Fixed smoothness, training data only; linear interpolation at runtime."""
    axis = np.linspace(0, 1, nodes)
    pos = np.clip(x, 0, 1)*(nodes-1)
    low = np.minimum(pos.astype(int), nodes-2); frac = pos-low
    design = np.zeros((len(x), nodes))
    design[np.arange(len(x)), low] = 1-frac
    design[np.arange(len(x)), low+1] = frac
    d2 = np.diff(np.eye(nodes), n=2, axis=0)
    mass=np.full(len(x),1/len(x)) if weights is None else np.asarray(weights)/np.sum(weights)
    h = design.T@(design*mass[:,None])+(0 if target_neighborhood else strength)*(d2.T@d2)+np.eye(nodes)*1e-10
    rhs=design.T@(values*mass if np.ndim(values)==1 else values*mass[:,None])
    return axis, np.linalg.solve(h, rhs)


def curve_backstep_loss_gradient(predicted,target,windows,amount):
    """Only isolated + - + / - + - RGB increments, above target allowance.

    Target clipping permits four prediction-native 14-bit output quanta in
    that channel, versus one in the interior. Target ICC floats stay intact.
    Predictions remain preclip, so clipping cannot be used to escape this cost.
    """
    gradient=np.zeros_like(predicted,dtype=float)
    if not len(windows) or not amount:return 0.,gradient,dict(active=0,clip_channels=0)
    p,t=np.asarray(predicted)[windows],np.asarray(target)[windows]
    dp,dt=np.diff(p,axis=1),np.diff(t,axis=1)
    clip=np.any((t<=1/16383)|(t>=1-1/16383),axis=1)
    allowance=np.where(clip,4/16383,1/16383)
    loss=0.;active=0
    scale=8*amount/100/(len(windows)*2*predicted.shape[1])
    for signs in (np.array([1.,-1.,1.]),np.array([-1.,1.,-1.])):
        signed=dp*signs[None,:,None]
        at=np.argmin(signed,axis=1)
        hf=np.maximum(np.min(signed,axis=1),0)
        target_hf=np.maximum(np.min(dt*signs[None,:,None],axis=1),0)
        excess=np.maximum(hf-target_hf-allowance,0)
        loss+=scale*np.sum(excess**2);active+=int(np.count_nonzero(excess))
        derivative=2*scale*excess
        for channel in range(predicted.shape[1]):
            interval=at[:,channel];signed_derivative=derivative[:,channel]*signs[interval]
            np.add.at(gradient[:,channel],windows[np.arange(len(windows)),interval],-signed_derivative)
            np.add.at(gradient[:,channel],windows[np.arange(len(windows)),interval+1],signed_derivative)
    return float(loss),gradient,dict(active=active,clip_channels=int(clip.sum()))


def refine_curve_backsteps(base,target,axis,tone,tint,amount):
    """Short analytic-gradient refinement; final monotone/zero-luma acceptance."""
    from scipy.optimize import minimize
    from parameter_smoothing import strength as checked_strength
    amount=checked_strength(amount)
    x=np.asarray(base)@LUMA
    unique,inverse,counts=np.unique(x,return_inverse=True,return_counts=True)
    b=np.zeros((len(unique),3));t=np.zeros_like(b)
    np.add.at(b,inverse,base);np.add.at(t,inverse,target)
    b/=counts[:,None];t/=counts[:,None]
    sample_mass=counts/counts.sum()
    step=np.diff(unique)
    window=np.arange(max(0,len(unique)-3))[:,None]+np.arange(4)[None,:]
    if len(window):
        h=step[window[:,:3]]
        window=window[(h.min(axis=1)>0)&(h.max(axis=1)<=.125)&(h.max(axis=1)<=4*h.min(axis=1))]
    nodes=len(axis);pos=np.clip(unique,0,1)*(nodes-1)
    low=np.minimum(pos.astype(int),nodes-2);fraction=pos-low
    design=np.zeros((len(unique),nodes));design[np.arange(len(unique)),low]=1-fraction;design[np.arange(len(unique)),low+1]=fraction
    def project(values):
        raw=values[:nodes];monotone=isotonic(raw);out=np.clip(monotone,0,1)
        tint_value=values[nodes:].reshape(nodes,3).copy();tint_value-=(tint_value@LUMA)[:,None]
        return out,tint_value,monotone
    def objective(values,gradient=True):
        tone_value,tint_value,monotone=project(values)
        p=b+(design@tone_value-unique)[:,None]+design@tint_value
        error=p-t
        loss=float(np.sum(error**2*sample_mass[:,None])/3);g=2*error*sample_mass[:,None]/3
        hf,hg,audit=curve_backstep_loss_gradient(p,t,window,amount)
        g+=hg
        if not gradient:return loss+hf,audit
        gt=design.T@g.sum(axis=1);gc=design.T@g
        # Exact Jacobian within a PAV block; equal adjacent blocks use the
        # deterministic merged subgradient. No derivative crosses clipping.
        starts=np.r_[0,np.flatnonzero(np.diff(monotone)!=0)+1];ends=np.r_[starts[1:],nodes]
        for start,end in zip(starts,ends):gt[start:end]=np.mean(gt[start:end])
        gt[(monotone<0)|(monotone>1)]=0
        gc-=gc.sum(axis=1)[:,None]*LUMA[None,:]
        return loss+hf,np.r_[gt,gc.ravel()]
    initial=np.r_[tone,np.asarray(tint).ravel()]
    before,_=objective(initial,False)
    if len(window):
        fit=minimize(objective,initial,jac=True,method='L-BFGS-B',options=dict(maxiter=16,maxfun=24,maxls=8,ftol=1e-12,gtol=1e-9))
        after,_=objective(fit.x,False)
        selected=fit.x if np.isfinite(after) and after<before else initial
        evaluations=int(fit.nfev)
    else:selected=initial;evaluations=0
    tone,tint,_=project(selected)
    after,audit=objective(selected,False)
    return tone,tint,dict(policy='gray-final-output-isolated-backsteps-v2',enabled=bool(amount and len(window)),
        strength=amount,training_only=True,samples=len(x),unique_lumas=len(unique),duplicate_lumas=len(x)-len(unique),
        windows=len(window),pattern='three RGB increments: + - + or - + - only',
        target_allowance='same-direction target backstep plus one prediction-native 14-bit output quantum',
        clip_allowance='target boundary in same channel only: four prediction-native output quanta total',
        target_precision='16-bit ICC-converted floating target; no assumed native-code quantization',
        output='preclip base + tone shift + zero-luma tint',legacy_d1_d2=False,legacy_curve_d2=False,
        max_gap=.125,max_step_ratio=4,evaluations=evaluations,before=before,after=after,
        accepted=bool(after<before),final_projection_acceptance=True,**audit)


def fit_curves(base_gray, target_gray, strength=.002, target_neighborhood=0):
    b, t = np.asarray(base_gray), np.asarray(target_gray)
    y = b@LUMA; ty = t@LUMA
    axis, tone = curve_fit(y, ty,strength=strength,target_neighborhood=target_neighborhood)
    tone = np.clip(isotonic(tone), 0, 1)
    # RGB chroma residual has zero encoded luma; tone cannot hide tint error.
    _, tint = curve_fit(y, (t-ty[:, None])-(b-y[:, None]),strength=strength,target_neighborhood=target_neighborhood)
    tint -= (tint@LUMA)[:, None]
    neighborhood_report=None
    if target_neighborhood:
        tone,tint,neighborhood_report=refine_curve_backsteps(b,t,axis,tone,tint,target_neighborhood)
    # Exact piecewise source locus, averaging only indistinguishable lumas.
    unique, inverse, counts = np.unique(y, return_inverse=True, return_counts=True)
    chroma = np.zeros((len(unique), 3)); np.add.at(chroma, inverse, b-y[:, None])
    chroma /= counts[:, None]
    result=dict(axis=axis.tolist(), tone=tone.tolist(), tint=tint.tolist(),
                gray_axis=unique.tolist(), gray_chroma=chroma.tolist(),
                gray_protection_radius=2/255, gray_transition=8/255,
                smoothness=strength, gray_samples=len(y),
                gray_definition='measured synthetic sensor-gray locus; not calibrated scene-neutral gray')
    if target_neighborhood:
        result['target_neighborhood']=neighborhood_report
    return result


def curves(base, value):
    b = np.asarray(base, dtype=float)
    if value.get('mode')=='qaq-grid':return b.copy(),b.copy(),np.ones(len(b))
    y = b@LUMA; axis = value['axis']
    tone_y = np.interp(y, axis, value['tone'])
    tone = b+(tone_y-y)[:, None]
    tint = np.stack([np.interp(y, axis, np.asarray(value['tint'])[:, c]) for c in range(3)], axis=1)
    staged = tone+tint
    if value.get('mode') == 'rgb-independent':
        staged=np.stack([np.interp(b[:,c],axis,np.asarray(value['rgb'])[:,c]) for c in range(3)],axis=1)
        tone=staged.copy()
    locus = np.stack([np.interp(y, value['gray_axis'], np.asarray(value['gray_chroma'])[:, c]) for c in range(3)], axis=1)
    distance = np.sqrt(np.mean((b-y[:, None]-locus)**2, axis=1))
    # Smoothstep gives an exact protected tube and continuous transition.
    u = np.clip((distance-value['gray_protection_radius'])/value['gray_transition'], 0, 1)
    gate = u*u*(3-2*u)
    return tone, staged, gate


def fit_grid(base, target, gate, weights, strength=.01):
    """Fit the exact gated runtime model with bounded, smooth RGB residuals."""
    from gpu_runtime import available
    if available():
        from gpu_grid import fit
        return fit(base,target,weights,strength,gate=gate)
    ids, w = stencil(coordinates(base))
    rows = np.repeat(np.arange(len(base)), 8)
    a = sparse.coo_matrix(((w*gate[:, None]).ravel(), (rows, ids.ravel())), shape=(len(base), 405)).tocsr()
    scale = np.sqrt(weights/weights.sum())
    a = a.multiply(scale[:, None])
    edges = []
    for y in range(5):
        for u in range(9):
            for v in range(9):
                at = y*81+u*9+v
                for yes, step in [(y<4, 81), (u<8, 9), (v<8, 1)]:
                    if yes: edges.append((at, at+step))
    edges = np.asarray(edges)
    smooth = sparse.coo_matrix((np.tile([1., -1.], len(edges)),
                               (np.repeat(np.arange(len(edges)), 2), edges.ravel())), shape=(len(edges), 405)).tocsr()
    design = sparse.vstack([a, smooth*np.sqrt(strength/405), sparse.eye(405)*1e-5]).tocsr()
    residual = (target-base)*scale[:, None]
    fitted, audit = [], []
    for c in range(3):
        rhs = np.r_[residual[:, c], np.zeros(len(edges)+405)]
        result = lsq_linear(design, rhs, bounds=(-64/256, 63/256), tol=1e-8, lsmr_tol=1e-9, max_iter=100)
        if not result.success: raise ValueError('PC residual solver failed: '+result.message)
        fitted.append(result.x); audit.append(dict(iterations=result.nit, cost=float(result.cost), optimality=float(result.optimality)))
    grid = np.clip(np.rint(np.stack(fitted, axis=1)*256), -64, 63).astype(np.int8)
    return grid, dict(channels=audit, regularization=strength, training_only=True,
                     objective='weighted RGB MSE plus neighbor smoothness; gray-locus gated',
                     limit_fraction=float(np.mean((grid==-64)|(grid==63))))


def fit_response_grid(base,target,weights,response,strength=.01,loss_progress=None):
    """Exact QAQ row-vector response model, bounded joint three-plane fit."""
    if isinstance(response,dict):
        from measured_response import get
        model=get(response)
        from paired_response import PairedModel
        if loss_progress is not None and isinstance(model,PairedModel):
            return model.fit(base,target,weights,strength,loss_progress=loss_progress)
        return model.fit(base,target,weights,strength)
    from gpu_runtime import available
    if available():
        from gpu_grid import fit
        return fit(base,target,weights,strength,response=response,loss_progress=loss_progress)
    a=grid_design(base,(5,9,9))
    scale=np.sqrt(weights/np.sum(weights))
    # Node-major coefficients: vec(A C R) = (A kron R.T) vec(C).
    design=sparse.kron(a.multiply(scale[:,None]),sparse.csr_matrix(response.T),format='csr')
    smooth=neighbor_design((5,9,9))
    regularizer=sparse.kron(smooth,sparse.eye(3),format='csr')*np.sqrt(strength/405)
    system=sparse.vstack([design,regularizer,sparse.eye(1215)*1e-5]).tocsr()
    rhs=np.r_[((target-base)*scale[:,None]).ravel(),np.zeros(regularizer.shape[0]+1215)]
    fit=lsq_linear(system,rhs,bounds=(-64/256,63/256),tol=1e-8,lsmr_tol=1e-9,max_iter=100)
    if not fit.success:raise ValueError('QAQ response grid solver failed: '+fit.message)
    grid=np.clip(np.rint(fit.x.reshape(405,3)*256),-64,63).astype(np.int8)
    return grid,dict(regularization=strength,training_only=True,objective='weighted RGB residual A*C*response; no curves or gray gate',
                     response=response.tolist(),iterations=fit.nit,cost=float(fit.cost),limit_fraction=float(np.mean((grid==-64)|(grid==63))))


def render(base, value, grid, stages=False):
    a = np.asarray(base, dtype=float)
    from gpu_runtime import available
    if available() and not stages and len(a)>=512:
        from gpu_color import pc_numpy
        return pc_numpy(a,value,grid)
    tone, tinted, gate = curves(a, value)
    if value.get('mode')=='qaq-grid' and isinstance(value['response'],dict):
        from residual_grid import evaluate
        final=evaluate(a,grid,value['response'])
        return (tone,tinted,final) if stages else final
    ids, w = stencil(coordinates(tinted))
    delta = np.sum(w[..., None]*coefficients(grid)[ids]/256, axis=1)*gate[:, None]
    if value.get('mode')=='qaq-grid':delta=delta@np.asarray(value['response'])
    final = np.clip(tinted+delta, 0, 1)
    return (tone, tinted, final) if stages else final


def validate(value):
    if value.get('mode')=='qaq-grid':
        from residual_grid import response_matrix
        response_matrix(value['response'])
        return
    axis = np.asarray(value['axis'], dtype=float)
    tone = np.asarray(value['tone'], dtype=float); tint = np.asarray(value['tint'], dtype=float)
    gray = np.asarray(value['gray_axis'], dtype=float); chroma = np.asarray(value['gray_chroma'], dtype=float)
    if value.get('mode','tone-tint') not in ('tone-tint','rgb-independent'):
        raise ValueError('Unknown curve mode')
    if value.get('mode')=='rgb-independent':
        rgb=np.asarray(value.get('rgb'),dtype=float)
        if rgb.shape!=(len(axis),3) or not np.isfinite(rgb).all() or np.any(rgb<0) or np.any(rgb>1) or np.any(np.diff(rgb,axis=0)<-1e-12):
            raise ValueError('Invalid independent RGB curves')
    if (axis.ndim != 1 or not 2 <= len(axis) <= 1024 or tone.shape != axis.shape or tint.shape != (len(axis), 3)
        or gray.ndim != 1 or len(gray) < 2 or chroma.shape != (len(gray), 3)
        or not all(np.isfinite(x).all() for x in [axis, tone, tint, gray, chroma])
        or axis[0] != 0 or axis[-1] != 1 or np.any(np.diff(axis)<=0) or np.any(np.diff(gray)<=0)
        or np.any(np.diff(tone)<-1e-12) or np.any(tone<0) or np.any(tone>1)
        or np.max(np.abs(tint@LUMA))>1e-8
        or not 0 <= value['gray_protection_radius'] <= .1 or not 0 < value['gray_transition'] <= .5):
        raise ValueError('Invalid PC tone/tint curves')


TEACHER_SHAPE = (17, 33, 33)


def grid_design(rgb, shape):
    """Same provisional coordinates and trilinear rule at arbitrary resolution."""
    shape = np.asarray(shape, dtype=int)
    pos = np.clip((coordinates(rgb)+[0, .5, .5])*(shape-1), 0, shape-1)
    low = np.minimum(np.floor(pos).astype(int), shape-2); f = pos-low
    rows, cols, values = [], [], []
    for y in (0, 1):
        for u in (0, 1):
            for v in (0, 1):
                rows.append(np.arange(len(rgb)))
                cols.append(((low[:, 0]+y)*shape[1]+low[:, 1]+u)*shape[2]+low[:, 2]+v)
                values.append((f[:, 0] if y else 1-f[:, 0])*(f[:, 1] if u else 1-f[:, 1])*(f[:, 2] if v else 1-f[:, 2]))
    return sparse.coo_matrix((np.concatenate(values), (np.concatenate(rows), np.concatenate(cols))),
                             shape=(len(rgb), int(np.prod(shape)))).tocsr()


def neighbor_design(shape):
    nodes = np.arange(np.prod(shape)).reshape(shape)
    edges = np.concatenate([np.stack([np.take(nodes, range(shape[d]-1), axis=d).ravel(),
                                     np.take(nodes, range(1, shape[d]), axis=d).ravel()], axis=1)
                            for d in range(3)])
    return sparse.coo_matrix((np.tile([1., -1.], len(edges)),
                            (np.repeat(np.arange(len(edges)), 2), edges.ravel())),
                            shape=(len(edges), int(np.prod(shape)))).tocsr()


def fit_compressed(base, target, curve, weights, smooth_factor=1,target_neighborhood=0,training_penalties=True):
    """Train-only floating teacher, then gated least-squares distillation to 405 nodes.

    Uniform RGB probes are synthetic queries of the teacher, never target/test data.
    Equal mass for measured train and synthetic probes; final runtime stays 7 bit.
    """
    from gpu_runtime import available
    if type(training_penalties) is not bool:
        raise ValueError('training_penalties must be a boolean')
    if not training_penalties:
        smooth_factor=0.
        target_neighborhood=0
    if target_neighborhood:smooth_factor=0.
    if available():
        from gpu_grid import fit
        from gpu_tensor import TensorTools,stencil_tensor,provisional_coordinates
        _,tinted,gate=curves(base,curve)
        teacher,solver=fit(tinted,target,weights,.001*smooth_factor,gate=gate,
            shape=TEACHER_SHAPE,iterations=1200,continuous=True)
        axis=np.linspace(0,1,25)
        probes=np.stack(np.meshgrid(axis,axis,axis,indexing='ij'),axis=-1).reshape(-1,3)
        samples=np.concatenate([base,probes])
        _,staged,gates=curves(samples,curve)
        tools=TensorTools();values=tools.tensor(staged)
        ids,w=stencil_tensor(tools,provisional_coordinates(tools,values),TEACHER_SHAPE)
        desired=(values+(tools.tensor(teacher)[ids]*w[:,:,None]).sum(dim=1)*tools.tensor(gates)[:,None]).cpu().numpy()
        mass=np.r_[weights/np.sum(weights),np.full(len(probes),1/len(probes))]
        grid,audit=fit(staged,desired,mass,.001*smooth_factor,gate=gates)
        audit.update(teacher_shape=list(TEACHER_SHAPE),teacher_nodes=int(np.prod(TEACHER_SHAPE)),
            teacher_regularization=.001*smooth_factor,teacher_solver=[solver],synthetic_probes=len(probes),
            compression='GPU bounded dense teacher -> gated 5x9x9; equal train/probe mass',output_shape=[5,9,9])
        return grid,audit
    from scipy.sparse.linalg import lsmr
    _, tinted, gate = curves(base, curve)
    nodes = int(np.prod(TEACHER_SHAPE)); strength = .001*smooth_factor
    scale = np.sqrt(weights/np.sum(weights))
    a = grid_design(tinted, TEACHER_SHAPE).multiply((gate*scale)[:, None])
    smooth = neighbor_design(TEACHER_SHAPE)
    design = sparse.vstack([a, smooth*np.sqrt(strength/nodes), sparse.eye(nodes)*1e-5]).tocsr()
    teacher, solver = [], []
    for c in range(3):
        rhs = np.r_[(target[:, c]-tinted[:, c])*scale, np.zeros(smooth.shape[0]+nodes)]
        fit = lsmr(design, rhs, atol=1e-6, btol=1e-6, maxiter=2000)
        if fit[1] not in (0, 1, 2, 4, 5, 7):
            raise ValueError('Dense teacher did not converge: '+str(fit[1]))
        teacher.append(np.clip(fit[0], -64/256, 63/256))
        solver.append(dict(stop=int(fit[1]), converged=fit[1]!=7, iterations=int(fit[2]), residual_norm=float(fit[3])))
    teacher = np.stack(teacher, axis=1)
    axis = np.linspace(0, 1, 25)
    probes = np.stack(np.meshgrid(axis, axis, axis, indexing='ij'), axis=-1).reshape(-1, 3)
    samples = np.concatenate([base, probes])
    _, staged, gates = curves(samples, curve)
    desired = staged+(grid_design(staged, TEACHER_SHAPE)@teacher)*gates[:, None]
    sample_weights = np.r_[weights/np.sum(weights), np.full(len(probes), 1/len(probes))]
    grid, audit = fit_grid(staged, desired, gates, sample_weights, strength=.001*smooth_factor)
    audit.update(teacher_shape=list(TEACHER_SHAPE), teacher_nodes=nodes,
                 teacher_regularization=strength, teacher_solver=solver,
                 synthetic_probes=len(probes), compression='gated trilinear least squares; equal train/probe mass; signed 7-bit rounding',
                 output_shape=[5, 9, 9])
    return grid, audit
