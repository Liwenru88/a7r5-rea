"""固定密集输入的整体与逐射线验收，保留量化区间和原始变化。"""
import numpy as np

from native_guard_policy import quantization_box
from perceptual import to_lab


def dense_report(reference,candidate):
    a,b=np.asarray(reference,float),np.asarray(candidate,float)
    if a.shape!=b.shape or a.ndim!=3 or a.shape[-1]!=3 or a.shape[1]<3:
        raise ValueError('密集检查要求相同的射线/采样点/RGB形状')
    if any(not np.isfinite(v).all() or v.min()<0 or v.max()>1 for v in (a,b)):
        raise ValueError('密集RGB无效')
    def curve(rgb):return np.diff(to_lab(rgb*255)[...,1:],n=2,axis=1)
    da,db=curve(a),curve(b);old,new=np.linalg.norm(da,axis=-1),np.linalg.norm(db,axis=-1)
    box=quantization_box(a.reshape(-1,3))
    lo,hi=(box[key].reshape(a.shape)[...,1:] for key in ('lab_low','lab_high'))
    lower=lo[:,2:]-2*hi[:,1:-1]+lo[:,:-2]
    upper=hi[:,2:]-2*lo[:,1:-1]+hi[:,:-2]
    error=np.linalg.norm(np.maximum(np.abs(lower-da),np.abs(upper-da)),axis=-1)
    def stats(v):return dict(p95=float(np.percentile(v,95)),max=float(v.max()))
    base,after=stats(old),stats(new)
    global_flags=[key for key in base if after[key]>base[key]+1e-8]
    rows=[];raw=[];quant=[]
    for line in range(len(a)):
        ref,cur,limit=stats(old[line]),stats(new[line]),stats(old[line]+error[line])
        flags=[key for key in ref if cur[key]>ref[key]+1e-8]
        calibrated=[key for key in ref if cur[key]>limit[key]+1e-8]
        raw += [dict(line=line,metric=key) for key in flags]
        quant += [dict(line=line,metric=key) for key in calibrated]
        rows.append(dict(line=line,reference=ref,candidate=cur,quantization_upper=limit,raw_flags=flags,quantization_flags=calibrated))
    return dict(points=a.shape[1],rays=a.shape[0],reference=base,candidate=after,
        global_exceedances=global_flags,local_raw_exceedances=raw,local_quantization_exceedances=quant,lines=rows,
        interpretation='原始退步与8位舍入区间分开；量化区间不是人眼可见阈值')
