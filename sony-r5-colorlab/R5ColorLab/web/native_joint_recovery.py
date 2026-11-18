"""按参数组恢复可行性：TRAIN子集提议，完整开发门槛决定采用。"""
import copy,json
from pathlib import Path
import numpy as np
from native_solver import blob,save
from native_feasible_experiment import blend_entry
from native_scoring import color_metrics
from fit_bin_joint import grid_from
from measured_response import get
import core


def recover(data,gate,checkpoints,output,*,progress=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    rng=np.random.default_rng(42);chosen=list(np.flatnonzero(data.gray));kinds=np.unique(data.kinds[data.train&~data.gray])
    for kind in kinds:
        ids=np.flatnonzero(data.train&~data.gray&(data.kinds==kind))
        chosen.extend(rng.choice(ids,min(len(ids),4096//len(kinds)),replace=False).tolist())
    at=np.array(sorted(set(chosen)));assert np.all(data.train[at]);x=data.inputs[at];target=data.target[at];gray=data.gray[at]
    response=get(gate.response);cache={}
    def measure(e):
        key=tuple(json.dumps(e[k]) for k in ('gamma_native_129','cc1_delta','block13'))
        if key not in cache:
            if len(cache)>48:cache.clear()
            model=data.context.build(**core.slot_native_parameters(data.context,e))
            cache[key]=model.color_only(x[:,:5])[:,2]/16383
        p=response.predict_cpu(cache[key],grid_from(e));m=color_metrics(p,target)
        m['gray_rmse']=color_metrics(p[gray],target[gray])['rgb_rmse'];return m
    reference=gate.reference;ref=measure(reference);rows=[];selected=gate.baseline;evaluations=0;seen=set()
    for i,entry in enumerate(checkpoints):
        buckets={}
        for gamma in (0.,.25,.5,1.):
            for grid in (0.,.25,.5,1.):
                for color in (0.,.25,.5,1.):
                    try:
                        c=blend_entry(reference,entry,color);g=blend_entry(reference,entry,gamma);t=blend_entry(reference,entry,grid)
                        c['gamma_native_129']=g['gamma_native_129'];c['grid_5x9x9']=t['grid_5x9x9']
                        c=core.compiler.unpack(blob(c))['entries'][0]
                    except (ValueError,OverflowError):continue
                    identity=blob(c)
                    if identity in seen:continue
                    seen.add(identity);m=measure(c);evaluations+=1
                    if any(m[k]>=ref[k]-1e-10 for k in ('rgb_rmse','delta_e00_mean')):continue
                    if any(m[k]>ref[k]+1e-8 for k in ('gray_rmse','delta_e00_p95')):continue
                    score=m['rgb_rmse']/ref['rgb_rmse']+m['delta_e00_mean']/ref['delta_e00_mean']
                    key=(gamma,grid)
                    if key not in buckets or score<buckets[key][0]:buckets[key]=(score,c,dict(gamma=gamma,color=color,grid=grid))
        for rank,(_,c,settings) in enumerate(sorted(buckets.values(),key=lambda x:x[0])):
            label=f'checkpoint{i}-groups{rank}';row=gate.assess(c,label);rows.append(dict(row,group_mix=settings))
            if row['fully_evaluated'] and not row['failures'] and row['score']<selected['score']-1e-10:selected=row
        if progress:progress(stage='四组参数可行性恢复',state='running',iteration=i+1,evaluations=evaluations)
        save(output/'progress.json',dict(evaluations=evaluations,checked=len(rows),selected=selected))
    (output/'selected.BIN').write_bytes(blob(selected['entry']))
    audit=dict(evaluations=evaluations,training_samples=len(at),candidates=rows,selected=selected,used_test=False,used_holdout=False)
    save(output/'audit.json',audit)
    return selected['entry'],audit
