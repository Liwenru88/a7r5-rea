"""以缩减原生／叠加预算验证正式流程，输出仅作离线测试。"""
import argparse
import copy
import json
import os
from pathlib import Path
import sys
import time
import uuid
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'web'),str(ROOT/'scripts')]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',type=Path,required=True,help='现有 v4.5 色卡目标 TIFF／JPG')
    parser.add_argument('--output',type=Path,required=True,help='必须尚不存在的测试目录')
    args=parser.parse_args()
    os.environ.update(R5_GPU_TRAINING='1',OPENBLAS_NUM_THREADS='1',VECLIB_MAXIMUM_THREADS='1')
    import core,server,chart_target,training_profile
    from grid_distillation import firmware_config
    from gpu_runtime import available
    if not available():raise RuntimeError('本验证必须使用 Apple Metal/MPS')
    target=args.target.resolve();data=target.read_bytes()
    args.output.mkdir(parents=True,exist_ok=False)
    identifier=uuid.uuid4().hex
    options=copy.deepcopy(training_profile.PROFILE['options'])
    options.update(evaluations=4,number=24,short_name='验证',full_name='Hybrid离线验证',
        training_profile='upstream-formal/1',training_revision=training_profile.REVISION)
    options['search_options'].update(starts=2,adaptive_rounds=0,quantization_sweeps=0,gamma_color_rounds=0)
    settings=dict(training_profile.SETTINGS,native_evaluations=2,grid_evaluations=2,rounding_steps=2,block_budget=2)
    # 只替代上传文件的寻址；目标解码、原生拟合和后续步骤均执行实际代码。
    def prepare(identifier,body,output,job):
        chart_target.prepare(data,output,source_path=target,dataset_id=options['dataset_id'])
        server.solve_native(body,output,job)
    started=time.monotonic()
    with patch.object(server,'RUNS',args.output),patch.dict(server.JOBS,{},clear=True), \
         patch.object(server,'fit_native',side_effect=prepare),patch.object(training_profile,'SETTINGS',settings):
        server.reserve_job(identifier,options)
        server.work(identifier,options)
        state=server.JOBS[identifier]
        if state['status']!='done':raise RuntimeError(state.get('error','正式流程未完成'))
        job=args.output/identifier
        config=firmware_config(job,state['result']['grid_key'],True)
        binary=core.compiler.pack(config)
        assert binary==core.compiler.pack(core.compiler.unpack(binary))
        assert config['entries'][0]['number']==24
        audit=json.loads((job/'stack_audit.json').read_text())
        parent=args.output/state['base_job']
        recipe=json.loads((parent/'fit/recipe.json').read_text())
        summary=dict(schema='r5-hybrid-update-smoke/1',seconds=round(time.monotonic()-started,2),
            job=identifier,parent=state['base_job'],status=state['status'],
            target_sha256=core.sha(data),target_name=target.name,
            training_revision=training_profile.REVISION,slot=24,format=core.compiler.format_version(config),
            bytes=len(binary),binary_sha256=core.sha(binary),
            bin_decode_recompile=audit['bin_decode_recompile'],decoded_native_cpu_replay=audit['decoded_native_cpu_replay'],
            parent_files_unchanged=audit['parent_files_unchanged'],settings=settings,native_options=options,
            gpu_initialization=recipe['fitting']['gpu_initialization'],
            gpu_fallbacks=[r for r in recipe['fitting'].get('convergence',[]) if r.get('backend')=='GPU fallback'],
            grid_continuation_rounds=5,stack_rounds=len(audit['rounds']),
            camera_connected=False,production_filter=False)
        training_profile.save(args.output/'smoke-summary.json',summary)
        print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
