"""保护规则第二版：合法性硬门槛、量化容差、真实目标渐变与分级复核。"""
from collections import defaultdict
from itertools import product
import hashlib

import numpy as np

from calibrated_guard import phase_rgb
from integer_grid import PROBE_AXES
from native_scoring import color_metrics
from perceptual import to_lab,de2000

POLICY='native-quantization-target-review/1'
STRIDES=(1,2,4)
AUDIT_PHASES=np.random.default_rng(713).uniform(-.499,.499,(12,3))


def finite_rgb(rgb):
    values=np.asarray(rgb,float)
    if values.ndim!=2 or values.shape[1]!=3 or not len(values) or not np.isfinite(values).all():
        raise ValueError('保护规则需要非空有限RGB')
    if values.min() < -1e-10 or values.max()>1+1e-10:raise ValueError('RGB超出0–1')
    return np.clip(values,0,1)


def quantization_box(rgb,target=None):
    """小于半码值的舍入扰动只能落在每通道floor/ceil的8个离散角点。"""
    rgb=finite_rgb(rgb);low=np.floor(rgb*255);high=np.ceil(rgb*255)
    lab_low=np.full_like(rgb,np.inf);lab_high=np.full_like(rgb,-np.inf)
    upper_de=np.zeros(len(rgb))
    target_lab=to_lab(phase_rgb(finite_rgb(target))*255) if target is not None else None
    for bits in product((0,1),repeat=3):
        pixels=np.where(np.asarray(bits),high,low)
        lab=to_lab(pixels)
        lab_low=np.minimum(lab_low,lab);lab_high=np.maximum(lab_high,lab)
        if target_lab is not None:upper_de=np.maximum(upper_de,de2000(lab,target_lab))
    return dict(rgb_low=low,rgb_high=high,lab_low=lab_low,lab_high=lab_high,upper_de=upper_de)


def quality_envelope(reference,target):
    reference,target=finite_rgb(reference),finite_rgb(target)
    if reference.shape!=target.shape:raise ValueError('量化校准需要对齐的参考与目标')
    box=quantization_box(reference,target);fixed=phase_rgb(target)*255
    worst=np.maximum((box['rgb_low']-fixed)**2,(box['rgb_high']-fixed)**2)
    baseline=color_metrics(reference,target)
    upper=dict(rgb_rmse=float(np.sqrt(worst.mean())),delta_e00_mean=float(box['upper_de'].mean()),
        delta_e00_p95=float(np.percentile(box['upper_de'],95)))
    margins={key:max(0.,upper[key]-baseline[key]) for key in upper}
    audited=[]
    for phase in AUDIT_PHASES:
        metrics=color_metrics(phase_rgb(reference,phase),target)
        audited.append(all(metrics[key]<=upper[key]+1e-9 for key in upper))
    if not all(audited):raise ValueError('量化区间未覆盖独立舍入扰动')
    return dict(baseline=baseline,upper=upper,margins=margins,
        audit_cases=len(audited),audit_passed=True,
        interpretation='舍入不确定性上界，不是人眼可见阈值')


def quality_failures(candidate,reference,margins,*,require_improvement=True):
    names=('rgb_rmse','delta_e00_mean','delta_e00_p95','gray_rmse')
    if any(not np.isfinite(reference.get(key,np.nan)) for key in names):raise ValueError('基准指标无效')
    if any(not np.isfinite(candidate.get(key,np.nan)) for key in names):return ['nonfinite_or_missing_metrics']
    if any(not np.isfinite(margins.get(key,np.nan)) or margins[key]<0 for key in names[2:]):raise ValueError('校准容差无效')
    failures=[]
    for key in names[:2]:
        bad=candidate[key]>=reference[key]-1e-10 if require_improvement else candidate[key]>reference[key]+1e-10
        if bad:failures.append(key)
    failures += [key for key in names[2:] if candidate[key]>reference[key]+margins[key]+1e-10]
    return failures


def decision(hard_failures,review_reasons):
    return 'rejected' if hard_failures else 'review_required' if review_reasons else 'eligible_offline'


def _curvature(lab,stride):
    return lab[:,2*stride:]-2*lab[:,stride:-stride]+lab[:,:-2*stride]


def _stats(values):
    return dict(p95=float(np.percentile(values,95)),max=float(values.max()))


def multiscale_report(bank,reference,candidate):
    reference,candidate=finite_rgb(reference),finite_rgb(candidate)
    if reference.shape!=candidate.shape or len(reference)!=len(bank.rgb):raise ValueError('渐变输出形状不符')
    box=quantization_box(reference)
    ref_lab=to_lab(reference*255);new_lab=to_lab(candidate*255)
    ref8=to_lab(phase_rgb(reference)*255);new8=to_lab(phase_rgb(candidate)*255)
    axes={};exceedances=[]
    for axis in PROBE_AXES:
        span,shape=bank.span(axis)
        def lines(value):return value[span].reshape(*shape,3)[...,1:]
        lo,hi=lines(box['lab_low']),lines(box['lab_high'])
        axes[axis]={}
        for stride in STRIDES:
            base_c=_curvature(lines(ref_lab),stride);new_c=_curvature(lines(new_lab),stride)
            base_norm=np.linalg.norm(base_c,axis=-1);new_norm=np.linalg.norm(new_c,axis=-1)
            # 区间传播覆盖三个位置所有允许的量化组合，不截断为固定0.5/0.75。
            lower=lo[:,2*stride:]-2*hi[:,stride:-stride]+lo[:,:-2*stride]
            upper=hi[:,2*stride:]-2*lo[:,stride:-stride]+hi[:,:-2*stride]
            error=np.linalg.norm(np.maximum(np.abs(lower-base_c),np.abs(upper-base_c)),axis=-1)
            upper_stats=_stats(base_norm+error);lower_stats=_stats(np.maximum(base_norm-error,0))
            original=_stats(base_norm);newer=_stats(new_norm)
            noise={key:max(upper_stats[key]-original[key],original[key]-lower_stats[key]) for key in original}
            flags=[key for key in original if newer[key]>original[key]+noise[key]+1e-9]
            for key in flags:exceedances.append(dict(axis=axis,stride=stride,stat=key,
                increase=newer[key]-original[key],quantization_bound=noise[key]))
            axes[axis][str(stride)]=dict(baseline_float=original,candidate_float=newer,
                baseline_quantized=_stats(np.linalg.norm(_curvature(lines(ref8),stride),axis=-1)),
                candidate_quantized=_stats(np.linalg.norm(_curvature(lines(new8),stride),axis=-1)),
                quantization_upper=upper_stats,quantization_lower=lower_stats,noise=noise,flags=flags)
    return dict(input_sha256=bank.sha256,axes=axes,exceedances=exceedances,
        interpretation='超界是复核线索，不直接等同可见断层')


def transition_review(reports):
    reasons=[]
    for axis in PROBE_AXES:
        by_phase={name:{row['stride'] for row in report['exceedances'] if row['axis']==axis}
                  for name,report in reports.items()}
        persistent=sum(len(scales)>=2 for scales in by_phase.values())>=2
        isolated_large=any(row['axis']==axis and row['increase']>2*max(row['quantization_bound'],1e-9)
                           for report in reports.values() for row in report['exceedances'])
        if persistent or isolated_large:reasons.append('unconfirmed_transition:'+axis)
    return reasons


def dense_probe_inputs(bank,axis,line,model,*,factor=64):
    """在HSV定义的同一路径重新生成高密度输入，不插值模型输出冒充验证图。"""
    import colorsys
    from types import SimpleNamespace
    from output_continuity import ProbeBank
    span,shape=bank.span(axis)
    design=bank.rgb[span].reshape(*shape,3)[line]
    hsv=np.asarray([colorsys.rgb_to_hsv(*rgb) for rgb in design])
    coordinate=np.arange(len(design));dense=np.linspace(0,len(design)-1,(len(design)-1)*factor+1)
    hue=np.unwrap(hsv[:,0]*2*np.pi)/(2*np.pi)
    if axis.removeprefix('native-')=='hue':
        new_hsv=np.column_stack((np.interp(dense,coordinate,hue)%1,np.full(len(dense),hsv[0,1]),np.full(len(dense),hsv[0,2])))
    else:
        new_hsv=np.column_stack((np.full(len(dense),hsv[0,0]),np.interp(dense,coordinate,hsv[:,1]),np.interp(dense,coordinate,hsv[:,2])))
    rgb=np.asarray([colorsys.hsv_to_rgb(*point) for point in new_hsv])
    if not np.allclose(rgb[::factor],design,atol=1e-12,rtol=0):raise ValueError('高密度路径偏离原探针')
    if axis.startswith('native-'):inputs=np.repeat(np.rint(rgb*16383).astype('<u2')[:,None],9,axis=1)
    else:
        container=SimpleNamespace(rgb=np.tile(rgb,(2,1)),domain_size=len(rgb))
        inputs=ProbeBank.inputs(container,model)[:len(rgb)]
    return rgb,inputs


class TargetToneBank:
    """只使用实测TRAIN明暗射线，跟随目标转折；不伪造原生域色相/饱和度目标。"""
    def __init__(self,design,target,split,kind,reference):
        design,target,reference=map(finite_rgb,(design,target,reference))
        split,kind=np.asarray(split).astype(str),np.asarray(kind).astype(str)
        if target.shape!=design.shape or reference.shape!=design.shape or split.shape!=(len(design),) or kind.shape!=split.shape:
            raise ValueError('实测目标渐变形状不符')
        groups=defaultdict(list)
        for index in np.flatnonzero((split=='train')&(kind=='hue24_tonal')):
            high=design[index].max()
            if high>0:groups[tuple(np.round(design[index]/high,12))].append(int(index))
        if len(groups)!=24:raise ValueError('目标渐变需要24条真实TRAIN射线')
        rows=[]
        for key in sorted(groups):
            at=np.array(groups[key]);at=at[np.argsort(design[at].max(axis=1))]
            if len(at)<9 or np.any(np.diff(design[at].max(axis=1))<=0):raise ValueError('目标射线采样无效')
            rows.append(at)
        if len({len(row) for row in rows})!=1:raise ValueError('目标射线长度不同')
        self.indices=np.stack(rows);self.x=design[self.indices].max(axis=-1)
        self.target_lab=to_lab(target[self.indices]*255)
        base_lab=to_lab(reference[self.indices]*255)
        self.scales={}
        for stride in STRIDES:
            t=self.features(self.target_lab,stride);b=self.features(base_lab,stride)
            self.scales[stride]=tuple(max(float(np.sqrt(np.mean(a*a))),float(np.sqrt(np.mean((c-a)**2))),1.) for a,c in zip(t,b))
        self.source_sha256=hashlib.sha256(self.indices.tobytes()+target[self.indices].tobytes()).hexdigest()

    def features(self,lab,stride):
        first=(lab[:,stride:]-lab[:,:-stride])/(self.x[:,stride:]-self.x[:,:-stride])[...,None]
        left=(lab[:,stride:-stride]-lab[:,:-2*stride])/(self.x[:,stride:-stride]-self.x[:,:-2*stride])[...,None]
        right=(lab[:,2*stride:]-lab[:,stride:-stride])/(self.x[:,2*stride:]-self.x[:,stride:-stride])[...,None]
        second=2*(right-left)/(self.x[:,2*stride:]-self.x[:,:-2*stride])[...,None]
        return first,second

    def report(self,prediction):
        lab=to_lab(finite_rgb(prediction)[self.indices]*255);rows={}
        for stride in STRIDES:
            errors=[(a-b)/scale for a,b,scale in zip(self.features(lab,stride),self.features(self.target_lab,stride),self.scales[stride])]
            rows[str(stride)]=dict(slope_rmse=float(np.sqrt(np.mean(errors[0]**2))),curvature_rmse=float(np.sqrt(np.mean(errors[1]**2))))
        return dict(scales=rows,rays=24,samples=int(self.indices.size),training_only=True,
            missing_synthetic_target_domains=list(PROBE_AXES),target_sha256=self.source_sha256)

    def tensor_loss(self,tools,prediction):
        t=tools.torch
        lab=tools.lab(prediction[tools.tensor(self.indices,True)].reshape(-1,3)).reshape(*self.indices.shape,3)
        target=tools.tensor(self.target_lab);x=tools.tensor(self.x)
        loss=prediction.new_zeros(())
        for stride in STRIDES:
            dx=(x[:,stride:]-x[:,:-stride])[...,None]
            first=(lab[:,stride:]-lab[:,:-stride])/dx
            desired=(target[:,stride:]-target[:,:-stride])/dx
            left=(lab[:,stride:-stride]-lab[:,:-2*stride])/(x[:,stride:-stride]-x[:,:-2*stride])[...,None]
            right=(lab[:,2*stride:]-lab[:,stride:-stride])/(x[:,2*stride:]-x[:,stride:-stride])[...,None]
            dl=(target[:,stride:-stride]-target[:,:-2*stride])/(x[:,stride:-stride]-x[:,:-2*stride])[...,None]
            dr=(target[:,2*stride:]-target[:,stride:-stride])/(x[:,2*stride:]-x[:,stride:-stride])[...,None]
            error=2*((right-left)-(dr-dl))/(x[:,2*stride:]-x[:,:-2*stride])[...,None]
            a,b=self.scales[stride]
            loss=loss+((first-desired)/a).square().mean()+(error/b).square().mean()
        return loss/(2*len(STRIDES))


def photo_regions(display):
    display=np.asarray(display)
    if display.ndim!=2 or display.dtype.kind not in 'iu':raise ValueError('照片区域索引无效')
    regions={'whole':np.unique(display)}
    for y,ys in enumerate(np.array_split(display,3,axis=0)):
        for x,tile in enumerate(np.array_split(ys,3,axis=1)):
            if tile.size:regions[f'tile-{y}-{x}']=np.unique(tile)
    return regions


def build_calibration(reference,target,gray,development):
    reference,target=finite_rgb(reference),finite_rgb(target);gray=np.asarray(gray,bool)
    if gray.shape!=(len(reference),) or not gray.any():raise ValueError('灰阶校准样本无效')
    full=quality_envelope(reference,target);gray_bounds=quality_envelope(reference[gray],target[gray])
    photo_margins={kind:dict.fromkeys(('rgb_rmse','delta_e00_mean','delta_e00_p95'),0.) for kind in ('whole','tile')}
    audits=[]
    for scene,prediction,expected,display in development:
        for region,indices in photo_regions(display).items():
            bounds=quality_envelope(prediction[indices],expected[indices])
            limits=photo_margins['whole' if region=='whole' else 'tile']
            for key in limits:limits[key]=max(limits[key],bounds['margins'][key])
            audits.append(dict(scene=scene,region=region,**bounds))
    if not audits:raise ValueError('照片保护需要独立开发照片校准')
    return dict(policy=POLICY,chart=dict(gray_rmse=gray_bounds['margins']['rgb_rmse'],delta_e00_p95=full['margins']['delta_e00_p95']),
        photo=photo_margins,chart_audit=full,gray_audit=gray_bounds,photo_audits=audits,
        caps_applied=False,perceptual_threshold_validated=False,
        scope='仅TRAIN与开发照片确定容差；测试集不用于调参')


def photo_failures(reference,candidate,target,display,margins):
    failures=[];rows={}
    for region,indices in photo_regions(display).items():
        base=color_metrics(reference[indices],target[indices]);new=color_metrics(candidate[indices],target[indices])
        rows[region]=dict(baseline=base,candidate=new)
        limits=margins['whole' if region=='whole' else 'tile']
        failures += [region+':'+key for key in limits if new[key]>base[key]+limits[key]+1e-10]
    return failures,rows


def legality_failures(data):
    import core
    try:
        config=core.compiler.unpack(data)
        if len(config['entries'])!=1:raise ValueError('单款候选必须恰有一个槽位')
        if core.compiler.pack(config)!=data:raise ValueError('BIN回读变化')
    except (ValueError,TypeError,OverflowError,KeyError) as error:
        return ['bin_invalid:'+str(error)]
    return []


from native_feasible_experiment import BalancedObjective


class ReviewedObjective(BalancedObjective):
    """过渡拟合跟随实测目标；未知目标的合成探针不作旧形状惩罚。"""
    def __init__(self,*args,calibration,tone_bank,**kwargs):
        super().__init__(*args,**kwargs)
        self.calibration,self.tone_bank=calibration,tone_bank
        import torch
        from stack_objective import de00_squared
        with torch.no_grad():
            rgb=self.rounded(self.reference[:self.ntrain])
            de=(de00_squared(self.tools,self.tools.lab(rgb),self.target_lab)+1e-10).sqrt()
            tail=torch.topk(de,max(1,int(np.ceil(.05*self.ntrain)))).values.mean()
            base_data=(rgb-self.target8).square().mean()+self.de_weight*(de.mean()+.1*tail)
            derivative=tone_bank.tensor_loss(self.tools,self.reference[:self.ntrain])
            self.tone_weight=.1*float(base_data.cpu())/max(float(derivative.cpu()),.01)
        self.guard_gray=calibration['gray_audit']['baseline']['rgb_rmse']+calibration['chart']['gray_rmse']
        self.guard_p95=calibration['chart_audit']['baseline']['delta_e00_p95']+calibration['chart']['delta_e00_p95']

    def parts(self,prediction,decoded):
        import torch
        from stack_objective import de00_squared
        from parameter_smoothing import native_rows_tensor
        from native_gamma import EDIT_AXIS
        from native_four_experiment import quantile95
        p=self.rounded(prediction[:self.ntrain])
        mse=(p-self.target8).square().mean()
        de=(de00_squared(self.tools,self.tools.lab(p),self.target_lab)+1e-10).sqrt()
        tail=torch.topk(de,max(1,int(np.ceil(.05*self.ntrain)))).values.mean()
        color=mse+self.de_weight*(de.mean()+.1*tail)
        tone=self.tone_weight*self.tone_bank.tensor_loss(self.tools,prediction[:self.ntrain])
        gray=(p[self.gray]-self.target8[self.gray]).square().mean().sqrt()*255
        violations=torch.stack(((gray-self.guard_gray).clamp(min=0)/max(self.calibration['chart']['gray_rmse'],1e-6),
            (quantile95(de)-self.guard_p95).clamp(min=0)/max(self.calibration['chart']['delta_e00_p95'],1e-6)))
        penalty=(violations+.5*violations.square()).mean()
        grid=decoded['grid'].flatten();regularization=.007*(grid@(self.gram@grid))
        rows=native_rows_tensor(self.tools,decoded['matrix']/1024,decoded['gamma']*16,EDIT_AXIS,30,
            cc1=decoded['vector'][:8],config=self.config)
        regularization=regularization+rows.square().sum()
        data=color+tone
        stats=dict(data=float(data.detach().cpu()),color_data=float(color.detach().cpu()),
            target_gradient_loss=float(tone.detach().cpu()),target_gradient_weight=self.tone_weight,
            raw_penalty=float(penalty.detach().cpu()),regularization=float(regularization.detach().cpu()),
            training_samples=self.ntrain,rgb_rmse=float(mse.detach().sqrt().cpu())*255,
            delta_e00_mean=float(de.mean().detach().cpu()),gray_rmse=float(gray.detach().cpu()),
            max_violation=float(violations.max().detach().cpu()),violations=violations.detach().cpu().tolist(),
            synthetic_transition_penalty_enabled=False)
        return data+regularization,penalty,stats
