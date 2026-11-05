"""Bounded single-span quadratic tensor B-spline coordinate correction.

Open knots [0,0,0,1,1,1] on each RGB axis: 27 control points, C-infinity
inside the RGB cube. Native 5x9x9 lookup and ordering are unchanged.
"""
import numpy as np
KIND='rgb-quadratic-bspline-3x3x3'
LIMIT=.06
LIPSCHITZ=.45

def basis(rgb):
    x=np.asarray(rgb,float)
    if x.ndim!=2 or x.shape[1]!=3 or not np.isfinite(x).all() or np.any((x<0)|(x>1)):raise ValueError('warp RGB must be finite Nx3 in 0..1')
    b=np.stack([(1-x)**2,2*x*(1-x),x*x],axis=2)
    return np.einsum('ni,nj,nk->nijk',b[:,0],b[:,1],b[:,2]).reshape(-1,27)

def certificate(control,affine):
    c=np.asarray(control,float).reshape(3,3,3,3);a=np.asarray(affine,float)[:,:3]
    # Each partial derivative is a convex combination of degree-scaled differences.
    bound=np.column_stack([2*np.max(abs(np.diff(c,axis=i)),axis=(0,1,2)) for i in range(3)])
    relative=bound@abs(np.linalg.inv(a))
    return dict(maximum_control_abs=float(abs(c).max()),global_relative_derivative_bound=float(np.linalg.norm(relative)),limit=LIMIT,relative_derivative_limit=LIPSCHITZ,proof='Frobenius bound of abs(Jcorrection) @ abs(inv(affine)); <1 guarantees no fold throughout RGB cube, not just sampled points',valid=bool(abs(c).max()<=LIMIT+1e-9 and np.linalg.norm(relative)<=LIPSCHITZ+1e-8))

def validate(warp,affine):
    if warp.get('kind')!=KIND:raise ValueError('unsupported coordinate warp')
    c=np.asarray(warp['control'],float)
    if c.shape!=(3,3,3,3) or not np.isfinite(c).all():raise ValueError('invalid warp controls')
    if not certificate(c,affine)['valid']:raise ValueError('coordinate warp exceeds global deformation bounds')
    return c

def coordinates(rgb,affine,warp=None):
    x=np.asarray(rgb,float);a=np.asarray(affine,float);out=x@a[:,:3].T+a[:,3]
    if warp is not None:out+=basis(x)@validate(warp,affine).reshape(27,3)
    return out

def delta_at(c,grid):
    a=np.clip(c*[4,8,8]+[0,4,4],0,[4,8,8]);lo=np.minimum(np.floor(a).astype(int),[3,7,7]);f=a-lo;g=np.asarray(grid).reshape(405,3)/256;out=np.zeros_like(c)
    for y in (0,1):
        for u in (0,1):
            for v in (0,1):
                w=(f[:,0] if y else 1-f[:,0])*(f[:,1] if u else 1-f[:,1])*(f[:,2] if v else 1-f[:,2])
                out+=w[:,None]*g[(lo[:,0]+y)*81+(lo[:,1]+u)*9+lo[:,2]+v]
    return out

def projected_control(raw,affine):
    c=LIMIT*np.tanh(np.asarray(raw)).reshape(3,3,3,3);bound=certificate(c,affine)['global_relative_derivative_bound']
    return c/max(1,bound/LIPSCHITZ)

def penalty(control):
    c=np.asarray(control).reshape(3,3,3,3)
    return .001*np.mean(c*c)+.003*sum(np.mean(np.diff(c,axis=i)**2) for i in range(3))+.01*sum(np.mean(np.diff(c,n=2,axis=i)**2) for i in range(3))

def solve_gpu(x,y,ids,grids,coef,affine,initial_raw,weights,scale=3,mix=1,iterations=100):
    import torch
    from perceptual import torch_oklab,joint_residual
    if not torch.backends.mps.is_available():raise ValueError('Apple MPS unavailable')
    t=lambda v:torch.as_tensor(v,dtype=torch.float32,device='mps')
    tx=t(x);ty=t(y);tb=t(basis(x));tc=t(coef);ta=t(affine);ti=torch.as_tensor(ids,dtype=torch.int64,device='mps');tg=t(np.asarray(grids).reshape(-1,3)/256)
    z=tx-.5;quadratic=torch.stack([z[:,0]**2,z[:,1]**2,z[:,2]**2,z[:,0]*z[:,1],z[:,0]*z[:,2],z[:,1]*z[:,2]],1)
    inv=t(abs(np.linalg.inv(np.asarray(affine)[:,:3])));raw=t(initial_raw).reshape(3,3,3,3).clone().requires_grad_(True)
    def control():
        c=LIMIT*torch.tanh(raw)
        bound=torch.stack([2*torch.amax(torch.abs(torch.diff(c,dim=i)),dim=(0,1,2)) for i in range(3)],dim=1)
        relative=torch.linalg.vector_norm(bound@inv)
        return c/torch.clamp(relative/LIPSCHITZ,min=1)
    def forward():
        c=control();at=tx@ta[:,:3].T+ta[:,3]+tb@c.reshape(27,3)
        at=torch.minimum(torch.clamp(at*t([4,8,8])+t([0,4,4]),min=0),t([4,8,8]))
        lo=torch.minimum(torch.floor(at).to(torch.int64),torch.tensor([3,7,7],device='mps'));f=at-lo;d=torch.zeros_like(tx)
        for a in (0,1):
            for b in (0,1):
                for e in (0,1):
                    w=(f[:,0] if a else 1-f[:,0])*(f[:,1] if b else 1-f[:,1])*(f[:,2] if e else 1-f[:,2])
                    index=ti*405+(lo[:,0]+a)*81+(lo[:,1]+b)*9+lo[:,2]+e;d=d+w[:,None]*tg[index]
        features=torch.cat([d,(d[:,:,None]*z[:,None]).reshape(-1,9),(d[:,:,None]*quadratic[:,None]).reshape(-1,18)],1)
        return torch.clamp(tx+features@tc,0,1),c
    # Weights supplied separately below, no use of held-out samples.
    weights=t(weights);weights=weights/weights.sum()
    def loss():
        pred,c=forward();er=pred-ty
        def squash(e,s):return e*torch.sqrt(2/(torch.sqrt(1+(e/s)**2)+1)) if s else e
        er=squash(er,scale/255)
        # Positive floor has no measurable forward effect at black, and avoids cube-root infinity.
        lab=squash(torch_oklab(pred,torch)-torch_oklab(ty,torch),.03)
        components=torch.cat([er,mix**.5*lab],1) if mix else er
        data=(components**2).mean(1)@weights
        reg=.001*(c*c).mean()+.003*sum(torch.diff(c,dim=i).square().mean() for i in range(3))+.01*sum(torch.diff(c,n=2,dim=i).square().mean() for i in range(3))
        return data+reg
    with torch.no_grad():pred,c=forward()
    import model
    cpu_d=np.empty_like(x)
    for i,g in enumerate(grids):
        keep=ids==i
        if keep.any():cpu_d[keep]=delta_at(coordinates(x[keep],affine,dict(kind=KIND,control=c.cpu().numpy().tolist())),g)
    cpu=np.clip(x+model.features(x,cpu_d,'quadratic')@coef,0,1)
    error=float(np.max(abs(cpu-pred.cpu().numpy())))
    if error>2e-5:raise ValueError(f'GPU warp predictor disagrees with CPU {error}')
    calls=[0];initial_loss=float(loss().detach().cpu())
    opt=torch.optim.LBFGS([raw],lr=.8,max_iter=iterations,max_eval=iterations*2,tolerance_grad=1e-9,tolerance_change=1e-12,history_size=12,line_search_fn='strong_wolfe')
    def closure():
        opt.zero_grad();v=loss()*1e5  # Scale numerical gradients; does not change the objective minimizer.
        if not torch.isfinite(v):raise ValueError('nonfinite warp objective')
        v.backward();calls[0]+=1;return v
    opt.step(closure)
    value=float(loss().detach().cpu());accepted=value<=initial_loss+1e-12
    returned=raw.detach().cpu().numpy() if accepted else np.asarray(initial_raw).reshape(3,3,3,3)
    controls=projected_control(returned,affine)
    return returned,controls,dict(device='mps',autograd=True,closure_calls=calls[0],initial_objective=initial_loss,final_objective=value,accepted=accepted,preflight_max_rgb_error=error,certificate=certificate(controls,affine))
