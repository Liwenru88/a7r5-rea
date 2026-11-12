"""锁定上游正式训练流程，保留本地工程、预览和历史任务入口。"""
from pathlib import Path
import copy
import json
import threading
import time
import traceback
import uuid
from stack_training import train, save
from training_progress import TrainingProgress

HERE = Path(__file__).resolve().parent
REVISION = '06c35577255eddef641c695d179b0e6f699ffe62+native24/2'
PROFILE = json.loads((HERE/'formal_profile.json').read_text(encoding='utf-8'))
SETTINGS = PROFILE['settings']


def bind(body):
    """正式色卡模式固定预算；标识、槽号和目标来源仍属于用户。"""
    result = copy.deepcopy(body)
    mode = result.get('training_profile')
    if mode not in (None, 'custom', 'upstream-formal/1'):
        raise ValueError('未知训练方案')
    formal = result.get('target_kind') == 'chart-image' and not result.get('speed_priority', False) and mode != 'custom'
    if mode == 'upstream-formal/1' and not formal:
        raise ValueError('正式方案需要色卡图目标及标准训练模式')
    if formal:
        if result.get('dataset_id') not in (None, PROFILE['options']['dataset_id']):
            raise ValueError('正式方案色卡版本不符；旧版色卡请选择自定义预算')
        result.update(copy.deepcopy(PROFILE['options']))
        result.update(training_profile='upstream-formal/1', training_revision=REVISION)
    else:
        result['training_profile'] = 'custom'
        for key in ('packed_selection_policy','packed_baseline','quality_set'):
            result.pop(key,None)
        options = dict(result.get('search_options') or {})
        options.setdefault('postfit_deburr', False)
        result['search_options'] = options
    return result


def completed(identifier, job, srv):
    path = srv.RUNS/identifier/'stack_audit.json'
    if not path.exists():
        return False
    audit = json.loads(path.read_text())
    if (audit['settings'] != SETTINGS or not audit['bin_decode_recompile']
            or not audit['decoded_native_cpu_replay']):
        raise ValueError('Formal stack audit mismatch')
    from grid_distillation import load_result
    load_result(srv.RUNS/identifier, job['result']['grid_key'])
    if srv.core.sha((srv.RUNS/identifier/'R5NATIVE.BIN').read_bytes()) != audit['binary_sha256']:
        raise ValueError('Formal BIN identity mismatch')
    return True


def mirror_progress(source, output, positions):
    """实时转发父任务进度，只追加完整日志行，不重复写入。"""
    for name in ('training_progress.json', 'grid_progress.json'):
        path=source/name
        if path.exists():save(output/name,json.loads(path.read_text()))
        log=path.with_suffix('.jsonl')
        if log.exists():
            at=positions.get(log.name,0)
            with log.open('rb') as stream:
                stream.seek(at)
                chunk=stream.read()
            end=chunk.rfind(b'\n')+1
            if end:
                with (output/log.name).open('ab') as stream:stream.write(chunk[:end])
                positions[log.name]=at+end


def work(server, native_work, identifier, options, resume=False):
    final = server.JOBS[identifier]
    out = server.RUNS/identifier
    out.mkdir(exist_ok=True)
    # 接续时保留原生父任务及其目标身份。
    prior = json.loads((out/'job.json').read_text()) if (out/'job.json').exists() else {}
    baseid = prior.get('base_job') or uuid.uuid4().hex
    source = server.RUNS/baseid
    base = json.loads((source/'job.json').read_text()) if (source/'job.json').exists() else dict(
        id=baseid, status='queued', target_kind=options.get('target_kind'), started=time.time(), phase='原生基准准备')
    base["internal_parent"] = True
    server.JOBS[baseid] = base
    source.mkdir(parents=True, exist_ok=True)
    request_path=source/'request.json'
    previous_options=json.loads(request_path.read_text()) if request_path.exists() else None
    if previous_options is None:save(request_path, options)
    if resume:
        # 只归档本任务的中断产物，保留重试输入；重新转发父任务日志。
        names=[p for p in out.iterdir() if p.name not in ('job.json','request.json','interrupted_stack')]
        if names:
            archive=out/'interrupted_stack'/uuid.uuid4().hex
            archive.mkdir(parents=True)
            for path in names:path.rename(archive/path.name)
    final.update(status='running', base_job=baseid, phase='正式方案：原生12起点基准')
    save(out/'job.json', final)
    stop = threading.Event()
    positions={}

    def mirror():
        while not stop.wait(1):
            try:
                final['phase'] = '正式基准：' + base.get('phase', '训练中')
                mirror_progress(source,out,positions)
                progress_name = ('grid_progress.json' if base.get('status') == 'done'
                    or '压缩训练' in base.get('phase', '') else 'training_progress.json')
                if (source/progress_name).exists():
                    save(out/'training_progress.json', json.loads((source/progress_name).read_text()))
                save(out/'job.json', {k:v for k,v in final.items() if k != 'process'})
            except (OSError, ValueError):
                pass

    thread = threading.Thread(target=mirror, daemon=True)
    thread.start()
    try:
        if previous_options is not None and previous_options!=options:
            raise ValueError('正式父任务的目标或训练选项不一致，拒绝复用')
        if not __import__('gpu_runtime').available():
            raise RuntimeError('正式训练需要 Apple Metal/MPS；可选择自定义训练显式使用 CPU')
        if base.get('status') != 'done':
            native_work(baseid, options, resume=source.exists())
        if base['status'] != 'done':
            raise RuntimeError(base.get('error', 'Native baseline failed'))
        if not base.get('continuation'):
            base['phase'] = '最终网格五轮目标拟合'
            from batch_multiround import continue_job
            with server.RAW_LOCK:
                key, audit = continue_job(baseid, server, total_rounds=5)
            base.update(status='done', phase='正式父基准：五轮网格完成（叠加前）',
                result=dict(base['result'], grid_key=key), continuation=audit)
            save(source/'job.json', base)
        stop.set()
        thread.join()
        mirror_progress(source,out,positions)
        final['phase'] = '正式方案：三轮原生／网格／整数交替'
        save(out/'job.json', final)
        tracker = TrainingProgress(out/'training_progress.json', 3)
        with server.RAW_LOCK:
            if options.get('packed_selection_policy'):
                from packed_training import prepare, finalize
                seed, gate, reference, candidates = prepare(source, out/'packed_candidates', options,
                    tracker.update, validation_runs=server.RUNS)
                train(out, source, final, tracker.update, SETTINGS, seed_entry=seed)
                quality = finalize(out, final, gate, reference, candidates)
                final['quality_selection'] = quality
            else:
                train(out, source, final, tracker.update, SETTINGS)
        if not completed(identifier, final, server):
            raise RuntimeError('Final stack audit missing')
        retained = final.get('quality_selection', {}).get('adopted') is False
        final['phase'] = options.get('short_name', '') + ('：新候选未通过全部验收，已保留基准配方' if retained
            else '：正式训练完成，BIN核验通过')
        tracker.update(stage='正式训练完成，BIN解码与CPU重放通过', state='done')
    except Exception as error:
        final.update(status='error', phase='正式训练失败，日志已保留', error=str(error), finished=time.time())
        (out/'error.log').write_text(traceback.format_exc(), encoding='utf-8')
        traceback.print_exc()
    finally:
        stop.set()
        thread.join()
        if base.get('status') in ('queued', 'running'):
            base.update(status='error', phase='正式父任务已中断', error=final.get('error', 'Parent interrupted'), finished=time.time())
            save(source/'job.json', {k:v for k,v in base.items() if k != 'process'})
        save(out/'job.json', {k:v for k,v in final.items() if k != 'process'})
