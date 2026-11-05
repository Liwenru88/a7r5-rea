"""Train-only hierarchical response refinement with unchanged native lookup.

Coordinates are frozen to the supplied empirical model. Original04 is used as
an independent indexing/interpolation/packing preflight, never as an RGB target.
"""
import copy
import numpy as np
import model
from coordinate_warp import coordinates,delta_at
from quality import balanced_weights,enriched_metric,grouped_metrics
from perceptual import joint_residual,metrics as perceptual_metrics


def arrays(pairs):
    xs=[];ys=[];ids=[];splits=[]
    for i,p in enumerate(pairs):
        xx=np.asarray(p['x'],float);yy=np.asarray(p['y'],float);b=np.asarray(p['buckets'])
        split=np.where(b<7,0,np.where(b<9,1,2))
        if p['role']=='validation':split[:]=1
        if p['role']=='test':split[:]=2
        xs.append(xx);ys.append(yy);ids.extend([i]*len(xx));splits.extend(split)
    return np.concatenate(xs),np.concatenate(ys),np.asarray(ids),np.asarray(splits)


def path_constraints(grids,affine,warp,kind=None):
    """Predeclared RGB lines and TRAIN probe grids only, no measured targets.

    Points straddle the response field's 0.5 knots. Penalize preclip correction,
    not a clipped output with zero derivative. These are soft curvature costs,
    not a proof of monotone hue or of all-domain bounded derivatives.
    """
    from structured_response import features,KIND_C1
    kind=kind or KIND_C1
    rows1=[];rows2=[];h=1/64
    for axis in range(3):
        other=[i for i in range(3) if i!=axis]
        points=[]
        for t in np.linspace(1/32,31/32,31):
            for a in np.linspace(0,1,5):
                for b in np.linspace(0,1,5):
                    xx=np.zeros(3);xx[axis]=t;xx[other]=[a,b];points.append(xx)
        center=np.asarray(points);plus=center.copy();minus=center.copy();plus[:,axis]+=h;minus[:,axis]-=h
        for grid in grids:
            fs=[]
            for xx in [minus,center,plus]:
                dd=delta_at(coordinates(xx,affine,warp),grid);fs.append(features(xx,dd,kind))
            rows1.append((fs[2]-fs[0])/(2*h));rows2.append((fs[2]-2*fs[1]+fs[0])/h**2)
    return dict(first=np.concatenate(rows1),second=np.concatenate(rows2))


def refine(pairs,initial,progress=lambda s:None,device=None,strengths=(.25,1.,4.),iterations=300,curvature_scales=(1.,),baseline_model=None,on_candidate=None):
    from stock_reference import audit
    from structured_response import KIND,KIND_C1,features,from_quadratic,solve,penalty_rates
    kind=KIND_C1
    for curve in curvature_scales:penalty_rates(kind,curve)
    if not curvature_scales:raise ValueError('至少需要一档曲率惩罚')
    if baseline_model is not None:
        if not np.array_equal(initial['coordinate_affine'],baseline_model['coordinate_affine']) or initial.get('coordinate_warp')!=baseline_model.get('coordinate_warp'):
            raise ValueError('基准模型必须使用相同冻结坐标')
    preflight=audit()
    options=initial['report']['optimization']['options']
    device=device or options.get('coordinate_device','cpu')
    x,y,ids,splits=arrays(pairs);tr=splits==0;va=splits==1;te=splits==2
    if min(tr.sum(),va.sum(),te.sum())<10:raise ValueError('训练、验证、测试各需至少10个色块')
    weights=balanced_weights(x,ids,splits,options['color_balance'],options.get('hue24_balance',False))
    affine=np.asarray(initial['coordinate_affine']);warp=initial.get('coordinate_warp');grids=[np.asarray(p['grid']) for p in pairs]
    # Only training input colors and the supplied fixed predictor initialize the
    # response fit. Test targets/colors/grids never enter this construction.
    train_ids=np.unique(ids[tr]);train_grids=[grids[i] for i in train_ids]
    paths=path_constraints(train_grids,affine,warp,kind)
    dd=np.empty_like(x[tr])
    for i in train_ids:
        keep=ids[tr]==i;dd[keep]=model.delta(x[tr][keep],grids[i],affine,warp)
    def predict(m,mask):
        out=np.empty_like(x[mask])
        for i in np.unique(ids[mask]):
            keep=ids[mask]==i;out[keep]=model.predict(x[mask][keep],grids[i],m)
        return out
    def objective(pred,mask):
        er=joint_residual(pred,y[mask],options['robust_scale'],options['perceptual_mix'])
        return float(np.average(np.mean(er**2,axis=1),weights=weights[mask])*255**2)
    best=copy.deepcopy(initial if baseline_model is None else baseline_model);base_score=objective(predict(best,va),va);best_score=base_score
    candidates=[dict(name='unchanged-previous-model',validation_objective=base_score)]
    if initial.get('response_basis') in (KIND,KIND_C1):raise ValueError('请选择先前二阶/仿射模型作为结构训练起点')
    old=np.asarray(initial['response_weights']);quad=np.zeros((30,3));quad[:len(old)]=old
    init=from_quadratic(quad,kind);runs=[]
    for strength,curve in [(s,c) for s in strengths for c in curvature_scales]:
        progress(f'分段响应训练 · 正则倍率 {strength:g} · 曲率 {curve:.0%} · 最多 {iterations} 步')
        coef,note=solve(x[tr],y[tr],dd,weights[tr],init,regularization=strength,device=device,iterations=iterations,scale=options['robust_scale'],mix=options['perceptual_mix'],path_constraints=paths,kind=kind,curvature_scale=curve)
        candidate={k:copy.deepcopy(v) for k,v in initial.items() if k not in ('report','provenance')}
        suffix='' if curve==1 else f'-c{curve*100:g}'
        candidate.update(schema='r5-grid-response-calibration/4',name=f'structured-c1-r{strength:g}'+suffix,response_basis=kind,response_weights=coef.tolist(),smooth=True,curvature_scale=float(curve))
        vp=predict(candidate,va);value=objective(vp,va)
        candidates.append(dict(name=candidate['name'],regularization=strength,curvature_scale=float(curve),validation_objective=value,validation=enriched_metric(vp,y[va]),training=enriched_metric(predict(candidate,tr),y[tr])))
        runs.append(dict(regularization=strength,**note))
        if on_candidate is not None:on_candidate(copy.deepcopy(candidate),copy.deepcopy(candidates[-1]),copy.deepcopy(note))
        if value<best_score:best=copy.deepcopy(candidate);best_score=value
    # No selection or fitting after this point: the first use of test samples is
    # final reporting for the already selected parameters.
    pred=predict(best,np.ones(len(x),bool));report=copy.deepcopy(initial['report'])
    for k in ['display_comparison','perceptual_comparison','hue24_comparison']:report.pop(k,None)
    report['selected_model']=best.get('name',initial['report']['selected_model'])
    for k,mask in [('training',tr),('validation',va),('test',te)]:report[k]=enriched_metric(pred[mask],y[mask])
    report['grouped_test']=grouped_metrics(x,pred,y,te);report['grouped_test_24']=grouped_metrics(x,pred,y,te,24)
    report['quantized_test']=enriched_metric(np.rint(pred[te]*255)/255,y[te]);report['perceptual_test']=perceptual_metrics(pred[te],y[te])
    report['per_pair']=[dict(name=p.get('audit',{}).get('name',str(i+1)),role=p['role'],samples=int(sum(ids==i)),predicted=enriched_metric(pred[ids==i],y[ids==i]),baseline=enriched_metric(x[ids==i],y[ids==i])) for i,p in enumerate(pairs)]
    report['coordinate_note']='坐标固定于输入模型；原生5×9×9查询保持。RGB响应采用C1连续分段粗结构＋局部残差候选，验证集可保留原模型。C1仅指响应场，不包含网格单元边界。'
    selected=best.get('response_basis')==kind
    report['structured_response']=dict(initial_model=initial.get('name',initial['report']['selected_model']),fallback_model=(baseline_model or initial).get('name'),basis=kind,coarse_nodes=8,detail_nodes=19,parameters=243,coordinates_frozen=True,selected_structured=selected,initial_validation_objective=base_score,selected_validation_objective=best_score,candidates=candidates,runs=runs,regularization_strengths=list(strengths),curvature_scales=list(curvature_scales),selected_curvature_scale=best.get('curvature_scale',1.),iterations=iterations,path_regularization=dict(source='fixed dense RGB axis triplets and training probe grids only',first_rows=len(paths['first']),second_rows=len(paths['second']),step=1/64,centers_per_axis=31,preclip=True),stock04_preflight=preflight,continuity='C1 smoothstep response field; full correction retains native lookup kinks; no monotone hue guarantee',selection='validation data loss only; test never selects model')
    report['optimization']['options']['structured_response']=True
    report['optimization']['options']['curvature_scale']=best.get('curvature_scale',1.)
    # Recompute feature rank and node support with the actual selected basis.
    from quality import support_report
    funcs=(lambda xx,d,s:features(xx,d,kind)) if selected else model.features
    report['support_diagnostics']=support_report(x[tr],dd,affine,funcs,'quadratic' if selected or best.get('response_basis')=='rgb-quadratic' else best['smooth'],coordinate_values=coordinates(x[tr],affine,warp))
    report['warnings'].append('分段结构响应仍是经验预测；原04校验不是新增实拍真值。11/12已被开发观察，需新探针才能做独立验收。')
    best['validation_objective']=best_score;best['report']=report
    return best
