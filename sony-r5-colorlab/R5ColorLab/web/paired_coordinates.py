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

