"""共享原生联合训练的工作台适配。"""
import copy,json,time,traceback,uuid,threading
from pathlib import Path


def request_cancel(job,parent):
    job['cancel_requested']=True
    process=job.get('process') or parent.get('process')
    if process is not None:process.terminate()
    job['phase']='正在取消，保留已有日志和检查点'


def check_cancel(job):
    if job.get('cancel_requested'):raise RuntimeError('用户已取消训练，日志和检查点已保留')


def work(server,native_work,identifier,options,resume=False):
    from native_joint import Data,fit
    from native_solver import digest
    from edit_parameter_context import ParameterContext,RuntimeColor
    from training_profile import mirror_progress,train,SETTINGS
    from training_progress import TrainingProgress
    from packed_training import attach_result
    import baseline,core,grid_distillation,quality_data
    import numpy as np
    from stack_training import save
    final=server.JOBS[identifier];out=server.RUNS/identifier;out.mkdir(exist_ok=True)
    prior=json.loads((out/'job.json').read_text()) if (out/'job.json').exists() else {}
    baseid=prior.get('base_job') or uuid.uuid4().hex;source=server.RUNS/baseid;source.mkdir(exist_ok=True)
    base=json.loads((source/'job.json').read_text()) if (source/'job.json').exists() else dict(id=baseid,status='queued',started=time.time())
    base['internal_parent']=True;server.JOBS[baseid]=base
    positions={};stop=threading.Event();mirror=None
    final.pop('cancel_requested',None)
    final.update(status='running',base_job=baseid,training_profile='native-joint/1',phase='联合训练：原生起点准备')
    save(out/'job.json',final)
    try:
        if not __import__('gpu_runtime').available():raise RuntimeError('原生联合训练需要Apple Metal/MPS')
        request=source/'request.json'
        if request.exists() and json.loads(request.read_text())!=options:raise ValueError('接续任务的目标或训练配置不同')
        if not request.exists():save(request,options)
        if base.get('status')!='done':
            def observe():
                while not stop.wait(.5):
                    try:
                        mirror_progress(source,out,positions)
                        final['phase']='原生起点准备：'+base.get('phase','训练中')
                        save(out/'job.json',{k:v for k,v in final.items() if k!='process'})
                    except (OSError,ValueError):pass
            mirror=threading.Thread(target=observe,daemon=True);mirror.start()
            try:native_work(baseid,options,resume=(source/'fit/recipe.json').exists())
            finally:stop.set();mirror.join()
        check_cancel(final)
        if base.get('status')!='done':raise RuntimeError(base.get('error','原生起点准备失败'))
        mirror_progress(source,out,positions)
        # 只构建一次现有预览/导出所需的基准产物；不再执行旧固定Gamma三轮叠加。
        key=json.loads((source/'grid_training.json').read_text())['key']
        parent=grid_distillation.firmware_config(source,key,True)['entries'][0]
        reference=options.get('packed_baseline',{}).get('entry',parent)
        tracker=TrainingProgress(out/'training_progress.json',5)
        def report(**values):
            check_cancel(final)
            tracker.update(**values)
        artifact_state=copy.deepcopy({k:v for k,v in final.items() if k!='process'})
        with server.RAW_LOCK:
            train(out,source,artifact_state,report,dict(SETTINGS,rounds=0),seed_entry=parent)
            tracker.update(round=1,total_rounds=5)
            final.update(status='running',phase='联合训练：四组原生参数与网格',result=artifact_state['result'])
            save(out/'job.json',final)
            with np.load(out/'pairs.npz',allow_pickle=False) as archive:a={k:archive[k] for k in archive.files}
            photos=quality_data.load(options.get('quality_set'),server.RUNS,options.get('target_sha256'))
            development=[p for p in photos if p['role']=='development']
            context=ParameterContext(RuntimeColor.from_capture(*baseline.for_job(out)),native_gamma=True)
            data=Data(context,a['input'],a['0_target']/16383,a['split'],a['anchor_index'],a['design_srgb'],a['sample_kind'],
                photos=development,holdout_loader=lambda:[p for p in photos if p['role']=='holdout'])
            folder=out/'native_joint'
            if folder.exists():
                archive=out/'interrupted_joint'/uuid.uuid4().hex;archive.parent.mkdir(exist_ok=True);folder.rename(archive)
            selected,audit,gate=fit(data,reference,folder,seed=parent,options=options['joint_options'],progress=report)
            check_cancel(final)
            chosen,quality=accept(selected,audit,gate,force_new=True)
            check_cancel(final)
            quality['baseline_identity']=copy.deepcopy(options.get('packed_baseline'))
            save(folder/'final-acceptance.json',quality)
            attach_result(out,artifact_state,chosen,quality)
            check_cancel(final)
            artifact_state['result'].pop('stack_experiment',None)
            artifact_state['result']['native_joint']=dict(policy=quality['policy'],adopted=quality['adopted'],
                quality_passed=quality['quality_passed'],failed_checks=quality['failed_checks'],
                selected_sha256=quality['selected_sha256'],options=options['joint_options'],full_gamma129=True)
            stack_path=out/'stack_audit.json'
            if stack_path.exists():
                stack=json.loads(stack_path.read_text());stack['baseline_artifact_only']=True
                stack['final_training_policy']=quality['policy'];save(stack_path,stack)
            # attach_result复用同一selected_config通道，独立CPU重放与预览/导出共同绑定。
            verified=grid_distillation.firmware_config(out,artifact_state['result']['grid_key'],True)
            if verified['entries'][0]!=chosen:raise ValueError('工作台预览与最终联合配方不一致')
            check_cancel(final)
            final.update(result=artifact_state['result'],quality_selection=quality,status='done',finished=time.time(),
                phase='C 原生联合训练完成：'+('新配方质量验收通过' if quality['quality_passed'] else '已保存新配方，存在质量警告，可导出'))
            tracker.update(stage=final['phase'],state='done')
    except Exception as error:
        final.update(status='error',phase='原生联合训练失败，证据保留',error=str(error),finished=time.time())
        (out/'error.log').write_text(traceback.format_exc(),encoding='utf-8')
    finally:
        stop.set()
        if mirror is not None:mirror.join()
        if base.get('status') in ('queued','running'):
            base.update(status='error',phase='父任务中断',error=final.get('error','子任务已中断'),finished=time.time())
            save(source/'job.json',{k:v for k,v in base.items() if k!='process'})
        save(out/'job.json',{k:v for k,v in final.items() if k!='process'})


def accept(candidate,audit,gate,*,force_new=None):
    from native_joint import POLICY,FORCED_POLICY,recipe_key
    from native_runtime import blob
    from packed_training import canonical
    from native_gamma import POLICY as GAMMA_POLICY
    reference=gate.baseline;selected=audit['selected']
    if force_new is None:force_new=audit.get('policy')==FORCED_POLICY
    if force_new:
        if blob(candidate)!=blob(selected['entry']):raise ValueError('锁定候选与发布配方身份不一致')
        if recipe_key(candidate)==recipe_key(reference['entry']):raise ValueError('没有本次优化的新候选，禁止回退旧配方')
        if not selected.get('fully_evaluated'):raise ValueError('缺少新候选的完整开发诊断')
        # 非有限指标属于计算异常，不能作为允许导出的品质警告。
        json.dumps(selected,allow_nan=False)
    final=gate.assess(candidate,'locked-final',final=True,complete=True)
    if force_new:json.dumps(final,allow_nan=False)
    accepted=selected if force_new else (reference if final['failures'] else selected)
    adopted=accepted['sha256']!=reference['sha256']
    chosen=copy.deepcopy(accepted['entry'])
    quality=dict(policy=FORCED_POLICY if force_new else POLICY,gamma_forward_policy=GAMMA_POLICY,adopted=adopted,accepted=accepted['label'],screen_selected=selected['label'],
        baseline_sha256=canonical(reference['entry'])[1],selected_sha256=canonical(chosen)[1],final=final,
        independent_checks=1,holdout_used_for_training=False,holdout_used_to_try_other_candidates=False,
        accepted_validation=accepted['metrics']['weighted_loss'],
        photo_scope='development-and-holdout' if getattr(gate,'data',None) and gate.data.photos else 'not-bound',
        fallback_reason=[] if force_new else (final['failures'] or ([] if adopted else ['no-qualified-development-improvement'])),
        implementation_sha256={name:__import__('core').sha(Path(__file__).with_name(name).read_bytes())
            for name in ('native_joint.py','native_solver.py','native_runtime.py','native_joint_workbench.py',
                'native_conditional_grid.py','native_joint_integer.py','native_joint_recovery.py','native_guard_policy.py','native_precision_research.py')})
    for name in ('web/native_full_photos.py','web/native_joint_photo.py','web/native_robust_grid.py',
                 'web/native_cached_forward.py','scripts/native_gamma.py',
                 'scripts/edit_parameter_context.py','scripts/edit_native_model.py'):
        quality['implementation_sha256'][name]=__import__('core').sha((Path(__file__).resolve().parents[1]/name).read_bytes())
    def describe(reason):
        if reason.startswith('dense'):return '双域过渡未通过'
        if reason.startswith('photo'):return '照片误差未通过'
        return {'gray_rmse':'灰阶误差上升','delta_e00_p95':'颜色P95上升','rgb_rmse':'RGB误差未改善',
            'delta_e00_mean':'感知色差未改善','no-qualified-development-improvement':'没有同时改善色差的合格候选'}.get(reason,'候选未通过独立验收')
    quality['fallback_reason_zh']=list(dict.fromkeys(describe(r) for r in quality['fallback_reason']))
    if force_new:
        failures=[('development',r) for r in selected['failures']]+[('independent',r) for r in final['failures']]
        quality.update(quality_passed=not failures,retained_baseline=False,export_allowed=True,
            failed_checks=[scope+':'+r for scope,r in failures],
            failed_checks_zh=list(dict.fromkeys(('开发集：' if scope=='development' else '独立终检：')+describe(r) for scope,r in failures)))
    return chosen,quality
