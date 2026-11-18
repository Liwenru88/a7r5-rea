"""研究与工作台共享的归一化原生联合求解；冻结验收，保持原BIN。"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import sys
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'web'),str(ROOT/'scripts')]
import numpy as np
import torch
import baseline
import core
from calibrated_guard import RampBank,calibrate,phase_rgb,ramp_report
from edit_parameter_context import ParameterContext,RuntimeColor
from native_four_experiment import FourHeads,sensitivity_scales,metric_failures,transition_failures
from native_feasible_experiment import POLICY,REPAIR_ALPHAS,OriginalSpace,FlatRenderer,BalancedObjective,blend_entry
from native_runtime import digest,save,blob,predict,combined_metrics
from native_guard_policy import (POLICY as GUARD_POLICY,ReviewedObjective,TargetToneBank,build_calibration,
    quality_failures as reviewed_quality,multiscale_report,transition_review,photo_failures,decision)


def load_frozen_scales(path,initial):
    """相同起点复用已有尺度，避免分次GPU估计引入额外对照差异。"""
    data=path.read_bytes();value=json.loads(data)
    start=np.asarray(value.get('initial',[]),float)
    scales=np.asarray(value.get('scales',[]),float)
    if start.shape!=(1448,) or not np.isfinite(start).all() or not np.array_equal(start,initial):
        raise ValueError('冻结归一化起点与当前原配方不同')
    if scales.shape!=(1448,) or not np.isfinite(scales).all() or np.any(scales<=0):
        raise ValueError('冻结归一化尺度必须为1448个正有限数')
    return scales,dict(method='frozen',file=str(path),sha256=hashlib.sha256(data).hexdigest())


def training_score(renderer,entry,objective,bank,reference,margins,*,guard_calibration=None):
    rgb=renderer.exact_entry(entry)[0];n=objective.ntrain
    gray=objective.gray.detach().cpu().numpy()
    target=objective.target.detach().cpu().numpy()
    metrics=combined_metrics(rgb[:n],target,rgb[:n][gray],target[gray])
    if guard_calibration is not None:
        return dict(metrics=metrics,failures=reviewed_quality(metrics,reference['metrics'],guard_calibration['chart'],require_improvement=False),
            synthetic_transition_mode='diagnostic_only')
    jumps=bank.jumps(phase_rgb(rgb[n:]))
    failures=metric_failures(metrics,reference['metrics'])
    # 可行性允许颜色持平；严格改善仍由验证与最终验收单独要求。
    failures=[key for key in failures if key not in ('rgb_rmse','delta_e00_mean')]
    failures += [key for key in ('rgb_rmse','delta_e00_mean') if metrics[key]>reference['metrics'][key]+1e-10]
    failures += transition_failures(reference['jumps'],jumps,margins)
    return dict(metrics=metrics,failures=failures)


def screening_reviewed(context,entry,valid_inputs,valid_target,gray_inputs,gray_target,bank,response,reference,calibration):
    output=predict(context,entry,np.concatenate((valid_inputs,gray_inputs,bank.inputs(context.base))),response)
    n=len(valid_inputs);g=len(gray_inputs)
    metrics=combined_metrics(output[:n],valid_target,output[n:n+g],gray_target)
    report=multiscale_report(bank,reference['rgb'],output[n+g:])
    failures=reviewed_quality(metrics,reference['metrics'],calibration['chart'])
    reviews=transition_review({'valid':report})
    score=metrics['rgb_rmse']/reference['metrics']['rgb_rmse']+metrics['delta_e00_mean']/reference['metrics']['delta_e00_mean']
    return dict(metrics=metrics,failures=failures,review_reasons=reviews,validation_status=decision(failures,reviews),
        transitions=report,score=score,qualification_scope='numeric_quality; transition_review_separate')


def repair_candidates(source,entry,evaluate):
    raw=evaluate(entry)
    repaired=[]
    if not raw['failures']:repaired.append((entry,1.,raw))
    seen={blob(entry),blob(source)}
    for alpha in REPAIR_ALPHAS:
        candidate=blend_entry(source,entry,alpha);data=blob(candidate)
        if data in seen:continue
        seen.add(data);row=evaluate(candidate)
        if not row['failures']:repaired.append((candidate,alpha,row))
    return repaired or [(copy.deepcopy(source),0.,evaluate(source))],raw


def make_optimizer(parameters,*,steps,lr=.003,min_lr=.00006,schedule_steps=None):
    """短试验可沿用完整训练的调度跨度，默认行为与历史入口一致。"""
    horizon=steps if schedule_steps is None else schedule_steps
    if type(steps) is not int or steps<1 or type(horizon) is not int or horizon<steps:
        raise ValueError('学习率调度跨度必须覆盖全部更新步数')
    if not all(math.isfinite(x) for x in (lr,min_lr)) or not 0<=min_lr<=lr or lr<=0:
        raise ValueError('学习率必须有限且满足0<=min_lr<=lr、lr>0')
    optimizer=torch.optim.Adam(parameters,lr=lr)
    return optimizer,torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,T_max=horizon,eta_min=min_lr)


def save_research_checkpoint(folder,step,state,entry):
    """按需保留各步原始BIN，供独立质量筛选复算。"""
    checkpoint=folder/'checkpoints';checkpoint.mkdir(exist_ok=True)
    path=checkpoint/f'{step:06d}.BIN';path.write_bytes(blob(entry))
    torch.save(state,path.with_suffix('.pt'))


def train(arm,space,renderer,objective,scales,screen,train_reference,margins,args):
    folder=args.output/arm;folder.mkdir()
    seed=space.tensor(space.initial);scale=space.tensor(scales)
    model=FourHeads(device='mps',seed=args.seed) if arm=='D' else None
    if model:model.train()
    offset=torch.nn.Parameter(torch.zeros_like(seed)) if model is None else None
    parameters=list(model.parameters()) if model else [offset]
    radius=None
    if getattr(args,'research_radius',False):
        if model is not None:raise ValueError('自适应搜索半径仅用于C离线研究')
        from native_search_radius import SearchRadius
        radius=SearchRadius(seed,adaptive=getattr(args,'adaptive_radius',False),
            confirmations=getattr(args,'radius_confirmations',1))
    if getattr(args,'start_vector',None) is not None:
        if offset is None:raise ValueError('研究检查点起步仅支持C')
        normalized=(space.tensor(args.start_vector)-seed)/scale
        if not bool((normalized.abs()<.25).all()):raise ValueError('研究起点超出初始半径')
        with torch.no_grad():offset.copy_(.25*torch.atanh(normalized/.25))
    def delta():
        return radius.delta(offset) if radius is not None else .25*torch.tanh((model() if model else offset)/.25)
    optimizer,scheduler=make_optimizer(parameters,steps=args.steps,lr=getattr(args,'lr',.003),
        min_lr=getattr(args,'min_lr',.00006),schedule_steps=getattr(args,'schedule_steps',None))
    initial=space.entry(seed+scale*delta())
    expected=getattr(args,'start_bin',None) or blob(space.seed)
    if blob(initial)!=expected:raise ValueError('起点不是指定配方字节')
    (folder/'initial.BIN').write_bytes(blob(initial))
    save(folder/'normalization.json',dict(initial=space.initial.tolist(),scales=scales.tolist()))
    pool=[];best=None;qualified=None;start=time.monotonic();best_loss=float('inf')
    progress=getattr(args,'progress',None)
    def evaluate_training(entry):
        return training_score(renderer,entry,objective,objective.bank,train_reference,margins,
            guard_calibration=getattr(args,'guard_calibration',None))
    if evaluate_training(initial)['failures'] and not getattr(args,'allow_infeasible_seed',False):
        raise ValueError('原配方训练可行性检查失败')
    step_guard=getattr(args,'step_guard',None)
    if step_guard is not None:
        if model is not None:raise ValueError('步后整数过渡检查仅用于C离线研究')
        if step_guard(initial)['failures']:raise ValueError('指定起点未通过步后过渡基准')
    radius_score=evaluate_training(initial)['metrics'] if radius is not None else None
    def fit_score(metrics):
        return metrics['rgb_rmse']/train_reference['metrics']['rgb_rmse']+metrics['delta_e00_mean']/train_reference['metrics']['delta_e00_mean']

    def record(step):
        nonlocal best,qualified
        with torch.no_grad():vector=seed+scale*delta();raw=space.entry(vector)
        repaired,raw_train=repair_candidates(space.seed,raw,evaluate_training)
        state=dict(step=step,vector=vector.detach().cpu(),model=model.state_dict() if model else None,
            offset=offset.detach().cpu() if offset is not None else None,optimizer=optimizer.state_dict(),scheduler=scheduler.state_dict())
        if radius is not None:
            state['trust_radius']=radius.values.detach().cpu()
            state['radius_pending']=radius.pending.copy()
        if getattr(args,'retain_checkpoints',False):save_research_checkpoint(folder,step,state,raw)
        candidates=[('raw',raw,1.,raw_train)]
        candidates += [('train-repaired',entry,alpha,train_row) for entry,alpha,train_row in repaired if blob(entry)!=blob(raw)]
        for kind,entry,fraction,train_metrics in candidates:
            row=dict(step=step,kind=kind,alpha=fraction,training=train_metrics,**screen(entry))
            row['failures'] += ['training:'+key for key in train_metrics['failures']]
            pool.append(row)
            names=[]
            if best is None or row['score']<best[0]['score']:best=(row,entry);names.append('best-color')
            if not row['failures'] and (qualified is None or row['score']<qualified[0]['score']):
                qualified=(row,entry);names.append('best-qualified')
            for name in names:
                (folder/(name+'.BIN')).write_bytes(blob(entry));save(folder/(name+'.json'),row)
                torch.save(dict(state,selected=row),folder/(name+'.pt'))
        torch.save(state,folder/'latest.pt')
        (folder/'latest-raw.BIN').write_bytes(blob(raw))
        save(folder/'candidate-pool.json',pool)
        selected=qualified[0] if qualified else best[0]
        selected_summary={key:selected[key] for key in ('step','kind','alpha','metrics')}
        selected_summary.update(failure_count=len(selected['failures']),review_reasons=selected.get('review_reasons',[]))
        print(json.dumps(dict(event='checkpoint',arm=arm,step=step,seconds=time.monotonic()-start,
            raw_rgb=raw_train['metrics']['rgb_rmse'],repair_alphas=[x[1] for x in repaired],
            selected=selected_summary),ensure_ascii=False),flush=True)
    record(0)
    with (folder/'loss.jsonl').open('w') as log:
        for step in range(1,args.steps+1):
            optimizer.zero_grad(set_to_none=True)
            before=delta().detach();vector=seed+scale*delta()
            prediction,audit=renderer.evaluate(vector,corrected=True,dynamic=True)
            loss,stats=objective.balanced(prediction,space.decode(vector),vector,scale,budget=.5)
            if not torch.isfinite(loss):raise ValueError('平衡损失无效')
            loss.backward()
            if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in parameters):raise ValueError('平衡梯度无效')
            norm=float(torch.nn.utils.clip_grad_norm_(parameters,10.).detach().cpu())
            with torch.no_grad():old=[p.clone() for p in parameters]
            optimizer_before=copy.deepcopy(optimizer.state_dict()) if step_guard is not None else None
            optimizer.step()
            with torch.no_grad():
                proposed=[p.clone() for p in parameters];fraction=1.
                for _ in range(8):
                    distance=float((delta()-before).abs().max().cpu())
                    if distance<=.0030001:break
                    fraction*=min(.5,.003/max(distance,1e-20))
                    for parameter,a,b in zip(parameters,old,proposed):parameter.copy_(a+fraction*(b-a))
                else:
                    for parameter,a in zip(parameters,old):parameter.copy_(a)
                    fraction=0.;distance=0.
            guarded=None
            if step_guard is not None:
                from native_step_guard import backtrack_update
                with torch.no_grad():
                    guarded=backtrack_update(parameters,old,optimizer,optimizer_before,
                        lambda:step_guard(space.entry(seed+scale*delta())))
                    distance=float((delta()-before).abs().max().cpu())
                fraction*=guarded['fraction']
            scheduler.step()
            expansions=[];expansion_rejected=False
            if radius is not None and step%50==0:
                with torch.no_grad():
                    radius_entry=space.entry(seed+scale*delta());radius_row=evaluate_training(radius_entry)
                    minimum=getattr(args,'radius_min_relative_improvement',0.)
                    old_radius=radius.values.clone();old_offset=offset.clone();old_pending=radius.pending.copy()
                    old_optimizer=copy.deepcopy(optimizer.state_dict())
                    expansions=radius.expand(offset,optimizer,
                        feasible=not radius_row['failures'] and (guarded is None or guarded['accepted']),
                        improved=fit_score(radius_row['metrics'])<fit_score(radius_score)*(1-minimum)-1e-8)
                    if expansions and blob(space.entry(seed+scale*delta()))!=blob(radius_entry):
                        radius.values.copy_(old_radius);offset.copy_(old_offset);radius.pending=old_pending
                        optimizer.load_state_dict(old_optimizer);expansions=[];expansion_rejected=True
                    if radius.confirmations==1 or expansions:radius_score=radius_row['metrics']
            log.write(json.dumps(dict(step=step,loss=float(loss.detach().cpu()),lr=scheduler.get_last_lr()[0],
                gradient_norm=norm,applied_fraction=fraction,normalized_max_step=distance,
                radius_expansions=expansions,radius_expansion_rejected=expansion_rejected,step_guard=guarded,
                seconds=time.monotonic()-start,**stats,**audit),allow_nan=False)+'\n')
            best_loss=min(best_loss,float(loss.detach().cpu()))
            if progress is not None and (step==1 or step%10==0 or step==args.steps):
                progress(stage='原生四组联合拟合',iteration=step,evaluations=step,max_evaluations=args.steps,
                    state='running',gpu_backend='Apple Metal/MPS',
                    loss_sample=('MPS 原生整数前向联合 Adam',step,float(loss.detach().cpu()),best_loss))
            if step%args.checkpoint==0 or step==args.steps:log.flush();record(step)
    selected,entry=qualified or best
    (folder/'proposal.BIN').write_bytes(blob(entry));save(folder/'proposal.json',entry)
    row=dict(arm=arm,selected=selected,qualified_on_validation=qualified is not None,steps=args.steps,
        seconds=time.monotonic()-start,device='mps',dtype='float32',full_batch=objective.ntrain,
        probe_samples=len(objective.bank.rgb),integer_reference_calls=renderer.calls,
        proposal_sha256=digest(folder/'proposal.BIN'),final_neural_delta_norm=float(model.neural_delta().detach().norm().cpu()) if model else None)
    save(folder/'locked.json',row)
    return entry,row

