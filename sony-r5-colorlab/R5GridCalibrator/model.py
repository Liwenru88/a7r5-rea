"""Empirical grid response calibration; no assertion of recovered ISP internals."""
import numpy as np
from scipy.optimize import least_squares
from quality import balanced_weights, response_solve, enriched_metric, grouped_metrics, support_report, weighting_report

SCHEMA='r5-grid-response-calibration/1'
BT=np.array([[.299,.587,.114],[-.299/(2*.886),-.587/(2*.886),.5],[.5,-.587/(2*.701),-.114/(2*.701)]])*255/np.array([219,224,224])[:,None]
OFFSET=np.array([-16/219,0,0])

def delta(rgb, grid, affine,warp=None):
    from coordinate_warp import coordinates
    c=coordinates(rgb,affine,warp)
    a=np.clip(c*np.array([4,8,8])+[0,4,4],0,[4,8,8])
    lo=np.minimum(np.floor(a).astype(int),[3,7,7]); f=a-lo
    out=np.zeros_like(rgb,dtype=float);g=np.asarray(grid).reshape(405,3)/256
    for y in (0,1):
        for u in (0,1):
            for v in (0,1):
                w=(f[:,0] if y else 1-f[:,0])*(f[:,1] if u else 1-f[:,1])*(f[:,2] if v else 1-f[:,2])
                out+=w[:,None]*g[(lo[:,0]+y)*81+(lo[:,1]+u)*9+lo[:,2]+v]
    return out

def features(x,d,smooth=False):
    if not smooth:return d
    # No intercept: a zero grid predicts exactly the baseline image.
    z=np.asarray(x)-.5
    parts=[d,np.einsum('ni,nj->nij',d,z).reshape(-1,9)]
    if smooth=='quadratic':
        q=np.column_stack([z[:,0]**2,z[:,1]**2,z[:,2]**2,z[:,0]*z[:,1],z[:,0]*z[:,2],z[:,1]*z[:,2]])
        parts.append(np.einsum('ni,nj->nij',d,q).reshape(-1,18))
    return np.concatenate(parts,axis=1)

def predict(rgb,grid,model):
    d=delta(np.asarray(rgb),grid,model['coordinate_affine'],model.get('coordinate_warp'))
    if model.get('response_basis')=='rgb-hue-experts-c1/1':
        from hue_experts import predict_correction
        return np.clip(np.asarray(rgb)+predict_correction(np.asarray(rgb),d,np.asarray(model['response_weights']),np.asarray(model['expert_weights']),model.get('expert_gate')),0,1)
    if model.get('response_basis')=='rgb-hue24-residual/1':
        from hue24_experts import predict_correction
        return np.clip(np.asarray(rgb)+predict_correction(np.asarray(rgb),d,np.asarray(model['response_weights']),np.asarray(model['expert_weights']),model.get('expert_gate')),0,1)
    if model.get('response_basis') in ('rgb-hierarchical-hat-3x3x3','rgb-hierarchical-c1-3x3x3'):
        from structured_response import features as structured_features
        return np.clip(np.asarray(rgb)+structured_features(np.asarray(rgb),d,model['response_basis'])@np.asarray(model['response_weights']),0,1)
    return np.clip(np.asarray(rgb)+features(np.asarray(rgb),d,'quadratic' if model.get('response_basis')=='rgb-quadratic' else model['smooth'])@np.asarray(model['response_weights']),0,1)

def metric(pred,target):
    return enriched_metric(pred,target)


def optimization_options(value=None):
    defaults=dict(max_nfev=200,starts=4,alternations=3,samples_per_pair=1000,robust_scale=3,color_balance=True,adaptive=True,coordinate_device="mps",response_degree=2,hue24_balance=True,perceptual_mix=1,nonlinear_coordinates=True,structured_response=True,curvature_scale=.5,hue_experts=False,hue_expert_count=3)
    if value is not None:
        if type(value) is not dict or set(value)-set(defaults):raise ValueError('未知优化选项')
        defaults.update(value)
    for key,lo,hi in [('max_nfev',10,1000),('starts',1,8),('alternations',1,6),('samples_per_pair',40,2000)]:
        if type(defaults[key]) is not int or not lo<=defaults[key]<=hi:raise ValueError(key+' 超出允许范围')
    if type(defaults['robust_scale']) not in (int,float) or not np.isfinite(defaults['robust_scale']) or not 0<=defaults['robust_scale']<=20:raise ValueError('robust_scale 超出允许范围')
    if type(defaults['response_degree']) is not int or defaults['response_degree'] not in (1,2):raise ValueError('response_degree 必须为1或2')
    for key in ('color_balance','adaptive','hue24_balance','nonlinear_coordinates','structured_response','hue_experts'):
        if type(defaults[key]) is not bool:raise ValueError(key+' 必须为布尔值')
    if type(defaults['perceptual_mix']) not in (int,float) or not np.isfinite(defaults['perceptual_mix']) or not 0<=defaults['perceptual_mix']<=10:raise ValueError('perceptual_mix 超出范围')
    if defaults['coordinate_device'] not in ('cpu','mps'):raise ValueError('coordinate_device 必须为 cpu 或 mps')
    if defaults['nonlinear_coordinates'] and (defaults['response_degree']!=2 or defaults['coordinate_device']!='mps'):raise ValueError('非线性坐标需要二阶响应和Apple MPS')
    if defaults['structured_response'] and defaults['response_degree']!=2:raise ValueError('分段结构响应需要二阶响应作为起点')
    if defaults['hue_experts'] and not defaults['structured_response']:raise ValueError('色相专家需要先启用C1分段结构响应')
    if type(defaults['hue_expert_count']) is not int or defaults['hue_expert_count'] not in (3,24):raise ValueError('色相残差数量必须为3或24')
    if type(defaults['curvature_scale']) not in (int,float) or not np.isfinite(defaults['curvature_scale']) or not 0<=defaults['curvature_scale']<=1:raise ValueError('curvature_scale 必须在0–1之间')
    return defaults


def stratified_indices(x,indices,limit):
    # RGB-derived luminance/hue/saturation; only baseline TRAIN colors are read.
    colors=x[indices];hi=colors.max(axis=1);lo=colors.min(axis=1);span=hi-lo
    hue=np.zeros(len(colors));chromatic=span>1e-8
    channel=colors.argmax(axis=1)
    for c in range(3):
        mask=chromatic & (channel==c)
        hue[mask]=((colors[mask,(c+1)%3]-colors[mask,(c+2)%3])/span[mask]+2*c)%6
    lum=colors@np.array([.2126,.7152,.0722]);sat=span/np.maximum(hi,1e-8)
    keys=np.minimum((lum*6).astype(int),5)*48+np.minimum((hue*2).astype(int),11)*4+np.minimum((sat*4).astype(int),3)
    groups=[list(indices[keys==k]) for k in np.unique(keys)]
    rng=np.random.default_rng(20261024)
    for group in groups:rng.shuffle(group)
    chosen=[]
    while groups and len(chosen)<limit:
        for group in groups:
            if len(chosen)>=limit:break
            chosen.append(group.pop())
        groups=[g for g in groups if g]
    return np.array(chosen,dtype=int)


def fit(pairs,progress=lambda value:None,refine=True,options=None):
    options=optimization_options(options)
    if not pairs:raise ValueError('请先添加样本')
    if not any(p['role']=='train' for p in pairs):raise ValueError('至少一组训练样本')
    modes=(False,True,'quadratic') if options['response_degree']==2 else (False,True)
    affine=np.column_stack([BT,OFFSET]);grids=[np.asarray(p['grid']) for p in pairs]
    xs=[];ys=[];ids=[];splits=[];weights=[]
    for i,p in enumerate(pairs):
        x=np.asarray(p['x']);y=np.asarray(p['y']);n=len(x)
        if n<40:raise ValueError('每组至少需要40个有效色块')
        # Block split fixed by image position, not shuffled neighboring pixels.
        bucket=np.asarray(p['buckets']);split=np.where(bucket<7,0,np.where(bucket<9,1,2))
        if p['role']=='validation':split[:]=1
        if p['role']=='test':split[:]=2
        xs.append(x);ys.append(y);ids.extend([i]*n);splits.extend(split);weights.extend([1/np.sqrt(n)]*n)
    x=np.concatenate(xs);y=np.concatenate(ys);ids=np.asarray(ids);splits=np.asarray(splits);weights=np.asarray(weights)
    weights=balanced_weights(x,ids,splits,options["color_balance"],hue24=options["hue24_balance"])
    tr=splits==0;va=splits==1;te=splits==2
    if min(tr.sum(),va.sum(),te.sum())<10:raise ValueError('训练、验证、测试各需至少10个块；请增加样本')
    def deltas(a):
        out=np.empty_like(x)
        for i,g in enumerate(grids):out[ids==i]=delta(x[ids==i],g,a)
        return out
    # Bounded coordinate search uses a deterministic subset of TRAINING only.
    search=np.zeros(len(x),bool)
    for i in range(len(pairs)):
        indices=np.flatnonzero(tr & (ids==i));search[stratified_indices(x,indices,options["samples_per_pair"])]=True
    def solve(d,smooth,mask=None):
        mask=tr if mask is None else mask
        coef,pred,note=response_solve(x,y,d,smooth,features,weights,mask,options['robust_scale'],options['perceptual_mix'])
        return coef,pred
    def score(pred,mask):
        e=(pred[mask]-y[mask])*255;sc=options['robust_scale']
        loss=2*sc**2*(np.sqrt(1+(e/sc)**2)-1) if sc else e*e
        if options['perceptual_mix']:
            from perceptual import joint_residual
            loss=(joint_residual(pred[mask],y[mask],sc,options['perceptual_mix'])*255)**2
        return float(np.sum(loss.mean(1)*weights[mask])/np.sum(weights[mask]))
    def candidate(a,smooth,name):
        d=deltas(a);coef,pred=solve(d,smooth)
        return dict(name=name,coordinate_affine=a.tolist(),smooth=bool(smooth),response_basis='rgb-quadratic' if smooth=='quadratic' else ('rgb-linear' if smooth else 'constant'),response_weights=coef.tolist(),validation=metric(pred[va],y[va]),training=metric(pred[tr],y[tr]),validation_objective=score(pred,va)),pred
    progress('拟合固定坐标响应与平滑响应')
    candidates=[]
    for smooth in modes:candidates.append(candidate(affine,smooth,'fixed-quadratic' if smooth=='quadratic' else ('fixed-smooth' if smooth else 'fixed-matrix')))
    coord_note='未请求坐标微调'
    # Constant-axis probes cannot identify coordinates: variation across grid nodes required.
    spatial_variation=max(float(np.std(g.reshape(405,3),axis=0).max()) for i,g in enumerate(grids) if np.any(tr & (ids==i)))
    diagnostics=[]
    if refine and spatial_variation>1:
        rng=np.random.default_rng(20261024)
        starts=[affine.copy()]+[affine+rng.uniform(-.12,.12,affine.shape) for _ in range(options['starts']-1)]
        lower=(affine-.3).ravel();upper=(affine+.3).ravel()
        sx=x[search];sy=y[search];si=ids[search];sw=np.sqrt(weights[search,None])
        def search_delta(a):
            out=np.empty_like(sx)
            for i,g in enumerate(grids):
                mask=si==i
                if mask.any():out[mask]=delta(sx[mask],g,a)
            return out
        for start_number,initial in enumerate(starts,1):
            for smooth in modes:
                a=initial.copy();local_search=search.copy()
                for turn in range(1,options['alternations']+1):
                    progress(f'起点 {start_number}/{options["starts"]} · {"颜色相关响应" if smooth else "矩阵响应"} · 交替 {turn}/{options["alternations"]} · 每轮最多 {options["max_nfev"]} 次评估')
                    # Conditional response solve, then coordinate update with response fixed.
                    coef,initial_pred=solve(deltas(a),smooth,local_search)
                    # Add high-error TRAIN samples only, retaining all original strata.
                    if options['adaptive'] and turn>1:
                        err=np.mean((initial_pred-y)**2,axis=1)
                        for pid in range(len(pairs)):
                            pool=np.flatnonzero(tr&(ids==pid)&~local_search)
                            count=min(len(pool),max(1,options['samples_per_pair']//4))
                            if count:local_search[pool[np.argsort(err[pool],kind='stable')[-count:]]]=True
                        coef,_=solve(deltas(a),smooth,local_search)
                    sx=x[local_search];sy=y[local_search];si=ids[local_search];sw=np.sqrt(weights[local_search,None])
                    calls=[0]
                    def residual(flat):
                        calls[0]+=1
                        d=search_delta(flat.reshape(3,4))
                        from perceptual import joint_residual
                        pred=np.clip(sx+features(sx,d,smooth)@coef,0,1)
                        e=joint_residual(pred,sy,options['robust_scale'],options['perceptual_mix'])
                        return np.r_[(e*sw).ravel(),.02*(flat-affine.ravel())]
                    if options['coordinate_device']=='mps':
                        from gpu_coordinates import solve as gpu_solve
                        opt=gpu_solve(sx,sy,si,grids,coef,smooth,sw,affine,a.ravel(),lower,upper,options['max_nfev'],options['robust_scale'],residual,perceptual_mix=options['perceptual_mix'])
                    else:
                        opt=least_squares(residual,a.ravel(),bounds=(lower,upper),max_nfev=options['max_nfev'],ftol=1e-6)
                    a=opt.x.reshape(3,4)
                    name=f'refined-{"quadratic" if smooth=="quadratic" else ("smooth" if smooth else "matrix")}-s{start_number}-a{turn}'
                    candidates.append(candidate(a,smooth,name))
                    diagnostics.append(dict(candidate=name,gpu=getattr(opt,'gpu_audit',None),search_samples=int(local_search.sum()),start=start_number,alternation=turn,smooth=smooth,nfev=int(opt.nfev),residual_calls=calls[0],status=int(opt.status),success=bool(opt.success),message=str(opt.message),cost=float(opt.cost),optimality=float(opt.optimality),bound_parameters=int(np.count_nonzero(opt.active_mask)),budget_exhausted=bool(opt.status==0)))
        coord_note='多起点、训练颜色分层抽样、响应与坐标交替优化；每轮验证选模，测试不参与。局部收敛不等于唯一ISP解'
    elif refine:coord_note='网格缺少节点变化，坐标不可辨识；保持暂定BT.601坐标'
    best,pred=min(candidates,key=lambda v:v[0]['validation_objective'])
    d=deltas(np.asarray(best['coordinate_affine']));sing=np.linalg.svd(d[tr],compute_uv=False)
    rank=int(np.linalg.matrix_rank(d[tr],tol=max(float(sing[0])*1e-3,1e-8)))
    warnings=[]
    if any(d["budget_exhausted"] for d in diagnostics):warnings.append("部分坐标求解达到评估上限，可增大预算后比较验证误差；不保证更准确")
    if rank<3:warnings.append('网格探针通道激励不足：只能约束已激励方向，需三轴独立探针')
    if len(pairs)<2:warnings.append('只有一对图：空间留出不能代替独立场景/探针验证')
    if not any(p['role']=='test' for p in pairs):warnings.append('测试为同图空间留出，尚无独立测试图')
    observed=float(np.sqrt(np.mean(((y-x)*255)**2)))
    if observed<.8:warnings.append('图像差异低于0.8级：可能网格未生效或被噪声掩盖，不足以恢复可靠响应')
    basepred=np.clip(x+deltas(affine),0,1)
    per_pair=[]
    for i,p in enumerate(pairs):
        keep=ids==i
        per_pair.append(dict(name=p.get('audit',{}).get('name',str(i+1)),role=p['role'],samples=int(keep.sum()),predicted=metric(pred[keep],y[keep]),baseline=metric(x[keep],y[keep])))
    coords=x[tr]@np.asarray(best['coordinate_affine'])[:,:3].T+np.asarray(best['coordinate_affine'])[:,3]
    cells=np.floor(np.clip(coords*[4,8,8]+[0,4,4],0,[3.99999,7.99999,7.99999])).astype(int)
    occupied=len(np.unique(cells,axis=0))
    coverage=dict(occupied_cells=occupied,total_cells=256,fraction=occupied/256,
                  coordinate_min=coords.min(axis=0).tolist(),coordinate_max=coords.max(axis=0).tolist())
    if occupied<64:warnings.append('训练颜色覆盖少于四分之一网格单元，未覆盖区域仍是外推')
    test_error=metric(pred[te],y[te])['rmse']
    if test_error>=metric(basepred[te],y[te])['rmse']:warnings.append('留出测试未优于原暂定模型；当前结果不应作为更准确模型替换')
    if test_error>=metric(x[te],y[te])['rmse']:warnings.append('留出测试未优于零修正，尚未证明模型可预测实际网格效果')
    support=support_report(x[tr],d[tr],np.asarray(best['coordinate_affine']),features,'quadratic' if best.get('response_basis')=='rgb-quadratic' else best['smooth'])
    if support['response_feature_rank']<support['response_feature_columns']:warnings.append('完整响应特征秩不足：正则化不能替代新增独立探针/颜色')
    selected=dict(best);selected.pop('training');selected.pop('validation');selected['schema']='r5-grid-response-calibration/2' if selected.get('response_basis')=='rgb-quadratic' else SCHEMA
    report=dict(optimization=dict(options=options,search_samples=int(search.sum()),sampling="training-only H/L/S strata + high-error additions",selection_objective=('24 equal hue-sector and pair-balanced ' if options['hue24_balance'] else 'pair-balanced color-density weighted ')+('soft-L1' if options['robust_scale'] else 'squared RGB'),runs=diagnostics),selected_model=best['name'],training=metric(pred[tr],y[tr]),validation=metric(pred[va],y[va]),test=metric(pred[te],y[te]),
                baseline_test=metric(x[te],y[te]),legacy_identity_test=metric(basepred[te],y[te]),
                counts=dict(train=int(tr.sum()),validation=int(va.sum()),test=int(te.sum()),pairs=len(pairs)),
                per_pair=per_pair,coordinate_coverage=coverage,excitation_rank=rank,singular_values=sing.tolist(),warnings=warnings,coordinate_note=coord_note,
                observed_change_rmse=observed,candidates=[a for a,_ in candidates],
                grouped_test=grouped_metrics(x,pred,y,te),
                grouped_test_24=grouped_metrics(x,pred,y,te,hue_bins=24),
                weighting=weighting_report(x,ids,splits,weights),
                quantized_test=metric(np.rint(pred[te]*255)/255,y[te]),
                quantization_note='8-bit PC output rounding only; not firmware integer ISP validation',
                support_diagnostics=support,
                acceptance='empirical fit only; held-out image errors do not establish unique ISP recovery')
    if options['perceptual_mix']:
        from perceptual import metrics as perceptual_metrics
        report['perceptual_test']=perceptual_metrics(pred[te],y[te])
        report['optimization']['selection_objective']+=' + OKLab soft-L1 (scale0.03)'
    selected['report']=report
    if options['nonlinear_coordinates']:
        from warp_training import refine as refine_warp
        if selected.get('response_basis')=='rgb-quadratic':selected=refine_warp(pairs,selected,progress)
        else:selected['report']['warnings'].append('验证集选择了低阶响应，保留该模型，未强制进入非线性坐标训练。')
    if options['structured_response']:
        from structured_training import refine as refine_structured
        selected=refine_structured(pairs,selected,progress,device=options['coordinate_device'],curvature_scales=(options['curvature_scale'],))
    if options['hue_experts']:
        if selected.get('response_basis')=='rgb-hierarchical-c1-3x3x3':
            from hue_training import refine as refine_hue
            selected=refine_hue(pairs,selected,progress,device=options['coordinate_device'],expert_module='hue24_experts' if options['hue_expert_count']==24 else 'hue_experts')
        else:selected['report']['warnings'].append('验证集未采用C1共享响应，已跳过三专家训练并保留所选模型。')
    progress('完成')
    return selected
