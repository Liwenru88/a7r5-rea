"""MPS batched coordinate residual/Jacobian, guarded by the CPU float reference."""
import numpy as np
from scipy.optimize import least_squares

def solve(x,y,pair_ids,grids,coef,smooth,weights,reference,initial,lower,upper,budget,robust_scale,cpu_residual,perceptual_mix=0):
    import torch
    if not torch.backends.mps.is_available():raise ValueError('Apple MPS GPU unavailable')
    device='mps'
    tensor=lambda v,dtype=torch.float32:torch.as_tensor(v,dtype=dtype,device=device)
    tx=tensor(x);ty=tensor(y);tw=tensor(weights);tg=tensor(np.array(grids).reshape(-1,3)/256);ti=tensor(pair_ids,torch.int64);tc=tensor(coef);ref=tensor(reference.ravel())
    def batch(flat):
        aa=tensor(flat).reshape(-1,3,4)
        c=torch.einsum('nj,bij->bni',tx,aa[:,:,:3])+aa[:,:,3,None].transpose(1,2)
        at=torch.clamp(c*tensor([4,8,8])+tensor([0,4,4]),min=0);at=torch.minimum(at,tensor([4,8,8]))
        lo=torch.minimum(torch.floor(at).to(torch.int64),tensor([3,7,7],torch.int64));f=at-lo
        delta=torch.zeros_like(c)
        for iy in (0,1):
            for iu in (0,1):
                for iv in (0,1):
                    w=(f[:,:,0] if iy else 1-f[:,:,0])*(f[:,:,1] if iu else 1-f[:,:,1])*(f[:,:,2] if iv else 1-f[:,:,2])
                    index=ti[None,:]*405+(lo[:,:,0]+iy)*81+(lo[:,:,1]+iu)*9+lo[:,:,2]+iv
                    delta+=w[:,:,None]*tg[index]
        features=delta
        if smooth:
            z=tx-.5
            parts=[delta,(delta[:,:,:,None]*z[None,:,None,:]).reshape(len(aa),len(x),9)]
            if smooth=='quadratic':
                q=torch.stack([z[:,0]**2,z[:,1]**2,z[:,2]**2,z[:,0]*z[:,1],z[:,0]*z[:,2],z[:,1]*z[:,2]],dim=1)
                parts.append((delta[:,:,:,None]*q[None,:,None,:]).reshape(len(aa),len(x),18))
            features=torch.cat(parts,dim=2)
        pred=torch.clamp(tx[None]+features@tc,0,1)
        error=pred-ty[None]
        scale=robust_scale/255
        if scale:error=error*torch.sqrt(2/(torch.sqrt(1+(error/scale)**2)+1))
        if perceptual_mix:
            from perceptual import torch_oklab
            lab_error=torch_oklab(pred,torch)-torch_oklab(ty,torch)[None]
            lab_error=lab_error*torch.sqrt(2/(torch.sqrt(1+(lab_error/.03)**2)+1))
            error=torch.cat([error,perceptual_mix**.5*lab_error],dim=2)
        error=(error*tw[None]).reshape(len(aa),-1)
        return torch.cat([error,.02*(aa.reshape(-1,12)-ref)],dim=1).cpu().numpy().astype(float)
    cache={}
    def fun(p):
        key=np.asarray(p).tobytes()
        if key not in cache:cache.clear();cache[key]=batch(np.asarray(p)[None])[0]
        return cache[key]
    # Float32 MPS requires a physical finite-difference step, not the float64 sqrt-epsilon default.
    def jac(p):
        step=2e-4;rows=np.tile(p,(24,1))
        for k in range(12):rows[2*k,k]+=step;rows[2*k+1,k]-=step
        value=batch(rows)
        return ((value[::2]-value[1::2])/(2*step)).T
    err=float(np.max(abs(fun(initial)-cpu_residual(initial))))
    if err>2e-6:raise ValueError(f'MPS/CPU residual disagreement {err}')
    opt=least_squares(fun,initial,jac=jac,bounds=(lower,upper),max_nfev=budget,ftol=1e-6,xtol=1e-6,gtol=1e-7)
    # Low-cost double precision correction also detects an unsuitable float32 stationary point.
    corrected=least_squares(cpu_residual,opt.x,bounds=(lower,upper),max_nfev=12,ftol=1e-7)
    if np.sum(cpu_residual(corrected.x)**2)<np.sum(cpu_residual(opt.x)**2):opt.x=corrected.x
    opt.cost=float(np.sum(cpu_residual(opt.x)**2)/2)
    opt.gpu_audit=dict(device='mps',preflight_max_residual_error=err,jacobian='GPU batched central differences, h=2e-4',cpu_polish_nfev=int(corrected.nfev),diagnostic_scope='status/nfev/optimality describe GPU solve before CPU correction; cost and parameters describe accepted CPU-checked result')
    return opt
