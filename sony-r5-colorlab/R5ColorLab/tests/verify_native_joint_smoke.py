"""实际GPU工作台链路复验；缩减预算，仅替代上传文件寻址，不用假求解器。"""
import argparse,copy,json,os,sys,time,uuid
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'web'),str(ROOT/'scripts')]


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--target',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--quality-manifest',type=Path)
    parser.add_argument('--target-key',default='target_5')
    args=parser.parse_args()
    os.environ.update(R5_GPU_TRAINING='1',OPENBLAS_NUM_THREADS='1',VECLIB_MAXIMUM_THREADS='1')
    import core,server,chart_target,training_profile
    from grid_distillation import firmware_config,model_for_config
    from gpu_runtime import available
    from edit_parameter_context import ParameterContext,RuntimeColor
    import baseline
    assert available()
    data=args.target.read_bytes();args.output.mkdir(parents=True,exist_ok=False)
    identifier=uuid.uuid4().hex;started=time.monotonic()
    options=copy.deepcopy(training_profile.JOINT_PROFILE['options'])
    options.update(evaluations=4,number=24,short_name='链路验证',full_name='原生联合离线链路验证',target_sha256=core.sha(data),
        training_profile='native-joint/1',training_revision=training_profile.JOINT_REVISION,
        joint_options=dict(steps=200,lr=.003,dense_budget=.1,conditional_steps=50,
            conditional_candidates=1,integer_sweeps=1,recovery_enabled=False,full_photo_steps=50,
            robust_rounds=1,robust_steps=20,selection_policy='force-new'))
    if args.quality_manifest:
        import quality_data
        index=json.loads(args.quality_manifest.read_text())
        assert index['chart']['sources'][args.target_key.split('_')[-1]]['sha256']==core.sha(data)
        options['quality_set']=quality_data.register(args.output,args.quality_manifest,core.sha(data),args.target_key)
    options['search_options'].update(starts=2,adaptive_rounds=0,quantization_sweeps=0,gamma_color_rounds=0)
    def prepare(identifier,body,output,job):
        chart_target.prepare(data,output,source_path=args.target,dataset_id=options['dataset_id'])
        server.solve_native(body,output,job)
    with patch.object(server,'RUNS',args.output),patch.dict(server.JOBS,{},clear=True),patch.object(server,'fit_native',side_effect=prepare):
        server.reserve_job(identifier,options);server.work(identifier,options)
        state=server.JOBS[identifier]
        if state['status']!='done':raise RuntimeError(state.get('error','联合工作台链路未完成'))
        job=args.output/identifier;config=firmware_config(job,state['result']['grid_key'],True)
        binary=core.compiler.pack(config);assert core.compiler.pack(core.compiler.unpack(binary))==binary
        assert (job/'R5NATIVE.BIN').read_bytes()==binary
        assert config['entries'][0]['number']==24
        quality=json.loads((job/'quality_selection.json').read_text());assert quality['policy']=='native-joint-forced/1'
        assert quality['adopted'] and not quality['retained_baseline'] and quality['export_allowed']
        selected=core.compiler.unpack((job/'native_joint/selected.BIN').read_bytes())['entries'][0]
        assert selected==config['entries'][0]
        from native_gamma import POLICY as GAMMA_POLICY
        assert quality['gamma_forward_policy']==GAMMA_POLICY
        assert quality['photo_scope']==('development-and-holdout' if args.quality_manifest else 'not-bound')
        assert quality['independent_checks']==1
        context=ParameterContext(RuntimeColor.from_capture(*baseline.for_job(job)),native_gamma=True)
        model=context.build(**core.slot_native_parameters(context,config['entries'][0]))
        assert model.runtime==model_for_config(job,config).runtime
        assert state['result']['native_joint']['full_gamma129']
        from export_policy423 import validate
        export=dict(config,export_sources={'24':dict(kind='compressed',job=identifier,key=state['result']['grid_key'])})
        assert core.compiler.pack(validate(export,args.output)[0])==binary
        events=[json.loads(line) for line in (job/'training_progress.jsonl').read_text().splitlines()]
        assert any('联合 Adam' in e.get('solver','') for e in events)
        assert any('条件网格' in e.get('solver','') for e in events)
        assert any(e.get('kind')=='integer' for e in events)
        if args.quality_manifest:
            assert (job/'native_joint/full-photos/photo-constraints.jsonl').is_file()
            assert json.loads((job/'native_joint/full-photos/audit.json').read_text())['full_photos']
        summary=dict(schema='r5-native-joint-smoke/1',status=state['status'],job=identifier,
            seconds=time.monotonic()-started,gpu='mps',target_sha256=core.sha(data),slot=24,
            adopted=quality['adopted'],quality_passed=quality['quality_passed'],failed_checks=quality['failed_checks'],
            retained_baseline=quality['retained_baseline'],fallback_reason=quality['fallback_reason'],
            bin_decode_recompile=True,preview_and_export_runtime_equal=True,
            full_gamma129=True,photo_scope=quality['photo_scope'],loss_events=len(events),
            binary_sha256=core.sha(binary),joint_options=options['joint_options'],
            production_filter=False,camera_connected=False)
        (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
