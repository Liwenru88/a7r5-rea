"""原配方起步的C/D平衡训练；冻结验收，保持原BIN和历史实验。"""
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
from benchmark_native_four import digest,save,blob,predict,combined_metrics,screening,ramp_stats,photo_summary
from native_guard_policy import (POLICY as GUARD_POLICY,ReviewedObjective,TargetToneBank,build_calibration,
    quality_failures as reviewed_quality,multiscale_report,transition_review,photo_failures,decision)


from native_solver import (load_frozen_scales,training_score,screening_reviewed,repair_candidates,
    make_optimizer,save_research_checkpoint,train)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for key in ('bin','manifest','output'):parser.add_argument('--'+key,type=Path,required=True)
    parser.add_argument('--previous',type=Path)
    parser.add_argument('--normalization',type=Path,help='复用相同原配方起点的normalization.json，冻结敏感度尺度')
    parser.add_argument('--steps',type=int,default=2000)
    parser.add_argument('--checkpoint',type=int,default=50)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--arms',nargs='+',choices=('C','D'),default=['C','D'],
        help='选择本次实验方案；默认保持C/D对照，--arms C只运行直接参数拟合')
    parser.add_argument('--pilot',action='store_true')
    parser.add_argument('--protection-policy',choices=('reviewed','legacy'),default='reviewed',
        help='reviewed使用分级新规则；legacy复现上一轮零退步规则')
    args=parser.parse_args()
    args.arms=list(dict.fromkeys(args.arms))
    if args.steps<1 or args.checkpoint<1:raise ValueError('训练预算必须为正')
    if not torch.backends.mps.is_available():raise RuntimeError('MPS不可用，不退回CPU训练')
    args.output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads(args.manifest.read_text());frozen=args.manifest.parent
    protected={str(args.bin):digest(args.bin),str(args.manifest):digest(args.manifest)}
    def load(row):
        path=frozen/row['file']
        if digest(path)!=row['sha256']:raise ValueError('冻结输入摘要变化')
        protected[str(path)]=digest(path)
        with np.load(path,allow_pickle=False) as data:return {key:data[key] for key in data.files}
    chart=load(manifest['chart'])
    for key in ('input','split'):
        if hashlib.sha256(chart[key].tobytes()).hexdigest()!=manifest['chart'][key+'_sha256']:raise ValueError('色卡输入/划分不符')
    original=core.compiler.unpack(args.bin.read_bytes())
    if core.compiler.pack(original)!=args.bin.read_bytes():raise ValueError('原库回读变化')
    source=next(e for e in original['entries'] if e['number']==5)
    (args.output/'preserved-full-library.BIN').write_bytes(args.bin.read_bytes())
    (args.output/'preserved-recipe.BIN').write_bytes(blob(source))
    context=ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID)),native_gamma=True)
    response=__import__('grid_models').default_response()
    train_mask=chart['split']=='train';valid=chart['split']=='valid';test=chart['split']=='test'
    gray=(chart['anchor_index']>=4)&(chart['anchor_index']<260)
    if gray.sum()!=256 or not np.all(train_mask[gray]):raise ValueError('灰阶划分变化')
    target=chart['target_5'];banks={phase:RampBank(phase) for phase in (.17,.53,.87)}
    inputs=np.concatenate((chart['input'][train_mask],banks[.17].inputs(context.base)))
    full_reference=predict(context,source,inputs,response)
    n=int(train_mask.sum());gray_train=np.flatnonzero(gray[train_mask])
    train_reference=dict(metrics=combined_metrics(full_reference[:n],target[train_mask],full_reference[:n][gray_train],target[gray]),
        jumps=banks[.17].jumps(phase_rgb(full_reference[n:])))
    gray_base=predict(context,source,chart['input'][gray],response)
    valid_base=predict(context,source,chart['input'][valid],response)
    ramp_valid=predict(context,source,banks[.53].inputs(context.base),response)
    reference=dict(metrics=combined_metrics(valid_base,target[valid],gray_base,target[gray]),jumps=banks[.53].jumps(phase_rgb(ramp_valid)),rgb=ramp_valid)
    dev=[];development=[]
    for scene in manifest['scenes']:
        if scene['role']=='development':
            d=load(scene);old=predict(context,source,d['inputs'],response)
            dev.append((scene['scene'],old,d['target_5']));development.append((scene['scene'],old,d['target_5'],d['display']))
    margins=calibrate(banks[.17],full_reference[n:],dev);save(args.output/'frozen-margins.json',margins)
    args.guard_calibration=None;tone_bank=None
    if args.protection_policy=='reviewed':
        args.guard_calibration=build_calibration(full_reference[:n],target[train_mask],gray[train_mask],development)
        tone_bank=TargetToneBank(chart['design_srgb'][train_mask],target[train_mask],chart['split'][train_mask],
            chart['sample_kind'][train_mask],full_reference[:n])
        save(args.output/'guard-calibration.json',args.guard_calibration)
    report=dict(policy=POLICY,filter=source['full_name'],steps=args.steps,pilot=args.pilot,seed=args.seed,
        original_bin_sha256=digest(args.bin),response=response,validation_baseline=reference['metrics'],
        starting_gamma_max_change=0,camera_connected=False,production_changed=False,
        optimizer=dict(lr=.003,min_lr=.00006,trust=.25,max_normalized_step=.003,constraint_value_and_gradient_budget=.5),
        repair_alphas=REPAIR_ALPHAS,counts={part:int((chart['split']==part).sum()) for part in ('train','valid','test')},
        heldout_caveat='沿用历史研究集，不是全新盲测。',torch=torch.__version__,arms=[])
    report['protection_policy']=GUARD_POLICY if args.protection_policy=='reviewed' else 'legacy-zero-regression'
    report['protection_mode']=args.protection_policy
    report['requested_arms']=args.arms
    if args.guard_calibration is not None:report['guard_calibration']=args.guard_calibration
    if args.previous:
        previous=json.loads(args.previous.read_text())
        if previous['original_bin_sha256']!=report['original_bin_sha256']:raise ValueError('历史对照原库不同')
        protected[str(args.previous)]=digest(args.previous)
        report['previous']={key:previous[key] for key in ('test_baseline','arms')}
    paths=[ROOT/'web'/name for name in ('native_feasible_experiment.py','native_four_experiment.py','apple_gpu.py','core.py','calibrated_guard.py','parameter_smoothing.py','native_scoring.py')]
    paths +=[Path(__file__),ROOT/'scripts/benchmark_native_four.py',ROOT/'scripts/native_gamma.py']
    paths.append(ROOT/'web/native_guard_policy.py')
    report['source_sha256']={str(path.relative_to(ROOT)):digest(path) for path in paths}
    for path in paths:
        snapshot=args.output/'source-snapshot'/path.relative_to(ROOT)
        snapshot.parent.mkdir(parents=True,exist_ok=True)
        snapshot.write_bytes(path.read_bytes())
    save(args.output/'protocol.json',report)
    proposals={};scales=None
    for arm in args.arms:
        print('ARM_START',arm,flush=True)
        space=OriginalSpace(context,source,device='mps');renderer=FlatRenderer(space,inputs,response)
        if not np.array_equal(renderer.exact_entry(source)[0],full_reference):raise ValueError('五像素加速与完整参考不同')
        report['flat_acceleration_full_batch_exact']=True
        if scales is None:
            if args.normalization:
                scales,normalization=load_frozen_scales(args.normalization,space.initial)
                protected[str(args.normalization)]=normalization['sha256']
                report['frozen_normalization']=normalization
                save(args.output/'protocol.json',report)
            else:scales,normalization=sensitivity_scales(space,renderer,seed=args.seed)
        objective_args=(space,target[train_mask],gray[train_mask],banks[.17],full_reference)
        if args.guard_calibration is not None:
            objective=ReviewedObjective(*objective_args,new_loss=True,response=response,margins=margins,
                calibration=args.guard_calibration,tone_bank=tone_bank)
        else:objective=BalancedObjective(*objective_args,new_loss=True,response=response,margins=margins)
        v=space.tensor(space.initial).requires_grad_(True)
        initial,_=renderer.evaluate(v)
        _,penalty,stats=objective.parts(initial,space.decode(v))
        if float(penalty.detach().cpu())>1e-8:raise ValueError('原配方起点训练惩罚不为零')
        if args.guard_calibration is not None:
            screen=lambda entry:screening_reviewed(context,entry,chart['input'][valid],target[valid],chart['input'][gray],target[gray],
                banks[.53],response,reference,args.guard_calibration)
        else:
            screen=lambda entry:screening(context,entry,chart['input'][valid],target[valid],chart['input'][gray],target[gray],
                banks[.53],response,reference,margins)
        entry,row=train(arm,space,renderer,objective,scales,screen,train_reference,margins,args)
        proposals[arm]=entry;row.update(normalization=normalization,initial_penalty=float(penalty.detach().cpu()),initial_bin_sha256=hashlib.sha256(blob(source)).hexdigest())
        report['arms'].append(row);save(args.output/'progress.json',report)
        del renderer,objective,space,initial,penalty,v
        torch.mps.empty_cache()
    if not args.pilot:
        baseline_test=combined_metrics(predict(context,source,chart['input'][test],response),target[test],gray_base,target[gray])
        original_final=predict(context,source,banks[.87].inputs(context.base),response)
        final_jumps=banks[.87].jumps(phase_rgb(original_final))
        report['test_baseline']=baseline_test;report['transition_baseline']=ramp_stats(final_jumps)
        photos=[(scene,load(scene)) for scene in manifest['scenes']]
        before={s['scene']:predict(context,source,d['inputs'],response) for s,d in photos}
        from PIL import Image,ImageDraw
        from native_scoring import color_metrics
        for row in report['arms']:
            arm=row['arm'];entry=proposals[arm]
            metrics=combined_metrics(predict(context,entry,chart['input'][test],response),target[test],
                predict(context,entry,chart['input'][gray],response),target[gray])
            candidate_final=predict(context,entry,banks[.87].inputs(context.base),response)
            jumps=banks[.87].jumps(phase_rgb(candidate_final))
            legacy_failures=metric_failures(metrics,baseline_test)+transition_failures(final_jumps,jumps,margins)
            reviews=[];new_reports={}
            if args.guard_calibration is not None:
                failures=reviewed_quality(metrics,baseline_test,args.guard_calibration['chart'])
                original_probes={.17:full_reference[n:],.53:ramp_valid,.87:original_final}
                for phase,bank in banks.items():
                    rendered=candidate_final if phase==.87 else predict(context,entry,bank.inputs(context.base),response)
                    new_reports[str(phase)]=multiscale_report(bank,original_probes[phase],rendered)
                reviews=transition_review(new_reports)
            else:failures=legacy_failures.copy()
            rows=[]
            for scene,data in photos:
                after=predict(context,entry,data['inputs'],response);old=before[scene['scene']]
                photo_errors=[];regions=None
                if args.guard_calibration is not None:
                    photo_errors,regions=photo_failures(old,after,data['target_5'],data['display'],args.guard_calibration['photo'])
                    failures += [f"photo:{scene['scene']}:{reason}" for reason in photo_errors]
                rows.append(dict(scene=scene['scene'],role=scene['role'],baseline=color_metrics(old,data['target_5']),
                    candidate=color_metrics(after,data['target_5']),region_checks=regions,failures=photo_errors))
                if scene['role']=='holdout':
                    tiles=[np.floor(np.clip(x,0,1)*255+.5).astype('uint8')[data['display']] for x in (data['target_5'],old,after)]
                    h,w=tiles[0].shape[:2];image=Image.new('RGB',(3*w,h+25),'white');draw=ImageDraw.Draw(image)
                    for i,(tile,label) in enumerate(zip(tiles,('Target','Preserved','New '+arm))):
                        image.paste(Image.fromarray(tile),(i*w,25));draw.text((i*w+5,5),label,fill='black')
                    image.save(args.output/arm/(scene['scene']+'.png'))
            summary={role:{key:photo_summary(rows,role,key) for key in ('baseline','candidate')} for role in ('development','holdout')}
            holdout=summary['holdout']
            for key in ('rgb_rmse','delta_e00_mean'):
                if holdout['candidate'][key]>=holdout['baseline'][key]-1e-10:failures.append('photo_holdout:'+key)
            p95_margin=args.guard_calibration['photo']['whole']['delta_e00_p95'] if args.guard_calibration is not None else 0.
            if holdout['candidate']['delta_e00_p95']>holdout['baseline']['delta_e00_p95']+p95_margin+1e-10:failures.append('photo_holdout:delta_e00_p95')
            if not row['qualified_on_validation']:failures.append('validation_failed')
            status=decision(failures,reviews)
            row.update(test=metrics,transitions=ramp_stats(jumps),transition_diagnostics=ramp_report(final_jumps,jumps,margins)[0],
                final_failures=failures,review_reasons=reviews,status=status,adopted=status=='eligible_offline',photos=rows,photo_summary=summary,
                legacy_diagnostic_failures=legacy_failures,reviewed_transition_diagnostics=new_reports)
            (args.output/arm/'accepted.BIN').write_bytes(blob(entry if row['adopted'] else source))
    if any(digest(path)!=sha for path,sha in protected.items()):raise ValueError('保护输入摘要变化')
    if any(digest(ROOT/path)!=sha for path,sha in report['source_sha256'].items()):raise ValueError('训练时源码变化')
    report.update(protected_inputs=protected,protected_inputs_unchanged=True)
    save(args.output/'result.json',report)
    lines=['# 原配方可行起点C/D对照','','MPS整批训练；每步CPU整数参考校正。原BIN及历史实验保留，未连接相机。','',
        '| 配方 | RGB RMSE | 平均ΔE00 | P95 | 灰阶RMSE | 采用 |','|---|---:|---:|---:|---:|---|']
    if not args.pilot:
        m=report['test_baseline'];lines.append('| 原配方 | '+' | '.join(f'{m[k]:.6f}' for k in ('rgb_rmse','delta_e00_mean','delta_e00_p95','gray_rmse'))+' | 保留 |')
    for row in report['arms']:
        m=row.get('test',row['selected']['metrics']);lines.append('| '+row['arm']+' | '+' | '.join(f'{m[k]:.6f}' for k in ('rgb_rmse','delta_e00_mean','delta_e00_p95','gray_rmse'))+f" | {'是' if row.get('adopted') else '否'} |")
    lines+=['','候选仅按训练/验证筛选；锁定后才复验测试集和留出照片，不据最终结果重选。',
        '失败时accepted.BIN回退原单槽配方；proposal.BIN保留实验候选，均未合并正式库。','',
        f"保护规则：{report['protection_policy']}。需复核状态不自动采用；旧规则结果另行保留。全部分数使用回读BIN和固定Hybrid响应，不能代替实机结论。"]
    (args.output/'实验报告.md').write_text('\n'.join(lines)+'\n')
    print('DONE',str(args.output/'result.json'),flush=True)


if __name__=='__main__':main()
