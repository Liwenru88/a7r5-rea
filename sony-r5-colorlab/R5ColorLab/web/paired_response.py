"""Pinned R5 paired-capture response; linear in table coefficients at fixed RGB."""
from itertools import product
from numbers import Real
import numpy as np
from scipy import sparse
from scipy.optimize import least_squares

_DETAIL_INDICES=np.array([a*9+b*3+c for a,b,c in product(range(3),repeat=3)
                          if (a,b,c) not in tuple(product((0,2),repeat=3))])
_EXPERT_DIRECTIONS=np.array([[1.,0.],[-.5,np.sqrt(3)/2],[-.5,-np.sqrt(3)/2]])


def _c1_basis(x):
    """27 hierarchical bases in the exact calibrator coefficient order."""
    ends=np.stack([1-x,x],axis=2)
    coarse=np.einsum('ni,nj,nk->nijk',ends[:,0],ends[:,1],ends[:,2]).reshape(-1,8)
    hats=np.maximum(1-np.abs(2*x[:,:,None]-np.arange(3)),0)
    hats=hats*hats*(3-2*hats)
    fine=np.einsum('ni,nj,nk->nijk',hats[:,0],hats[:,1],hats[:,2]).reshape(-1,27)
    return np.concatenate([coarse,fine[:,_DETAIL_INDICES]],axis=1)


def _c1_basis_tensor(tools,x):
    t=tools.torch
    ends=t.stack([1-x,x],dim=2)
    coarse=t.einsum('ni,nj,nk->nijk',ends[:,0],ends[:,1],ends[:,2]).reshape(-1,8)
    hats=(1-t.abs(2*x[:,:,None]-tools.tensor([0.,1.,2.]))).clamp(min=0)
    hats=hats*hats*(3-2*hats)
    fine=t.einsum('ni,nj,nk->nijk',hats[:,0],hats[:,1],hats[:,2]).reshape(-1,27)
    return t.cat([coarse,fine[:,tools.tensor(_DETAIL_INDICES,integer=True)]],dim=1)


class PairedModel:
    def __init__(self,value,digest,identity=None):
        self.identity=identity
        self.value=dict(value,metadata=dict(model='ILCE-7RM5',physical_scope=value.get('scope','paired image capture')))
        self.sha256=digest;self.proxy=False
        self.affine=np.asarray(value['coordinate_affine'],float)
        self.weights=np.asarray(value['response_weights'],float)
        self.smooth=value['smooth'];self.validation=value['report']
        self.quadratic=value.get('response_basis')=='rgb-quadratic'
        self.hue_experts=value.get('response_basis')=='rgb-hue-experts-c1/1'
        if self.hue_experts:
            self.expert_weights=np.asarray(value['expert_weights'],float)
            self.expert_gate=dict(value.get('expert_gate',dict(kappa=2.,s0=.25,c0=.04)))
            if set(self.expert_gate)!={'kappa','s0','c0'} or any(
                isinstance(v,(bool,np.bool_)) or not isinstance(v,Real) or not np.isfinite(v) or v<=0
                for v in self.expert_gate.values()):raise ValueError('Invalid paired hue-expert gate')
            if self.expert_weights.shape!=(3,81,3) or not np.isfinite(self.expert_weights).all():raise ValueError('Invalid paired hue-expert response')
        self.warp=value.get('coordinate_warp')
        if self.warp is not None:
            from paired_coordinates import validate
            validate(self.warp,self.affine)
        if self.affine.shape!=(3,4) or self.weights.shape!=((81,3) if self.hue_experts else (30,3) if self.quadratic else (12,3) if self.smooth else (3,3)) or not np.isfinite(self.affine).all() or not np.isfinite(self.weights).all():raise ValueError('Invalid paired response model')
    def coordinates(self,rgb):
        from paired_coordinates import coordinates
        return coordinates(rgb,self.affine,self.warp)
    def stencil(self,rgb):
        from residual_grid import stencil
        c=self.coordinates(rgb);ids,w=stencil(c);return c,ids,w
    def response(self,rgb):
        x=np.asarray(rgb,float)
        if self.hue_experts:
            b=_c1_basis(x)
            shared=np.einsum('nb,cbo->nco',b,self.weights.reshape(3,27,3))
            experts=np.einsum('nb,ecbo->neco',b,self.expert_weights.reshape(3,3,27,3))
            z=np.column_stack([x[:,0]-(x[:,1]+x[:,2])/2,np.sqrt(3)/2*(x[:,1]-x[:,2])])
            q=np.sum(z*z,axis=1);gate=self.expert_gate
            logits=gate['kappa']*(z@_EXPERT_DIRECTIONS.T)/gate['s0']
            logits-=logits.max(axis=1,keepdims=True)
            p=np.exp(logits);p/=p.sum(axis=1,keepdims=True)
            w=(q/(q+gate['c0']**2))[:,None]*p
            return (shared+np.einsum('ne,neco->nco',w,experts))/256
        r=np.broadcast_to(self.weights[:3],(len(x),3,3)).copy()
        if self.smooth:r+=np.einsum('nj,cjo->nco',x-.5,self.weights[3:12].reshape(3,3,3))
        if self.quadratic:
            z=x-.5
            q=np.column_stack([z[:,0]**2,z[:,1]**2,z[:,2]**2,z[:,0]*z[:,1],z[:,0]*z[:,2],z[:,1]*z[:,2]])
            r+=np.einsum('nj,cjo->nco',q,self.weights[12:].reshape(3,6,3))
        return r/256
    def coordinates_tensor(self,tools,rgb):
        a=tools.tensor(self.affine)
        out=rgb@a[:,:3].T+a[:,3]
        if self.warp is not None:
            t=tools.torch
            b=t.stack([(1-rgb)**2,2*rgb*(1-rgb),rgb*rgb],dim=2)
            basis=t.einsum('ni,nj,nk->nijk',b[:,0],b[:,1],b[:,2]).reshape(-1,27)
            out=out+basis@tools.tensor(self.warp['control']).reshape(27,3)
        return out
    def response_tensor(self,tools,rgb):
        t=tools.torch
        if self.hue_experts:
            # Every RGB-dependent operation stays in Torch: gradients through
            # basis, neutral attenuation and expert mixing reach native fits.
            b=_c1_basis_tensor(tools,rgb)
            shared=t.einsum('nb,cbo->nco',b,tools.tensor(self.weights.reshape(3,27,3)))
            experts=t.einsum('nb,ecbo->neco',b,tools.tensor(self.expert_weights.reshape(3,3,27,3)))
            z=t.stack([rgb[:,0]-(rgb[:,1]+rgb[:,2])/2,np.sqrt(3)/2*(rgb[:,1]-rgb[:,2])],dim=1)
            q=(z*z).sum(dim=1);gate=self.expert_gate
            logits=gate['kappa']*(z@tools.tensor(_EXPERT_DIRECTIONS).T)/gate['s0']
            w=(q/(q+gate['c0']**2))[:,None]*t.softmax(logits,dim=1)
            return (shared+t.einsum('ne,neco->nco',w,experts))/256
        z=rgb-.5
        r=tools.tensor(self.weights[:3]).expand(len(rgb),3,3)
        if self.smooth:r=r+t.einsum('nj,cjo->nco',z,tools.tensor(self.weights[3:12].reshape(3,3,3)))
        if self.quadratic:
            q=t.stack([z[:,0]**2,z[:,1]**2,z[:,2]**2,z[:,0]*z[:,1],z[:,0]*z[:,2],z[:,1]*z[:,2]],dim=1)
            r=r+t.einsum('nj,cjo->nco',q,tools.tensor(self.weights[12:].reshape(3,6,3)))
        return r/256
    def predict(self,rgb,table,clip=True):
        from gpu_runtime import available
        if self.identity is not None and available() and clip and len(rgb)>=512:
            from gpu_color import paired_numpy
            identity=self.identity
            return paired_numpy(rgb,table,identity)
        return self.predict_cpu(rgb,table,clip)
    def predict_cpu(self,rgb,table,clip=True):
        x=np.asarray(rgb,float);_,ids,w=self.stencil(x)
        d=(np.asarray(table)[ids]*w[...,None]).sum(1)
        out=x+np.einsum('nc,nco->no',d,self.response(x))
        return np.clip(out,0,1) if clip else out
    def probes(self,count,seed=20261022):
        # Compression also needs extrapolation colors: explicitly not additional camera evidence.
        return np.random.default_rng(seed).uniform(.015,.985,(count,3))
    def fit(self,base,target,weights,strength=.01,loss_progress=None):
        from gpu_runtime import available
        if self.identity is not None and available():
            from gpu_grid import fit
            identity=self.identity
            result,audit=fit(base,target,weights,strength,response=identity,loss_progress=loss_progress)
            audit.update(model_sha256=self.sha256,physical_scope=self.value['metadata']['physical_scope'],
                calibration_validation=self.validation,new_scene_camera_verified=False)
            return result,audit
        from pc_stages import neighbor_design
        x=np.asarray(base,float);target=np.asarray(target,float);weights=np.asarray(weights,float)
        if x.shape!=target.shape or weights.shape!=(len(x),) or np.any(weights<=0):raise ValueError('Invalid paired training samples')
        _,ids,w=self.stencil(x);r=self.response(x);mass=np.sqrt(weights/weights.sum())
        rows=[];cols=[];data=[]
        for c in range(3):
            for o in range(3):
                rows.append(np.repeat(np.arange(len(x))*3+o,8));cols.append((ids*3+c).ravel())
                data.append((w*r[:,c,o,None]*mass[:,None]).ravel())
        design=sparse.coo_matrix((np.concatenate(data),(np.concatenate(rows),np.concatenate(cols))),shape=(len(x)*3,1215)).tocsr()
        if self.identity is not None:
            from grid_regularization import get_penalty
            regularizer=get_penalty(self.identity).rows*np.sqrt(strength)
        else:
            regularizer=sparse.kron(neighbor_design((5,9,9)),sparse.eye(3),format='csr')*np.sqrt(strength/405)/256
        def loss(v):
            raw=x+(design@v).reshape(-1,3)/mass[:,None]
            return np.r_[((np.clip(raw,0,1)-target)*mass[:,None]).ravel(),regularizer@v]
        def jac(v):
            raw=x+(design@v).reshape(-1,3)/mass[:,None]
            return sparse.vstack([design.multiply(((raw>0)&(raw<1)).ravel()[:,None]),regularizer],format='csr')
        zero=np.zeros(1215)
        best=float('inf')
        def sample(intermediate_result):
            nonlocal best
            current=float(intermediate_result.cost)
            best=min(best,current)
            loss_progress('CPU 网格 least_squares',int(intermediate_result.nfev),current,best)
        options={'callback':sample} if loss_progress else {}
        result=least_squares(loss,zero,jac=jac,bounds=(-64,63),tr_solver='lsmr',max_nfev=60,ftol=1e-6,**options)
        if loss_progress:
            sample(result)
        v=result.x if np.isfinite(result.fun).all() and np.linalg.norm(result.fun)<=np.linalg.norm(loss(zero)) else zero
        table=np.clip(np.rint(v.reshape(405,3)),-64,63).astype(np.int8)
        return table,dict(model_sha256=self.sha256,regularization=strength,training_only=True,evaluations=result.nfev,converged=bool(result.success),calibration_validation=self.validation,physical_scope=self.value['metadata']['physical_scope'],new_scene_camera_verified=False)
