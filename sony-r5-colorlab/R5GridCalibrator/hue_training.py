"""Train-only RGB-hue residual experts with an immutable shared C1 response."""
import copy
import hashlib
import importlib
import numpy as np
import model
from coordinate_warp import coordinates
from quality import balanced_weights,enriched_metric,grouped_metrics,support_report
from perceptual import joint_residual,metrics as perceptual_metrics
from structured_training import arrays


def path_constraints(grids,baseline,gate=None,expert_module='hue_experts'):
    """Fixed RGB triplets and TRAIN grids, including smooth gate derivatives."""
    experts=importlib.import_module(expert_module)
    from structured_response import features as base_features,KIND_C1
    first=[];second=[];base_first=[];base_second=[];h=1/64
    shared=np.asarray(baseline['response_weights'])
    for axis in range(3):
        other=[i for i in range(3) if i!=axis];points=[]
        for t in np.linspace(1/32,31/32,31):
            for a in np.linspace(0,1,5):
                for b in np.linspace(0,1,5):
                    x=np.zeros(3);x[axis]=t;x[other]=[a,b];points.append(x)
        center=np.asarray(points);minus=center.copy();plus=center.copy();minus[:,axis]-=h;plus[:,axis]+=h
        for grid in grids:
            fs=[];bs=[]
            for x in [minus,center,plus]:
                d=model.delta(x,grid,baseline['coordinate_affine'],baseline.get('coordinate_warp'))
                fs.append(experts.features(x,d,gate));bs.append(base_features(x,d,KIND_C1)@shared)
            first.append((fs[2]-fs[0])/(2*h));second.append((fs[2]-2*fs[1]+fs[0])/h**2)
            base_first.append((bs[2]-bs[0])/(2*h));base_second.append((bs[2]-2*bs[1]+bs[0])/h**2)
    return dict(first=np.concatenate(first),second=np.concatenate(second),base_first=np.concatenate(base_first),base_second=np.concatenate(base_second))


def refine(pairs,baseline,progress=lambda s:None,device='mps',strengths=(.25,1.,4.),iterations=400,gate=None,on_candidate=None,expert_module='hue_experts'):
    if expert_module not in ('hue_experts','hue24_experts'):raise ValueError('未知色相残差方案')
    experts=importlib.import_module(expert_module)
    expert_count=24 if expert_module=='hue24_experts' else 3
    parameters=648 if expert_count==24 else 729
    from structured_response import KIND_C1
    from stock_reference import audit
    if baseline.get('response_basis')!=KIND_C1:raise ValueError('共享起点必须为C1分段响应模型')
    gate=copy.deepcopy(experts.GATE if gate is None else gate)
    experts.weights(np.array([[.5,.5,.5]]),gate)
    preflight=audit();x,y,ids,splits=arrays(pairs);tr=splits==0;va=splits==1;te=splits==2
    if min(tr.sum(),va.sum(),te.sum())<10:raise ValueError('训练、验证和测试各需至少10个色块')
    options=baseline['report']['optimization']['options']
    weights=balanced_weights(x,ids,splits,options['color_balance'],options.get('hue24_balance',False))
    shared=np.asarray(baseline['response_weights']);grids=[np.asarray(p['grid']) for p in pairs];train_ids=np.unique(ids[tr])
    paths=path_constraints([grids[i] for i in train_ids],baseline,gate,expert_module)
    d=np.empty_like(x[tr])
    for i in train_ids:
        keep=ids[tr]==i;d[keep]=model.delta(x[tr][keep],grids[i],baseline['coordinate_affine'],baseline.get('coordinate_warp'))
    def predict(m,mask):
        out=np.empty_like(x[mask])
        for i in np.unique(ids[mask]):
            keep=ids[mask]==i;out[keep]=model.predict(x[mask][keep],grids[i],m)
        return out
    def objective(p,mask):
        err=joint_residual(p,y[mask],options['robust_scale'],options['perceptual_mix'])
        return float(np.average(np.mean(err**2,axis=1),weights=weights[mask])*255**2)
    best=copy.deepcopy(baseline);base_score=objective(predict(best,va),va);best_score=base_score
    candidates=[dict(name=baseline['name'],validation_objective=base_score,unchanged_baseline=True)];runs=[]
    for strength in strengths:
        progress(f'{expert_count}色相残差联合训练 · 正则 {strength:g} · 最多{iterations}步')
        coef,note=experts.solve(x[tr],y[tr],d,weights[tr],shared,device=device,regularization=strength,iterations=iterations,gate=gate,path_constraints=paths,scale=options['robust_scale'],mix=options['perceptual_mix'])
        candidate={k:copy.deepcopy(v) for k,v in baseline.items() if k not in ('report','provenance')}
        candidate.update(schema=f'r5-grid-response-calibration/{6 if expert_count==24 else 5}',name=f'rgb-hue{expert_count}-residual-r{strength:g}',response_basis=experts.KIND,expert_weights=coef.tolist(),expert_gate=copy.deepcopy(gate))
        vp=predict(candidate,va);score=objective(vp,va)
        row=dict(name=candidate['name'],regularization=strength,validation_objective=score,validation=enriched_metric(vp,y[va]),training=enriched_metric(predict(candidate,tr),y[tr]))
        candidates.append(row);runs.append(dict(regularization=strength,**note))
        if on_candidate is not None:on_candidate(copy.deepcopy(candidate),copy.deepcopy(row),copy.deepcopy(note))
        if score<best_score:best=copy.deepcopy(candidate);best_score=score
    # Final reporting starts only after the validation-selected model is fixed.
    pred=predict(best,np.ones(len(x),bool));report=copy.deepcopy(baseline['report'])
    for k in ['display_comparison','perceptual_comparison','hue24_comparison','curvature_comparison','smoothness_summary']:report.pop(k,None)
    report['selected_model']=best['name']
    for k,mask in [('training',tr),('validation',va),('test',te)]:report[k]=enriched_metric(pred[mask],y[mask])
    report['baseline_test']=enriched_metric(x[te],y[te])
    report['grouped_test']=grouped_metrics(x,pred,y,te);report['grouped_test_24']=grouped_metrics(x,pred,y,te,24)
    report['quantized_test']=enriched_metric(np.rint(pred[te]*255)/255,y[te]);report['perceptual_test']=perceptual_metrics(pred[te],y[te])
    report['per_pair']=[dict(name=p.get('audit',{}).get('name',str(i+1)),role=p['role'],samples=int(sum(ids==i)),predicted=enriched_metric(pred[ids==i],y[ids==i]),baseline=enriched_metric(x[ids==i],y[ids==i])) for i,p in enumerate(pairs)]
    selected=best.get('response_basis')==experts.KIND
    report['coordinate_note']=f'共享C1响应与坐标固定；原生5×9×9查询保持。{expert_count}套色相残差输出完整RGB，输入门控混合后统一裁切；低彩度退回共享。'
    report['hue_experts']=dict(expert_count=expert_count,expert_module=expert_module,selected_experts=selected,shared_frozen=True,coordinates_frozen=True,shared_model=baseline['name'],shared_response_sha256=hashlib.sha256(shared.tobytes()).hexdigest(),parameters_trained=parameters,parameters_shared=243,gate=gate,candidates=candidates,runs=runs,initial_validation_objective=base_score,selected_validation_objective=best_score,strengths=list(strengths),iterations=iterations,stock04_preflight=preflight,selection='validation joint data loss only; test/repeat never select',path_regularization=dict(source='fixed RGB triplets and TRAIN probe grids only',first_rows=len(paths['first']),second_rows=len(paths['second']),step=1/64,includes_gate_derivatives=True,preclip=True),continuity='effective response C1; native lookup and final clip retain derivative kinks')
    # Old structured-stage report describes the frozen shared model, not the
    # expert stage. Keep it for provenance and label it explicitly.
    report['structured_response']['scope']='prior shared-model training only; frozen during hue-expert refinement'
    report['optimization']['options']['hue_experts']=selected
    report['optimization']['options']['hue_expert_count']=expert_count
    feats=(lambda xx,dd,s:experts.features(xx,dd,gate)) if selected else (lambda xx,dd,s:__import__('structured_response').features(xx,dd,KIND_C1))
    report['support_diagnostics']=support_report(x[tr],d,np.asarray(baseline['coordinate_affine']),feats,True,coordinate_values=coordinates(x[tr],baseline['coordinate_affine'],baseline.get('coordinate_warp')))
    report['warnings']=[s for s in report['warnings'] if '100%曲率' not in s and '曲率50%' not in s and '曲率，50%' not in s]
    report['warnings'].append(f'{expert_count}色相残差为经验候选，新增{parameters}参数；只识别混合响应，不保证各残差分别可唯一恢复。开发留出已多轮观察，仍需新场景验收。')
    report['warnings'].append('C1只针对有效响应场；门控和专家重叠区已纳入完整路径正则，不代表完整ISP无折点或所有色相单调。')
    best['validation_objective']=best_score;best['report']=report
    return best
