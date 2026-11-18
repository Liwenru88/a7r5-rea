"""独立C精度入口：先200步对照，再用相同2000步预算确认；不操作相机。"""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'web'),str(ROOT/'scripts')]
import numpy as np
import torch
import baseline,core
import benchmark_native_loss as driver
from benchmark_native_four import predict,digest
from edit_parameter_context import ParameterContext,RuntimeColor
from grid_models import default_response
from calibrated_guard import RampBank
from native_objective_research import PhotoBank
from native_precision_research import PrecisionObjective,WindowRampBank


def screen_plan():
    return [dict(name=name,photo_samples=256,dense_budget=budget,project_conflicts=projection)
        for name,budget,projection in [('coverage256',0.,False),('dense10',.1,False),
            ('dense25',.25,False),('project_dense25',.25,True)]]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--steps',type=int,choices=(200,600,2000),default=200)
    parser.add_argument('--configs',default=','.join(x['name'] for x in screen_plan()))
    own,rest=parser.parse_known_args()
    names=own.configs.split(',');plan=[x for x in screen_plan() if x['name'] in names]
    if not plan or len(plan)!=len(set(names)):raise ValueError('精度配置名称无效或重复')
    values=argparse.ArgumentParser(add_help=False)
    for name in ('bin','manifest','normalization','output'):values.add_argument('--'+name,type=Path,required=True)
    paths=values.parse_args(rest)
    if not torch.backends.mps.is_available():raise RuntimeError('MPS不可用，不回退CPU')
    source=next(x for x in core.compiler.unpack(paths.bin.read_bytes())['entries'] if x['number']==5)
    context=ParameterContext(RuntimeColor.from_capture(*baseline.resolve(baseline.V45_ID)),native_gamma=True)
    response=default_response();banks={};frozen={}
    def bank(phase):
        if phase not in banks:
            banks[phase]=WindowRampBank(RampBank(phase),context.base,lambda x:predict(context,source,x,response))
        return banks[phase]
    class CoveredPhotos(PhotoBank):
        def __init__(self,rows,*,per_region=64,seed=42):super().__init__(rows,per_region=256,seed=seed)
    original_save=driver.save;original_train=driver.train
    def save(path,value):
        if path.name=='protocol.json':
            if not frozen:
                for phase,window in banks.items():
                    filename=f'precision-probes-{phase}.npz';file=paths.output/filename
                    np.savez_compressed(file,inputs=window.inputs(context.base),rgb=window.rgb)
                    frozen[str(file)]=digest(file)
                    metadata=paths.output/f'precision-windows-{phase}.json'
                    original_save(metadata,window.groups);frozen[str(metadata)]=digest(metadata)
            value.update(steps=own.steps,checkpoint=50 if own.steps==200 else 200,
                learning_rates=[.003],precision_inputs=frozen,precision_plan=plan,
                precision_policy=dict(window_factor=16,uniform_windows=24,source_peak_windows=8,
                    axes=['saturation','native-saturation'],all_saturation_rays=True,
                    photo_samples_per_region=256,source_only_peak_selection=True,
                    projection_scope='归一化配方坐标中的辅助梯度，Adam前处理；不保证实际整数更新单调'))
        if isinstance(value,dict) and 'scope' in value:
            value['scope']=f'{own.steps}步离线C精度实验，候选需独立回读验收'
        return original_save(path,value)
    def train(arm,space,renderer,objective,scales,screen,reference,margins,args):
        args.steps=own.steps;args.checkpoint=50 if own.steps==200 else 200
        args.retain_checkpoints=True
        return original_train(arm,space,renderer,objective,scales,screen,reference,margins,args)
    def study(_):
        return dict(loss_trials=[],fixed_trials=[dict(name=x['name'],tone_ratio=.1,cap=.2,lr=.003,
            research=dict(photo_ratio=.05,photo_guard_budget=.25,dense_budget=x['dense_budget'],
                project_conflicts=x['project_conflicts'])) for x in plan],
            selection='扩大覆盖与密集窗口固定对照，按开发质量选择；接受既有小幅色差取舍，不使用本轮留出挑选')
    driver.RampBank=bank;driver.PhotoBank=CoveredPhotos;driver.ResearchObjective=PrecisionObjective
    driver.study_plan=study;driver.save=save;driver.train=train
    sys.argv=[str(Path(__file__).resolve()),*rest,'--study','photo_guard','--arm','C']
    driver.main()
    if any(digest(path)!=sha for path,sha in frozen.items()):raise ValueError('密集冻结输入变化')
    result=json.loads((paths.output/'result.json').read_text())
    lines=[f'# C精度研究：每组{own.steps}步','',
        'MPS整批；每区域256点；双域全部饱和度射线均匀窗口及原配方高曲率窗口；格式和原配方不变。','',
        '| 配置 | VALID RGB RMSE | 平均ΔE00 | 灰阶RMSE | 开发照片超限项 |',
        '|---|---:|---:|---:|---:|']
    for row in result['trials']:
        m=row['selected']['metrics']
        lines.append(f"| {row['name']} | {m['rgb_rmse']:.6f} | {m['delta_e00_mean']:.6f} | {m['gray_rmse']:.6f} | {len(row['development_failures'])} |")
    (paths.output/'筛查报告.md').write_text('\n'.join(lines)+'\n')


if __name__=='__main__':main()
