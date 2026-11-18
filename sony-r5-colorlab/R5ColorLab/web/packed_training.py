"""按实际 BIN 回读筛选原生候选，保留旧配方并隔离最终验收。"""
from pathlib import Path
import copy
import json
import math

import numpy as np
import core
import baseline
from native_scoring import color_metrics
from residual_grid import pack, unpack
from fit_bin_joint import grid_from
from patch_sampling import center_mean
from calibrated_guard import RampBank, calibrate, ramp_report, phase_rgb, SceneProtection
from edit_parameter_context import ParameterContext, RuntimeColor
from stack_training import save

POLICY = 'native-packed-quality/1'
REQUIRED = ('rgb_rmse','delta_e00_mean','delta_e00_p95','gray_rmse','weighted_loss')


def quality_choice(reference, candidates):
    """先过全部保护，再要求两项色差同时改善；缺失证据不放行。"""
    start=reference['metrics']
    if any(not math.isfinite(start.get(k,float('nan'))) for k in REQUIRED):
        raise ValueError('基准评分不完整')
    eligible=[]
    for row in candidates:
        m=row.get('metrics',{})
        if row.get('failures') != [] or any(not math.isfinite(m.get(k,float('nan'))) for k in REQUIRED):continue
        if all(m[k]<start[k]-1e-10 for k in ('rgb_rmse','delta_e00_mean')):eligible.append(row)
    return min(eligible,key=lambda r:(r['metrics']['weighted_loss'],r['label'])) if eligible else reference


def canonical(entry):
    version=5 if entry['number']>12 else 4
    config=core.compiler.config([copy.deepcopy(entry)],version)
    binary=core.compiler.pack(config)
    return core.compiler.unpack(binary)['entries'][0],core.sha(binary)


def snapshot(entry, source=None, response=None):
    value,digest=canonical(entry)
    return dict(entry=value,sha256=digest,origin=copy.deepcopy(source),source_response=response)


def bind_context(body, runs):
    """在排队时冻结已保存槽位；重试复用同一快照，不读取后来修改的槽位。"""
    if body.get('packed_selection_policy')!=POLICY:return
    prior=body.get('packed_baseline')
    if prior is not None:
        _,digest=canonical(prior['entry'])
        if digest!=prior['sha256'] or prior['entry']['number']!=body['number']:
            raise ValueError('旧配方快照身份不符')
    elif body.get('project_id'):
        import projects
        project=projects.Store(Path(runs)).get(body['project_id'])
        entry=next((e for e in project['entries'] if e['number']==body['number']),None)
        if entry:
            source=project['sources'].get(str(body['number']))
            response=None
            if source and source.get('kind')=='compressed':
                from grid_distillation import load_result
                report,_,_=load_result(Path(runs)/source['job'],source['key'])
                response=report['identity']['response']
            body['packed_baseline']=snapshot(entry,source,response)
    from quality_data import bind
    bind(body,Path(runs))


def native_prediction(context, entry, inputs):
    model=context.build(**core.slot_native_parameters(context,entry))
    return np.concatenate([center_mean(model.color_only(inputs[i:i+8192]))
                           for i in range(0,len(inputs),8192)])/16383


class QualityGate:
    """候选只接触 valid、训练灰阶、开发照片和筛选相位；final 单独调用。"""
    def __init__(self, source, reference, response, photos=()):
        self.source=Path(source)
        self.context=ParameterContext(RuntimeColor.from_capture(*baseline.for_job(source)))
        from measured_response import get
        self.response=get(response)
        with np.load(self.source/'pairs.npz',allow_pickle=False) as p:
            self.data={k:p[k] for k in p.files}
        self.target=self.data['0_target']/16383
        self.gray=(self.data['anchor_index']>=4)&(self.data['anchor_index']<260)&(self.data['split']=='train')
        if not self.gray.any() or not np.any(self.data['split']=='valid') or not np.any(self.data['split']=='test'):
            raise ValueError('需要训练灰阶和分离的验证／测试集')
        self.photos=tuple(photos)
        if self.photos and (not any(p['role']=='development' for p in self.photos) or not any(p['role']=='holdout' for p in self.photos)):
            raise ValueError('照片验收集必须保留开发与留出划分')
        self.reference=canonical(reference)[0]
        self.banks={phase:RampBank(phase) for phase in (.17,.53,.87)}
        self.front={phase:bank.inputs(self.context.base) for phase,bank in self.banks.items()}
        self.cache={}
        bank=self.banks[.17]
        initial=self.predict(self.reference,self.front[.17],'calibration')
        dev=[(p['scene'],self.predict(self.reference,p['inputs'],'photo:'+p['scene']),p['target'])
             for p in self.photos if p['role']=='development']
        self.margins=calibrate(bank,initial,dev,allow_no_photos=not dev)
        self.margins['photo_calibrated']=bool(dev)
        self.final_evaluations=0

    def predict(self, entry, inputs, name):
        native_key=core.sha(json.dumps({k:entry[k] for k in ('cc1_delta','block13','gamma_native_129')},sort_keys=True).encode())
        key=(native_key,name)
        if key not in self.cache:
            if len(self.cache)>=80:self.cache.clear()
            self.cache[key]=native_prediction(self.context,entry,inputs)
        return self.response.predict_cpu(self.cache[key],grid_from(entry))

    def assess(self, entry, label, *, final=False):
        from multiround import cpu_cost
        entry,digest=canonical(entry)
        part='test' if final else 'valid';mask=self.data['split']==part
        p=self.predict(entry,self.data['input'][mask],part)
        start=self.predict(self.reference,self.data['input'][mask],part)
        m=color_metrics(p,self.target[mask]);b=color_metrics(start,self.target[mask])
        gp=self.predict(entry,self.data['input'][self.gray],'gray')
        gb=self.predict(self.reference,self.data['input'][self.gray],'gray')
        m['gray_rmse']=color_metrics(gp,self.target[self.gray])['rgb_rmse']
        b['gray_rmse']=color_metrics(gb,self.target[self.gray])['rgb_rmse']
        m['weighted_loss']=cpu_cost(p,self.target[mask]);b['weighted_loss']=cpu_cost(start,self.target[mask])
        failures=[]
        if digest!=canonical(self.reference)[1]:
            failures.extend(k for k in ('rgb_rmse','delta_e00_mean') if m[k]>=b[k]-1e-10)
            for k in ('gray_rmse','delta_e00_p95'):
                if m[k]>b[k]+self.margins[k]+1e-10:failures.append(k)
        phase=.87 if final else .53;bank=self.banks[phase]
        r0=bank.jumps(phase_rgb(self.predict(self.reference,self.front[phase],'ramp:'+str(phase))))
        r1=bank.jumps(phase_rgb(self.predict(entry,self.front[phase],'ramp:'+str(phase))))
        ramps,ramp_errors=ramp_report(r0,r1,self.margins);failures.extend(ramp_errors)
        photo_rows=[];role='holdout' if final else 'development'
        for photo in self.photos:
            if photo['role']!=role:continue
            bp=self.predict(self.reference,photo['inputs'],'photo:'+photo['scene'])
            pp=self.predict(entry,photo['inputs'],'photo:'+photo['scene'])
            guard=SceneProtection(bp,photo['target'],{'whole':np.arange(len(bp))})
            metrics=guard.score(pp);errors=guard.failures(metrics)
            failures.extend('photo:'+photo['scene']+':'+k for k in errors)
            photo_rows.append(dict(scene=photo['scene'],metrics=color_metrics(pp,photo['target']),baseline=color_metrics(bp,photo['target'])))
        if photo_rows and digest!=canonical(self.reference)[1]:
            for k in ('rgb_rmse','delta_e00_mean'):
                if np.mean([r['metrics'][k] for r in photo_rows])>=np.mean([r['baseline'][k] for r in photo_rows])-1e-10:
                    failures.append('photos:'+k)
        if final:self.final_evaluations+=1
        return dict(label=label,entry=entry,sha256=digest,metrics=m,baseline_metrics=b,failures=failures,
                    split=part,ramp_phase=phase,ramps=ramps,photos=photo_rows,photos_verified=bool(photo_rows))


def entry_from_parameters(source, params, folder):
    """先走冻结编译器，再用解码后的真实单位训练网格。"""
    source=Path(source);folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    recipe=json.loads((source/'fit/recipe.json').read_text());recipe.pop('fitting',None)
    if 'gamma_native_129' not in params:
        recipe['parameters'].pop('gamma_native_129',None)
        recipe['parameters'].pop('gamma_domain',None)
    recipe['parameters'].update(params)
    path=folder/'native-recipe.json';save(path,recipe)
    original=json.loads((source/'native_config.json').read_text())['entries'][0]
    config,_=core.compiler.from_fit(path,baseline.for_job(source)[0],original['number'],original['short_name'],original['full_name'],131071)
    return canonical(config['entries'][0])[0]


def prepare(source, output, body, progress, *, validation_runs=None):
    """所有短名单候选先拟合同预算机内网格，再选联合优化的起点。"""
    from grid_distillation import firmware_config
    from grid_models import default_response
    from native_candidates import shortlist
    from formal_grid_distillation import fit_target
    from fit_anchor_native import training_plan
    from multiround import run
    from quality_data import load
    source=Path(source);output=Path(output);output.mkdir(parents=True,exist_ok=True)
    key=json.loads((source/'grid_training.json').read_text())['key']
    parent=firmware_config(source,key,True)['entries'][0]
    reference=body.get('packed_baseline',{}).get('entry',parent)
    response=default_response();photos=load(body.get('quality_set'),Path(validation_runs or source.parent),body.get('target_sha256'))
    gate=QualityGate(source,reference,response,photos)
    gate.baseline_identity=copy.deepcopy(body.get('packed_baseline'))
    ref=gate.assess(reference,'saved-slot' if body.get('packed_baseline') else 'current-run-parent')
    rows=[gate.assess(parent,'new-native-parent')]
    records=shortlist(source/'fit/native_candidates.json',limit=4,expected_pairs_sha256=core.sha((source/'pairs.npz').read_bytes())) if (source/'fit/native_candidates.json').exists() else []
    native=[('pool-'+str(i+1),entry_from_parameters(source,r['parameters'],output/('native-'+str(i+1)))) for i,r in enumerate(records)]
    native.insert(0,('new-native',parent))
    if body.get('packed_baseline'):
        native.append(('saved-native',reference))
        from concave_gamma import ConcaveGamma
        context=gate.context;old=core.slot_native_parameters(context,reference)
        shape=ConcaveGamma(context.native_axis,control_count=129,parameter_count=129,global_correction=True)
        gamma=shape.curve(shape.encode(np.asarray(old['gamma_y'])/16))*16
        quantized,audit=shape.quantize_global_raw(gamma,time_limit=2,return_audit=True)
        from native_gamma import parameter_fields
        p=parameter_fields(dict(old,gamma_y=quantized))
        projected=entry_from_parameters(source,p,output/'saved-concave')
        save(output/'saved-concave/gamma-audit.json',audit);native.append(('saved-concave',projected))
    data=gate.data;fitting=json.loads((source/'fit/recipe.json').read_text())['fitting']
    train_selection=np.flatnonzero((data['split']=='train')&(data['anchor_index']<0)&(data['sector16_index']<0))
    train,_,_,weights=training_plan(data['split'],data['anchor_index'],fitting['group_total_weights'],data['sector16_index'],data['baseline_tonal_index'] if fitting.get('tonal_balance') else None,train_selection,data['sample_kind'],fitting['search_options'])
    valid=data['split']=='valid';seen=set()
    for label,entry in native:
        native_id=core.sha(json.dumps({k:entry[k] for k in ('cc1_delta','block13','gamma_native_129')},sort_keys=True).encode())
        if native_id in seen:continue
        seen.add(native_id);folder=output/label;folder.mkdir(exist_ok=True)
        progress(stage='整数配方候选：'+label,state='running')
        base=native_prediction(gate.context,entry,data['input'])
        grid,audit=fit_target(base[train],gate.target[train],weights,response,training_penalties=False)
        def assess_round(record,table):
            payload=pack(table);(folder/f"round-{record['round']}.payload").write_bytes(payload)
            save(folder/f"round-{record['round']}.json",record)
            candidate=copy.deepcopy(entry);candidate['grid_5x9x9']=dict(coefficients=table.T.reshape(3,5,9,9).astype(int).tolist())
            rows.append(gate.assess(candidate,label+'/round-'+str(record['round'])))
        grid,continuation=run(grid,audit,base[train],gate.target[train],weights,base[valid],gate.target[valid],response,total_rounds=5,device='mps',save_round=assess_round)
        save(folder/'continuation.json',continuation)
        # 原生参数不变时也检查温和整数网格，避免只有极端全量更新可选。
        if label=='saved-native':
            old_grid=grid_from(reference)
            for alpha in (.5,.25,.125,.0625):
                table=unpack(pack(np.rint(old_grid+alpha*(grid-old_grid))))
                proposal=copy.deepcopy(entry);proposal['grid_5x9x9']=dict(coefficients=table.T.reshape(3,5,9,9).astype(int).tolist())
                rows.append(gate.assess(proposal,label+'/blend-'+str(alpha)))
        save(output/'candidates.json',dict(policy=POLICY,reference=ref,candidates=rows,margins=gate.margins,selection_uses_test=False))
    chosen=quality_choice(ref,rows)
    save(output/'selection.json',dict(policy=POLICY,reference=ref,candidates=rows,selected=chosen['label'],selected_sha256=chosen['sha256'],margins=gate.margins,selection_uses_test=False,photos_bound=bool(photos)))
    return chosen['entry'],gate,ref,rows


def attach_result(job, state, selected, quality):
    """复用已绑定结果的 selected_config 通道，预览与导出读取同一配方。"""
    import grid_distillation as gd
    job=Path(job);old_key=state['result']['grid_key'];report,_,_=gd.load_result(job,old_key)
    entry=canonical(selected)[0]
    config=core.compiler.config([entry],5 if entry['number']>12 else 4)
    binary=core.compiler.pack(config);grid=grid_from(entry)
    identity=copy.deepcopy(report['identity'])
    # 旧修复表属于原始结果，新结果以完整所选配置和品质审计重新绑定。
    for key in tuple(identity):
        if key.startswith('postfit_') or key=='shape_preserving_implementation_sha256':identity.pop(key)
    identity.update(native_config_sha256=core.sha((job/'native_config.json').read_bytes()),
        selected_bin_sha256=core.sha(binary),grid_payload_sha256=core.sha(pack(grid)),
        quality_policy=quality.get('policy',POLICY),quality_audit_sha256=core.sha(json.dumps(quality,sort_keys=True,allow_nan=False).encode()))
    key=core.sha(json.dumps(identity,sort_keys=True).encode())
    report.update(identity=identity,payload_hex=pack(grid).hex(),selected_config=config)
    report['fitting']=dict(training_only=False,quality_selection=quality,original_stack_report=old_key)
    # 模型图、色块和下载都使用解码后的已选配方；电脑端补偿只保留作诊断。
    factory=RuntimeColor.from_capture(*baseline.for_job(job));context=ParameterContext(factory)
    with np.load(job/'pairs.npz',allow_pickle=False) as data:
        inputs=data['input'];base=native_prediction(context,entry,inputs);target=data['0_target']/16383;split=data['split'];ids=data['anchor_index']
    from measured_response import get
    prediction=get(identity['response']).predict_cpu(base,grid)
    # 在发布任何下载文件前完成独立 B 端点解码回放。
    independent=__import__('stack_training').decode_model(core.compiler.unpack(binary)['entries'][0],factory)
    exact=np.concatenate([center_mean(independent.color_only(chunk)) for chunk in np.array_split(inputs,16)])/16383
    if not np.array_equal(exact,base):raise ValueError('最终 BIN 独立 CPU 回放不一致')
    from pc_compensation import load
    import pc_stages
    pc,pc_grid=load(job)
    _,proposal_model=baseline.read_job(job)
    proposal_base=np.concatenate([center_mean(proposal_model.color_only(chunk)) for chunk in np.array_split(inputs,16)])/16383
    from gpu_runtime import cpu_reference
    with cpu_reference():combined=pc_stages.render(proposal_base,pc['curves'],pc_grid)
    for part,mask in [('gray_training',(ids>=4)&(ids<260)&(split=='train')),('primaries_training',(ids>=0)&(ids<4)&(split=='train')),('colorchecker24_training',(ids>=260)&(ids<284)&(split=='train')),('validation',split=='valid'),('test',split=='test')]:
        if part in report['metrics'] and mask.any():
            report['metrics'][part]['grid_vs_lut']=core.tonal_comparison(target[mask],prediction[mask])
            report['metrics'][part]['grid_vs_combined']=core.tonal_comparison(combined[mask],prediction[mask])
    report['samples']['gray_grid']=prediction[(ids>=4)&(ids<260)&(split=='train')].tolist()
    probes=get(identity['response']).probes(4096,seed=20261023)
    with cpu_reference():teacher=pc_stages.render(probes,pc['curves'],pc_grid)
    report['metrics']['unseen_synthetic']['grid_vs_combined']=core.tonal_comparison(teacher,get(identity['response']).predict_cpu(probes,grid))
    comparisons=json.loads((job/'stack_comparison.json').read_text())
    for name,mask in [('train',split=='train'),('validation',split=='valid'),('test',split=='test'),('gray_train',(split=='train')&(ids>=4)&(ids<260))]:
        comparisons[name]['stack']=__import__('stack_training').metrics(target[mask],prediction[mask])
        comparisons[name]['display_stack']=core.tonal_comparison(target[mask],prediction[mask])
    destination=job/'grid_distillation'/key;destination.mkdir(parents=True,exist_ok=False)
    save(destination/'result.json',report);(destination/'grid.payload').write_bytes(pack(grid));(destination/'teacher.json').write_bytes((job/'pc_compensation.json').read_bytes())
    (job/'stack-proposal.BIN').write_bytes((job/'R5NATIVE.BIN').read_bytes())
    (job/'R5NATIVE.BIN').write_bytes(binary)
    save(job/'grid_training.json',dict(status='done',key=key,phase='整数配方品质筛选完成'))
    audit=json.loads((job/'stack_audit.json').read_text());audit.update(stack_proposal_binary_sha256=audit['binary_sha256'],binary_sha256=core.sha(binary),quality_selection=quality,decoded_validation=quality['accepted_validation'],decoded_native_cpu_replay=True,bin_decode_recompile=core.compiler.pack(core.compiler.unpack(binary))==binary)
    save(job/'stack_audit.json',audit)
    save(job/'stack_comparison.json',comparisons)
    state['result'].update(config=config,grid_key=key,binary_sha256=core.sha(binary),binary_bytes=len(binary),quality_selection=quality)
    save(job/'quality_selection.json',quality)
    if gd.firmware_config(job,key,True)!=config:raise ValueError('品质筛选结果与导出不一致')
    return key


def finalize(job, state, gate, reference, candidates):
    """先在筛选域选唯一胜者，再做一次独立终检；失败只回到原配方。"""
    proposal=core.compiler.unpack((Path(job)/'R5NATIVE.BIN').read_bytes())['entries'][0]
    row=gate.assess(proposal,'stack-proposal')
    chosen=quality_choice(reference,[*candidates,row])
    accepted=chosen
    final=gate.assess(chosen['entry'],chosen['label'],final=True)
    if chosen['sha256']!=reference['sha256'] and final['failures']:accepted=reference
    from native_gamma import POLICY as GAMMA_POLICY
    quality=dict(policy=POLICY,gamma_forward_policy=GAMMA_POLICY,screen_selected=chosen['label'],accepted=accepted['label'],adopted=accepted['sha256']!=reference['sha256'],
        baseline_sha256=reference['sha256'],baseline_identity=getattr(gate,'baseline_identity',None),
        comparison_response=gate.response.identity,selected_sha256=accepted['sha256'],stack_screen=row,final=final,
        independent_checks=1,holdout_used_for_training=False,holdout_used_to_try_other_candidates=False,
        accepted_validation=accepted['metrics']['weighted_loss'],margins=gate.margins,
        photo_scope='development-and-holdout' if gate.photos else 'not-bound',fallback_reason=final['failures'] if final['failures'] else ([] if accepted is not reference else ['no-qualified-screen-candidate']),
        implementation_sha256={name:core.sha(Path(__file__).with_name(name).read_bytes())
            for name in ('packed_training.py','native_candidates.py','quality_data.py','calibrated_guard.py')})
    quality['implementation_sha256']['scripts/native_gamma.py']=core.sha((core.ROOT/'scripts/native_gamma.py').read_bytes())
    quality['implementation_sha256']['scripts/edit_parameter_context.py']=core.sha((core.ROOT/'scripts/edit_parameter_context.py').read_bytes())
    attach_result(job,state,accepted['entry'],quality)
    return quality
