"""固定200步C方案损失/学习率筛查；不使用TEST和留出照片挑选，不更改正式库。"""
import argparse
import json
from pathlib import Path
import sys
from types import SimpleNamespace

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'web'),str(ROOT/'scripts')]
import numpy as np
import torch
import baseline,core
from benchmark_native_feasible import train,load_frozen_scales,screening_reviewed
from benchmark_native_four import blob,digest,save,predict,combined_metrics,ramp_stats
from calibrated_guard import RampBank,calibrate,phase_rgb
from edit_parameter_context import ParameterContext,RuntimeColor
from grid_models import default_response
from native_feasible_experiment import OriginalSpace,FlatRenderer
from native_guard_policy import (ReviewedObjective,TargetToneBank,build_calibration,photo_failures,
    legality_failures,multiscale_report,transition_review)
from native_loss_experiment import LossObjective
from native_objective_research import PhotoBank,PhotoProtection,MixedRenderer,ResearchObjective
from native_scoring import color_metrics


def study_plan(study):
    """固定实验矩阵，避免观察结果后切换损失或补选学习率。"""
    if study=='photo_guard':
        configs=[('photo05_control',dict(photo_ratio=.05)),('guard25',dict(photo_guard_budget=.25)),
            ('photo05_guard10',dict(photo_ratio=.05,photo_guard_budget=.1)),
            ('photo05_guard25',dict(photo_ratio=.05,photo_guard_budget=.25))]
        return dict(loss_trials=[],fixed_trials=[dict(name=name,tone_ratio=.1,cap=.2,lr=.003,research=values)
            for name,values in configs],selection='四组照片区域门限对照，接受此前小幅色卡误差取舍；仍按原VALID锁定并报告照片、灰阶、P95和双域过渡，不自动采用')
    if study=='objective_plus':
        configs=[('research_control',{}),('de_half',dict(de_factor=.5)),('de_double',dict(de_factor=2.)),
            ('transition10',dict(transition_budget=.1)),('photo05',dict(photo_ratio=.05)),
            ('photo20',dict(photo_ratio=.2)),('photo10_transition10',dict(photo_ratio=.1,transition_budget=.1))]
        return dict(loss_trials=[],fixed_trials=[dict(name=name,tone_ratio=.1,cap=.2,lr=.003,research=values)
            for name,values in configs],selection='七组预先固定的损失方法/权重对照，按同一VALID规则锁定并报告开发照片和三相位过渡，不自动采用')
    if study=='cap_lr':
        return dict(loss_trials=[],fixed_trials=[dict(name=name,tone_ratio=.1,cap=.2,lr=lr)
            for name,lr in (('cap_lr_0015',.0015),('cap_lr_003',.003),('cap_lr_006',.006))],
            selection='固定20%渐变梯度限幅，三档学习率各自从原配方训练200步；锁定后报告开发区域与三相位双域过渡，不自动采用')
    if study=='loss_lr':
        return dict(loss_trials=[dict(name='control',tone_ratio=.1,cap=None),dict(name='tone_off',tone_ratio=0.,cap=None),
            dict(name='tone_002',tone_ratio=.02,cap=None),dict(name='tone_cap02',tone_ratio=.1,cap=.2)],fixed_trials=[],
            selection='loss阶段仅依VALID数值合格候选的原综合评分选择；开发照片报告退步，不放宽阈值；再比较该损失的三档学习率')
    raise ValueError('未知损失研究模式')


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    for name in ('bin','manifest','normalization','output'):parser.add_argument('--'+name,type=Path,required=True)
    parser.add_argument('--study',choices=('loss_lr','cap_lr','objective_plus','photo_guard'),default='loss_lr')
    parser.add_argument('--arm',choices=('C','D'),default='C',help='C直接优化坐标，D使用四个神经参数头')
    args=parser.parse_args()
    if args.study in ('objective_plus','photo_guard') and args.arm!='C':raise ValueError('本轮扩展损失研究限定C方案')
    if not torch.backends.mps.is_available():raise RuntimeError('MPS不可用，不回退CPU训练')
    args.output.mkdir(parents=True,exist_ok=True);(args.output/'trials').mkdir()
    protected={str(path):digest(path) for path in (args.bin,args.manifest,args.normalization)}
    manifest=json.loads(args.manifest.read_text());frozen=args.manifest.parent
    def load(record):
        path=frozen/record['file'];actual=digest(path)
        if actual!=record['sha256']:raise ValueError('冻结数据摘要变化')
        protected[str(path)]=actual
        with np.load(path,allow_pickle=False) as archive:return {key:archive[key] for key in archive.files}
    chart=load(manifest['chart']);train_mask=chart['split']=='train';valid=chart['split']=='valid'
    for key in ('input','split'):
        import hashlib
        if hashlib.sha256(chart[key].tobytes()).hexdigest()!=manifest['chart'][key+'_sha256']:raise ValueError('输入/划分变化')
    config=core.compiler.unpack(args.bin.read_bytes())
    if core.compiler.pack(config)!=args.bin.read_bytes():raise ValueError('原库回读变化')
    source=next(entry for entry in config['entries'] if entry['number']==5)
    (args.output/'preserved-full-library.BIN').write_bytes(args.bin.read_bytes())
    (args.output/'preserved-recipe.BIN').write_bytes(blob(source))
    (args.output/'normalization.json').write_bytes(args.normalization.read_bytes())
    context=ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID)),native_gamma=True)
    response=default_response();banks={phase:RampBank(phase) for phase in (.17,.53)}
    gray=(chart['anchor_index']>=4)&(chart['anchor_index']<260)
    if gray.sum()!=256 or not np.all(train_mask[gray]):raise ValueError('灰阶划分变化')
    target=chart['target_5'];n=int(train_mask.sum())
    inputs=np.concatenate((chart['input'][train_mask],banks[.17].inputs(context.base)))
    reference=predict(context,source,inputs,response)
    training=dict(metrics=combined_metrics(reference[:n],target[train_mask],reference[:n][gray[train_mask]],target[gray]),
        jumps=banks[.17].jumps(phase_rgb(reference[n:])))
    gray_base=predict(context,source,chart['input'][gray],response)
    valid_base=predict(context,source,chart['input'][valid],response)
    ramp_valid=predict(context,source,banks[.53].inputs(context.base),response)
    validation=dict(metrics=combined_metrics(valid_base,target[valid],gray_base,target[gray]),rgb=ramp_valid)
    base_ramps={.17:reference[n:],.53:ramp_valid}
    development=[];photo_data=[]
    for scene in manifest['scenes']:
        if scene['role']!='development':continue
        data=load(scene);old=predict(context,source,data['inputs'],response)
        development.append((scene['scene'],old,data['target_5'],data['display']));photo_data.append((scene,data,old))
    margins=calibrate(banks[.17],reference[n:],[(s,p,t) for s,p,t,_ in development])
    calibration=build_calibration(reference[:n],target[train_mask],gray[train_mask],development)
    tone=TargetToneBank(chart['design_srgb'][train_mask],target[train_mask],chart['split'][train_mask],chart['sample_kind'][train_mask],reference[:n])
    photo_bank=None
    if args.study in ('objective_plus','photo_guard'):
        photo_bank=PhotoBank([dict(scene=s['scene'],role=s['role'],inputs=x['inputs'],target=x['target_5'],display=x['display'])
            for s,x,_ in photo_data],per_region=64,seed=42)
        photo_bank.reference=predict(context,source,photo_bank.inputs,response)
        np.savez_compressed(args.output/'photo-training-bank.npz',inputs=photo_bank.inputs,target=photo_bank.target,reference=photo_bank.reference)
        save(args.output/'photo-training-indices.json',photo_bank.groups)
        for name in ('photo-training-bank.npz','photo-training-indices.json'):
            protected[str(args.output/name)]=digest(args.output/name)
        if args.study=='photo_guard':
            save(args.output/'photo-guard-calibration.json',PhotoProtection(photo_bank).calibration)
            protected[str(args.output/'photo-guard-calibration.json')]=digest(args.output/'photo-guard-calibration.json')
    protocol=dict(policy='native-loss-lr-200-screen/1',filter=source['full_name'],steps=200,schedule_steps=2000,
        seed=42,device='mps',dtype='float32',full_batch=n,checkpoint=50,response=response,
        counts=dict(train=n,valid=int(valid.sum())),guard_calibration=calibration,validation_baseline=validation['metrics'],
        original_bin_sha256=digest(args.bin),normalization_sha256=digest(args.normalization),
        learning_rates=[.0015,.003,.006],min_lr_fraction=.02,
        study=args.study,arm=args.arm,**study_plan(args.study),
        test_evaluated=False,holdout_photos_evaluated=False,adopted=False,camera_connected=False,production_changed=False)
    if photo_bank is not None:
        protocol.update(development_photos_used_for_auxiliary_training=True,photo_training_samples=len(photo_bank.inputs),
            photo_training_regions=len(photo_bank.groups),photo_samples_per_region=photo_bank.per_region,
            development_caveat='开发照片结果含辅助训练样本，只作开发诊断；四张留出照片未参与')
    save(args.output/'protocol.json',protocol)
    rows=[];scales=None;normalization=None;sources={}
    def run(name,ratio,cap,lr,research=None):
        nonlocal scales,normalization,sources
        folder=args.output/'trials'/name;folder.mkdir()
        space=OriginalSpace(context,source,device='mps');renderer=FlatRenderer(space,inputs,response)
        if not np.array_equal(renderer.exact_entry(source)[0],reference):raise ValueError('平坦加速与原生参考不同')
        if scales is None:scales,normalization=load_frozen_scales(args.normalization,space.initial)
        kwargs=dict(new_loss=True,response=response,margins=margins,calibration=calibration,tone_bank=tone)
        objective=(ReviewedObjective(space,target[train_mask],gray[train_mask],banks[.17],reference,**kwargs)
                   if name=='control' else LossObjective(space,target[train_mask],gray[train_mask],banks[.17],reference,
                       **kwargs,tone_ratio=ratio,tone_gradient_cap=cap))
        if research is not None:
            objective=ResearchObjective(space,target[train_mask],gray[train_mask],banks[.17],reference,**kwargs,
                tone_ratio=ratio,tone_gradient_cap=cap,photo_bank=photo_bank,**research)
            if research.get('photo_ratio',0) or research.get('photo_guard_budget',0):renderer=MixedRenderer(renderer,photo_bank.inputs)
        if not sources:
            for module in list(sys.modules.values()):
                filename=getattr(module,'__file__',None)
                if not filename:continue
                path=Path(filename).resolve()
                try:relative=path.relative_to(ROOT)
                except ValueError:continue
                if path.suffix=='.py' and relative.parts[0] in ('web','scripts','compilers'):
                    sources[str(relative)]=digest(path)
                    copy=args.output/'source-snapshot'/relative;copy.parent.mkdir(parents=True,exist_ok=True);copy.write_bytes(path.read_bytes())
            protocol['source_sha256']=sources;save(args.output/'protocol.json',protocol)
        screen=lambda entry:screening_reviewed(context,entry,chart['input'][valid],target[valid],chart['input'][gray],target[gray],banks[.53],response,validation,calibration)
        options=SimpleNamespace(output=folder,steps=200,checkpoint=50,seed=42,guard_calibration=calibration,
            lr=lr,min_lr=lr*.02,schedule_steps=2000)
        print('TRIAL_START',name,'lr',lr,'tone',ratio,'cap',cap,flush=True)
        entry,row=train(args.arm,space,renderer,objective,scales,screen,training,margins,options)
        if legality_failures(blob(entry)):raise ValueError('候选BIN非法')
        photos=[]
        for scene,data,old in photo_data:
            new=predict(context,entry,data['inputs'],response)
            failures,regions=photo_failures(old,new,data['target_5'],data['display'],calibration['photo'])
            photos.append(dict(scene=scene['scene'],baseline=color_metrics(old,data['target_5']),candidate=color_metrics(new,data['target_5']),failures=failures,regions=regions))
        row.update(name=name,tone_ratio=ratio,tone_gradient_cap=cap,lr=lr,min_lr=lr*.02,schedule_steps=2000,
            research_config=research or {},photo_training_samples=len(photo_bank.inputs) if research and (research.get('photo_ratio',0) or research.get('photo_guard_budget',0)) else 0,
            development=photos,development_failures=[s['scene']+':'+reason for s in photos for reason in s['failures']],
            test_evaluated=False,holdout_photos_evaluated=False,adopted=False,scope='200步方向筛查，不是完整收敛或最终验收')
        if args.study in ('cap_lr','objective_plus','photo_guard'):
            checks={}
            for phase in (.17,.53,.87):
                if phase not in banks:banks[phase]=RampBank(phase)
                bank=banks[phase]
                if phase not in base_ramps:base_ramps[phase]=predict(context,source,bank.inputs(context.base),response)
                rendered=predict(context,entry,bank.inputs(context.base),response)
                checks[str(phase)]=multiscale_report(bank,base_ramps[phase],rendered)
                if phase==.87:
                    row['independent_transition_raw']=dict(baseline=ramp_stats(bank.jumps(phase_rgb(base_ramps[phase]))),
                        candidate=ramp_stats(bank.jumps(phase_rgb(rendered))))
            row['transition_checks']=checks
            row['transition_review_reasons']=transition_review(checks)
        rows.append(row);save(folder/'result.json',row);save(args.output/'progress.json',dict(protocol=protocol,trials=rows))
        print('TRIAL_DONE',name,'score',row['selected']['score'],'development_failures',len(row['development_failures']),flush=True)
        del renderer,objective,space;torch.mps.empty_cache()
    if protocol['fixed_trials']:
        loss_choice='research_terms_fixed' if args.study in ('objective_plus','photo_guard') else 'tone_cap02_fixed'
        save(args.output/'locked-loss-choice.json',dict(name=loss_choice,tone_ratio=.1,cap=.2,criterion=protocol['selection']))
        for trial in protocol['fixed_trials']:run(trial['name'],trial['tone_ratio'],trial['cap'],trial['lr'],trial.get('research'))
    else:
        for trial in protocol['loss_trials']:run(trial['name'],trial['tone_ratio'],trial['cap'],.003)
        eligible=[row for row in rows if row['qualified_on_validation']]
        if not eligible:raise ValueError('四组损失均无VALID数值合格候选，停止追加学习率试验')
        chosen=min(eligible,key=lambda row:row['selected']['score']);loss_choice=chosen['name']
        save(args.output/'locked-loss-choice.json',dict(name=loss_choice,tone_ratio=chosen['tone_ratio'],cap=chosen['tone_gradient_cap'],criterion=protocol['selection']))
        run('best_lr_0015',chosen['tone_ratio'],chosen['tone_gradient_cap'],.0015)
        run('best_lr_006',chosen['tone_ratio'],chosen['tone_gradient_cap'],.006)
    if any(digest(path)!=sha for path,sha in protected.items()):raise ValueError('冻结输入变化')
    if any(digest(ROOT/path)!=sha for path,sha in sources.items()):raise ValueError('试验期间源码变化')
    result=dict(protocol=protocol,trials=rows,loss_choice=loss_choice,protected_inputs=protected,protected_inputs_unchanged=True)
    save(args.output/'result.json',result)
    lines=[f'# 暖金日光：{args.arm}方案200步损失与学习率筛查','','MPS整批；每组200步，余弦调度跨度保持2000步。保留原配方，不更新正式工作台或BIN格式，不连接相机。',
        '仅使用TRAIN/VALID与六张开发照片，未评TEST和四张留出照片；不能把本轮排名视为完整训练的最终优劣。','',
        '| 组别 | 初始学习率 | 渐变起点比例 | 梯度上限 | VALID RGB RMSE | 平均ΔE00 | P95 | 灰阶RMSE | 开发区域失败数 | 过渡待复核 |',
        '|---|---:|---:|---:|---:|---:|---:|---:|---:|---|']
    for row in rows:
        m=row['selected']['metrics'];reviews=row.get('transition_review_reasons',row['selected'].get('review_reasons',[]))
        lines.append(f"| {row['name']} | {row['lr']} | {row['tone_ratio']} | {row['tone_gradient_cap']} | "+' | '.join(f'{m[k]:.6f}' for k in ('rgb_rmse','delta_e00_mean','delta_e00_p95','gray_rmse'))+f" | {len(row['development_failures'])} | {','.join(reviews) or '无'} |")
    lines+=['',f"损失配置：`{loss_choice}`。{protocol['selection']}。",
        '所有指标来自量化BIN回读；各组所选步数可小于200，完整候选池和末步BIN同时保留。','']
    (args.output/'筛查报告.md').write_text('\n'.join(lines))
    print('DONE',args.output,flush=True)


if __name__=='__main__':main()
