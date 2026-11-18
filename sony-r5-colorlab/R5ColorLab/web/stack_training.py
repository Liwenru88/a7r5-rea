"""Bounded stacked continuation of an immutable completed NC job."""
from pathlib import Path
import copy,hashlib,json,shutil,struct,time
import numpy as np
import core,baseline
from stack_objective import (Scorer,TargetDerivatives,GridObjective,data_loss,
    optimize_grid,optimize_rounding,acceptable)


def save(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    temporary=path.with_suffix(path.suffix+'.pending')
    temporary.write_text(json.dumps(value,ensure_ascii=False,allow_nan=False,indent=2)+'\n')
    temporary.replace(path)


class FrozenGamma:
    def __init__(self,gamma):self.gamma=np.array(gamma,copy=True)
    def curve(self,tail):return self.gamma/16
    def integer_curve(self,tail):return self.gamma.copy()
    def tensor_curve(self,torch,tail):return torch.as_tensor(self.gamma.copy(),device=tail.device,dtype=tail.dtype)/16


def native_update(tools,smooth,vector,base,grid,scorer,render_native,progress,evaluations=120):
    from scipy.optimize import minimize
    from apple_gpu import SmoothGPU
    from gpu_color import paired_tensor
    gpu=SmoothGPU(smooth,device=tools.device,dtype=tools.dtype)
    lookup={int(row):i for i,row in enumerate(scorer.train)}
    did=tools.tensor([lookup[int(i)]for i in scorer.direction.source_indices],True)
    sid=tools.tensor([lookup[int(i)]for i in scorer.derivatives.source_indices],True)
    desired=tools.tensor(scorer.target[scorer.train]);mass=tools.tensor(scorer.weights/scorer.weights.sum())
    fixed=tools.tensor(grid);tail=tools.tensor(vector[104:])
    calls=0;best_loss=float('inf')
    def loss(v):
        rgb=gpu.render(v)/16383
        p=paired_tensor(tools,rgb,fixed,scorer.model.identity)
        return (data_loss(tools,p,desired,mass)
            +scorer.direction.tensor_loss(tools,p[did],30)
            +scorer.derivatives.tensor_loss(tools,p[sid]))*255**2
    # Independent CPU64 gate uses the same smooth native relaxation, not an
    # assumption that it is identical to the true integer native renderer.
    smooth_rgb=smooth.render(vector)/16383
    predicted=scorer.model.predict_cpu(smooth_rgb,grid)
    from multiround import cpu_cost
    expected=cpu_cost(predicted,scorer.target[scorer.train],scorer.weights)
    expected+=scorer.direction.cost(predicted[did.cpu().numpy()],30)
    expected+=scorer.derivatives.cpu_cost(predicted[sid.cpu().numpy()])
    actual=float(loss(tools.tensor(vector)).detach().cpu())
    if abs(actual-expected)>max(.02,abs(expected)*3e-3):
        raise ValueError(f'Stack native GPU/CPU smooth loss mismatch {actual} vs {expected}')
    def fg(v):
        nonlocal calls,best_loss
        color=tools.tensor(v).requires_grad_(True)
        complete=tools.torch.cat([color,tail])
        value=loss(complete);value.backward();calls+=1
        f=float(value.detach().cpu());g=color.grad.detach().cpu().numpy().astype(float)
        if not np.isfinite(f) or not np.isfinite(g).all():raise ValueError('Nonfinite native stack gradient')
        best_loss=min(best_loss,f)
        if calls==1 or calls%10==0 or calls==evaluations:
            progress(stage='叠加：固定整数网格优化CC1/block13，Gamma冻结',evaluations=calls,max_evaluations=evaluations,
                loss_sample=('MPS 叠加原生 L-BFGS-B',calls,f,best_loss))
        return f,g
    seed=vector.copy()
    radius=np.r_[np.full(8,.08),np.full(96,.12)]
    lower=np.maximum(seed[:104]-radius,np.r_[np.full(4,-.999),np.full(4,.05),np.full(96,-6)])
    upper=np.minimum(seed[:104]+radius,np.r_[np.full(4,.996),np.full(4,3.98),np.full(96,6)])
    fitted=minimize(fg,np.clip(seed[:104],lower,upper),jac=True,method='L-BFGS-B',bounds=list(zip(lower,upper)),
        options=dict(maxfun=evaluations,maxiter=evaluations,maxls=20,ftol=1e-10,gtol=1e-6))
    best,best_base=seed,base;before=score=scorer.score(base,grid);selected_params=None
    attempts=[]
    for alpha in (1.,.5,.25):
        trial=seed.copy();trial[:104]+=alpha*(fitted.x-seed[:104])
        params=smooth.params(trial)
        if not np.array_equal(params['gamma_y'],smooth.gamma_shape.gamma):raise ValueError('Frozen Gamma changed')
        params['cc1'][4:]=2*np.minimum(1023,(params['cc1'][4:]+1)//2)
        candidate_base=render_native(params)
        proposal=scorer.score(candidate_base,grid)
        attempts.append(dict(alpha=alpha,score=proposal))
        if acceptable(score,proposal):best,best_base,score,selected_params=trial,candidate_base,proposal,params
    return best,best_base,selected_params,dict(before=before,after=score,calls=calls,attempts=attempts,
        solver_message=str(fitted.message),gamma_frozen=True,coordinate_and_response_gradients=True,
        cpu64_smooth_gate=dict(cpu=expected,gpu=actual),integer_native_acceptance=True)


def fields(params):
    from native_gamma import parameter_fields
    return parameter_fields(params)


def decode_model(entry,factory):
    """Independent inverse of the native BIN fields used by the compiler."""
    from edit_parameter_context import ParameterContext
    ctx=ParameterContext(factory)
    return ctx.build(**core.slot_native_parameters(ctx,entry))


def metrics(target,predicted):
    from perceptual import to_lab,de2000
    a,b=[np.clip(v,0,1)*255 for v in (target,predicted)]
    la,lb=to_lab(a),to_lab(b);ca,cb=[np.linalg.norm(v[:,1:],axis=1)for v in (la,lb)]
    mask=ca>=5
    ha,hb=[np.degrees(np.arctan2(v[:,2],v[:,1]))for v in (la,lb)]
    error=np.abs((hb-ha+180)%360-180)
    return dict(rgb_rmse=float(np.sqrt(np.mean((a-b)**2))),
        delta_e00_mean=float(de2000(la,lb).mean()),lightness_rmse=float(np.sqrt(np.mean((la[:,0]-lb[:,0])**2))),
        ab_rmse=float(np.sqrt(np.mean(np.sum((la[:,1:]-lb[:,1:])**2,axis=1)))),
        chroma_rmse=float(np.sqrt(np.mean((ca-cb)**2))),
        hue_mae_deg=float(error[mask].mean()) if mask.any() else None,
        target_chromatic_samples=int(mask.sum()),predicted_neutral_samples=int(np.sum(mask&(cb<5))),
        rgb_p95=float(np.percentile(np.abs(a-b),95)),rgb_max=float(np.max(np.abs(a-b))),
        hue_mask='fixed target C* >= 5; coverage loss reported explicitly')


def train(job,source,state,progress,settings, *, seed_entry=None):
    from fit_anchor_native import SmoothNative,vector_for,training_plan,report_metrics
    from edit_parameter_context import ParameterContext,RuntimeColor
    from gpu_tensor import TensorTools
    from hue_direction import HueDirectionBank
    from measured_response import get
    from grid_models import default_response
    from residual_grid import pack,unpack
    import grid_distillation as gd
    import torch
    if not __import__('gpu_runtime').available():raise RuntimeError('Stack training requires actual Apple Metal/MPS')
    started=time.time()
    source_key=json.loads((source/'grid_training.json').read_text())['key']
    parent_report,parent_grid,_=gd.load_result(source,source_key)
    protected_files=[source/n for n in ('fit/recipe.json','pairs.npz','native_config.json','pc_compensation.json','grid_training.json')]
    protected_files+=[source/'grid_distillation'/source_key/n for n in ('result.json','grid.payload')]
    protected={str(p):core.sha(p.read_bytes())for p in protected_files}
    for name in ('pairs.npz','input_audit.json','chart_target.json','target-image.bin','native_config.json','conversion_audit.json','pc_compensation.json'):
        shutil.copy2(source/name,job/name)
    (job/'fit').mkdir(exist_ok=True)
    shutil.copy2(source/'fit/recipe.json',job/'fit/recipe.json')
    recipe,initial_model=baseline.read_job(job)
    original_recipe=copy.deepcopy(recipe)
    if __import__('white_balance').active(__import__('white_balance').from_recipe(recipe)):
        raise ValueError('Stack continuation requires fixed zero white balance')
    with np.load(job/'pairs.npz',allow_pickle=False) as archive:data={k:archive[k]for k in archive.files}
    split=data['split'].astype(str);target=data['0_target']/16383
    selection=np.flatnonzero((split=='train')&(data['anchor_index']<0)&(data['sector16_index']<0))
    fitting=recipe['fitting'];options=fitting['search_options']
    train_ids,_,_,weights=training_plan(split,data['anchor_index'],fitting['group_total_weights'],data['sector16_index'],
        data['baseline_tonal_index'] if fitting.get('tonal_balance') else None,selection,data['sample_kind'],options)
    valid=np.flatnonzero(split=='valid')
    factory=RuntimeColor.from_capture(*baseline.for_job(job));ctx=ParameterContext(factory,native_gamma=True)
    if seed_entry is not None:
        from packed_training import canonical
        seed_entry=canonical(seed_entry)[0]
        initial_model=ctx.build(**core.slot_native_parameters(ctx,seed_entry))
        seed_params=core.slot_native_parameters(ctx,seed_entry)
        recipe['parameters'].update(fields({k:np.asarray(v) if k!='matrix_payload' else v for k,v in seed_params.items()}))
        recipe['fitting']['packed_seed_sha256']=core.sha(core.compiler.pack(core.compiler.config([seed_entry],5 if seed_entry['number']>12 else 4)))
        from fit_bin_joint import grid_from
        parent_grid=grid_from(seed_entry)
    vector=vector_for(ParameterContext(initial_model));smooth=SmoothNative(ctx,data['input'][train_ids])
    from native_gamma import parameter_values, from_raw
    gamma=parameter_values(recipe['parameters'])['gamma_y']
    if len(gamma)==128:gamma=2*from_raw(gamma)
    smooth.gamma_shape=FrozenGamma(gamma)
    params=dict(matrix_payload=bytes.fromhex(recipe['parameters']['matrix_780f_hex']),
        cc1=np.array(recipe['parameters']['cc1_direct_raw']),gamma_y=gamma.copy())
    response=default_response();model=get(response)
    direction=HueDirectionBank(data['design_srgb'],target,split,data['sample_kind'])
    derivatives=TargetDerivatives(data['design_srgb'],target,split,data['sample_kind'],settings['derivative_strength'])
    scorer=Scorer(model,target,train_ids,weights,direction,derivatives)
    tools=TensorTools('mps',torch.float32)
    # Exact integer rendering for candidate acceptance. Final selected BIN is
    # independently replayed below from decoded fields using the CPU model.
    def render(p):
        from compute_backend import render_native
        from patch_sampling import center_mean
        return center_mean(render_native(ctx.build(**p),data['input']))/16383
    base=render(params);grid=parent_grid.copy()
    def val(b,g):
        from multiround import cpu_cost
        return cpu_cost(model.predict_cpu(b[valid],g),target[valid])
    seed_base,seed_grid=base.copy(),grid.copy()
    seed_metrics=dict(train=scorer.score(base,grid),validation=val(base,grid))
    current=dict(params=params,vector=vector,base=base,grid=grid,label='parent',validation=seed_metrics['validation'])
    chosen=copy.deepcopy(current);rounds=[]
    for index in range(1,settings['rounds']+1):
        progress(round=index,total_rounds=settings['rounds'],stage='叠加训练：开始第%d轮'%index,gpu_backend='Apple Metal/MPS',state='running')
        vector,base,native_params,native_audit=native_update(tools,smooth,current['vector'],current['base'],current['grid'],scorer,render,progress,settings['native_evaluations'])
        params=current['params'] if native_params is None else native_params
        grid,continuous,grid_audit=optimize_grid(tools,base,current['grid'],scorer,progress,settings['grid_evaluations'])
        grid,rounding_audit=optimize_rounding(tools,base,grid,continuous,scorer,progress,
            settings['rounding_steps'],settings['block_budget'])
        validation=val(base,grid)
        current=dict(params=params,vector=vector,base=base,grid=grid,label='stack-round-%d'%index,validation=validation)
        if validation<chosen['validation']:chosen=copy.deepcopy(current)
        record=dict(round=index,native=native_audit,grid=grid_audit,rounding=rounding_audit,
            train=scorer.score(base,grid),validation=validation,selected_so_far=chosen['label'])
        rounds.append(record)
        folder=job/'stack_rounds'/str(index);folder.mkdir(parents=True,exist_ok=True)
        save(folder/'audit.json',record);save(folder/'parameters.json',fields(params));(folder/'grid.payload').write_bytes(pack(grid))
        save(job/'stack_progress.json',dict(settings=settings,seed=seed_metrics,rounds=rounds,selected=chosen['label']))
        print(json.dumps(dict(round=index,validation=validation,selected=chosen['label']),ensure_ascii=False),flush=True)
    if not np.array_equal(chosen['params']['gamma_y'],gamma):raise ValueError('Selected Gamma changed')
    stack_audit=dict(schema='r5-nc-stacked-fit/1',settings=settings,continued_from=source.name,
        parent_grid_key=source_key,parent_source_sha256=protected,seed=seed_metrics,rounds=rounds,
        selected=chosen['label'],selected_validation=chosen['validation'],selection='minimum fixed validation RGB MSE + .35*(2.55*DE00)^2; parent included',
        target_derivative='real TRAIN Lab vector first differences / actual design delta V; pseudo-Huber',
        hue_direction_strength=30,test_used_for_training_or_selection=False,gamma_frozen=True,
        implementation_sha256={name:core.sha(Path(__file__).with_name(name).read_bytes())
            for name in ('stack_training.py','stack_objective.py','hue_direction.py')})
    recipe['parameters'].update(fields(chosen['params']))
    recipe['fitting']['stack_experiment']=stack_audit
    recipe['fitting']['selected']=chosen['label']
    recipe['fitting']['training_pipeline'].append('actual-Hybrid-native-grid-DE00-direction30-derivative-quantization-stack')
    # Preserve normal search-options schema; experimental settings have their
    # own versioned field rather than silently overloading existing controls.
    recipe['fitting']['search_options']['hue_direction_strength']=30
    recipe['fitting']['search_options']['postfit_deburr']=False
    recipe['fitting']['candidate_domain']='actual-native-plus-packed-Hybrid-grid'
    # The legacy summary is native-only; keep it honest after changing native
    # parameters. Final-grid metrics are generated separately after selection.
    test_ids=np.flatnonzero(split=='test')
    from patch_sampling import center_mean
    exact_selected=center_mean(ctx.build(**chosen['params']).color_only(data['input']))/16383
    recipe['heldout']['after']=report_metrics(exact_selected[test_ids]*16383,data['0_target'][test_ids])
    save(job/'fit/recipe.json',recipe)
    progress(stage='叠加训练：转换整数原生参数、重建诊断PC并导出',state='running')
    entry=json.loads((source/'native_config.json').read_text())['entries'][0]
    result=core.finish_fit(job,entry['number'],entry['short_name'],entry['full_name'],131071)
    import pc_compensation
    pc=pc_compensation.generate(job)
    # generate() consumes this already fitted table; no extra fit or repair
    # can remove the explicit constraints after final validation selection.
    final_audit=dict(training_only=True,stack_experiment=stack_audit,
        hue_direction=direction.report(model.predict_cpu(chosen['base'][direction.source_indices],chosen['grid']),30),
        objective='actual target RGB + DE00 + HueDir30 + target derivative',
        limit_fraction=float(np.mean((chosen['grid']==-64)|(chosen['grid']==63))))
    report=gd.generate(job,response,objective='fuji-target',fitted_target=(chosen['grid'],final_audit))
    save(job/'grid_training.json',dict(status='done',phase='叠加训练最终整数网格完成',key=report['key'],finished=time.time()))
    config=gd.firmware_config(job,report['key'],configuration_only=True)
    binary=core.compiler.pack(config);decoded=core.compiler.unpack(binary)
    if core.compiler.pack(decoded)!=binary:raise ValueError('BIN independent decode/recompile mismatch')
    entry=decoded['entries'][0];decoded_native=decode_model(entry,factory)
    from patch_sampling import center_mean
    # Force CPU native replay for independent final verification.
    decoded_base=center_mean(decoded_native.color_only(data['input']))/16383
    if not np.array_equal(decoded_base,center_mean(ctx.build(**chosen['params']).color_only(data['input']))/16383):
        raise ValueError('BIN decoded native parameters do not match selected candidate')
    decoded_grid=np.asarray(entry['grid_5x9x9']['coefficients']).reshape(3,405).T
    if not np.array_equal(decoded_grid,chosen['grid']):raise ValueError('BIN decoded grid mismatch')
    # GPU integer native scoring must not change the final CPU64 validation conclusion.
    decoded_validation=val(decoded_base,decoded_grid)
    if abs(decoded_validation-chosen['validation'])>max(1e-7,abs(chosen['validation'])*1e-6):
        raise ValueError('Final CPU native replay differs from validation selection')
    final=model.predict_cpu(decoded_base,decoded_grid)
    parent=model.predict_cpu(seed_base,seed_grid)
    comparisons={}
    for name,mask in [('train',split=='train'),('validation',split=='valid'),('test',split=='test'),
        ('gray_train',(split=='train')&(data['anchor_index']>=4)&(data['anchor_index']<260))]:
        comparisons[name]=dict(samples=int(mask.sum()),parent=metrics(target[mask],parent[mask]),stack=metrics(target[mask],final[mask]),
            display_parent=core.tonal_comparison(target[mask],parent[mask]),display_stack=core.tonal_comparison(target[mask],final[mask]))
    for path,digest in protected.items():
        if core.sha(Path(path).read_bytes())!=digest:raise ValueError('Parent evidence changed during continuation: '+path)
    (job/'R5NATIVE.BIN').write_bytes(binary)
    save(job/'stack_comparison.json',comparisons)
    save(job/'stack_audit.json',dict(**stack_audit,seconds=time.time()-started,
        binary_sha256=core.sha(binary),bin_decode_recompile=True,decoded_native_cpu_replay=True,
        decoded_validation=decoded_validation,parent_files_unchanged=True))
    result.update(grid_key=report['key'],stack_experiment=stack_audit,
        pc_compensation=dict(enabled=True,sha256=core.sha((job/'pc_compensation.json').read_bytes()),metrics=pc['metrics']))
    state.update(status='done',phase='叠加训练完成；最终网格与目标对照已生成',result=result,finished=time.time())
    return result
