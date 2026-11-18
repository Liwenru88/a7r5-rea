"""单款四组GPU整批离线对照；输出到新目录，不修改输入或工作台。"""
import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
import platform
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
from fit_bin_joint import grid_from
from grid_models import default_response
from measured_response import get
from native_four_experiment import ARM_SPECS,POLICY,Space,FourHeads,Renderer,Objective,sensitivity_scales,metric_failures,transition_failures
from native_scoring import color_metrics


from native_runtime import digest,save,blob,predict,combined_metrics

def ramp_stats(jumps):
    return {axis:dict(p95=float(np.percentile(value,95)),max=float(value.max())) for axis,value in jumps.items()}


def screening(context,entry,valid_inputs,valid_target,gray_inputs,gray_target,bank,response,reference,margins):
    inputs=np.concatenate((valid_inputs,gray_inputs,bank.inputs(context.base)))
    output=predict(context,entry,inputs,response)
    a,b=np.split(output,(len(valid_inputs),len(valid_inputs)+len(gray_inputs)))[:2]
    metrics=combined_metrics(a,valid_target,b,gray_target)
    jumps=bank.jumps(phase_rgb(output[len(valid_inputs)+len(gray_inputs):]))
    failures=metric_failures(metrics,reference['metrics'])+transition_failures(reference['jumps'],jumps,margins)
    score=metrics['rgb_rmse']/reference['metrics']['rgb_rmse']+metrics['delta_e00_mean']/reference['metrics']['delta_e00_mean']
    return dict(metrics=metrics,transitions=ramp_stats(jumps),failures=failures,score=score)


def train_arm(arm,space,renderer,objective,scales,steps,checkpoint,output,screen,seed):
    spec=ARM_SPECS[arm]
    output.mkdir()
    initial=space.tensor(space.initial);scale=space.tensor(scales)
    if spec['neural']:
        model=FourHeads(device='mps',seed=seed)
        parameters=list(model.parameters())
        delta=model
    else:
        model=None
        offset=torch.nn.Parameter(torch.zeros_like(initial))
        parameters=[offset]
        delta=lambda:offset
    optimizer=torch.optim.Adam(parameters,lr=.015)
    scheduler=torch.optim.lr_scheduler.CosineAnnealingLR(optimizer,T_max=max(1,steps),eta_min=.0003)
    save(output/'normalization.json',dict(scales=scales.tolist(),initial=space.initial.tolist(),spec=spec))
    (output/'initial.BIN').write_bytes(blob(space.entry(initial)))
    best_any=None;best_pass=None;pool=[];start=time.monotonic();best_loss=float('inf')

    def record(step):
        nonlocal best_any,best_pass
        with torch.no_grad():
            vector=initial+scale*delta()
            entry=space.entry(vector)
        row=dict(step=step,**screen(entry))
        pool.append(row)
        targets=[]
        if best_any is None or row['score']<best_any[0]['score']:
            best_any=(row,entry);targets.append('best-color')
        if not row['failures'] and (best_pass is None or row['score']<best_pass[0]['score']):
            best_pass=(row,entry);targets.append('best-qualified')
        state=dict(step=step,optimizer=optimizer.state_dict(),scheduler=scheduler.state_dict(),
            vector=vector.detach().cpu(),model=model.state_dict() if model else None,
            offset=offset.detach().cpu() if model is None else None,
            multipliers=objective.multipliers.detach().cpu())
        torch.save(state,output/'latest.pt')
        for name in targets:
            (output/(name+'.BIN')).write_bytes(blob(entry))
            save(output/(name+'.json'),row)
            torch.save(state,output/(name+'.pt'))
        save(output/'candidate-pool.json',pool)
        print(json.dumps(dict(event='checkpoint',arm=arm,seconds=round(time.monotonic()-start,2),**row)),flush=True)

    record(0)
    with (output/'loss.jsonl').open('w') as log:
        for step in range(1,steps+1):
            optimizer.zero_grad(set_to_none=True)
            vector=initial+scale*delta()
            prediction,audit=renderer.evaluate(vector,corrected=spec['corrected'],dynamic=spec['corrected'])
            decoded=space.decode(vector,quantized=spec['corrected'])
            loss,stats=objective(prediction,decoded)
            if not torch.isfinite(loss):raise ValueError(f'{arm}第{step}步损失无效')
            loss.backward()
            if any(p.grad is not None and not torch.isfinite(p.grad).all() for p in parameters):
                raise ValueError(f'{arm}第{step}步梯度无效')
            norm=float(torch.nn.utils.clip_grad_norm_(parameters,10.).detach().cpu())
            value=float(loss.detach().cpu());best_loss=min(best_loss,value)
            optimizer.step();scheduler.step()
            if step%25==0:objective.adapt()
            log.write(json.dumps(dict(step=step,loss=value,best_loss=best_loss,lr=scheduler.get_last_lr()[0],
                gradient_norm=norm,seconds=time.monotonic()-start,**stats,**audit),allow_nan=False)+'\n')
            if step%checkpoint==0 or step==steps:
                log.flush();record(step)
    selected=best_pass or best_any
    row,entry=selected
    proposal=blob(entry)
    (output/'proposal.BIN').write_bytes(proposal)
    save(output/'proposal.json',entry)
    result=dict(arm=arm,spec=spec,selected=row,qualified_on_validation=best_pass is not None,
        proposal_sha256=hashlib.sha256(proposal).hexdigest(),steps=steps,seed=seed,full_batch=len(objective.target),
        training_probe_samples=len(objective.bank.rgb),seconds=time.monotonic()-start,
        integer_reference_calls=renderer.calls,parameters=sum(p.numel() for p in parameters),
        final_neural_delta_norm=float(model.neural_delta().detach().norm().cpu()) if model else None,
        device='mps',dtype='float32',budget='相同更新步数；精确CPU整数校正耗时另计')
    save(output/'locked.json',result)
    return entry,result


def photo_summary(rows,role,key):
    return {metric:float(np.mean([row[key][metric] for row in rows if row['role']==role]))
        for metric in ('rgb_rmse','delta_e00_mean','delta_e00_p95')}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('bin','manifest','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--steps',type=int,default=2000)
    parser.add_argument('--checkpoint',type=int,default=50)
    parser.add_argument('--seed',type=int,default=42)
    parser.add_argument('--pilot',action='store_true',help='只跑训练/验证，不读测试及留出照片')
    args=parser.parse_args()
    if args.steps<1 or args.checkpoint<1:raise ValueError('训练预算必须为正')
    if not torch.backends.mps.is_available():raise RuntimeError('GPU不可用；不自动退回CPU训练')
    args.output.mkdir(parents=True,exist_ok=False)
    manifest=json.loads(args.manifest.read_text());frozen=args.manifest.parent
    protected={str(args.bin):digest(args.bin),str(args.manifest):digest(args.manifest)}
    def load(row):
        path=frozen/row['file']
        if digest(path)!=row['sha256']:raise ValueError('冻结输入校验失败：'+str(path))
        protected[str(path)]=digest(path)
        with np.load(path,allow_pickle=False) as data:return {key:data[key] for key in data.files}
    chart=load(manifest['chart'])
    if hashlib.sha256(chart['input'].tobytes()).hexdigest()!=manifest['chart']['input_sha256']:
        raise ValueError('色卡输入摘要不符')
    if hashlib.sha256(chart['split'].tobytes()).hexdigest()!=manifest['chart']['split_sha256']:
        raise ValueError('留出集划分摘要不符')
    original=core.compiler.unpack(args.bin.read_bytes())
    if core.compiler.pack(original)!=args.bin.read_bytes():raise ValueError('原始BIN不能逐字节回读')
    source=next(e for e in original['entries'] if e['number']==5)
    save(args.output/'preserved-full-config.json',original)
    (args.output/'preserved-full-library.BIN').write_bytes(args.bin.read_bytes())
    (args.output/'preserved-recipe.BIN').write_bytes(blob(source))
    context=ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID)),native_gamma=True)
    response=default_response()
    seed=copy.deepcopy(source)
    for _ in range(4):
        space=Space(context,seed,kind='concave')
        candidate=space.entry(space.tensor(space.initial))
        if blob(candidate)==blob(seed):break
        seed=candidate
    else:raise ValueError('共同起点不能收敛到稳定编码')
    (args.output/'common-seed.BIN').write_bytes(blob(seed))
    train=chart['split']=='train';valid=chart['split']=='valid';test=chart['split']=='test'
    gray=(chart['anchor_index']>=4)&(chart['anchor_index']<260)
    if not gray.any() or not np.all(train[gray]):raise ValueError('灰阶不在训练集')
    if not np.array_equal(np.unique(chart['split']),['test','train','valid']):raise ValueError('划分无效')
    target=chart['target_5'];gray_target=target[gray]
    banks={phase:RampBank(phase) for phase in (.17,.53,.87)}
    reference_train=predict(context,source,np.concatenate((chart['input'][train],banks[.17].inputs(context.base))),response)
    before_valid=predict(context,source,chart['input'][valid],response)
    before_gray=predict(context,source,chart['input'][gray],response)
    baseline_metrics=combined_metrics(before_valid,target[valid],before_gray,gray_target)
    base_ramps={p:predict(context,source,b.inputs(context.base),response) for p,b in banks.items() if p!=.87}
    dev=[]
    for scene in manifest['scenes']:
        if scene['role']=='development':
            data=load(scene);dev.append((scene['scene'],predict(context,source,data['inputs'],response),data['target_5']))
    margins=calibrate(banks[.17],base_ramps[.17],dev)
    save(args.output/'frozen-margins.json',margins)
    reference=dict(metrics=baseline_metrics,jumps=banks[.53].jumps(phase_rgb(base_ramps[.53])))
    report=dict(policy=POLICY,filter=source['full_name'],camera_connected=False,production_changed=False,
        original_bin_sha256=digest(args.bin),response=response,steps=args.steps,pilot=args.pilot,
        counts={part:int((chart['split']==part).sum()) for part in ('train','valid','test')},
        starting_gamma_max_change=int(np.max(np.abs(np.array(seed['gamma_native_129'])-source['gamma_native_129']))),
        scope='A是共同整批联合框架中复现现有机制，不是正式多起点全流程重跑；B/C/D为逐项消融。',
        validation_baseline=baseline_metrics,python=sys.version,torch=torch.__version__,numpy=np.__version__,
        platform=platform.platform(),seed=args.seed,heldout_caveat='沿用历史研究集，不是全新盲测。',arms=[])
    sources=[ROOT/'web'/name for name in ('native_four_experiment.py','apple_gpu.py','native_rounding.py',
        'core.py','native_scoring.py','calibrated_guard.py','stack_objective.py','parameter_smoothing.py')]
    sources +=[Path(__file__),ROOT/'scripts/native_gamma.py']
    report['source_sha256']={str(path.relative_to(ROOT)):digest(path) for path in sources}
    save(args.output/'protocol.json',report)
    proposals={};common_hash=hashlib.sha256(blob(seed)).hexdigest();mono_scales=None
    for arm,spec in ARM_SPECS.items():
        print('ARM_START',arm,flush=True)
        space=Space(context,seed,kind=spec['kind'])
        if hashlib.sha256(blob(space.entry(space.tensor(space.initial)))).hexdigest()!=common_hash:
            raise ValueError('四组实际BIN起点不同')
        inputs=np.concatenate((chart['input'][train],banks[.17].inputs(context.base)))
        renderer=Renderer(space,inputs,response)
        if spec['normalized']:
            if arm=='D':scales=mono_scales.copy();normalization=dict(reused_from='C')
            else:scales,normalization=sensitivity_scales(space,renderer,seed=args.seed)
            if arm=='C':mono_scales=scales.copy()
        else:scales=space.legacy_scales;normalization=dict(policy='legacy fixed scales')
        objective=Objective(space,target[train],gray[train],banks[.17],reference_train,
            new_loss=spec['new_loss'],response=response,margins=margins)
        screen=lambda entry:screening(context,entry,chart['input'][valid],target[valid],chart['input'][gray],gray_target,
            banks[.53],response,reference,margins)
        proposal,row=train_arm(arm,space,renderer,objective,scales,args.steps,args.checkpoint,args.output/arm,screen,args.seed)
        row['normalization']=normalization;row['initial_bin_sha256']=common_hash
        report['arms'].append(row);proposals[arm]=proposal
        save(args.output/'progress.json',report)
        del renderer,objective,space
        torch.mps.empty_cache()
    # 所有候选锁定之后才访问测试目标和留出照片；不根据最终结果重新选候选。
    if not args.pilot:
        before_test=predict(context,source,chart['input'][test],response)
        baseline_test=combined_metrics(before_test,target[test],before_gray,gray_target)
        base_final=predict(context,source,banks[.87].inputs(context.base),response)
        final_jumps=banks[.87].jumps(phase_rgb(base_final))
        report['test_baseline']=baseline_test
        report['transition_baseline']=ramp_stats(final_jumps)
        photo_data=[(scene,load(scene)) for scene in manifest['scenes']]
        photo_before={s['scene']:predict(context,source,d['inputs'],response) for s,d in photo_data}
        from PIL import Image,ImageDraw
        for row in report['arms']:
            arm=row['arm'];entry=proposals[arm]
            out=predict(context,entry,chart['input'][test],response)
            gray_out=predict(context,entry,chart['input'][gray],response)
            metrics=combined_metrics(out,target[test],gray_out,gray_target)
            jumps=banks[.87].jumps(phase_rgb(predict(context,entry,banks[.87].inputs(context.base),response)))
            failures=metric_failures(metrics,baseline_test)+transition_failures(final_jumps,jumps,margins)
            photos=[]
            for scene,data in photo_data:
                after=predict(context,entry,data['inputs'],response)
                before=photo_before[scene['scene']]
                photos.append(dict(scene=scene['scene'],role=scene['role'],
                    baseline=color_metrics(before,data['target_5']),candidate=color_metrics(after,data['target_5'])))
                if scene['role']=='holdout':
                    display=data['display'];tiles=[]
                    for pixels in (data['target_5'],before,after):
                        tiles.append(np.floor(np.clip(pixels,0,1)*255+.5).astype('uint8')[display])
                    h,w=tiles[0].shape[:2];image=Image.new('RGB',(w*3,h+25),'white');draw=ImageDraw.Draw(image)
                    for i,(pixels,label) in enumerate(zip(tiles,('Target','Preserved','Arm '+arm))):
                        image.paste(Image.fromarray(pixels),(w*i,25));draw.text((w*i+5,5),label,fill='black')
                    image.save(args.output/arm/(scene['scene']+'.png'))
            summary={role:{key:photo_summary(photos,role,key) for key in ('baseline','candidate')} for role in ('development','holdout')}
            holdout=summary['holdout']
            for key in ('rgb_rmse','delta_e00_mean'):
                if holdout['candidate'][key]>=holdout['baseline'][key]-1e-10:failures.append('photo_holdout:'+key)
            if holdout['candidate']['delta_e00_p95']>holdout['baseline']['delta_e00_p95']+1e-10:
                failures.append('photo_holdout:delta_e00_p95')
            if not row['qualified_on_validation']:failures.append('validation_failed')
            row.update(test=metrics,transitions=ramp_stats(jumps),transition_diagnostics=ramp_report(final_jumps,jumps,margins)[0],
                final_failures=failures,adopted=not failures,photos=photos,photo_summary=summary)
            accepted=entry if not failures else source
            accepted_blob=blob(accepted);(args.output/arm/'accepted.BIN').write_bytes(accepted_blob)
            row['accepted_sha256']=hashlib.sha256(accepted_blob).hexdigest()
    if any(digest(path)!=sha for path,sha in protected.items()):raise ValueError('保护输入摘要发生变化')
    if any(digest(ROOT/path)!=sha for path,sha in report['source_sha256'].items()):raise ValueError('训练期间源码变化')
    report['protected_inputs']=protected;report['protected_inputs_unchanged']=True
    save(args.output/'result.json',report)
    lines=['# 暖金日光四组离线实验','',report['scope'],'',
        '训练/反向传播使用 MPS 整批；B/C/D 每步由 CPU 同参数整数前向校正数值，GPU 代理提供梯度。',
        '原配方、原完整库均保留；BIN v5、129点 Gamma、CC1、16色相矩阵、5×9×9网格布局不变。',
        f"共同起点 Gamma 相对原配方最大变化 {report['starting_gamma_max_change']} 个17位刻度。",'',
        '验收严格要求 RGB RMSE 与平均ΔE00均降低，灰阶、颜色P95及双域各轴P95/最大值不升；另保留局部异常保护。',
        '候选只按验证集选择。测试/照片失败后回退原配方，不重新选择候选。照片使用冻结曝光对齐的历史缓存，不代表机内结果。','',
        '| 配方 | RGB RMSE | 平均 ΔE00 | P95 | 灰阶 RMSE | 采用 |','|---|---:|---:|---:|---:|---|']
    if not args.pilot:
        b=report['test_baseline'];lines.append(f"| 原配方 | {b['rgb_rmse']:.4f} | {b['delta_e00_mean']:.4f} | {b['delta_e00_p95']:.4f} | {b['gray_rmse']:.4f} | 保留 |")
    for row in report['arms']:
        m=row.get('test',row['selected']['metrics'])
        lines.append(f"| {row['arm']} | {m['rgb_rmse']:.4f} | {m['delta_e00_mean']:.4f} | {m['delta_e00_p95']:.4f} | {m['gray_rmse']:.4f} | {'是' if row.get('adopted') else '否'} |")
    lines+=['','## 保护与耗时','']
    for row in report['arms']:
        lines.append(f"- {row['arm']}：{row['seconds']/60:.2f}分钟，选择第{row['selected']['step']}步；拒绝项："+', '.join(row.get('final_failures',row['selected']['failures'])))
    lines+=['','proposal.BIN为未必通过验收的实验候选；accepted.BIN在失败时为原配方。均为单槽离线审计产物，未合并或替换正式库。',
        '四组是逐项机制对照，C同时变更损失与Gamma约束，不能单独归因于某一项；D保留独立参数残差，神经头仅作结构先验。',
        '本实验只验证一款滤镜，不能据此认定通用算法在其他滤镜上更好。未连接相机。']
    (args.output/'实验报告.md').write_text('\n'.join(lines)+'\n')
    print('DONE',str(args.output/'result.json'),flush=True)


if __name__=='__main__':main()
