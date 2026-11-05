"""Train/validation-only warp/response alternation on top of an affine fit."""
import copy
import numpy as np
import model
from coordinate_warp import KIND,coordinates,delta_at,solve_gpu,certificate
from perceptual import joint_residual,metrics as perceptual_metrics
from quality import balanced_weights,response_solve,enriched_metric,grouped_metrics,support_report

def refine(pairs,initial,progress=lambda s:None,starts=2,turns=3,iterations=100):
    if initial.get('response_basis')!='rgb-quadratic':raise ValueError('nonlinear coordinate refinement requires quadratic response')
    options=initial['report']['optimization']['options']
    if options.get('coordinate_device')!='mps':raise ValueError('nonlinear coordinate training currently requires Apple MPS')
    xs=[];ys=[];ids=[];splits=[]
    for i,p in enumerate(pairs):
        x=np.asarray(p['x']);b=np.asarray(p['buckets']);split=np.where(b<7,0,np.where(b<9,1,2))
        if p['role']=='validation':split[:]=1
        if p['role']=='test':split[:]=2
        xs.append(x);ys.append(np.asarray(p['y']));ids.extend([i]*len(x));splits.extend(split)
    x=np.concatenate(xs);y=np.concatenate(ys);ids=np.array(ids);splits=np.array(splits);tr=splits==0;va=splits==1;te=splits==2
    weights=balanced_weights(x,ids,splits,options['color_balance'],options.get('hue24_balance',False));affine=np.asarray(initial['coordinate_affine']);grids=[np.asarray(p['grid']) for p in pairs]
    search=np.zeros(len(x),bool)
    for i in range(len(pairs)):
        pool=np.flatnonzero(tr&(ids==i));search[model.stratified_indices(x,pool,options['samples_per_pair'])]=True
    def predict(m):
        pred=np.empty_like(x)
        for i,g in enumerate(grids):
            keep=ids==i;pred[keep]=model.predict(x[keep],g,m)
        return pred
    def score(pred,mask):
        error=joint_residual(pred[mask],y[mask],options['robust_scale'],options['perceptual_mix'])
        return float(np.average(np.mean(error**2,axis=1),weights=weights[mask])*255**2)
    base=copy.deepcopy(initial);pred=predict(base);best=base;best_score=score(pred,va);candidates=[dict(name='unchanged-affine',validation_objective=best_score,validation=enriched_metric(pred[va],y[va]))];runs=[]
    rng=np.random.default_rng(20261102)
    for start in range(starts):
        raw=np.zeros((3,3,3,3)) if start==0 else rng.normal(0,.02,(3,3,3,3))
        coef=np.asarray(initial['response_weights'])
        for turn in range(turns):
            progress(f'非线性坐标 · 起点 {start+1}/{starts} · 坐标/响应交替 {turn+1}/{turns}')
            raw,controls,note=solve_gpu(x[search],y[search],ids[search],grids,coef,affine,raw,weights[search],options['robust_scale'],options['perceptual_mix'],iterations)
            warp=dict(kind=KIND,control=controls.tolist());d=np.empty_like(x)
            for i,g in enumerate(grids):
                keep=ids==i;d[keep]=delta_at(coordinates(x[keep],affine,warp),g)
            coef,pred,_=response_solve(x,y,d,'quadratic',model.features,weights,tr,options['robust_scale'],options['perceptual_mix'])
            candidate={k:v for k,v in initial.items() if k not in ('report','provenance')};candidate.update(coordinate_warp=warp,response_weights=coef.tolist(),schema='r5-grid-response-calibration/3',name=f'nonlinear-bspline-s{start+1}-a{turn+1}')
            value=score(pred,va);candidates.append(dict(name=candidate['name'],validation_objective=value,validation=enriched_metric(pred[va],y[va]),training=enriched_metric(pred[tr],y[tr])))
            # Compare candidates by validation only. Test colors/targets do not influence search.
            if value<best_score:best_score=value;best=copy.deepcopy(candidate)
            runs.append(dict(start=start+1,turn=turn+1,**note))
    pred=predict(best);report=copy.deepcopy(initial['report'])
    # Remove inherited summaries of unrelated model comparisons; worker builds fresh ones.
    for key in ['display_comparison','perceptual_comparison','hue24_comparison']:report.pop(key,None)
    report['selected_model']=best.get('name','unchanged-affine');report['coordinate_note']='仿射坐标＋27控制点二次张量B样条；节点排列/原生网格保持。幅度限制及全域导数界防止折叠；测试不选模。'
    for key,mask in [('training',tr),('validation',va),('test',te)]:report[key]=enriched_metric(pred[mask],y[mask])
    report['grouped_test']=grouped_metrics(x,pred,y,te);report['grouped_test_24']=grouped_metrics(x,pred,y,te,24);report['quantized_test']=enriched_metric(np.rint(pred[te]*255)/255,y[te]);report['perceptual_test']=perceptual_metrics(pred[te],y[te])
    report['per_pair']=[dict(name=p.get('audit',{}).get('name',str(i+1)),role=p['role'],samples=int(sum(ids==i)),predicted=enriched_metric(pred[ids==i],y[ids==i]),baseline=enriched_metric(x[ids==i],y[ids==i])) for i,p in enumerate(pairs)]
    c=coordinates(x[tr],affine,best.get('coordinate_warp'));cells=np.floor(np.clip(c*[4,8,8]+[0,4,4],0,[3.99999,7.99999,7.99999])).astype(int);occupied=len(np.unique(cells,axis=0));report['coordinate_coverage']=dict(occupied_cells=occupied,total_cells=256,fraction=occupied/256,coordinate_min=c.min(0).tolist(),coordinate_max=c.max(0).tolist())
    report['nonlinear_coordinates']=dict(initial_model=initial['report']['selected_model'],initial_validation_objective=candidates[0]['validation_objective'],selected_validation_objective=best_score,options=dict(starts=starts,turns=turns,iterations=iterations,control_nodes=[3,3,3],degree=2,maximum_displacement=.06,relative_derivative_bound=.45,regularization=dict(magnitude=.001,gradient=.003,curvature=.01)),candidates=candidates,runs=runs,selected_warp=bool(best.get('coordinate_warp')),certificate=certificate(best['coordinate_warp']['control'],affine) if best.get('coordinate_warp') else None)
    report['optimization']['options']['nonlinear_coordinates']=True
    # Recompute support with warped coordinates, not the inherited affine estimate.
    dd=np.empty_like(x[tr]);train_ids=ids[tr]
    for i,g in enumerate(grids):
        keep=train_ids==i;dd[keep]=delta_at(c[keep],g)
    support=support_report(x[tr],dd,affine,model.features,'quadratic',coordinate_values=c);report['support_diagnostics']=support
    report['warnings'].append('非线性坐标只由现有渐变探针约束，未触及区域仍为外推；11/12已被开发观察，不能代替新探针盲测。')
    best['validation_objective']=best_score;best['report']=report
    return best
