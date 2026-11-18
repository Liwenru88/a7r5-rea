"""C/D第二轮：原配方可行起点，拟合与约束同时按数值和梯度平衡。"""
import copy
import math

import numpy as np
import torch

import core
from fit_bin_joint import grid_from
from measured_response import get
from native_four_experiment import Space,Renderer,Objective,quantile95,local_violations
from native_gamma import EDIT_AXIS

POLICY='native-feasible-cd-experiment/2'
REPAIR_ALPHAS=tuple(2.**-i for i in range(1,17))


class OriginalSpace(Space):
    """保留负矩阵无效低位，避免起点编码变化；不作Gamma凹性投影。"""
    def __init__(self,context,seed,**kwargs):
        super().__init__(context,seed,kind='monotone',**kwargs)
        raw=np.asarray(seed['block13'][0],int)
        self.negative_bit=np.where(raw<0,raw&1,0)

    def entry(self,vector):
        entry=super().entry(vector)
        matrix=np.asarray(entry['block13'][0],int)
        matrix=matrix+np.where(matrix<0,self.negative_bit,0)
        entry['block13']=[matrix.tolist() for _ in range(3)]
        return core.compiler.unpack(core.compiler.pack(core.compiler.config([entry],5)))['entries'][0]


class FlatRenderer(Renderer):
    """色卡/探针九点相同时用合法的五像素宽度渲染；照片仍走完整参考。"""
    def exact_entry(self,entry):
        model=self.space.context.build(**core.slot_native_parameters(self.space.context,entry))
        parts=[]
        for start in range(0,len(self.inputs),16384):
            parts.append(model.color_only(self.inputs[start:start+16384,:5])[:,2]/16383)
        native=np.concatenate(parts)
        self.calls+=1
        return get(self.response).predict_cpu(native,grid_from(entry)),model,native


def balance_weight(data,penalty,fit_gradient,guard_gradient,*,budget=.5):
    """约束贡献同时不超过拟合损失和归一化梯度的固定比例。"""
    values=(data,penalty,fit_gradient,guard_gradient,budget)
    if not all(math.isfinite(v) and v>=0 for v in values) or not 0<budget<=1:
        raise ValueError('损失平衡输入无效')
    if penalty<=1e-20 or guard_gradient<=1e-20:return 0.
    return min(budget*data/penalty,budget*fit_gradient/guard_gradient)


def blend_entry(source,candidate,alpha):
    if not math.isfinite(alpha) or not 0<=alpha<=1:raise ValueError('缩步比例无效')
    entry=copy.deepcopy(source)
    for key in ('gamma_native_129','cc1_delta','block13'):
        a,b=np.asarray(source[key]),np.asarray(candidate[key])
        entry[key]=np.rint(a+alpha*(b-a)).astype(int).tolist()
    a=np.asarray(source['grid_5x9x9']['coefficients'])
    b=np.asarray(candidate['grid_5x9x9']['coefficients'])
    entry['grid_5x9x9']['coefficients']=np.rint(a+alpha*(b-a)).astype(int).tolist()
    return core.compiler.unpack(core.compiler.pack(core.compiler.config([entry],5)))['entries'][0]


class BalancedObjective(Objective):
    def parts(self,prediction,decoded):
        from stack_objective import de00_squared
        from parameter_smoothing import native_rows_tensor
        p=self.rounded(prediction)
        error=(p[:self.ntrain]-self.target8).square().mean()
        de=(de00_squared(self.tools,self.tools.lab(p[:self.ntrain]),self.target_lab)+1e-10).sqrt()
        tail=torch.topk(de,max(1,int(np.ceil(.05*self.ntrain)))).values.mean()
        data=error+self.de_weight*(de.mean()+.1*tail)
        gray=(p[:self.ntrain][self.gray]-self.target8[self.gray]).square().mean()
        constraints=[(gray/self.gray_limit-1).clamp(min=0),
                     (quantile95(de)/self.p95_limit-1).clamp(min=0)]
        for jumps,limits,reference,local in zip(self.ramp_jumps(p[self.ntrain:]),self.ramp_limits,self.reference_jumps,self.local_limits):
            constraints.extend((v/limit.clamp(min=.0005)-1).clamp(min=0)
                               for v,limit in zip((quantile95(jumps),jumps.max()),limits))
            constraints.extend(local_violations(jumps,reference,*local))
        violations=torch.stack(constraints).clamp(max=100)
        # 平均各保护项，不让增加探针/约束数量自动扩大损失权重。
        penalty=(violations+.5*violations.square()).mean()
        grid=decoded['grid'].flatten()
        regularization=.007*(grid@(self.gram@grid))
        rows=native_rows_tensor(self.tools,decoded['matrix']/1024,decoded['gamma']*16,
                               EDIT_AXIS,30,cc1=decoded['vector'][:8],config=self.config)
        regularization=regularization+rows.square().sum()
        stats=dict(data=float(data.detach().cpu()),raw_penalty=float(penalty.detach().cpu()),
            regularization=float(regularization.detach().cpu()),training_samples=self.ntrain,
            rgb_rmse=float(error.detach().sqrt().cpu())*255,
            delta_e00_mean=float(de.mean().detach().cpu()),gray_rmse=float(gray.detach().sqrt().cpu())*255,
            max_violation=float(violations.max().detach().cpu()),violations=violations.detach().cpu().tolist())
        return data+regularization,penalty,stats

    def balanced(self,prediction,decoded,vector,scales,*,budget=.5):
        fitting,penalty,stats=self.parts(prediction,decoded)
        first=torch.autograd.grad(fitting,vector,retain_graph=True)[0]*scales
        second=torch.autograd.grad(penalty,vector,retain_graph=True)[0]*scales
        fit_norm=float(first.detach().norm().cpu());guard_norm=float(second.detach().norm().cpu())
        weight=balance_weight(stats['data'],stats['raw_penalty'],fit_norm,guard_norm,budget=budget)
        guard=weight*stats['raw_penalty']
        stats.update(weight=weight,constraint=guard,fit_gradient_norm=fit_norm,
            raw_guard_gradient_norm=guard_norm,weighted_guard_gradient_norm=weight*guard_norm,
            value_ratio=guard/max(stats['data'],1e-20),gradient_ratio=weight*guard_norm/max(fit_norm,1e-20))
        return fitting+weight*penalty,stats
