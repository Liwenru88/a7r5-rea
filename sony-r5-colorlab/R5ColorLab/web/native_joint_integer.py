"""原生整数邻域补偿；TRAIN预筛只提议，完整开发验收决定接受。"""
import copy,json
from pathlib import Path
import numpy as np
import core
from native_solver import blob,save
from native_scoring import color_metrics
from fit_bin_joint import grid_from
from measured_response import get
from integer_blocks import matrix_move


def integer_event(best,record,checked):
    def gray(row):return any('gray' in reason for reason in row['failures'])
    def transition(row):return any(reason.startswith(('dense:','dense_quant:')) for reason in row['failures'])
    label={'cc1':'CC1','hue':'色相','gamma':'Gamma','grid':'网格'}[record['group']]
    return dict(sweep=str(record['sweep']+1)+' · '+label,
        proposed_moves=record['improving_training_neighbors'],applied_moves=record['accepted'],
        rejected_candidates=len(checked)-record['accepted'],metrics=best['metrics'],
        gray_passed=best['fully_evaluated'] and not gray(best),
        saturation_passed=best['fully_evaluated'] and not transition(best),
        gray_rejections=sum(gray(row) for row in checked),saturation_rejections=sum(transition(row) for row in checked))


def move(entry,group,index,step):
    e=copy.deepcopy(entry)
    if group=='cc1':e['cc1_delta'][0][index]+=4*step
    elif group=='hue':
        row,column=divmod(index,6);value=matrix_move(e['block13'][0][row][column],step)
        for matrix in e['block13']:matrix[row][column]=value
    elif group=='gamma':e['gamma_native_129'][index]+=step
    elif group=='grid':
        channel,a,b,c=np.unravel_index(index,(3,5,9,9));e['grid_5x9x9']['coefficients'][channel][a][b][c]+=step
    else:raise ValueError('未知整数参数族')
    return core.compiler.unpack(blob(e))['entries'][0]


def polish(data,gate,entry,output,*,sweeps=2,shortlist=6,progress=None):
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    rng=np.random.default_rng(42);chosen=list(np.flatnonzero(data.gray));kinds=np.unique(data.kinds[data.train&~data.gray])
    for kind in kinds:
        at=np.flatnonzero(data.train&~data.gray&(data.kinds==kind));chosen.extend(rng.choice(at,min(len(at),4096//len(kinds)),replace=False).tolist())
    at=np.array(sorted(set(chosen)));assert np.all(data.train[at])
    x=data.inputs[at];target=data.target[at];gray=data.gray[at]
    if not np.all(x==x[:,:1]):raise ValueError('整数预筛只接受平坦色卡输入')
    np.savez_compressed(output/'training-indices.npz',indices=at)
    response=get(gate.response);cache={};evaluations=0;invalid=0
    def measure(e):
        nonlocal evaluations
        key=tuple(json.dumps(e[k]) for k in ('cc1_delta','block13','gamma_native_129'))
        if key not in cache:
            if len(cache)>4:cache.clear()
            model=data.context.build(**core.slot_native_parameters(data.context,e))
            cache[key]=model.color_only(x[:,:5])[:,2]/16383
        rgb=response.predict_cpu(cache[key],grid_from(e));evaluations+=1
        m=color_metrics(rgb,target);m['gray_rmse']=color_metrics(rgb[gray],target[gray])['rgb_rmse']
        return m
    start=measure(entry);best=gate.assess(entry,'integer-start');current=copy.deepcopy(entry);records=[];rows=[]
    for sweep in range(sweeps):
        old=blob(current)
        for group,count,steps in (('cc1',8,(1,2)),('hue',96,(1,2)),('gamma',129,(1,16,64)),('grid',1215,(1,))):
            initial=measure(current);candidates=[];seen=set()
            for index in range(1 if group=='gamma' else 0,count):
                for size in steps:
                    for sign in (-1,1):
                        try:e=move(current,group,index,size*sign)
                        except (ValueError,OverflowError):invalid+=1;continue
                        identity=blob(e)
                        if identity in seen:continue
                        seen.add(identity);m=measure(e)
                        score=m['rgb_rmse']/max(start['rgb_rmse'],1e-8)+m['delta_e00_mean']/max(start['delta_e00_mean'],1e-8)
                        current_score=initial['rgb_rmse']/max(start['rgb_rmse'],1e-8)+initial['delta_e00_mean']/max(start['delta_e00_mean'],1e-8)
                        if score<current_score-1e-10 and m['gray_rmse']<=start['gray_rmse']+1e-8 and m['delta_e00_p95']<=start['delta_e00_p95']+1e-8:
                            candidates.append((score,e,dict(group=group,index=index,step=size*sign,train=m)))
            accepted=0;checked=[]
            for rank,(_,e,update) in enumerate(sorted(candidates,key=lambda row:row[0])[:shortlist]):
                label=f's{sweep}-{group}-{rank}';row=gate.assess(e,label);rows.append(dict(row,integer_update=update))
                checked.append(row)
                if row['fully_evaluated'] and not row['failures'] and row['score']<best['score']-1e-10:
                    best=row;current=copy.deepcopy(e);accepted+=1
            records.append(dict(sweep=sweep,group=group,improving_training_neighbors=len(candidates),accepted=accepted,
                selected_sha256=core.sha(blob(current))))
            if progress:progress(stage='原生整数邻域复验',state='running',family=group,sweep=sweep+1,total_sweeps=sweeps,
                integer_round=integer_event(best,records[-1],checked))
            save(output/'progress.json',dict(records=records,evaluations=evaluations,invalid=invalid))
        if blob(current)==old:break
    (output/'selected.BIN').write_bytes(blob(current))
    audit=dict(evaluations=evaluations,invalid=invalid,training_samples=len(at),records=records,candidates=rows,
        selected=best,used_test=False,used_holdout=False)
    save(output/'audit.json',audit)
    return current,audit
