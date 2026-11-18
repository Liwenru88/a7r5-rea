"""统一原生四组参数训练：有限软约束探索、完整整数候选及独立终检。"""
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import torch
import core
from native_solver import train,save,blob,digest,predict,combined_metrics,sensitivity_scales
from native_feasible_experiment import OriginalSpace,FlatRenderer,blend_entry
from native_objective_research import PhotoBank,MixedRenderer
from native_precision_research import WindowRampBank,PrecisionObjective
from calibrated_guard import RampBank,calibrate,phase_rgb
from native_guard_policy import (build_calibration,quality_envelope,TargetToneBank,
    photo_failures,dense_probe_inputs)
from native_dense_audit import dense_report
from native_scoring import color_metrics
from grid_models import default_response

POLICY='native-joint-qualified/1'
FORCED_POLICY='native-joint-forced/1'
AXES=('saturation','native-saturation','hue','native-hue')
DEFAULTS=dict(steps=600,checkpoint=50,lr=.003,dense_budget=.1,photo_ratio=.05,
    photo_guard_budget=.25,radius_confirmations=2,radius_min_relative_improvement=.001,
    uniform_windows=48,peak_windows=16,seed=42,dense_axes=list(AXES),strict_training_quality=True,
    conditional_steps=2000,conditional_candidates=1,integer_sweeps=2,recovery_enabled=True,full_photo_steps=600,
    robust_rounds=6,robust_steps=500)


def validate_arrays(*,inputs,target,split,anchors,design,kinds):
    inputs,target,split,anchors,design,kinds=map(np.asarray,(inputs,target,split,anchors,design,kinds))
    n=len(target)
    if (inputs.shape!=(n,9,3) or target.shape!=(n,3) or design.shape!=(n,3)
            or any(x.shape!=(n,) for x in (split,anchors,kinds))
            or any(not np.isfinite(x).all() for x in (inputs,target,design))
            or inputs.min()<0 or inputs.max()>65535 or np.any(inputs!=np.rint(inputs))
            or target.min()<0 or target.max()>1 or design.min()<0 or design.max()>1
            or not set(np.unique(split))<= {'train','valid','test'}
            or any(not np.any(split==part) for part in ('train','valid','test'))):
        raise ValueError('联合训练需要有效的九点输入、RGB目标及分离的TRAIN/VALID/TEST')
    gray=(anchors>=4)&(anchors<260)
    if not gray.any() or not np.all(split[gray]=='train'):
        raise ValueError('灰阶锚点必须只属于TRAIN')


def choose(reference,candidates):
    keys=('rgb_rmse','delta_e00_mean','delta_e00_p95','gray_rmse');good=[]
    for row in candidates:
        m=row.get('metrics',{})
        if not row.get('fully_evaluated') or row.get('failures')!=[]:continue
        if any(not np.isfinite(m.get(k,np.nan)) for k in keys) or not np.isfinite(row.get('score',np.nan)):continue
        if not all(m[k]<reference['metrics'][k]-1e-10 for k in keys[:2]):continue
        if any(m[k]>reference['metrics'][k]+1e-8 for k in keys[2:]):continue
        good.append(row)
    return min(good,key=lambda r:(r['score'],r['metrics']['delta_e00_p95'],r['label'])) if good else reference


def recipe_key(entry):
    return json.dumps({k:entry[k] for k in ('gamma_native_129','cc1_delta','block13','grid_5x9x9')},sort_keys=True,allow_nan=False)


def choose_forced(reference,candidates,gate):
    """只选本次优化产生的合法新配方；品质超限是诊断，不替换为旧配方。"""
    keys=('rgb_rmse','delta_e00_mean','delta_e00_p95','gray_rmse','weighted_loss')
    good=[];seen=set();original=recipe_key(reference['entry'])
    for row in candidates:
        blob(row['entry']);identity=recipe_key(row['entry'])
        if identity==original or identity in seen:continue
        if any(not np.isfinite(row.get('metrics',{}).get(k,np.nan)) for k in keys):continue
        seen.add(identity);score=gate.selection_score(row)
        if not np.isfinite(score):continue
        good.append(dict(row,selection_score=score))
    if not good:raise ValueError('本次 C 优化没有合法、有限的新候选，停止发布；未回退旧配方')
    return min(good,key=lambda r:(r['selection_score'],r['metrics']['delta_e00_p95'],r['label']))


class Data:
    def __init__(self,context,inputs,target,split,anchors,design,kinds,*,photos=(),holdout_loader=None):
        validate_arrays(inputs=inputs,target=target,split=split,anchors=anchors,design=design,kinds=kinds)
        self.context=context;self.inputs=np.asarray(inputs);self.target=np.asarray(target,float)
        self.split=np.asarray(split).astype(str);self.anchors=np.asarray(anchors)
        self.design=np.asarray(design,float);self.kinds=np.asarray(kinds).astype(str)
        self.train=self.split=='train';self.valid=self.split=='valid';self.gray=(self.anchors>=4)&(self.anchors<260)
        if any(p['role']!='development' for p in photos):raise ValueError('训练入口只接受开发照片，留出由终检加载')
        self.photos=list(photos);self.holdout_loader=holdout_loader


def reference_calibration(data,entry,response):
    train=predict(data.context,entry,data.inputs[data.train],response)
    target=data.target[data.train];gray=data.gray[data.train]
    dev=[(p['scene'],predict(data.context,entry,p['inputs'],response),p['target'],p['display']) for p in data.photos]
    if dev:calibration=build_calibration(train,target,gray,dev)
    else:
        full=quality_envelope(train,target);gray_bound=quality_envelope(train[gray],target[gray])
        calibration=dict(chart=dict(gray_rmse=gray_bound['margins']['rgb_rmse'],delta_e00_p95=full['margins']['delta_e00_p95']),
            chart_audit=full,gray_audit=gray_bound,photo_audits=[],photo={},photo_calibrated=False)
    return calibration,train,dev


class Gate:
    def __init__(self,data,reference,*,phases=(.17,.53,.87),final_phases=(.113,.647),response=None):
        self.data=data;self.context=data.context;self.reference=copy.deepcopy(reference)
        self.response=response or default_response();self.phases=tuple(phases);self.final_phases=tuple(final_phases)
        from native_cached_forward import CachedForward
        self._forward=CachedForward(self.context,self.response)
        self.calibration,self.train_reference,self.development=reference_calibration(data,reference,self.response)
        self.geometry={};self.cache={};self.final_calls=0
        self.baseline=self.assess(reference,'reference')

    def _predict(self,entry,inputs):
        if hasattr(self,'_forward'):return self._forward(entry,inputs)
        return predict(self.context,entry,inputs,self.response)

    def selection_score(self,row):
        # 开发排名始终使用相同色卡与照片，不能因过渡检查短路而缺少照片项。
        cache=self.__dict__.setdefault('_selection_scores',{})
        if row['sha256'] not in cache:
            base=self.baseline['metrics'];m=row['metrics']
            score=sum(m[k]/max(base[k],1e-8) for k in ('rgb_rmse','delta_e00_mean'))
            if self.data.photos:
                photos=row.get('photos')
                if not photos:
                    photos=[dict(metrics=color_metrics(self._predict(row['entry'],p['inputs']),p['target']),
                        baseline=color_metrics(before,p['target'])) for p,(_,before,_,_) in zip(self.data.photos,self.development)]
                for k in ('rgb_rmse','delta_e00_mean'):
                    a=np.mean([p['metrics'][k] for p in photos]);b=np.mean([p['baseline'][k] for p in photos])
                    score+=.5*a/max(b,1e-8)
            cache[row['sha256']]=float(score)
        return cache[row['sha256']]

    def geometry_for(self,phase):
        if phase not in self.geometry:
            bank=RampBank(phase);arrays=[];sections={};offset=0
            for axis in AXES:
                _,shape=bank.span(axis);parts=[dense_probe_inputs(bank,axis,line,self.context.base,factor=16)[1] for line in range(shape[0])]
                x=np.concatenate(parts);arrays.append(x);sections[axis]=(slice(offset,offset+len(x)),(shape[0],len(parts[0]),3));offset+=len(x)
            inputs=np.concatenate(arrays);reference=self._predict(self.reference,inputs)
            self.geometry[phase]=(inputs,reference,sections)
        return self.geometry[phase]

    def assess(self,entry,label,*,final=False,complete=False):
        binary=blob(entry);sha=hashlib.sha256(binary).hexdigest();key=(sha,final)
        if key in self.cache and (self.cache[key]['fully_evaluated'] or not complete):
            return dict(copy.deepcopy(self.cache[key]),label=label)
        data=self.data;mask=data.split==('test' if final else 'valid')
        inputs=np.concatenate((data.inputs[mask],data.inputs[data.gray]));rgb=self._predict(entry,inputs)
        metrics=combined_metrics(rgb[:mask.sum()],data.target[mask],rgb[mask.sum():],data.target[data.gray])
        from multiround import cpu_cost
        metrics['weighted_loss']=cpu_cost(rgb[:mask.sum()],data.target[mask])
        same=binary==blob(self.reference)
        if same:base=metrics
        elif final:
            original=self._predict(self.reference,inputs)
            base=combined_metrics(original[:mask.sum()],data.target[mask],original[mask.sum():],data.target[data.gray])
        else:base=self.baseline['metrics']
        failures=[]
        if not same:
            failures += [k for k in ('rgb_rmse','delta_e00_mean') if metrics[k]>=base[k]-1e-10]
            failures += [k for k in ('gray_rmse','delta_e00_p95') if metrics[k]>base[k]+1e-8]
        score=metrics['rgb_rmse']/max(base['rgb_rmse'],1e-8)+metrics['delta_e00_mean']/max(base['delta_e00_mean'],1e-8)
        photos=[];dense={};raw=[];quant=[];fully=not failures or complete or same or final
        if fully:
            bank=(data.holdout_loader() if data.holdout_loader else []) if final else data.photos
            if final and data.photos and not bank:failures.append('photo:holdout-missing')
            for p in bank:
                before=self._predict(self.reference,p['inputs']);after=self._predict(entry,p['inputs'])
                if self.calibration['photo']:
                    flags,regions=photo_failures(before,after,p['target'],p['display'],self.calibration['photo'])
                else:flags,regions=[],{}
                photos.append(dict(scene=p['scene'],metrics=color_metrics(after,p['target']),baseline=color_metrics(before,p['target']),failures=flags,regions=regions))
                failures += ['photo:'+p['scene']+':'+x for x in flags]
            if photos:
                for k in ('rgb_rmse','delta_e00_mean'):
                    a=np.mean([p['metrics'][k] for p in photos]);b=np.mean([p['baseline'][k] for p in photos])
                    if not same and a>=b-1e-10:failures.append('photos:'+k)
                    score+=.5*a/max(b,1e-8)
            for phase in (self.final_phases if final else self.phases):
                x,before,sections=self.geometry_for(phase);after=before if same else self._predict(entry,x)
                reports={}
                for axis,(span,shape) in sections.items():
                    r=dense_report(before[span].reshape(shape),after[span].reshape(shape));reports[axis]=r
                    raw += [f'{phase}:{axis}:{x}' for x in r['global_exceedances']]
                    quant += [f'{phase}:{axis}:{x["line"]}:{x["metric"]}' for x in r['local_quantization_exceedances']]
                dense[str(phase)]=reports
            failures += ['dense:'+x for x in raw]+['dense_quant:'+x for x in quant]
        if final:self.final_calls+=1
        result=dict(label=label,entry=copy.deepcopy(entry),sha256=sha,metrics=metrics,baseline_metrics=base,
            failures=failures,score=float(score),fully_evaluated=fully,photos=photos,dense=dense,
            raw_transition_failures=raw,quantization_failures=quant,
            photo_scope=('holdout' if final else 'development') if data.photos else 'not-bound',
            split='test' if final else 'valid',review_reasons=[])
        self.cache[key]=copy.deepcopy(result)
        return result


def fit(data,reference,output,*,seed=None,options=None,progress=None,frozen_scales=None,gate=None):
    if not torch.backends.mps.is_available():raise RuntimeError('联合训练需要Apple Metal/MPS，不回退CPU')
    options=dict(DEFAULTS,**(options or {}));output=Path(output);output.mkdir(parents=True,exist_ok=False)
    forced=options.get('selection_policy')=='force-new'
    if options.get('selection_policy') not in (None,'force-new'):raise ValueError('未知候选选择策略')
    total_stages=7 if options['robust_rounds'] else (6 if data.photos and options['full_photo_steps'] else 5)
    if progress:progress(round=1,total_rounds=total_stages)
    if options['steps'] not in (200,600,1200,2000):raise ValueError('联合步数必须为200/600/1200/2000')
    seed=copy.deepcopy(seed or reference);response=default_response();gate=gate or Gate(data,reference,response=response)
    (output/'reference.BIN').write_bytes(blob(reference));(output/'seed.BIN').write_bytes(blob(seed))
    save(output/'options.json',options)
    bank=WindowRampBank(RampBank(.17),data.context.base,lambda x:predict(data.context,reference,x,response),
        uniform=options['uniform_windows'],peaks=options['peak_windows'],axes=options['dense_axes'])
    inputs=np.concatenate((data.inputs[data.train],bank.inputs(data.context.base)))
    source=predict(data.context,reference,inputs,response)
    space=OriginalSpace(data.context,seed,device='mps');chart=FlatRenderer(space,inputs,response)
    if not np.array_equal(chart.exact_entry(seed)[0],predict(data.context,seed,inputs,response)):raise ValueError('训练加速与完整原生整数前向不一致')
    if frozen_scales is None:scales,normalization=sensitivity_scales(space,chart,seed=options['seed'])
    else:
        scales=np.asarray(frozen_scales,float);normalization=dict(method='frozen-native-units')
        if scales.shape!=(1448,) or not np.isfinite(scales).all() or np.any(scales<=0):raise ValueError('归一化尺度无效')
    photos=None
    if data.photos:
        photos=PhotoBank(data.photos,per_region=256,seed=42);photos.reference=predict(data.context,reference,photos.inputs,response)
        renderer=MixedRenderer(chart,photos.inputs)
    else:renderer=chart
    tone=TargetToneBank(data.design[data.train],data.target[data.train],data.split[data.train],data.kinds[data.train],source[:data.train.sum()])
    calibration=gate.calibration
    margins=calibrate(bank,source[data.train.sum():],[(scene,pred,target) for scene,pred,target,_ in gate.development],allow_no_photos=not data.photos)
    objective=PrecisionObjective(space,data.target[data.train],data.gray[data.train],bank,source,new_loss=True,
        response=response,margins=margins,calibration=calibration,tone_bank=tone,tone_ratio=.1,tone_gradient_cap=.2,
        photo_bank=photos,photo_ratio=options['photo_ratio'] if photos else 0.,
        photo_guard_budget=options['photo_guard_budget'] if photos else 0.,dense_budget=options['dense_budget'])
    if options['strict_training_quality']:
        # 训练软惩罚与最终灰阶/P95零退步规则对齐；保留校准尺度作数值归一化。
        objective.guard_gray=calibration['gray_audit']['baseline']['rgb_rmse']
        objective.guard_p95=calibration['chart_audit']['baseline']['delta_e00_p95']
    training=dict(metrics=combined_metrics(source[:data.train.sum()],data.target[data.train],source[:data.train.sum()][data.gray[data.train]],data.target[data.gray]))
    args=SimpleNamespace(output=output,steps=options['steps'],checkpoint=options['checkpoint'],seed=options['seed'],
        lr=options['lr'],min_lr=options['lr']*.02,schedule_steps=max(2000,options['steps']),guard_calibration=calibration,
        retain_checkpoints=True,research_radius=True,adaptive_radius=True,radius_confirmations=options['radius_confirmations'],
        radius_min_relative_improvement=options['radius_min_relative_improvement'],progress=progress,
        allow_infeasible_seed=True)
    _,result=train('C',space,renderer,objective,scales,lambda e:gate.assess(e,'candidate'),training,margins,args)
    rows=[gate.baseline]
    def pick():
        return choose_forced(gate.baseline,rows,gate) if forced else choose(gate.baseline,rows)
    # 只用开发数据复选检查点及围绕冻结基准的整数缩步，不使用最终留出重挑。
    for file in sorted((output/'C/checkpoints').glob('*.BIN')):
        if forced and int(file.stem)==0:continue
        entry=core.compiler.unpack(file.read_bytes())['entries'][0]
        for alpha in (1.,.75,.5,.25,.125):
            try:candidate=blend_entry(reference,entry,alpha)
            except (ValueError,OverflowError):continue
            rows.append(gate.assess(candidate,file.stem+f'/a{alpha}'))
    selected=pick()
    extra={}
    def stage_progress(number,label):
        if progress is None:return None
        def report(**values):
            values['round']=number;values['total_rounds']=total_stages
            values['stage']=label+' · '+values.get('stage','训练中')
            if values.get('loss_sample'):
                solver,*sample=values['loss_sample'];values['loss_sample']=(label+' '+solver,*sample)
            progress(**values)
        return report
    # 保留不同原生参数方向，不以最终留出筛选条件恢复的起点。
    promising=[r for r in rows if all(r['metrics'][k]<=gate.baseline['metrics'][k]+1e-8
        for k in ('gray_rmse','delta_e00_p95'))]
    if forced:promising=[r for r in rows if recipe_key(r['entry'])!=recipe_key(reference)]
    promising=sorted(promising,key=lambda r:gate.selection_score(r) if forced else r['score'])
    distinct=[];seen_native=set()
    for row in promising:
        identity=tuple(json.dumps(row['entry'][k]) for k in ('gamma_native_129','cc1_delta','block13'))
        if identity in seen_native:continue
        seen_native.add(identity);distinct.append(row['entry'])
        if len(distinct)>=2:break
    if options['recovery_enabled'] and distinct:
        from native_joint_recovery import recover
        _,recovery=recover(data,gate,distinct,output/'recovery',progress=stage_progress(2,'分组恢复'))
        rows.extend(recovery['candidates']);extra['recovery']=dict(evaluations=recovery['evaluations'],selected=recovery['selected']['label'])
        selected=pick()
    if options['conditional_steps']:
        from native_conditional_grid import fit_grid
        candidates=[('conditional-reference',reference)]
        ref_native=tuple(json.dumps(reference[k]) for k in ('gamma_native_129','cc1_delta','block13'))
        for e in distinct:
            if tuple(json.dumps(e[k]) for k in ('gamma_native_129','cc1_delta','block13'))!=ref_native and options['conditional_candidates']:
                candidates.append(('conditional-candidate',e));break
        if forced:candidates=[('conditional-candidate',selected['entry'])]
        for i,(label,entry) in enumerate(candidates):
            _,conditional=fit_grid(data,gate,entry,output/label,steps=options['conditional_steps'],
                freeze_gray=(label=='conditional-reference'),progress=stage_progress(3+i,label))
            rows.extend(dict(r,label=label+'/'+r['label']) for r in conditional['candidates']);extra[label]=dict(selected=conditional['selected']['label'],
                protected_gray_nodes=conditional['protected_gray_nodes'],cpu_gpu_max_difference=conditional['cpu_gpu_max_difference'])
        selected=pick()
    if options['integer_sweeps']:
        from native_joint_integer import polish
        _,integer=polish(data,gate,selected['entry'],output/'integer',sweeps=options['integer_sweeps'],progress=stage_progress(5,'整数复验'))
        rows.extend(integer['candidates']);extra['integer']=dict(evaluations=integer['evaluations'],selected=integer['selected']['label'])
        selected=pick()
    if options['full_photo_steps'] and data.photos:
        from native_joint_photo import polish_photos
        _,photo=polish_photos(data,gate,selected,output/'full-photos',steps=options['full_photo_steps'],
            progress=stage_progress(6,'完整开发照片收敛'))
        rows.extend(photo['candidates']);selected=photo['selected']
        if forced:selected=pick()
        extra['full-photos']=dict(selected=selected['label'],photo_samples=photo['photo_samples'],
            cpu_gpu_max_difference=photo['cpu_gpu_max_difference'],selection_policy=photo['selection_policy'])
    if options['robust_rounds']:
        from native_robust_grid import repair
        _,robust,gate=repair(data,reference,selected['entry'],output/'robust',
            rounds=options['robust_rounds'],steps=options['robust_steps'],progress=stage_progress(7,'稳健过渡'))
        # 新活动集有更密集的开发几何，旧三相位的通过状态不能沿用。
        if forced:
            rows.extend(robust['candidates']);selected=pick()
        else:selected=robust['selected'];rows=robust['candidates']
        extra['robust']=dict(selected=selected['label'],phases=robust['phases'],
            final_phases=robust['final_phases'],rounds=robust['rounds'],steps_per_round=robust['steps_per_round'])
    if forced:
        score=selected['selection_score']
        selected=gate.assess(selected['entry'],selected['label'],complete=True)
        selected['selection_score']=score
    (output/'selected.BIN').write_bytes(blob(selected['entry']))
    audit=dict(policy=FORCED_POLICY if forced else POLICY,options=options,normalization=normalization,training=result,
        baseline=gate.baseline,selected=selected,candidates=rows,adopted_on_development=selected['sha256']!=gate.baseline['sha256'],
        final_evaluated=False,holdout_used_for_training=False,full_gamma129=True,camera_connected=False,stages=extra)
    save(output/'joint-audit.json',audit)
    return selected['entry'],audit,gate
