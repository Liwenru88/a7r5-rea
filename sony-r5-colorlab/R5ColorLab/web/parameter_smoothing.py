"""Operator-aware train-time regularization, never a spatial image blur.

Only new optimization costs change: saved native parameters/rendering do not.
Gamma uses its physical nonuniform abscissae; block13 uses the actual native
sector interpolation and complete linear/quadratic RGB action; CC1 compares
its branch Jacobians, not parameters with different meanings.
"""
from functools import lru_cache
import struct
import numpy as np

POLICY='native-operator-geometry/1'
RATES=dict(block_rate=.0025,block_curvature=.00004,block_jump=.002,
           gamma_curvature=.000002,gamma_monotonic=.05,gamma_gain=.002,
           cc1_branch=.0005,cc1_gain=.002)
_DIRECTIONS=np.array([[1,0,0],[0,1,0],[0,0,1],[1,.5,0],[1,0,.5],
                       [.5,1,0],[0,1,.5],[.5,0,1],[0,.5,1]],float)
_PROBES=np.concatenate([_DIRECTIONS*.25,_DIRECTIONS*.75])
_CC_ANGLE=np.arange(64)*2*np.pi/64+np.pi/128
_CC_DIRECTION=np.column_stack([np.cos(_CC_ANGLE),np.sin(_CC_ANGLE)])

def strength(value):
    if type(value) not in (int,float) or not np.isfinite(value) or not 0 <= value <= 100:
        raise ValueError('参数平滑强度需在0–100之间')
    return float(value)

def multiplier(value):
    return 1 + strength(value)/5

@lru_cache(maxsize=16)
def _geometry(config):
    """Frozen64-point sector sampling, exact native normalization and wrap."""
    if config is None:
        angles=np.arange(16)*64.;norm=np.full(16,256.);factor=1/16384
        scales=np.ones(16);diag=np.ones(3);threshold=np.zeros(3);quadratic=False;enabled=True
    else:
        if len(config)<0x226:raise ValueError('Invalid block13 native config')
        angles=np.array(struct.unpack_from('<16H',config,6),float)
        norm=np.array(struct.unpack_from('<16H',config,0x1e8),float)
        mode=struct.unpack_from('<H',config,0x26)[0]
        factor=1/(4096*(2<<mode)) if mode<3 else 1/65536
        scales=np.array(struct.unpack_from('<16f',config,0x1a8))
        diag=np.array(struct.unpack_from('<3f',config,0x208))
        threshold=np.array(struct.unpack_from('<3f',config,0x214))/16384
        quadratic=bool(struct.unpack_from('<H',config,0x222)[0])
        enabled=bool(struct.unpack_from('<H',config,0x220)[0])
    if np.any(np.diff(angles)<=0) or angles[0]<0 or angles[-1]>=1024:
        raise ValueError('Invalid periodic block13 sector axis')
    if not all(np.isfinite(v).all() for v in [norm,scales,diag,threshold]):
        raise ValueError('Nonfinite block13 configuration')
    spans=np.roll(angles,-1)-angles;spans[-1]+=1024
    positions=(angles[:,None]+spans[:,None]*np.arange(4)[None,:]/4).ravel()/1024
    w=np.zeros((64,16));wl=np.zeros((16,16));wr=np.zeros((16,16))
    for i in range(16):
        for j,t in enumerate(np.arange(4)/4):
            w[4*i+j,i]=(1-t)*spans[i]*norm[i]*factor
            w[4*i+j,(i+1)%16]=t*spans[i]*norm[i]*factor
        # Difference between the exact endpoint from the prior interval and
        # the next interval's exact starting value measures native norm jumps.
        wl[i,(i+1)%16]=spans[i]*norm[i]*factor
        wr[i,(i+1)%16]=spans[(i+1)%16]*norm[(i+1)%16]*factor
    dx=np.roll(positions,-1)-positions;dx[-1]+=1
    return w,wl,wr,dx,scales,diag,threshold,quadratic,enabled


class _Numpy:
    tensor=staticmethod(lambda v:np.asarray(v,float))
    stack=staticmethod(lambda v,axis=-1:np.stack(v,axis=axis))
    cat=staticmethod(lambda v:np.concatenate([a.reshape(-1) for a in v]))
    diff=staticmethod(lambda v:np.diff(v))
    roll=staticmethod(lambda v,n,axis:np.roll(v,n,axis=axis))
    positive=staticmethod(lambda v:np.maximum(v,0))
    where=staticmethod(np.where)
    einsum=staticmethod(np.einsum)


class _Tensor:
    def __init__(self,tools):self.tools=tools;self.t=tools.torch
    def tensor(self,v):return v if self.t.is_tensor(v) else self.tools.tensor(v)
    def stack(self,v,axis=-1):return self.t.stack(v,dim=axis)
    def cat(self,v):return self.t.cat([a.reshape(-1) for a in v])
    def diff(self,v):return self.t.diff(v)
    def roll(self,v,n,axis):return self.t.roll(v,n,dims=axis)
    def positive(self,v):return v.clamp(min=0)
    def where(self,c,a,b):return self.t.where(c,a,b)
    def einsum(self,s,*v):return self.t.einsum(s,*v)


def _cc1_jacobians(cc1,op):
    """Actual preclip CC1 derivatives sampled across all sign branches."""
    cc1=op.tensor(cc1).reshape(8);directions=op.tensor(_CC_DIRECTION)
    dr,db=directions[:,0],directions[:,1]
    mr=op.where(db>=0,cc1[0],cc1[2]);mb=op.where(dr>=0,cc1[1],cc1[3])
    cr=dr+db*mr;cb=db+dr*mb
    gr=.5*op.where(cr>=0,cc1[5],cc1[7]);gb=.5*op.where(cb>=0,cc1[4],cc1[6])
    return op.stack([gr,gr*mr,gb*mb,gb]).reshape(64,2,2)


def _rows(coefficients,gamma,axis,value,cc1,config,op):
    amount=strength(value)/100
    c=op.tensor(coefficients).reshape(6,16);y=op.tensor(gamma).reshape(-1)/262143
    x=op.tensor(axis).reshape(-1);x=x/x[-1];dx=op.diff(x)
    # The caller supplies physical axes, never Gamma softmax/logit coordinates.
    if len(x)!=len(y) or len(x)<3:raise ValueError('Invalid Gamma axes')
    w,wl,wr,h,scales,diag,threshold,quadratic,enabled=_geometry(None if config is None else bytes(config))
    h=op.tensor(h);mid=(h+op.roll(h,1,axis=0))/2
    def block_outputs(matrix):
        q=op.tensor(matrix)@c.T
        a,b,cc,d,e,f=[q[:,i] for i in range(6)]
        # Keep the recovered native use of diag[0] for both R and B.
        linear=op.stack([a+b+diag[0],-a,-b,-cc,cc+d+diag[1],-d,-e,-f,e+f+diag[0]]).reshape(-1,3,3)
        out=op.einsum('nij,pj->npi',linear,op.tensor(_PROBES))
        if quadratic:
            z=(op.tensor(matrix)*op.tensor(scales)[None,:])@c.T
            a,b,cc,d,e,f=[z[:,i] for i in range(6)]
            square=op.stack([-a-b,a,b,cc,-cc-d,d,e,f,-e-f]).reshape(-1,3,3)
            n=op.einsum('nij,pj->npi',square,op.tensor(_PROBES*_PROBES))
            out=out+op.positive(n-op.tensor(threshold)[None,None,:])
        return out
    response=block_outputs(w)
    rate=(op.roll(response,-1,axis=0)-response)/h[:,None,None]
    curvature=(rate-op.roll(rate,1,axis=0))/mid[:,None,None]
    jump=block_outputs(wr)-block_outputs(wl)
    # Integrated squared derivative over sector/1024; probes and RGB channels
    # have equal family mass. No forced output-channel or hue monotonicity.
    block_mask=float(enabled)
    rows=[rate*h[:,None,None]**.5*(RATES['block_rate']/np.sqrt(54))*block_mask,
          curvature*mid[:,None,None]**.5*(RATES['block_curvature']/np.sqrt(54))*block_mask,
          jump*(RATES['block_jump']/np.sqrt(jump.size if isinstance(op,_Numpy) else jump.numel()))*block_mask]
    slope=op.diff(y)/dx;half=(dx[:-1]+dx[1:])/2
    gamma_curve=op.diff(slope)/half
    rows.extend([gamma_curve*half**.5*RATES['gamma_curvature'],
                 op.positive(-slope)*dx**.5*RATES['gamma_monotonic'],
                 op.positive(slope/64-1)*dx**.5*RATES['gamma_gain']])
    if cc1 is not None:
        jacobian=_cc1_jacobians(cc1,op)
        branch=jacobian-op.roll(jacobian,1,axis=0)
        # The Jacobian of a global linear chroma transform is constant. This
        # avoids mistaking the sin/cos of a rotating probe for operator noise.
        rows.extend([branch*(RATES['cc1_branch']/np.sqrt(256)),
                     op.positive((jacobian*jacobian).sum(axis=(1,2))/16-1)*(RATES['cc1_gain']/8)])
    return op.cat(rows)*np.sqrt(amount)


def native_rows(coefficients,gamma,axis,value,cc1=None,config=None):
    """Native operator geometry rows; zero strength disables every new row."""
    c=np.asarray(coefficients,float);y=np.asarray(gamma,float);x=np.asarray(axis,float)
    if (c.size!=96 or not np.isfinite(c).all() or x.ndim!=1 or y.shape!=x.shape
            or len(x)<3 or not np.isfinite(x).all() or not np.isfinite(y).all()
            or x[0]!=0 or np.any(np.diff(x)<=0)):
        raise ValueError('Invalid native smoothing arrays')
    if cc1 is not None and (np.asarray(cc1).shape!=(8,) or not np.isfinite(cc1).all()):
        raise ValueError('Invalid continuous CC1')
    return _rows(c,y,x,value,cc1,config,_Numpy())


def native_rows_tensor(tools,coefficients,gamma,axis,value,cc1=None,config=None):
    """Differentiable Torch counterpart; only frozen geometry uses NumPy."""
    return _rows(coefficients,gamma,axis,value,cc1,config,_Tensor(tools))

def native_cost(parameters, axis, value):
    if not strength(value):return 0.0
    from edit_native_model import decode_matrix16
    import struct
    config=decode_matrix16(parameters['matrix_payload'])
    c=np.array(struct.unpack_from('<96f',config,0x28))
    cc1=np.asarray(parameters['cc1'],np.int64);bits=(cc1[:4]&65535)>>2&511
    cc1=np.r_[np.where(bits>255,bits-512,bits)/256,((cc1[4:]&65535)>>3&255)/64]
    rows=native_rows(c,parameters['gamma_y'],axis,value,cc1=cc1,config=config)
    return float(rows@rows*255**2)


def grid_cost(grid,value,response=None):
    amount=strength(value)
    if not amount:return 0.0
    if isinstance(response,dict):
        from grid_regularization import get_penalty
        return get_penalty(response).cost(grid,value)
    g=np.asarray(grid,dtype=float).reshape(5,9,9,3)/256
    total=sum(float(np.sum(np.diff(g,axis=d)**2))for d in range(3))
    return total*(.01*multiplier(amount))*255**2/(405*3)


def pc_cost(bundle,value):
    if bundle is None or not strength(value):return 0.0
    curve,grid=bundle[:2]
    cost=grid_cost(grid,value,curve.get('response'))
    if curve.get('mode','tone-tint')=='tone-tint':
        for key in ('tone','tint'):
            d2=np.diff(np.asarray(curve[key]),n=2,axis=0)
            cost+=float(np.sum(d2*d2))*.002*multiplier(value)*255**2/3
    return cost
