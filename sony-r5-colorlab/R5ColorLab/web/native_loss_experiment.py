"""独立损失消融：保留原前向和验收，仅调整目标渐变贡献。"""
import math

import torch

from native_feasible_experiment import balance_weight
from native_guard_policy import ReviewedObjective


def gradient_cap_factor(primary,auxiliary,cap):
    if cap is None:return 1.
    if not math.isfinite(cap) or cap<0:raise ValueError('辅助梯度比例必须为非负有限数')
    first=float(primary.detach().norm().cpu());second=float(auxiliary.detach().norm().cpu())
    if not math.isfinite(first) or not math.isfinite(second):raise ValueError('损失分项梯度无效')
    return 1. if second<=1e-20 else min(1.,cap*first/second)


class LossObjective(ReviewedObjective):
    """目标渐变权重可消融；梯度限幅只调辅助项，不修改主颜色梯度。"""
    def __init__(self,*args,tone_ratio=.1,tone_gradient_cap=None,**kwargs):
        if not math.isfinite(tone_ratio) or tone_ratio<0:raise ValueError('目标渐变权重比例无效')
        if tone_gradient_cap is not None and (not math.isfinite(tone_gradient_cap) or tone_gradient_cap<0):
            raise ValueError('目标渐变梯度比例无效')
        super().__init__(*args,**kwargs)
        self.tone_weight*=tone_ratio/.1
        self.tone_ratio,self.tone_gradient_cap=tone_ratio,tone_gradient_cap

    def balanced(self,prediction,decoded,vector,scales,*,budget=.5):
        fitting,penalty,stats=self.parts(prediction,decoded)
        tone=self.tone_weight*self.tone_bank.tensor_loss(self.tools,prediction[:self.ntrain])
        first=torch.autograd.grad(fitting,vector,retain_graph=True)[0]*scales
        tone_grad=torch.autograd.grad(tone,vector,retain_graph=True)[0]*scales
        primary=first-tone_grad
        factor=gradient_cap_factor(primary,tone_grad,self.tone_gradient_cap)
        effective=first if factor==1. else primary+factor*tone_grad
        second=torch.autograd.grad(penalty,vector,retain_graph=True)[0]*scales
        fit_norm=float(effective.detach().norm().cpu());guard_norm=float(second.detach().norm().cpu())
        primary_norm=float(primary.detach().norm().cpu());tone_norm=float(tone_grad.detach().norm().cpu())
        cosine=float((primary.detach()@tone_grad.detach()).cpu())/max(primary_norm*tone_norm,1e-20)
        data=stats['data']-(1-factor)*stats['target_gradient_loss']
        weight=balance_weight(data,stats['raw_penalty'],fit_norm,guard_norm,budget=budget)
        stats.update(data=data,uncapped_target_gradient_loss=stats['target_gradient_loss'],
            target_gradient_loss=factor*stats['target_gradient_loss'],tone_gradient_factor=factor,
            tone_gradient_ratio=tone_norm/max(primary_norm,1e-20),
            effective_tone_gradient_ratio=factor*tone_norm/max(primary_norm,1e-20),
            tone_primary_cosine=cosine,weight=weight,constraint=weight*stats['raw_penalty'],
            fit_gradient_norm=fit_norm,raw_guard_gradient_norm=guard_norm,
            weighted_guard_gradient_norm=weight*guard_norm,
            value_ratio=weight*stats['raw_penalty']/max(data,1e-20),
            gradient_ratio=weight*guard_norm/max(fit_norm,1e-20))
        adjusted=fitting if factor==1. else fitting-(1-factor)*tone
        return adjusted+weight*penalty,stats
