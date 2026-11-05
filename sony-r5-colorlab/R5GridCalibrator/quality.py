"""Training-only balancing, robust response solves and independent diagnostics."""
import numpy as np
from scipy.optimize import least_squares

def color_groups(x,hue_bins=12):
    x=np.asarray(x);hi=x.max(1);lo=x.min(1);span=hi-lo;ch=x.argmax(1);h=np.zeros(len(x))
    for c in range(3):
        m=(span>1e-8)&(ch==c)
        h[m]=((x[m,(c+1)%3]-x[m,(c+2)%3])/span[m]+2*c)%6
    sat=span/np.maximum(hi,1e-8);lum=x@np.array([.2126,.7152,.0722])
    neutral=span<=.02
    # Neutral is separate; no unstable near-gray hue classification.
    sector=np.minimum((h*(hue_bins/6)).astype(int),hue_bins-1)
    group=np.minimum((lum*6).astype(int),5)*(hue_bins*4+1)+np.where(neutral,hue_bins*4,sector*4+np.minimum((sat*4).astype(int),3))
    return group,neutral,sector

def balanced_weights(x,ids,splits,enabled=True,hue24=False):
    """Equal pair mass; inverse square-root density with capped rare-color amplification.

    Each split is independent so training weights cannot depend on held-out colors.
    """
    groups,neutral,hue=color_groups(x,24 if hue24 else 12);weights=np.empty(len(x))
    sectors=np.where(neutral,24,hue)
    for split in np.unique(splits):
        for pid in np.unique(ids[splits==split]):
            ix=np.flatnonzero((splits==split)&(ids==pid));_,inv,counts=np.unique(groups[ix],return_inverse=True,return_counts=True)
            w=1/np.sqrt(counts[inv]) if enabled else np.ones(len(ix))
            w=np.minimum(w,4*np.median(w))
            if hue24:
                # Every observed 15-degree hue sector has equal total mass;
                # neutral forms its own sector. Density balancing remains within each sector.
                for sector in np.unique(sectors[ix]):
                    keep=sectors[ix]==sector;w[keep]/=w[keep].sum()
            weights[ix]=w/w.sum()
    return weights

def response_solve(x,y,d,smooth,features,weights,mask,scale,perceptual_mix=0):
    """Same clipped floating predictor as runtime; soft-L1 data and quadratic ridge."""
    f=features(x,d,smooth);fm=f[mask];xx=x[mask];yy=y[mask];w=weights[mask]
    # Preserve original per-pair mass convention and ridge magnitude.
    mat=fm*np.sqrt(w)[:,None];tar=(yy-xx)*np.sqrt(w)[:,None]
    k=fm.shape[1];reg=np.full(k,3e-5 if smooth else 1e-6)
    if smooth=='quadratic':reg[12:]*=10
    penalty=np.repeat(np.sqrt(reg),3)
    initial=np.linalg.solve(mat.T@mat+np.diag(reg),mat.T@tar)
    if perceptual_mix:
        from perceptual import oklab,lab_jacobian,squash
        root=np.sqrt(w)[:,None];target_lab=oklab(yy);coef=initial
        for _ in range(4):
            pred=np.clip(xx+fm@coef,0,1);er=pred-yy;el=oklab(pred)-target_lab
            rr=(1+(er/(scale/255))**2)**(-.25) if scale else np.ones_like(er)
            rl=(1+(el/.03)**2)**(-.25)
            def residual(flat):
                pred=np.clip(xx+fm@flat.reshape(k,3),0,1)
                return np.r_[((pred-yy)*root*rr).ravel(),(np.sqrt(perceptual_mix)*(oklab(pred)-target_lab)*root*rl).ravel(),penalty*flat]
            def jac(flat):
                raw=xx+fm@flat.reshape(k,3);pred=np.clip(raw,0,1);active=(raw>0)&(raw<1)
                jr=np.einsum('nk,no,op->nokp',fm,active*root*rr,np.eye(3)).reshape(len(xx)*3,k*3)
                jl=np.einsum('noi,ni,nk->noki',lab_jacobian(pred)*root[:,:,None]*rl[:,:,None]*np.sqrt(perceptual_mix),active,fm).reshape(len(xx)*3,k*3)
                return np.vstack([jr,jl,np.diag(penalty)])
            opt=least_squares(residual,coef.ravel(),jac=jac,max_nfev=25,ftol=1e-7,xtol=1e-7,gtol=1e-9)
            new=opt.x.reshape(k,3)
            if np.max(abs(new-coef))<1e-7:coef=new;break
            coef=new
        return coef,np.clip(x+f@coef,0,1),dict(loss='RGB + OKLab soft-L1 IRLS',perceptual_mix=perceptual_mix)
    root=np.sqrt(w);sc=scale/255
    if scale<=0:return initial,np.clip(x+f@initial,0,1),dict(nfev=0,success=True,loss='ridge-linear',note='robust disabled')
    # IRLS computes robust influence from unweighted physical RGB errors.
    coef=initial
    for _ in range(4):
        raw=xx+fm@coef;e=np.clip(raw,0,1)-yy
        robust=1/np.sqrt(1+(e/sc)**2);rw=root[:,None]*np.sqrt(robust)
        def residual(flat):
            c=flat.reshape(k,3)
            return np.r_[((np.clip(xx+fm@c,0,1)-yy)*rw).ravel(),penalty*flat]
        def jac(flat):
            active=((xx+fm@flat.reshape(k,3)>0)&(xx+fm@flat.reshape(k,3)<1))*rw
            j=np.einsum('nk,no,op->nokp',fm,active,np.eye(3)).reshape(len(xx)*3,k*3)
            return np.vstack([j,np.diag(penalty)])
        opt=least_squares(residual,coef.ravel(),jac=jac,max_nfev=25,ftol=1e-7,xtol=1e-7,gtol=1e-9)
        new=opt.x.reshape(k,3)
        if np.max(abs(new-coef))<1e-7:coef=new;break
        coef=new
    return coef,np.clip(x+f@coef,0,1),dict(nfev=int(opt.nfev),success=bool(opt.success),loss='clipped-float-soft-L1-IRLS',robust_scale_codes=scale)

def enriched_metric(pred,target):
    e=(np.asarray(pred)-target)*255;px=np.sqrt(np.mean(e*e,axis=1))
    return dict(rmse=float(np.sqrt(np.mean(e*e))),mae=float(np.mean(abs(e))),p95=float(np.percentile(abs(e),95)),patch_rmse_p95=float(np.percentile(px,95)),maximum_abs=float(abs(e).max()))

def grouped_metrics(x,pred,target,mask,hue_bins=12):
    _,neutral,hue=color_groups(x,hue_bins);out={}
    for name,keep in [('neutral',neutral),('chromatic',~neutral)]+[(f'hue_{i*(360//hue_bins):03d}_{(i+1)*(360//hue_bins):03d}',(~neutral)&(hue==i)) for i in range(hue_bins)]:
        keep=keep&mask
        out[name]=dict(count=int(keep.sum()),metrics=enriched_metric(pred[keep],target[keep]) if keep.any() else None)
    return out

def support_report(x,d,affine,features,smooth,coordinate_values=None):
    c=x@affine[:,:3].T+affine[:,3] if coordinate_values is None else np.asarray(coordinate_values);at=np.clip(c*[4,8,8]+[0,4,4],0,[4,8,8]);lo=np.minimum(np.floor(at).astype(int),[3,7,7]);fr=at-lo
    mass=np.zeros(405)
    for iy in (0,1):
        for iu in (0,1):
            for iv in (0,1):
                ids=(lo[:,0]+iy)*81+(lo[:,1]+iu)*9+lo[:,2]+iv
                w=(fr[:,0] if iy else 1-fr[:,0])*(fr[:,1] if iu else 1-fr[:,1])*(fr[:,2] if iv else 1-fr[:,2])
                mass+=np.bincount(ids,weights=w,minlength=405)
    f=features(x,d,smooth);sing=np.linalg.svd(f,compute_uv=False);rank=int(np.sum(sing>max(sing[0]*1e-6,1e-10)))
    return dict(touched_nodes=int(sum(mass>1e-8)),total_nodes=405,node_support_mass=mass.tolist(),response_feature_rank=rank,response_feature_columns=f.shape[1],response_feature_condition=float(sing[0]/sing[-1]) if sing[-1]>1e-12 else None,scope='training samples only; node support is not parameter identifiability')


def weighting_report(x,ids,splits,weights):
    _,neutral,hue=color_groups(x,24);sector=np.where(neutral,24,hue);out=[]
    for split in np.unique(splits):
        for pid in np.unique(ids[splits==split]):
            keep=(splits==split)&(ids==pid)
            out.append(dict(split=int(split),pair=int(pid),sector_counts=np.bincount(sector[keep],minlength=25).tolist(),sector_weight_mass=np.bincount(sector[keep],weights=weights[keep],minlength=25).tolist()))
    return dict(bins=24,hue_space='encoded baseline sRGB HSV hue, 15 degree bins',neutral='RGB span<=0.02, separate sector24',per_pair_split=out)
