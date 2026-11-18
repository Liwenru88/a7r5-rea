"""C方案损失研究：开发照片辅助与冻结容差下的统计过渡惩罚。"""
import math

import numpy as np
import torch

from native_four_experiment import Renderer,quantile95
from native_feasible_experiment import balance_weight
from native_guard_policy import photo_regions,multiscale_report,quality_envelope
from native_loss_experiment import LossObjective


class PhotoBank:
    """每张开发照片的九个区域等量采样，留出照片禁止进入训练。"""
    def __init__(self,rows,*,per_region=64,seed=42):
        if type(per_region) is not int or per_region<1:raise ValueError('照片区域采样数无效')
        rng=np.random.default_rng(seed);inputs=[];targets=[];self.groups=[]
        self.per_region=per_region;self.reference=None
        for row in rows:
            if row['role']!='development':raise ValueError('照片辅助训练只接受开发集')
            x,t=np.asarray(row['inputs']),np.asarray(row['target'],float)
            if x.shape!=(len(t),9,3) or t.shape!=(len(t),3) or not np.isfinite(t).all() or t.min()<0 or t.max()>1:
                raise ValueError('照片训练输入/目标无效')
            for region,indices in photo_regions(row['display']).items():
                if region=='whole':continue
                if len(indices)<per_region or indices.min()<0 or indices.max()>=len(x):
                    raise ValueError('照片区域无法完成固定采样')
                selected=np.sort(rng.choice(indices,per_region,replace=False))
                self.groups.append(dict(scene=row['scene'],region=region,indices=selected.tolist()))
                inputs.append(x[selected]);targets.append(t[selected])
        if not inputs:raise ValueError('照片辅助训练缺少开发数据')
        self.inputs=np.concatenate(inputs);self.target=np.concatenate(targets)

    def tensor_loss(self,tools,prediction,de_weight):
        from stack_objective import de00_squared
        if tuple(prediction.shape)!=self.target.shape:raise ValueError('照片预测形状不同')
        p=self_rounded(prediction);target=tools.tensor(np.floor(self.target*255+.5)/255)
        de=(de00_squared(tools,tools.lab(p),tools.lab(target))+1e-10).sqrt()
        groups=de.reshape(len(self.groups),self.per_region)
        tail=torch.topk(groups,max(1,math.ceil(.05*self.per_region)),dim=1).values.mean()
        return (p-target).square().mean()+de_weight*(de.mean()+.1*tail)


def self_rounded(value):
    return value+(torch.floor(value.clamp(0,1)*255+.5)/255-value).detach()


class PhotoProtection:
    """区域误差超过各自冻结的舍入区间后才施加保护。"""
    def __init__(self,bank):
        if bank.reference is None:raise ValueError('照片门限缺少原配方参考')
        self.bank=bank;self.calibration=[]
        keys=('rgb_rmse','delta_e00_mean','delta_e00_p95')
        for index,group in enumerate(bank.groups):
            at=slice(index*bank.per_region,(index+1)*bank.per_region)
            bounds=quality_envelope(bank.reference[at],bank.target[at])
            self.calibration.append(dict(scene=group['scene'],region=group['region'],**bounds))
        self.limits=np.array([[row['upper'][key] for key in keys] for row in self.calibration])
        self.scales=np.maximum([[row['margins'][key] for key in keys] for row in self.calibration],1e-6)

    def parts(self,tools,prediction):
        from stack_objective import de00_squared
        if tuple(prediction.shape)!=self.bank.target.shape:raise ValueError('照片门限输入形状不同')
        p=self_rounded(prediction);target=tools.tensor(np.floor(self.bank.target*255+.5)/255)
        shape=(len(self.bank.groups),self.bank.per_region)
        rgb=((p-target).reshape(*shape,3).square().mean((1,2))+1e-20).sqrt()*255
        de=((de00_squared(tools,tools.lab(p),tools.lab(target))+1e-10).sqrt()-1e-5).clamp(min=0).reshape(shape)
        position=(self.bank.per_region-1)*.95;lower=int(math.floor(position));fraction=position-lower
        tail=torch.topk(de,self.bank.per_region-lower,dim=1).values
        p95=tail[:,-1] if not fraction else (1-fraction)*tail[:,-1]+fraction*tail[:,-2]
        metrics=torch.stack((rgb,de.mean(1),p95),dim=1)
        violations=((metrics-tools.tensor(self.limits))/tools.tensor(self.scales)).clamp(min=0)
        loss=(violations+.5*violations.square()).mean()
        return loss,dict(photo_guard_active_regions=int((violations.detach().amax(1)>0).sum().cpu()),
            photo_guard_max_violation=float(violations.detach().max().cpu()))


class TransitionPenalty:
    """只惩罚超过参考量化区间的分布统计，不匹配旧曲线转折位置。"""
    def __init__(self,bank,reference):
        self.bank=bank;report=multiscale_report(bank,reference,reference)
        self.limits={axis:{int(stride):{key:row['baseline_float'][key]+row['noise'][key]
            for key in ('p95','max')} for stride,row in values.items()} for axis,values in report['axes'].items()}

    def tensor_loss(self,tools,prediction):
        if len(prediction)!=len(self.bank.rgb):raise ValueError('过渡训练输入形状不同')
        lab=tools.lab(prediction);violations=[]
        for axis,scales in self.limits.items():
            span,shape=self.bank.span(axis);lines=lab[span].reshape(*shape,3)[...,1:]
            for stride,limits in scales.items():
                delta=lines[:,2*stride:]-2*lines[:,stride:-stride]+lines[:,:-2*stride]
                norm=(delta.square().sum(-1)+1e-12).sqrt()
                for stat,limit in ((quantile95(norm),limits['p95']),(norm.max(),limits['max'])):
                    violations.append((stat/max(limit,1e-6)-1).clamp(min=0).square())
        return torch.stack(violations).mean()


class MixedRenderer:
    """色卡保留平坦加速，照片显式使用完整九点路径。"""
    def __init__(self,chart,photo_inputs):
        self.chart=chart;self.space=chart.space;self.tools=chart.tools
        self.photo=Renderer(chart.space,photo_inputs,chart.response,allow_nonflat=True)

    @property
    def calls(self):return self.chart.calls+self.photo.calls

    def exact_entry(self,entry):
        chart,model,native=self.chart.exact_entry(entry)
        photo=self.photo.exact_entry(entry)[0]
        return np.concatenate((chart,photo)),model,native

    def evaluate(self,vector,**kwargs):
        chart,a=self.chart.evaluate(vector,**kwargs);photo,b=self.photo.evaluate(vector,**kwargs)
        a.update(photo_exact_corrected=b['exact_corrected'],photo_surrogate_max_rgb_difference=b['surrogate_max_rgb_difference'])
        a['surrogate_max_rgb_difference']=max(a['surrogate_max_rgb_difference'],b['surrogate_max_rgb_difference'])
        return torch.cat((chart,photo)),a


class ResearchObjective(LossObjective):
    """只改变实验损失，原验收与整数格式保持不变。"""
    def __init__(self,*args,de_factor=1.,tail_weight=.1,photo_bank=None,photo_ratio=0.,photo_cap=.25,
                 transition_budget=0.,photo_guard_budget=0.,**kwargs):
        values=(de_factor,tail_weight,photo_ratio,photo_cap,transition_budget,photo_guard_budget)
        if any(not math.isfinite(v) or v<0 for v in values) or max(photo_cap,transition_budget,photo_guard_budget)>1:
            raise ValueError('损失研究权重无效')
        frozen_reference=np.asarray(args[4] if len(args)>4 else kwargs['reference'])
        super().__init__(*args,**kwargs)
        self.de_factor,self.tail_weight=de_factor,tail_weight
        self.photo_bank,self.photo_ratio,self.photo_cap=photo_bank,photo_ratio,photo_cap
        self.photo_start=self.ntrain+len(self.bank.rgb)
        self.transition_budget=transition_budget
        self.transition=TransitionPenalty(self.bank,frozen_reference[self.ntrain:]) if transition_budget else None
        self.photo_guard_budget=photo_guard_budget
        if photo_guard_budget and photo_bank is None:raise ValueError('照片门限缺少开发采样')
        self.photo_guard=PhotoProtection(photo_bank) if photo_guard_budget else None
        self.photo_weight=0.
        if photo_ratio:
            if photo_bank is None or photo_bank.reference is None:raise ValueError('照片辅助缺少冻结参考')
            with torch.no_grad():
                vector=self.space.tensor(self.space.initial)
                _,_,stats=self.parts(self.reference,self.space.decode(vector))
                initial=photo_bank.tensor_loss(self.tools,self.tools.tensor(photo_bank.reference),self.de_weight)
                self.photo_weight=photo_ratio*stats['color_data']/max(float(initial.cpu()),1e-12)

    def parts(self,prediction,decoded):
        fitting,penalty,stats=super().parts(prediction,decoded)
        if self.de_factor!=1. or self.tail_weight!=.1:
            from stack_objective import de00_squared
            p=self.rounded(prediction[:self.ntrain])
            de=(de00_squared(self.tools,self.tools.lab(p),self.target_lab)+1e-10).sqrt()
            tail=torch.topk(de,max(1,math.ceil(.05*self.ntrain))).values.mean()
            delta=self.de_weight*((self.de_factor-1)*de.mean()+(self.de_factor*self.tail_weight-.1)*tail)
            change=float(delta.detach().cpu());fitting=fitting+delta
            stats['data']+=change;stats['color_data']+=change
        return fitting,penalty,stats

    def balanced(self,prediction,decoded,vector,scales,*,budget=.5):
        loss,stats=super().balanced(prediction,decoded,vector,scales,budget=budget)
        stats.update(photo_training_samples=0,photo_loss=0.,photo_gradient_ratio=0.,transition_loss=0.,transition_gradient_ratio=0.,
            photo_guard_loss=0.,photo_guard_gradient_ratio=0.,photo_guard_cosine=0.,photo_guard_active_regions=0,photo_guard_max_violation=0.)
        if not self.photo_ratio and not self.transition_budget and not self.photo_guard_budget:return loss,stats
        primary=torch.autograd.grad(loss,vector,retain_graph=True)[0]*scales
        norm=float(primary.detach().norm().cpu())
        if self.photo_ratio:
            raw=self.photo_weight*self.photo_bank.tensor_loss(self.tools,prediction[self.photo_start:],self.de_weight)
            grad=torch.autograd.grad(raw,vector,retain_graph=True)[0]*scales;gnorm=float(grad.detach().norm().cpu())
            weight=min(1.,balance_weight(stats['data'],float(raw.detach().cpu()),norm,gnorm,budget=self.photo_cap))
            loss=loss+weight*raw
            stats.update(photo_training_samples=len(self.photo_bank.inputs),photo_loss=weight*float(raw.detach().cpu()),
                photo_weight=self.photo_weight,photo_gradient_ratio=weight*gnorm/max(norm,1e-20))
        if self.photo_guard_budget:
            raw,guard_stats=self.photo_guard.parts(self.tools,prediction[self.photo_start:])
            grad=torch.autograd.grad(raw,vector,retain_graph=True)[0]*scales;gnorm=float(grad.detach().norm().cpu())
            weight=balance_weight(stats['data'],float(raw.detach().cpu()),norm,gnorm,budget=self.photo_guard_budget)
            cosine=float((primary.detach()@grad.detach()).cpu())/max(norm*gnorm,1e-20)
            loss=loss+weight*raw
            stats.update(guard_stats,photo_training_samples=len(self.photo_bank.inputs),photo_guard_loss=weight*float(raw.detach().cpu()),
                photo_guard_gradient_ratio=weight*gnorm/max(norm,1e-20),photo_guard_cosine=cosine)
        if self.transition_budget:
            raw=self.transition.tensor_loss(self.tools,prediction[self.ntrain:self.photo_start])
            grad=torch.autograd.grad(raw,vector,retain_graph=True)[0]*scales;gnorm=float(grad.detach().norm().cpu())
            weight=balance_weight(stats['data'],float(raw.detach().cpu()),norm,gnorm,budget=self.transition_budget)
            loss=loss+weight*raw
            stats.update(transition_loss=weight*float(raw.detach().cpu()),transition_gradient_ratio=weight*gnorm/max(norm,1e-20),
                synthetic_transition_penalty_enabled=True)
        return loss,stats
