"""冻结三款数据的共享联合求解入口；默认仅开发评分，显式终检才读留出。"""
import argparse,copy,json,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'web'),str(ROOT/'scripts')]
import numpy as np
import torch
import baseline,core
from native_joint import Data,Gate,fit,POLICY
from native_solver import digest,save,blob
from edit_parameter_context import ParameterContext,RuntimeColor


def load_data(manifest,slot):
    manifest=Path(manifest);index=json.loads(manifest.read_text());protected={str(manifest):digest(manifest)}
    def load(row):
        p=manifest.parent/row['file']
        if digest(p)!=row['sha256']:raise ValueError('冻结数据身份变化：'+str(p))
        protected[str(p)]=row['sha256']
        with np.load(p,allow_pickle=False) as a:return {k:a[k] for k in a.files}
    chart=load(index['chart']);key='target_'+str(slot);photos=[]
    for record in index['scenes']:
        if record['role']!='development':continue
        a=load(record);photos.append(dict(scene=record['scene'],role='development',inputs=a['inputs'],target=a[key],display=a['display']))
    def heldout():
        rows=[]
        for record in index['scenes']:
            if record['role']!='holdout':continue
            a=load(record);rows.append(dict(scene=record['scene'],role='holdout',inputs=a['inputs'],target=a[key],display=a['display']))
        return rows
    context=ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID)),native_gamma=True)
    return Data(context,chart['input'],chart[key],chart['split'],chart['anchor_index'],chart['design_srgb'],chart['sample_kind'],
        photos=photos,holdout_loader=heldout),protected


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for key in ('manifest','bin','output'):p.add_argument('--'+key,type=Path,required=True)
    p.add_argument('--slot',type=int,choices=(5,6,14),required=True)
    p.add_argument('--seed-bin',type=Path);p.add_argument('--scales',type=Path)
    p.add_argument('--steps',type=int,default=600);p.add_argument('--dense-budget',type=float,default=.1)
    p.add_argument('--lr',type=float,default=.003);p.add_argument('--finalize',action='store_true')
    args=p.parse_args();torch.manual_seed(42);np.random.seed(42)
    data,protected=load_data(args.manifest,args.slot);protected[str(args.bin)]=digest(args.bin)
    original=core.compiler.unpack(args.bin.read_bytes());reference=next(e for e in original['entries'] if e['number']==args.slot)
    seed=None;scales=None
    if args.seed_bin:
        seed=core.compiler.unpack(args.seed_bin.read_bytes())['entries'][0];protected[str(args.seed_bin)]=digest(args.seed_bin)
        if seed['number']!=args.slot:raise ValueError('研究起点槽位不同')
    if args.scales:
        scales=np.asarray(json.loads(args.scales.read_text())['scales']);protected[str(args.scales)]=digest(args.scales)
    from training_profile import JOINT_PROFILE
    options=dict(JOINT_PROFILE['joint_options'],steps=args.steps,lr=args.lr,dense_budget=args.dense_budget)
    # 先绑定全部本地实现，训练结束核对，避免运行中改代码导致证据错配。
    snapshot=args.output.with_name(args.output.name+'.sources');snapshot.mkdir(parents=True,exist_ok=False)
    paths=[path for folder in ('web','scripts','compilers') for path in (ROOT/folder).rglob('*.py')]
    paths.append(ROOT/'web/native_joint_profile.json');sources={}
    for path in paths:
        relative=path.relative_to(ROOT);sources[str(relative)]=digest(path)
        destination=snapshot/relative;destination.parent.mkdir(parents=True,exist_ok=True);destination.write_bytes(path.read_bytes())
    selected,audit,gate=fit(data,reference,args.output,seed=seed,options=options,frozen_scales=scales)
    if args.finalize:
        save(args.output/'locked-selection.json',dict(selected=audit['selected'],holdout_used_for_selection=False,
            audit_sha256=digest(args.output/'joint-audit.json')))
        from native_joint_workbench import accept
        accepted,quality=accept(selected,audit,gate)
        (args.output/'accepted.BIN').write_bytes(blob(accepted))
        save(args.output/'final-acceptance.json',quality)
    for relative,sha in sources.items():
        if digest(ROOT/relative)!=sha:raise ValueError('研究期间实现发生变化：'+relative)
    snapshot.rename(args.output/'source-snapshot')
    for file,sha in protected.items():
        if digest(file)!=sha:raise ValueError('输入或原库变化：'+file)
    save(args.output/'receipt.json',dict(policy=audit['policy'],slot=args.slot,options=audit['options'],source_sha256=sources,
        protected=protected,gpu='mps',full_batch=int(data.train.sum()),finalized=args.finalize,
        selected=audit['selected']['metrics'],adopted_on_development=audit['adopted_on_development'],camera_connected=False))
    print('JOINT_DONE',args.slot,audit['selected']['label'],audit['selected']['metrics'],audit['adopted_on_development'],flush=True)


if __name__=='__main__':main()
