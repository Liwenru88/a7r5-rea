"""密集色相覆盖的活动约束修复：真实整数输入，反复加入当前最坏跳点。"""
import copy
from pathlib import Path
import numpy as np
import core
from native_joint import Gate,choose,AXES
from native_runtime import blob,save
from perceptual import to_lab

def accumulate_phases(existing,extra):
    # 扩大覆盖时保留已验证的位置，避免相位平移把历史回归点移出门槛。
    return tuple(sorted(set(existing)|set(extra)))


PHASES=accumulate_phases((.17,.53,.87),((i+.5)/16 for i in range(16)))
FINAL_PHASES=(.271,.919)


def p95_round(index,rounds):
    # 先消除尖峰，再恢复完整分布；短预算也必须保留完整P95约束。
    return index>=max(0,rounds-2)


class ActiveCurves:
    def __init__(self,gate,include_p95=True):
        self.gate=gate;self.points={};self.full_axes=set();self.include_p95=include_p95

    def observe(self,entry):
        gate=self.gate
        for phase in gate.phases:
            x,reference,sections=gate.geometry_for(phase);prediction=gate._predict(entry,x)
            for axis,(span,shape) in sections.items():
                before,after=(v[span].reshape(shape) for v in (reference,prediction))
                jumps=[np.linalg.norm(np.diff(to_lab(v*255)[...,1:],n=2,axis=1),axis=-1) for v in (before,after)]
                if self.include_p95 and np.percentile(jumps[1],95)>np.percentile(jumps[0],95)*.97+1e-10:
                    self.full_axes.add((phase,axis))
                selected=self.points.setdefault((phase,axis),set())
                for values in jumps:
                    for line,position in enumerate(values.argmax(axis=1)):selected.add((line,int(position)))

    def geometry(self):
        rows=[]
        for phase in self.gate.phases:
            x,reference,sections=self.gate.geometry_for(phase);inputs=[];values=[];parts={};bounds={};offset=0
            for axis,(span,shape) in sections.items():
                raw=x[span].reshape(shape[0],shape[1],9,3);rgb=reference[span].reshape(shape)
                report=self.gate.baseline['dense'][str(phase)][axis]['reference']
                if (phase,axis) in self.full_axes:
                    xx=x[span];yy=reference[span];new_shape=shape;bounds[axis]=(report['p95'],report['max'])
                else:
                    points=sorted(self.points[(phase,axis)])
                    xx=np.concatenate([raw[line,at:at+3] for line,at in points]);yy=np.concatenate([rgb[line,at:at+3] for line,at in points])
                    new_shape=(len(points),3,3);bounds[axis]=(report['max'],report['max'])
                inputs.append(xx);values.append(yy);parts[axis]=(slice(offset,offset+len(xx)),new_shape);offset+=len(xx)
            rows.append(dict(phase=phase,geometry=(np.concatenate(inputs),np.concatenate(values),parts),bounds=bounds))
        return rows


def repair(data,reference,seed,output,*,rounds=6,steps=500,progress=None,gate=None):
    from native_conditional_grid import fit_grid
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    gate=gate or Gate(data,reference,phases=PHASES,final_phases=FINAL_PHASES)
    bank=ActiveCurves(gate,include_p95=False);current=copy.deepcopy(seed);rows=[gate.baseline]
    initial=gate.assess(seed,'robust-initial');rows.append(initial)
    selected=choose(gate.baseline,rows);records=[]
    for r in range(rounds):
        bank.include_p95=p95_round(r,rounds)
        bank.observe(current);geometry=bank.geometry()
        def report(**values):
            if progress:
                values['stage']=f'稳健过渡修复 {r+1}/{rounds} · '+values.get('stage','训练中')
                progress(**values)
        _,audit=fit_grid(data,gate,current,output/f'round-{r+1}',steps=steps,checkpoint=steps,
            full_photos=True,freeze_gray=False,colour_buckets=True,training_geometry=geometry,interior_margin=.03,progress=report)
        rows.extend(dict(row,label=f'robust-r{r+1}/'+row['label']) for row in audit['candidates'])
        selected=choose(gate.baseline,rows)
        # 活动集必须沿原始迭代点修复，不能把尚未合格的进展丢回起点。
        current=core.compiler.unpack((output/f'round-{r+1}/{steps:06d}.BIN').read_bytes())['entries'][0]
        record=dict(round=r+1,active_triples=sum(len(p) for p in bank.points.values()),full_p95_axes=len(bank.full_axes),
            raw_sha256=core.sha(blob(current)),selected_sha256=selected['sha256'],metrics=selected['metrics'],
            cpu_gpu_max_difference=audit['cpu_gpu_max_difference'])
        records.append(record);save(output/'progress.json',dict(records=records,selected=selected))
        print('ROBUST_ROUND',r+1,record['active_triples'],selected['metrics']['rgb_rmse'],selected['metrics']['delta_e00_mean'],selected['sha256']!=gate.baseline['sha256'],flush=True)
    (output/'selected.BIN').write_bytes(blob(selected['entry']))
    audit=dict(policy='native-robust-active-grid/1',selected=selected,baseline=gate.baseline,candidates=rows,records=records,
        phases=list(gate.phases),final_phases=list(gate.final_phases),rounds=rounds,steps_per_round=steps,
        source_native_unchanged=True,used_test=False,used_holdout=False)
    save(output/'audit.json',audit)
    return selected['entry'],audit,gate
