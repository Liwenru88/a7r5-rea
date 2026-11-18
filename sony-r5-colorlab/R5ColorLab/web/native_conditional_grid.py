"""固定真实原生前端的条件整数网格优化；完整渐变约束与灰阶节点冻结。"""
import copy,time
from pathlib import Path
import numpy as np
import torch
from gpu_tensor import TensorTools
from measured_response import get
from native_solver import blob,save,predict,combined_metrics
from native_scoring import color_metrics
from native_four_experiment import ste,quantile95
from native_objective_research import PhotoBank,PhotoProtection,self_rounded
from fit_bin_joint import grid_from
from stack_objective import de00_squared


def active_nodes(ids,gray,freeze_gray):
    protected=np.unique(ids[gray])
    active=np.ones((405,3))
    if freeze_gray:active[protected]=0
    return active,protected


def fit_grid(data,gate,seed,output,*,steps=600,lr=.05,rho_initial=100.,progress=None,interior_margin=.002,freeze_gray=True,full_photos=False,training_geometry=None,checkpoint=50,colour_buckets=False):
    if not torch.backends.mps.is_available():raise RuntimeError('条件网格需要MPS')
    output=Path(output);output.mkdir(parents=True,exist_ok=False);start=time.monotonic()
    tools=TensorTools('mps',torch.float32);response=get(gate.response)
    from packed_training import native_prediction
    parts=[data.inputs[data.train]];n=int(data.train.sum());photo=None
    if data.photos:
        bank_type=PhotoBank
        if full_photos:
            from native_full_photos import FullPhotoBank
            bank_type=FullPhotoBank
        photo=bank_type(data.photos,per_region=256,seed=42);photo.reference=predict(data.context,gate.reference,photo.inputs,gate.response)
        parts.append(photo.inputs)
    photo_count=len(photo.inputs) if photo else 0;offset=n+photo_count;spans=[];limits=[];sources=[]
    geometry=training_geometry or [dict(phase=phase,geometry=gate.geometry_for(phase)) for phase in gate.phases]
    for item in geometry:
        phase=item['phase'];x,reference,sections=item['geometry'];parts.append(x)
        for axis,(span,shape) in sections.items():
            report=gate.baseline['dense'][str(phase)][axis]
            limits.extend(item['bounds'][axis] if 'bounds' in item else (report['reference']['p95'],report['reference']['max']))
            spans.append((slice(offset+span.start,offset+span.stop),shape,phase,axis));sources.append(reference[span].reshape(shape))
        offset+=len(x)
    x=np.concatenate(parts);native=native_prediction(data.context,seed,x)
    _,ids,weights=response.stencil(native);mix=response.response(native)
    native_t=tools.tensor(native);ids_t=tools.tensor(ids,True);weights_t=tools.tensor(weights);mix_t=tools.tensor(mix)
    initial=grid_from(seed).astype(float);base=tools.tensor(initial)
    # 冻结真实灰阶经过的插值节点，避免靠训练惩罚近似保护灰阶。
    active,protected=active_nodes(ids[:n],data.gray[data.train],freeze_gray);mask=tools.tensor(active)
    gray_t=tools.tensor(data.gray[data.train],True).bool()
    def forward(table):
        d=(table[ids_t]*weights_t[...,None]).sum(1)
        return (native_t+torch.einsum('nc,nco->no',d,mix_t)).clamp(0,1)
    def features(rgb):
        result=[]
        for span,shape,_,_ in spans:
            lab=tools.lab(rgb[span]).reshape(shape)[...,1:]
            value=((lab[:,2:]-2*lab[:,1:-1]+lab[:,:-2]).square().sum(-1)+1e-20).sqrt()
            result.extend((quantile95(value),value.max()))
        if not freeze_gray:
            gray_error=(self_rounded(rgb[:n])[gray_t]-desired[gray_t]).square().mean().sqrt()*255
            result.append(gray_error)
        return torch.stack(result)
    with torch.no_grad():
        before=forward(base);oracle=response.predict_cpu(native,initial)
        parity=float(np.abs(before.cpu().numpy()-oracle).max())
        if parity>2e-6:raise ValueError('条件网格CPU/MPS前向差异超限')
    if not freeze_gray:limits.append(gate.baseline['metrics']['gray_rmse'])
    bounds=tools.tensor(np.maximum(np.asarray(limits)*(1-interior_margin),1e-5));delta=torch.nn.Parameter(torch.zeros_like(base))
    optimizer=torch.optim.Adam([delta],lr=lr);multipliers=torch.zeros_like(bounds);rho=rho_initial
    desired=tools.tensor(np.floor(data.target[data.train]*255+.5)/255);desired_lab=tools.lab(desired)
    with torch.no_grad():
        pred=self_rounded(before[:n]);mse=float((pred-desired).square().mean().cpu())
        de=(de00_squared(tools,tools.lab(pred),desired_lab)+1e-10).sqrt()
        de_weight=.5*mse/max(float(de.mean().cpu()),1e-8)
        normalizer=max(mse+de_weight*float(de.mean().cpu()),1e-8)
    if photo and full_photos:
        from native_full_photos import FullPhotoProtection
        pguard=FullPhotoProtection(photo,log_path=output/'photo-constraints.jsonl',colour_buckets=colour_buckets)
    else:pguard=PhotoProtection(photo) if photo else None
    rows=[gate.baseline];best=gate.baseline;best_loss=float('inf')
    def record(step):
        nonlocal best
        with torch.no_grad():table=(base+delta*mask).clamp(-64,63).round().cpu().numpy().astype(int)
        entry=copy.deepcopy(seed);entry['grid_5x9x9']=dict(coefficients=table.T.reshape(3,5,9,9).tolist())
        file=output/f'{step:06d}.BIN';file.write_bytes(blob(entry))
        row=gate.assess(entry,f'conditional/{step}');rows.append(row)
        for alpha in (1.,.75,.5,.25,.125):
            partial=copy.deepcopy(seed)
            partial['grid_5x9x9']=dict(coefficients=np.rint(initial+alpha*(table-initial)).astype(int).T.reshape(3,5,9,9).tolist())
            assessed=gate.assess(partial,f'conditional/{step}/a{alpha}');rows.append(assessed)
            if assessed['fully_evaluated'] and not assessed['failures'] and assessed['score']<best['score']-1e-10:best=assessed
        save(output/'progress.json',dict(step=step,selected=best,latest=row))
        print('GRID_CHECKPOINT',step,row['metrics']['rgb_rmse'],row['metrics']['delta_e00_mean'],len(row['failures']),flush=True)
    record(0)
    with (output/'loss.jsonl').open('w') as log:
        for step in range(1,steps+1):
            optimizer.zero_grad(set_to_none=True)
            continuous=(base+delta*mask).clamp(-64,63);table=ste(continuous,continuous.round())
            rgb=forward(table);p=self_rounded(rgb[:n]);de=(de00_squared(tools,tools.lab(p),desired_lab)+1e-10).sqrt()
            color=((p-desired).square().mean()+de_weight*(de.mean()+.1*torch.topk(de,max(1,int(.05*n))).values.mean()))/normalizer
            if photo:
                color=color+.05*photo.tensor_loss(tools,rgb[n:n+photo_count],de_weight)/normalizer
            values=features(rgb);g=values/bounds-1
            augmented=((multipliers+rho*g).clamp(min=0).square()-multipliers.square()).mean()/(2*rho)
            photo_loss=pguard.parts(tools,rgb[n:n+photo_count])[0] if pguard else color.new_zeros(())
            loss=color+augmented+10*photo_loss+.001*(delta*mask/64).square().mean()
            if not torch.isfinite(loss):raise ValueError('条件网格损失无效')
            loss.backward()
            if not torch.isfinite(delta.grad).all():raise ValueError('条件网格梯度无效')
            torch.nn.utils.clip_grad_norm_([delta],10.);optimizer.step()
            if step%25==0:
                with torch.no_grad():multipliers.copy_((multipliers+rho*g.detach()).clamp(0,10000))
            if step%100==0:rho=min(10000.,rho*2)
            best_loss=min(best_loss,float(loss.detach().cpu()))
            log.write(__import__('json').dumps(dict(step=step,loss=float(loss.detach().cpu()),color=float(color.detach().cpu()),
                max_violation=float(g.detach().max().cpu()),rho=rho,seconds=time.monotonic()-start))+'\n')
            if progress and (step==1 or step%10==0):progress(stage='条件整数网格：完整过渡与灰阶保护',state='running',iteration=step,
                loss_sample=('MPS 条件网格增广拉格朗日',step,float(loss.detach().cpu()),best_loss))
            if step%checkpoint==0 or step==steps:log.flush();record(step)
    (output/'selected.BIN').write_bytes(blob(best['entry']))
    audit=dict(candidates=rows,selected=best,steps=steps,lr=lr,rho_initial=rho_initial,cpu_gpu_max_difference=parity,
        protected_gray_nodes=protected.tolist() if freeze_gray else [],freeze_gray=freeze_gray,full_photos=full_photos,
        colour_buckets=colour_buckets,training_geometry_policy='active-max-triples' if training_geometry else 'full-curves',
        interior_margin=interior_margin,full_batch=n,photo_samples=photo_count,dense_probe_samples=len(x)-n-photo_count,
        used_test=False,used_holdout=False,seconds=time.monotonic()-start)
    save(output/'audit.json',audit)
    return best['entry'],audit
