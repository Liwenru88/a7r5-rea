"""C方案收敛研究：密集局部窗口与辅助梯度冲突处理。"""
import hashlib
import math

import numpy as np
import torch

from native_guard_policy import dense_probe_inputs
from native_feasible_experiment import balance_weight
from native_objective_research import ResearchObjective
from perceptual import to_lab


def project_auxiliary(loss,vector,scales,primary):
    """只移除辅助项与主梯度相反的分量，不改变损失前向值。"""
    gradient=torch.autograd.grad(loss,vector,retain_graph=True)[0]*scales
    dot=float((gradient.detach()@primary.detach()).cpu())
    square=float(primary.detach().square().sum().cpu())
    projected=dot<0 and square>1e-30
    if projected:
        correction=(-dot/square)*primary.detach()
        loss=loss+(((vector-vector.detach())/scales)*correction).sum()
    return loss,dict(projected=projected)


class WindowRampBank:
    """每条双域饱和度射线覆盖均匀位置和原配方高曲率位置。"""
    def __init__(self,base,model,render,*,uniform=24,peaks=8,factor=16,rays_per_axis=None,
                 axes=('saturation','native-saturation')):
        if min(uniform,peaks,factor)<1:raise ValueError('密集窗口参数无效')
        self.base=base;self.groups=[];designs=[];full=[]
        for axis in axes:
            _,shape=base.span(axis)
            indices=np.arange(shape[0]) if rays_per_axis is None else np.unique(np.linspace(0,shape[0]-1,rays_per_axis).astype(int))
            for line in indices:
                rgb,inputs=dense_probe_inputs(base,axis,int(line),model,factor=factor)
                designs.append(rgb);full.append(inputs)
                self.groups.append(dict(axis=axis,line=int(line),dense_points=len(rgb)))
        sizes=[len(x) for x in full];reference=render(np.concatenate(full));offset=0
        windows=[];inputs=[];metadata=[]
        for group,rgb,x,size in zip(self.groups,designs,full,sizes):
            lab=to_lab(reference[offset:offset+size]*255)[...,1:];offset+=size
            curvature=np.linalg.norm(np.diff(lab,n=2,axis=0),axis=1)
            selected=np.concatenate((np.linspace(0,size-3,uniform).round().astype(int),np.argsort(curvature,kind='stable')[-peaks:]))
            triples=selected[:,None]+np.arange(3)[None]
            windows.append(rgb[triples].reshape(-1,3));inputs.append(x[triples].reshape(-1,9,3))
            metadata.append(dict(group,starts=selected.tolist()))
        self.groups=metadata;self.dense_offset=len(base.rgb)
        self.window_shape=(len(self.groups),uniform+peaks,3)
        self.rgb=np.concatenate((base.rgb,*windows));self._inputs=np.concatenate((base.inputs(model),*inputs))
        self.sha256=hashlib.sha256(self.rgb.tobytes()+self._inputs.tobytes()).hexdigest()

    def inputs(self,model):return self._inputs
    def span(self,axis):return self.base.span(axis)
    def jumps(self,rgb):return self.base.jumps(np.asarray(rgb)[:self.dense_offset])
    def lines(self,rgb,axis):return self.base.lines(np.asarray(rgb)[:self.dense_offset],axis)


class DenseWindowPenalty:
    """约束各射线曲率分布，不要求旧配方的转折位置不变。"""
    def __init__(self,bank,reference):
        self.bank=bank;self.reference=np.asarray(reference);self.backend_limits={}
        lab=to_lab(np.asarray(reference)[bank.dense_offset:]*255).reshape(*bank.window_shape,3)[...,1:]
        value=np.linalg.norm(lab[:,:,2]-2*lab[:,:,1]+lab[:,:,0],axis=-1)
        self.limits=np.column_stack((np.percentile(value,95,axis=1),value.max(1)))

    def features(self,tools,prediction):
        lab=tools.lab(prediction[self.bank.dense_offset:]).reshape(*self.bank.window_shape,3)[...,1:]
        delta=lab[:,:,2]-2*lab[:,:,1]+lab[:,:,0]
        value=(delta.square().sum(-1)+1e-20).sqrt()
        n=value.shape[1];at=(n-1)*.95;lower=math.floor(at);fraction=at-lower
        top=torch.topk(value,n-lower,dim=1).values
        p95=top[:,-1] if not fraction else (1-fraction)*top[:,-1]+fraction*top[:,-2]
        return torch.stack((p95,value.amax(1)),dim=1)

    def tensor_loss(self,tools,prediction):
        metrics=self.features(tools,prediction)
        key=(str(tools.device),str(tools.dtype))
        if key not in self.backend_limits:
            with torch.no_grad():
                self.backend_limits[key]=torch.maximum(tools.tensor(self.limits),self.features(tools,tools.tensor(self.reference)))
        limits=self.backend_limits[key]
        violations=((metrics-limits)/limits.clamp(min=.001)).clamp(min=0)
        return (violations+.5*violations.square()).mean()


class PrecisionObjective(ResearchObjective):
    """保留原主损失、照片门限及整数入口，只追加可消融的密集项。"""
    def __init__(self,*args,dense_budget=0.,project_conflicts=False,**kwargs):
        if not math.isfinite(dense_budget) or not 0<=dense_budget<=1:raise ValueError('密集梯度预算无效')
        reference=np.asarray(args[4]);super().__init__(*args,**kwargs)
        self.dense_budget,self.project_conflicts=dense_budget,project_conflicts
        self.dense=DenseWindowPenalty(self.bank,reference[self.ntrain:])

    def balanced(self,prediction,decoded,vector,scales,*,budget=.5):
        loss,stats=super().balanced(prediction,decoded,vector,scales,budget=budget)
        stats.update(dense_loss=0.,dense_gradient_ratio=0.,dense_projected=False,photo_guard_projected=False)
        if self.project_conflicts and self.photo_guard_budget:
            raw,_=self.photo_guard.parts(self.tools,prediction[self.photo_start:])
            amount=float(raw.detach().cpu())
            if amount>1e-20:
                weighted=(stats['photo_guard_loss']/amount)*raw
                total=torch.autograd.grad(loss,vector,retain_graph=True)[0]*scales
                aux=torch.autograd.grad(weighted,vector,retain_graph=True)[0]*scales
                changed,info=project_auxiliary(weighted,vector,scales,total-aux)
                loss=loss+changed-weighted;stats['photo_guard_projected']=info['projected']
        if self.dense_budget:
            primary=torch.autograd.grad(loss,vector,retain_graph=True)[0]*scales
            raw=self.dense.tensor_loss(self.tools,prediction[self.ntrain:self.photo_start])
            grad=torch.autograd.grad(raw,vector,retain_graph=True)[0]*scales
            norm=float(primary.detach().norm().cpu());gnorm=float(grad.detach().norm().cpu())
            weight=balance_weight(stats['data'],float(raw.detach().cpu()),norm,gnorm,budget=self.dense_budget)
            if self.project_conflicts:
                raw,info=project_auxiliary(raw,vector,scales,primary);stats['dense_projected']=info['projected']
            actual=torch.autograd.grad(raw,vector,retain_graph=True)[0]*scales
            loss=loss+weight*raw
            stats.update(dense_loss=weight*float(raw.detach().cpu()),dense_gradient_ratio=weight*float(actual.detach().norm().cpu())/max(norm,1e-20))
        return loss,stats
