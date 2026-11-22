#!/usr/bin/env python3
"""Loopback-only color workstation; no device operations, shell or path API."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
import threading
import time
import traceback
from urllib.parse import urlparse, parse_qs
import uuid
import webbrowser
import zipfile

import core
import chart_target
import chart_datasets
import export_policy423
import filter_library
import projects
import batch_training
from grid_models import default_response
from residual_grid import response_json

STATIC = core.HERE / 'static'
RUNS = Path(os.environ.get('R5_RUNS_DIR', str(core.HERE / 'runs'))).resolve()
TOKEN = secrets.token_urlsafe(32)
JOBS = {}
LOCK = threading.Lock()
POOL = ThreadPoolExecutor(max_workers=1)
DIAGNOSTICS = {}
RAW_LOCK = threading.RLock()
PREVIEWS = {}
PREVIEW_POOL = ThreadPoolExecutor(max_workers=1)
COMPARISON_LOCK = threading.Lock()
MAX_BODY = 65 * 1024 * 1024
TRAINING_REVISION = '06c35577255eddef641c695d179b0e6f699ffe62+native24/2'


def dump(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + '\n').encode()


def preview_work(identifier, job_id, destination, pc=False, grid_key=None, reuse_id=None, grid_enabled=True):
    item = PREVIEWS[identifier]
    raster_input = item.get('input_kind') == 'image'
    source = (RUNS/job_id/'photo_previews'/reuse_id if reuse_id
              else destination/('input.photo' if raster_input else 'input.ARW'))
    slot_args = ['--slot-config', str(destination/'slot_config.json')] if 'project' in item else []
    calibration_args = ['--raw-calibrated'] if item.get('raw_calibrated') and not reuse_id else []
    try:
        item.update(status='running', phase='本地照片解码与预览渲染')
        (destination/'preview.json').write_bytes(dump(item))
        with (destination/'preview.log').open('w') as log:
            process = subprocess.run([sys.executable, str(core.HERE/'photo_preview.py'),
                str(source), str(RUNS/job_id), str(destination)]+slot_args+calibration_args+(['--pc'] if pc else [])+(['--grid',grid_key] if grid_key else [])+(['--reuse'] if reuse_id else [])+(['--raster-input'] if raster_input else [])+([] if grid_enabled else ['--no-grid-effect']),
                stdout=log, stderr=subprocess.STDOUT, timeout=1800,
                env={**os.environ, 'OPENBLAS_NUM_THREADS':'1', 'VECLIB_MAXIMUM_THREADS':'1'})
        if process.returncode:
            details = (destination/'preview.log').read_text(errors='replace')
            raise ValueError(details.strip().splitlines()[-1] if details.strip() else '渲染失败')
        item.update(status='done', phase='照片预览已生成',
                    result=json.loads((destination/'result.json').read_text()))
    except Exception as error:
        item.update(status='error', phase='预览失败', error=str(error))
    finally:
        if not reuse_id: source.unlink(missing_ok=True)
        (destination/'preview.json').write_bytes(dump(item))


def compression_work(identifier,response,post_gray_refinement=False,objective='fuji-target', *, output=None):
    output=RUNS/identifier if output is None else output
    state=dict(status='running',phase='压缩训练：采样总效果、求解与量化微调',started=time.time())
    path=output/'grid_training.json'
    path.write_bytes(dump(state))
    try:
        with RAW_LOCK:
            from grid_distillation import generate
            from training_progress import TrainingProgress
            tracker=TrainingProgress(output/'grid_progress.json',3)
            tracker.update(stage='压缩训练准备',state='running')
            report=generate(output,response,progress=tracker.update,post_gray_refinement=post_gray_refinement,
                            objective=objective)
            tracker.update(stage='压缩训练完成',state='done')
        state.update(status='done',phase='压缩训练完成',key=report['key'])
    except Exception as error:
        state.update(status='error',phase='压缩训练失败',error=str(error))
    state['finished']=time.time()
    path.write_bytes(dump(state))
    return state


def work(identifier, body, resume=False):
    from training_profile import bind,JOINT_REVISION
    from native_joint_workbench import work as joint_work
    if body.get('training_profile')!='native-joint/1' or body.get('training_revision')!=JOINT_REVISION:
        body=bind(body)
    return joint_work(sys.modules[__name__],native_work,identifier,body,resume)


def native_work(identifier, body, resume=False):
    job = JOBS[identifier]
    output = RUNS / identifier
    try:
        output.mkdir(parents=True,exist_ok=True)
        job.update(phase='检查传感器、原生前端与训练集来源', status='running')
        recipe_path=output/'fit/recipe.json'
        reuse_fit=resume and recipe_path.is_file()
        if reuse_fit:
            saved=json.loads(recipe_path.read_text())
            audit=json.loads((output/'chart_target.json').read_text())
            if audit['source_sha256']!=body.get('target_sha256') or saved['source']['pairs_sha256']!=core.sha((output/'pairs.npz').read_bytes()):
                raise ValueError('已有拟合的目标或训练数据身份不符，拒绝接续')
            if saved['source']['dataset_id'] not in chart_datasets.MODULES or saved['source']['dataset_id']!=body.get('dataset_id',__import__('v4_dataset').DATASET_ID):
                raise ValueError('已有拟合色卡版本不符')
            job.update(phase='复用已完成的原生拟合，接续补偿与压缩')
        else:
            fit_native(identifier,body,output,job)
        # Metal command encoders in one service process must not be entered
        # from concurrent batch/HTTP threads. Native fit subprocesses remain
        # independent and retain the requested batch concurrency.
        with RAW_LOCK:
            try:
                result=finish_native(identifier,body,output,job)
            finally:
                from gpu_runtime import available
                if available():
                    import torch
                    torch.mps.synchronize()
        job.update(status='done', phase='拟合与配置转换完成；待实际颜色验收', result=result)
    except Exception as error:
        output.mkdir(parents=True, exist_ok=True)
        (output / 'error.log').write_text(traceback.format_exc())
        job.update(status='error', phase='处理失败', error=str(error))
    finally:
        job['finished'] = time.time()
        write_job(identifier)


def write_job(identifier):
    output = RUNS / identifier
    temporary = output / 'job.tmp'
    temporary.write_bytes(dump({k: v for k, v in JOBS[identifier].items() if k != 'process'}))
    temporary.replace(output / 'job.json')


def fit_request(identifier):
    path = RUNS / identifier / 'request.json'
    if not path.is_file():
        raise ValueError('此历史任务未保存完整训练输入，可重新载入已有结果')
    return json.loads(path.read_bytes())


def reserve_job(identifier, body, signature=None):
    from packed_training import bind_context
    bind_context(body, RUNS)
    output = RUNS / identifier
    output.mkdir(parents=True, exist_ok=False)
    request = output/'request.tmp'
    request.write_bytes(dump(body))
    request.replace(output/'request.json')
    JOBS[identifier] = dict(id=identifier, target_kind=body.get('target_kind','lut'),
                            number=body['number'], name=body['full_name'],
                            signature=signature, status='queued', phase='等待开始', started=time.time())
    write_job(identifier)


def queue_fit(body, retry=False):
    expected_target = body.get('target_sha256') if retry else None
    validate_fit(body)
    from packed_training import bind_context
    bind_context(body, RUNS)
    if expected_target and body.get('target_sha256') != expected_target:
        raise ValueError('训练目标文件已变化，请重新选择目标')
    signature = None
    if body.get('project_id'):
        projects.identifier(body['project_id'])
        identity = {k:v for k,v in body.items() if k not in ('target_id', 'lut')}
        identity['training_revision'] = (dict(server=TRAINING_REVISION,profile=body.get('training_revision'))
            if body.get('training_profile')=='native-joint/1' else TRAINING_REVISION)
        if body.get('target_kind') != 'chart-image':
            identity['lut_sha256'] = core.sha(body['lut'].encode())
        signature = core.sha(json.dumps(identity, sort_keys=True, allow_nan=False).encode())
    with LOCK:
        if signature and not retry:
            from grid_distillation import firmware_config
            for job in reversed(tuple(JOBS.values())):
                if job.get('signature') != signature or job['status'] != 'done':
                    continue
                key = job.get('result', {}).get('grid_key')
                if not key:
                    continue
                try:
                    firmware_config(RUNS/job['id'], key, configuration_only=True)
                except (OSError, ValueError, KeyError):
                    continue
                return dict(id=job['id'], number=body['number'], reused=True)
        if any(job['status'] in ('queued','running') for job in JOBS.values()):
            raise projects.Conflict('已有拟合任务运行，请完成或取消后再提交')
        identifier = uuid.uuid4().hex
        reserve_job(identifier, body, signature)
        POOL.submit(work, identifier, body)
    return dict(id=identifier, number=body['number'])


def fit_native(identifier,body,output,job):
        if body.get('target_kind') == 'chart-image':
            source_path=core.HERE/'chart_uploads'/body['target_id']/'source.bin'
            data=source_path.read_bytes()
            if core.sha(data)!=body['target_sha256']:
                raise ValueError('目标图上传来源发生变化')
            chart_target.prepare(data,output,source_path=source_path,dataset_id=body.get('dataset_id'))
        else:
            lut = output / 'input.cube'
            lut.write_text(body['lut'], encoding='utf-8')
            core.prepare_target(lut, body['gamut'], output,dataset_id=body.get('dataset_id'))
        job.update(phase='原生分阶段拟合与 PC 交替优化' if body.get('pc_compensation',False) else '原生分阶段拟合：明暗、色彩、联合微调')
        solve_native(body,output,job)


def solve_native(body,output,job):
        description = ('source-bound measured RAW frontend -> processed chart image / sRGB'
                       if body.get('target_kind') == 'chart-image' else
                       'integer RAW -> raw-alchemy-v0.6.2-fused ' + body['gamut'] + ' S-Log3 -> uploaded cube')
        cmd = [sys.executable, str(core.HERE / 'fit_anchor_native.py'), str(output / 'pairs.npz'),
               '--capture', str(__import__('baseline').for_job(output)[0]), '--context', str(__import__('baseline').for_job(output)[1]), '--gamut', '0',
               '--output', str(output / 'fit'), '--evaluations', str(body['evaluations']),
               '--target-description', description]
        from training_policy import group_importance
        from optimizer_policy import search_options, pc_options
        cmd += ['--pc-options',json.dumps(pc_options(body.get('pc_options'))), '--group-weights',json.dumps(group_importance(body.get('group_weights'))), '--search-options',json.dumps(search_options(body.get('search_options')))]
        if body.get('packed_selection_policy'):
            cmd.append('--save-candidates')
        if body.get('white_balance',False):
            cmd.append('--white-balance')
        if body.get('speed_priority',False):
            cmd.append('--fast')
        elif body.get('pc_compensation',False):
            cmd.append('--pc-compensation')
        with (output / 'fit.log').open('w') as log:
            env={**os.environ, 'OPENBLAS_NUM_THREADS': '1', 'VECLIB_MAXIMUM_THREADS': '1'}
            if body.get('training_profile') in ('upstream-formal/1','native-joint/1'):env['R5_GPU_STRICT']='1'
            process = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT,
                                       env=env)
            job['process'] = process
            try:
                code = process.wait()
            finally:
                job.pop('process', None)
        if code:
            raise ValueError('拟合器退出码 %s，请查看完整日志' % code)


def finish_native(identifier,body,output,job):
        job.update(phase='验证配方并转换 4.23 自定义配置')
        result = core.finish_fit(output, body['number'], body['short_name'], body['full_name'], body.get('gamma_endpoint128'))
        if body.get('pc_compensation',False):
            job.update(phase='整体训练：从整数原生参数重建 PC 残差并验证')
            from pc_compensation import generate
            value=generate(output)
            result['pc_compensation']=dict(enabled=True,sha256=core.sha((output/'pc_compensation.json').read_bytes()),metrics=value['metrics'])
        else:
            result['pc_compensation']=dict(enabled=False)
        if body.get('compression_training'):
            job.update(phase='压缩训练：最终网格直接拟合富士目标')
            state=compression_work(identifier,body['pc_options']['response'],body.get('post_gray_refinement',False),
                                   objective=body.get('compression_objective','fuji-target'),output=output)
            if state['status']!='done':raise ValueError(state.get('error','压缩训练失败'))
            result['grid_key']=state['key']
        return result


def validate_fit(body):
    from training_profile import bind
    body.update(bind(body))
    body['post_gray_refinement']=False
    body['compressed_alternation_rounds']=0
    body.setdefault('compression_objective','fuji-target')
    if body['compression_objective'] not in ('fuji-target','pc-teacher'):
        raise ValueError('无效最终网格训练目标')
    if type(body.get('speed_priority',False)) is not bool:raise ValueError('速度优先开关须为布尔值')
    body.setdefault('speed_priority',False)
    from training_policy import group_importance
    body['group_weights']=group_importance(body.get('group_weights'))
    from optimizer_policy import search_options, pc_options
    if type(body.get('white_balance',False)) is not bool:raise ValueError('白平衡开关须为布尔值')
    body.setdefault('white_balance',False)
    body.setdefault('pc_compensation',True)
    options=body.get('search_options')
    if isinstance(options,dict):
        # 历史任务和旧页面仍可提交，新拟合采用上游的 Adam 预算。
        options={key:value for key,value in options.items()
                 if key not in ('adam_steps','adam_learning_rate')}
    body['search_options']=search_options(options)
    body['pc_options']=pc_options(body.get('pc_options'))
    if type(body.get('compression_training',False)) is not bool:raise ValueError('压缩训练开关无效')
    if body.get('compression_training'):
        body['pc_compensation']=True
        body['pc_options']=pc_options(dict(curve_mode='tone-tint',grid_enabled=True,response=body['pc_options']['response']))
    body.pop('joint_native', None)
    body.pop('guarded_adam', None)
    if type(body.get('pc_compensation',False)) is not bool:
        raise ValueError('PC 补偿开关必须为布尔值')
    if type(body.get('number')) is not int or not 1 <= body['number'] <= core.compiler.SLOT_LIMIT:
        raise ValueError('自定义配置序号必须为 1–24')
    if type(body.get('evaluations')) is not int or not 1 <= body['evaluations'] <= 2000:
        raise ValueError('每阶段求解评估上限必须为 1–2000')
    kind=body.get('target_kind','lut')
    if kind not in ('lut','chart-image'):
        raise ValueError('请选择目标来源')
    if kind=='chart-image':
        target_id=body.get('target_id')
        if not isinstance(target_id,str) or len(target_id)!=32 or any(c not in '0123456789abcdef' for c in target_id):
            raise ValueError('请先上传色卡目标图')
        folder=core.HERE/'chart_uploads'/target_id
        body['dataset_id']=chart_datasets.upload_version(folder,body.get('dataset_id'))
        data=(folder/'source.bin').read_bytes()
        chart_target.decode(data,body['dataset_id'])
        body['target_sha256']=core.sha(data)
    elif body.get('gamut') not in ('S-Gamut3', 'S-Gamut3.Cine'):
        raise ValueError('请选择 LUT 输入色域')
    if kind=='lut':
        body['dataset_id']=chart_datasets.get(body.get('dataset_id')).DATASET_ID
    core.gamma_endpoint(body.get('gamma_endpoint128'))
    if kind=='lut' and (not isinstance(body.get('lut'), str) or not body['lut'].strip()):
        raise ValueError('请导入 .cube LUT')
    sample = dict(core.presets()[0][0], number=body['number'],
                  short_name=body.get('short_name'), full_name=body.get('full_name'))
    core.compiler.pack(core.config([sample]))
    return body


class Handler(BaseHTTPRequestHandler):
    def respond(self, data, mime='application/json', status=200, filename=None, revision=None):
        if not isinstance(data, bytes):
            data = dump(data)
        self.send_response(status)
        self.send_header('Content-Type', mime)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' blob: data:; connect-src 'self'; frame-ancestors 'none'")
        if revision is not None:
            self.send_header('X-R5-Project-Revision', str(revision))
        if filename:
            self.send_header('Content-Disposition', 'attachment; filename="' + filename + '"')
        self.end_headers()
        self.wfile.write(data)

    def trusted(self):
        port = self.server.server_address[1]
        hosts = ('127.0.0.1:' + str(port), 'localhost:' + str(port))
        if self.headers.get('Host') not in hosts:
            return False
        origin = self.headers.get('Origin')
        return origin is None or origin in ['http://' + h for h in hosts]

    def do_GET(self):
        if not self.trusted():
            return self.respond(dict(error='Local origin required'), status=403)
        path = urlparse(self.path).path
        try:
            if path == '/api/filter-library':
                return self.respond(filter_library.catalog())
            if path.startswith('/api/filter-samples/'):
                from urllib.parse import unquote
                rel = unquote(path[len('/api/filter-samples/'):])
                return self.respond(filter_library.sample_file(rel).read_bytes(), 'image/jpeg')
            if path == '/api/projects':
                return self.respond(projects.Store(RUNS).list())
            if path == '/api/projects/open':
                key = parse_qs(urlparse(self.path).query).get('id', [''])[0]
                return self.respond(projects.Store(RUNS).public(projects.Store(RUNS).get(key)))
            if path.startswith('/api/batches/'):
                return batch_training.get(self, path, sys.modules[__name__])
            if path == '/api/chart-original':
                dataset_id=parse_qs(urlparse(self.path).query).get('dataset_id',[None])[0]
                return self.respond(chart_target.download(dataset_id), 'application/zip', filename='GFX-100MP-chart.zip')
            if path == '/api/chart-file':
                query=parse_qs(urlparse(self.path).query)
                name,data=chart_target.raw_file(query.get('dataset_id',[None])[0],query.get('format',['raf'])[0])
                return self.respond(data,'application/octet-stream',filename=name)
            if path == '/api/bootstrap':
                entries, provenance = core.presets()
                return self.respond(dict(token=TOKEN, presets=entries, provenance=provenance,
                                         default_chart=chart_target.manifest(),
                                         chart_versions=chart_datasets.catalog(),
                                         compute_backend=__import__('gpu_runtime').policy(),
                                         training_profile=__import__('training_profile').JOINT_PROFILE,
                                         legacy_training_profile=__import__('training_profile').PROFILE,
                                         training_revision=TRAINING_REVISION,
                                         latest_batch=batch_training.latest(core.HERE),
                                         template=core.config([]), slot_limit=core.compiler.SLOT_LIMIT,
                                         config_schemas=core.compiler.SCHEMAS, max_project_bytes=core.compiler.MAX_JSON,
                                         stock_grids=__import__("stock_grids").catalog(),
                                         fitting_baseline='PT / v4.5 5300K simulated ITP+SSCS · 99,372 patches; derived context',
                                         grid_response=default_response(), history=[dict(id=k, status=v['status'], started=v['started'], phase=v['phase'],target_kind=v.get('target_kind','lut'),pc_available=(RUNS/k/'pc_compensation.json').is_file())
                                                  for k, v in sorted(JOBS.items(), key=lambda kv: kv[1]['started'], reverse=True) if not v.get('internal_parent')][:30],
                                         jobs=[k for k, v in JOBS.items() if v['status'] in ('running', 'queued') and not v.get('internal_parent')]))
            if path.startswith('/api/previews/'):
                bits = path.split('/')
                item = PREVIEWS.get(bits[3])
                if not item:
                    return self.respond(dict(error='预览不存在'), status=404)
                if len(bits) == 4:
                    value = dict(item)
                    if item['status'] in ('queued','running'):
                        progress = RUNS/item['job']/'photo_previews'/item['id']/'progress.json'
                        try:
                            state = json.loads(progress.read_text())
                            value['phase'] = state['phase'] + (' · %d%%' % state['percent'])
                        except (OSError,ValueError,KeyError): pass
                    return self.respond(value)
                name = bits[4]
                names = ('lut.png', 'model.png', 'result.json')
                if item.get('result', {}).get('raw_calibration'):
                    names += ('calibrated.png',)
                if len(bits) == 5 and name in names and item['status'] == 'done':
                    file = RUNS/item['job']/'photo_previews'/item['id']/name
                    return self.respond(file.read_bytes(), 'image/png' if name.endswith('.png') else 'application/json')
                return self.respond(dict(error='预览尚未就绪'), status=404)
            if path.startswith('/api/jobs/'):
                bits = path.split('/')
                identifier = bits[3]
                if identifier not in JOBS:
                    return self.respond(dict(error='任务不存在'), status=404)
                job = JOBS[identifier]
                if len(bits) == 5 and bits[4] in ('training-trace', 'training-log'):
                    from training_progress import TRACE_FILES, read_trace
                    folder = RUNS / identifier
                    if bits[4] == 'training-trace':
                        query = parse_qs(urlparse(self.path).query)
                        traces = {kind: folder/name for kind, name in TRACE_FILES.items()}
                        if job.get('adam_candidate_folder'):
                            candidate_folder = folder/job['adam_candidate_folder']
                            traces.update({f'candidate_{kind}': candidate_folder/name for kind, name in TRACE_FILES.items()})
                        return self.respond({kind: read_trace(path,
                            max(0, int(query.get(kind, ['0'])[0]))) for kind, path in traces.items()})
                    memory = io.BytesIO()
                    with zipfile.ZipFile(memory, 'w', zipfile.ZIP_DEFLATED) as archive:
                        roots = [(folder, '')]
                        if job.get('adam_candidate_folder'):
                            roots.append((folder/job['adam_candidate_folder'], 'adam-2000/'))
                        for root, prefix in roots:
                            for name in (*TRACE_FILES.values(), 'fit.log', 'error.log', 'comparison/comparison.json'):
                                source = root/name
                                if source.is_file():
                                    archive.write(source, prefix+name)
                    return self.respond(memory.getvalue(), 'application/zip',
                        filename='r5-training-log-' + identifier + '.zip')
                if len(bits) == 5 and bits[4] == 'diagnostics':
                    if job['status'] not in ('done', 'error'):
                        raise ValueError('任务尚未完成')
                    pc=parse_qs(urlparse(self.path).query).get('pc',['0'])[0]=='1'
                    grid_key=parse_qs(urlparse(self.path).query).get('grid',[''])[0] or None
                    pc=bool(pc or grid_key)
                    key=(identifier,pc,grid_key)
                    with RAW_LOCK:
                        if key not in DIAGNOSTICS:
                            DIAGNOSTICS[key] = core.diagnostics(RUNS / identifier,pc,grid_key)
                    return self.respond(DIAGNOSTICS[key])
                if len(bits)==5 and bits[4]=='grid-training':
                    from grid_distillation import latest,load_result
                    state_path=RUNS/identifier/'grid_training.json'
                    state=json.loads(state_path.read_text()) if state_path.exists() else dict(status='idle')
                    from training_progress import read_progress
                    state['training_progress']=read_progress(RUNS/identifier/'grid_progress.json') if state['status']=='running' else None
                    requested_key=parse_qs(urlparse(self.path).query).get('key',[''])[0]
                    grid_key=requested_key
                    if not grid_key and state['status'] != 'running':
                        grid_key=state.get('key') or latest(RUNS/identifier)
                    if grid_key:
                        state['key']=grid_key
                        state['report']=load_result(RUNS/identifier,grid_key)[0]
                    return self.respond(state)
                if len(bits)==5 and bits[4]=='pc-download':
                    return self.respond((RUNS/identifier/'pc_compensation.json').read_bytes(), filename='PC-compensation.json')
                if len(bits)==5 and bits[4]=='grid-distillation-download':
                    from grid_distillation import download
                    key=parse_qs(urlparse(self.path).query).get('key',[''])[0]
                    return self.respond(download(RUNS/identifier,key),'application/zip',filename='native-sized-grid.zip')
                if len(bits)==5 and bits[4]=='grid-firmware-download':
                    from grid_distillation import firmware_config
                    key=parse_qs(urlparse(self.path).query).get('key',[''])[0]
                    return self.respond(firmware_config(RUNS/identifier,key),'application/zip',filename='r5-grid-config.zip')
                if len(bits)==5 and bits[4]=='grid-firmware-config':
                    from grid_distillation import firmware_config
                    key=parse_qs(urlparse(self.path).query).get('key',[''])[0]
                    config=firmware_config(RUNS/identifier,key,configuration_only=True)
                    config['export_sources']={str(config['entries'][0]['number']):dict(kind='compressed',job=identifier,key=key)}
                    return self.respond(config)
                if len(bits) == 5 and bits[4] == 'download':
                    if job['status'] not in ('done', 'error'):
                        raise ValueError('任务尚未完成')
                    memory = io.BytesIO()
                    with zipfile.ZipFile(memory, 'w', zipfile.ZIP_DEFLATED) as archive:
                        # Only files from this job, never the original capture/RAW.
                        for name in ['native_config.json', 'conversion_audit.json',
                                     'input_audit.json', 'chart_target.json', 'target-image.bin', 'fit/recipe.json', 'pc_compensation.json', 'fit.log', 'error.log', 'job.json',
                                     'request.json', 'training_progress.json', 'training_progress.jsonl', 'grid_progress.json', 'grid_progress.jsonl',
                                     'stack_audit.json', 'stack_comparison.json', 'stack_progress.json']:
                            source = RUNS / identifier / name
                            if source.is_file():
                                archive.write(source, name)
                        from grid_distillation import latest
                        grid_key=latest(RUNS/identifier)
                        if grid_key:
                            for name in ['result.json','teacher.json','grid.payload','postfit-before.payload']:
                                item=RUNS/identifier/'grid_distillation'/grid_key/name
                                if item.is_file():archive.write(item,'compressed/'+name)
                        if job.get('base_job'):
                            parent=RUNS/job['base_job']
                            for name in ('fit.log','training_progress.jsonl','grid_progress.jsonl','grid_4187_five_rounds/multiround.json','grid_4187_five_rounds/selection.json'):
                                item=parent/name
                                if item.is_file():archive.write(item,'baseline/'+name)
                        for name in ('options.json','joint-audit.json','final-acceptance.json','C/loss.jsonl',
                                     'conditional-reference/audit.json','conditional-reference/loss.jsonl',
                                     'conditional-candidate/audit.json','conditional-candidate/loss.jsonl',
                                     'integer/audit.json','recovery/audit.json','full-photos/audit.json',
                                     'full-photos/loss.jsonl','full-photos/photo-constraints.jsonl'):
                            item=RUNS/identifier/'native_joint'/name
                            if item.is_file():archive.write(item,'native_joint/'+name)
                        robust=RUNS/identifier/'native_joint'/'robust'
                        if robust.is_dir():
                            for item in sorted(robust.rglob('*')):
                                if item.is_file() and item.suffix in ('.json','.jsonl'):
                                    archive.write(item,'native_joint/robust/'+str(item.relative_to(robust)))
                    return self.respond(memory.getvalue(), 'application/zip', filename='r5-fit-' + identifier + '.zip')
                if len(bits) != 4:
                    return self.respond(dict(error='Not found'), status=404)
                value = {k: v for k, v in job.items() if k != 'process'}
                value['retry_available'] = (RUNS/identifier/'request.json').is_file()
                previews = [p for p in PREVIEWS.values() if p['job'] == identifier and p['status'] == 'done']
                if previews:
                    value['photo_preview'] = previews[-1]
                    value['photo_previews'] = previews
                from training_progress import read_progress
                progress_name='grid_progress.json' if '压缩训练' in job.get('phase','') else 'training_progress.json'
                progress_root = RUNS/identifier
                value['training_progress']=read_progress(progress_root/progress_name) if job['status']=='running' else None
                from training_progress import TRACE_FILES
                value['training_trace_available'] = any(
                    (RUNS/identifier/name).is_file() for name in TRACE_FILES.values())
                value['training_log_available'] = value['training_trace_available'] or any(
                    (RUNS/identifier/name).is_file() for name in ('fit.log', 'error.log'))
                log = RUNS / identifier / 'fit.log'
                value['log'] = log.read_text(errors='replace')[-12000:] if log.exists() else ''
                return self.respond(value)
            assets = {'/': ('index.html', 'text/html; charset=utf-8'),
                      '/photo-metrics.js': ('photo-metrics.js', 'text/javascript; charset=utf-8'),
                      '/workspace.js': ('workspace.js', 'text/javascript; charset=utf-8'),
                      '/filter-library.js': ('filter-library.js', 'text/javascript; charset=utf-8'),
                      '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                      '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if path in assets:
                name, mime = assets[path]
                return self.respond((STATIC / name).read_bytes(), mime)
            self.respond(dict(error='Not found'), status=404)
        except Exception as error:
            self.respond(dict(error=str(error)), status=400)

    def project_request(self, action, length):
        if not 0 < length <= projects.LIMIT:
            raise ValueError('工程请求大小须在 8 MiB 内')
        data = self.rfile.read(length)
        if len(data) != length:
            raise ValueError('工程上传不完整')
        store = projects.Store(RUNS)
        if action == 'restore':
            if self.headers.get('Content-Type') != 'application/octet-stream':
                raise ValueError('请选择 .r5proj 工程备份')
            value = projects.restore(data)
            with LOCK:
                result = store.write(value)
            return self.respond(result)
        body = projects.decoded(data)
        filename = None
        revision = None
        try:
            with LOCK:
                if action == 'create':
                    value = projects.empty(body['name'])
                    if 'sha256' in body:
                        store.import_bin(value, body['sha256'])
                    if 'config' in body:
                        incoming = body['config']
                        if 'export_sources' in incoming:
                            recipe, _ = export_policy423.validate(incoming, RUNS)
                        else:
                            recipe = export_policy423.configuration(incoming)
                            core.compile_config(recipe)
                        value['entries'] = recipe['entries']
                        value['format'] = core.compiler.format_version(recipe)
                        for source in incoming.get('export_sources', {}).values():
                            if source.get('kind') == 'imported-bin':
                                store.import_asset(value, source['sha256'])
                        value['sources'] = incoming.get('export_sources', {})
                    result = store.write(value)
                elif action in ('rename', 'duplicate', 'save', 'merge'):
                    result = store.update(body, action)
                elif action in ('export', 'backup', 'export-preview'):
                    value = store.get(body['id'])
                    if type(body['revision']) is not int or value['revision'] != body['revision']:
                        raise projects.Conflict('工程版本已变化，请重新打开工程')
                    if action == 'export-preview':
                        result = store.export_preview(value)
                    elif action == 'export':
                        mode = body.get('endpoint_mode', projects.STANDARD)
                        result, value = store.export(value, body.get('allow_saved') is True,
                                                     body.get('allow_empty') is True, mode)
                        suffix = '' if mode == projects.STANDARD else '-' + mode
                        filename = f'r5-native-config{suffix}.zip'
                        revision = value['revision']
                    else:
                        result = projects.zip_bytes({'project.json': projects.encoded(value)})
                        filename = 'colorlab.r5proj'
                else:
                    return self.respond(dict(error='Not found'), status=404)
        except projects.Conflict as error:
            return self.respond(dict(error=str(error)), status=409)
        if filename:
            return self.respond(result, 'application/zip', filename=filename, revision=revision)
        return self.respond(result)

    def do_POST(self):
        if not self.trusted() or self.headers.get('X-R5-Token') != TOKEN:
            return self.respond(dict(error='Local session token required'), status=403)
        try:
            length = int(self.headers.get('Content-Length', '0'))
            path = urlparse(self.path).path
            if path.startswith('/api/projects/'):
                return self.project_request(path.rsplit('/', 1)[-1], length)
            if path == '/api/import-bin':
                if (not core.compiler.HEADER <= length <= core.compiler.MAXIMUM or
                        self.headers.get('Content-Type') != 'application/octet-stream'):
                    raise ValueError('请上传128～58976字节的R5NATIVE.BIN（v4／v5）')
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError('BIN上传不完整')
                with LOCK:
                    value = export_policy423.import_binary(data, RUNS)
                return self.respond(value)
            if urlparse(self.path).path == '/api/chart-target':
                if not 0 < length <= chart_target.MAX_BYTES or self.headers.get('Content-Type')!='application/octet-stream':
                    raise ValueError('请以二进制上传 1 GiB 内的 TIFF 或 JPG')
                data=self.rfile.read(length)
                if len(data)!=length:
                    raise ValueError('目标图上传不完整')
                dataset_id=parse_qs(urlparse(self.path).query).get('dataset_id',[None])[0]
                dataset_id=chart_datasets.get(dataset_id).DATASET_ID
                _, audit=chart_target.decode(data,dataset_id)
                identifier=uuid.uuid4().hex
                destination=core.HERE/'chart_uploads'/identifier
                destination.mkdir(parents=True)
                (destination/'source.bin').write_bytes(data)
                (destination/'audit.json').write_bytes(dump(audit))
                return self.respond(dict(id=identifier,audit=audit),status=201)
            if urlparse(self.path).path == '/api/preview':
                if not 0 < length <= 512*1024*1024 or self.headers.get('Content-Type') != 'application/octet-stream':
                    raise ValueError('请上传 512 MiB 内的照片二进制文件')
                query = parse_qs(urlparse(self.path).query)
                job_id = query.get('job', [''])[0]
                project_id = query.get('project', [''])[0]
                input_kind = query.get('input', ['raw'])[0]
                if input_kind not in ('raw', 'image'):
                    raise ValueError('请选择 ARW、JPG、PNG 或 TIFF 照片')
                raw_calibrated = query.get('raw_calibrated', ['0'])[0]
                if raw_calibrated not in ('0', '1') or (raw_calibrated == '1' and input_kind != 'raw'):
                    raise ValueError('RAW 校准对照仅支持 ARW 输入')
                pc = query.get('pc', ['0'])[0] == '1'
                grid_key = query.get('grid', [''])[0] or None
                slot_config = None
                if project_id:
                    if job_id or pc or grid_key:
                        raise ValueError('请选择槽位或训练任务作为预览来源')
                    slot = int(query.get('slot', ['0'])[0])
                    project = projects.Store(RUNS).get(project_id)
                    entry = next((entry for entry in project['entries'] if entry['number']==slot), None)
                    if entry is None:
                        raise ValueError('请先选中已保存的槽位')
                    # 与工程导出共用有效格式，避免新增13–24槽后仍按原v4校验。
                    slot_config = projects.config(project)
                    slot_config['entries'] = [entry]
                    core.compiler.pack(slot_config)
                    job_id = '_slot_previews'
                elif job_id not in JOBS or JOBS[job_id]['status'] != 'done' or not (RUNS/job_id/'fit/recipe.json').is_file():
                    raise ValueError('请选择已保存的槽位或已完成的训练任务')
                elif grid_key:
                    from grid_distillation import load_result
                    load_result(RUNS/job_id,grid_key)
                with LOCK:
                    if any(p['status'] in ('queued', 'running') for p in PREVIEWS.values()):
                        return self.respond(dict(error='已有照片预览运行，请稍候'), status=409)
                    identifier = uuid.uuid4().hex
                    destination = RUNS/job_id/'photo_previews'/identifier
                    destination.mkdir(parents=True)
                    # Stream the original only into this isolated preview directory.
                    remaining = length
                    source = destination/('input.photo' if input_kind=='image' else 'input.ARW')
                    try:
                        with source.open('wb') as stream:
                            while remaining:
                                chunk = self.rfile.read(min(1024*1024, remaining))
                                if not chunk:
                                    raise ValueError('照片上传不完整')
                                stream.write(chunk)
                                remaining -= len(chunk)
                        if slot_config is not None:
                            (destination/'slot_config.json').write_bytes(dump(slot_config))
                    except (OSError, ValueError):
                        source.unlink(missing_ok=True)
                        (destination/'slot_config.json').unlink(missing_ok=True)
                        destination.rmdir()
                        raise
                    PREVIEWS[identifier] = dict(id=identifier, job=job_id, status='queued', phase='等待渲染',
                                                input_kind=input_kind, raw_calibrated=raw_calibrated == '1')
                    if slot_config is not None:
                        PREVIEWS[identifier].update(project=project_id, slot=slot)
                    (destination/'preview.json').write_bytes(dump(PREVIEWS[identifier]))
                    PREVIEW_POOL.submit(preview_work, identifier, job_id, destination,pc,grid_key,None,query.get('grid_effect',['1'])[0]!='0')
                return self.respond(dict(id=identifier), status=202)
            if path == '/api/preview-color-metrics':
                query = parse_qs(urlparse(self.path).query)
                rows = query.get('rows', [''])[0].split(',')
                width, height = [int(query.get(axis, ['0'])[0]) for axis in ('width', 'height')]
                if (not all(1 <= size <= 512 for size in (width, height))
                        or len(rows) != len(set(rows))
                        or not set(rows) <= {'model', 'calibrated', 'camera'}
                        or self.headers.get('Content-Type') != 'application/octet-stream'
                        or length != width*height*3*(len(rows)+1)):
                    raise ValueError('对照图采样数据无效')
                data = self.rfile.read(length)
                if len(data) != length:
                    raise ValueError('对照图采样数据不完整')

                import numpy as np
                from perceptual import compare_rgb8

                target, *predictions = np.frombuffer(data, dtype=np.uint8).reshape(len(rows)+1, -1, 3)
                return self.respond(compare_rgb8(target, dict(zip(rows, predictions))))
            if path == '/api/preview-comparison-image':
                if not 0 < length <= 512*1024*1024 or self.headers.get('Content-Type') != 'application/octet-stream':
                    raise ValueError('请上传 512 MiB 内的 JPG、PNG 或 RGB TIFF')
                kind = parse_qs(urlparse(self.path).query).get('kind', ['target'])[0]
                if kind not in ('target', 'camera'):
                    raise ValueError('对照图来源无效')
                if not COMPARISON_LOCK.acquire(blocking=False):
                    return self.respond(dict(error='已有对照图正在解码，请稍候'), status=409)
                try:
                    from photo_preview import comparison_png

                    with tempfile.TemporaryDirectory(prefix='r5-comparison-') as folder:
                        source = Path(folder)/'input.photo'
                        remaining = length
                        with source.open('wb') as stream:
                            while remaining:
                                chunk = self.rfile.read(min(1024*1024, remaining))
                                if not chunk:
                                    raise ValueError('对照图上传不完整')
                                stream.write(chunk)
                                remaining -= len(chunk)
                        try:
                            png = comparison_png(source, camera_jpeg=kind == 'camera')
                        except Exception as error:
                            raise ValueError('无法解码对照图，请检查图像格式和 ICC 配置') from error
                finally:
                    COMPARISON_LOCK.release()
                return self.respond(png, 'image/png')
            if urlparse(self.path).path == '/api/raw-export':
                if not 0 < length <= 512*1024*1024:
                    raise ValueError('ARW 大小必须在 512 MiB 内')
                if self.headers.get('Content-Type') != 'application/octet-stream':
                    raise ValueError('ARW 需以二进制上传')
                identifier = parse_qs(urlparse(self.path).query).get('job', [''])[0]
                job = JOBS.get(identifier)
                if not job or job['status'] not in ('done', 'error'):
                    raise ValueError('请先选择一个已完成的拟合任务')
                recipe = RUNS / identifier / 'fit/recipe.json'
                if not recipe.is_file():
                    raise ValueError('任务没有可用拟合配方')
                if not RAW_LOCK.acquire(blocking=False):
                    return self.respond(dict(error='已有 RAW 导出任务，请稍候'), status=409)
                try:
                    original = self.rfile.read(length)
                    if len(original) != length:
                        raise ValueError('ARW 上传不完整')
                    destination = RUNS / identifier / 'raw_exports' / uuid.uuid4().hex
                    audit = core.write_validation_raw(original, recipe, destination)
                    memory = io.BytesIO()
                    with zipfile.ZipFile(memory, 'w', zipfile.ZIP_STORED) as archive:
                        filename=audit.get('file','fitted-ST.ARW')
                        archive.write(destination / filename, filename)
                        audit_name=Path(filename).with_suffix('.audit.json').name
                        archive.write(destination / audit_name, audit_name)
                        archive.writestr('Edit验证说明.txt',
                            '本文件使用所选拟合任务的原始配方，非编辑器后续手动参数。\n'
                            '在 Imaging Edge Edit 中显式选择 '+audit.get('look','ST')+'。\n'
                            '关闭镜头补偿，保持白平衡、曝光、锐度和降噪等设置与对照一致后导出。\n'
                            'RAW 嵌入预览未重绘，不代表实际滤镜结果。传感器数据和其他外观参数保持。\n'
                            '任务ID：' + identifier + '\n配方SHA256：' + audit['recipe_sha256'] + '\n')
                    return self.respond(memory.getvalue(), 'application/zip', filename='r5-edit-validation.zip')
                finally:
                    RAW_LOCK.release()
            if not 0 < length <= MAX_BODY:
                raise ValueError('请求大小必须在 65 MiB 内')
            body = json.loads(self.rfile.read(length), object_pairs_hook=core.compiler.unique,
                              parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Nonfinite JSON')))
            path = urlparse(self.path).path
            if path == '/api/preview-reuse':
                job_id=body.get('job');reuse_id=body.get('preview');item=PREVIEWS.get(reuse_id)
                if job_id not in JOBS or not item or item['job']!=job_id or item['status']!='done':
                    raise ValueError('照片预览来源无效')
                source=RUNS/job_id/'photo_previews'/reuse_id
                if not (source/'render_inputs.npz').is_file():raise ValueError('历史预览没有缓存，请重新上传照片')
                from photo_preview import CALIBRATED_LONG_EDGE, PREVIEW_LONG_EDGE, RAW_CALIBRATION

                result = item['result']
                calibration = result.get('raw_calibration')
                requested = body.get('raw_calibrated', bool(calibration))
                if type(requested) is not bool or requested != bool(calibration) or (calibration and calibration != RAW_CALIBRATION):
                    raise ValueError('RAW 校准模式与照片缓存不一致，请重新上传照片')
                if result.get('preview_long_edge') != (CALIBRATED_LONG_EDGE if calibration else PREVIEW_LONG_EDGE):
                    raise ValueError('历史预览为低分辨率，请重新上传照片')
                if type(body.get('grid_effect',True)) is not bool:raise ValueError('网格效果开关必须为布尔值')
                grid_key=body.get('grid') or None
                native_variant=None
                if grid_key:
                    from grid_distillation import load_result
                    report,_,_=load_result(RUNS/job_id,grid_key)
                    native_variant=report['identity'].get('selected_bin_sha256')
                if native_variant != item['result'].get('native_variant'):
                    raise ValueError('所选配方的原生参数与缓存不同，请重新上传同一张照片')
                with LOCK:
                    if any(p['status'] in ('queued','running') for p in PREVIEWS.values()):raise ValueError('已有照片预览运行，请稍候')
                    identifier=uuid.uuid4().hex
                    destination=RUNS/job_id/'photo_previews'/identifier
                    destination.mkdir(parents=True)
                    PREVIEWS[identifier]=dict(id=identifier,job=job_id,status='queued',phase='复用同一照片采样切换算法')
                    (destination/'preview.json').write_bytes(dump(PREVIEWS[identifier]))
                    PREVIEW_POOL.submit(preview_work,identifier,job_id,destination,body.get('pc',False),grid_key,reuse_id,body.get('grid_effect',True))
                return self.respond(dict(id=identifier),status=202)
            if path == '/api/grid-training':
                identifier=body.get('job')
                if identifier not in JOBS or JOBS[identifier]['status']!='done':raise ValueError('请先选择完成的PC补偿任务，或导入LUT开始新的压缩训练')
                from residual_grid import response_matrix
                from pc_compensation import load
                value,_=load(RUNS/identifier)
                if value.get('curves',{}).get('mode','tone-tint')!='tone-tint':raise ValueError('压缩训练需要明暗＋灰阶染色方案')
                response=response_json(body.get('response',default_response()))
                gray_refinement=False
                with LOCK:
                    state_path=RUNS/identifier/'grid_training.json'
                    if state_path.exists() and json.loads(state_path.read_text()).get('status') in ('running','queued'):raise ValueError('该任务压缩训练仍在运行')
                    state_path.write_bytes(dump(dict(status='queued',phase='等待压缩训练',started=time.time())))
                    POOL.submit(compression_work,identifier,response,gray_refinement)
                return self.respond(dict(job=identifier,status='queued'),status=202)
            if path == '/api/grid-distillation':
                identifier=body.get('job')
                if identifier not in JOBS or JOBS[identifier]['status']!='done':
                    raise ValueError('请先载入已完成的 PC 补偿任务')
                if not RAW_LOCK.acquire(blocking=False):
                    raise ValueError('已有文件处理任务，请稍候')
                try:
                    from grid_distillation import generate
                    return self.respond(generate(RUNS/identifier,body.get('response',default_response()),post_gray_refinement=body.get('post_gray_refinement',False)))
                finally:
                    RAW_LOCK.release()
            if path == '/api/pc-compensation':
                identifier=body.get('job')
                if identifier not in JOBS or JOBS[identifier]['status']!='done':
                    raise ValueError('请先载入已完成任务')
                if not RAW_LOCK.acquire(blocking=False):
                    raise ValueError('已有文件处理任务，请稍候')
                try:
                    from pc_compensation import generate
                    value=generate(RUNS/identifier)
                    for cache_key in list(DIAGNOSTICS):
                        if cache_key[0]==identifier:DIAGNOSTICS.pop(cache_key,None)
                    return self.respond(value)
                finally:
                    RAW_LOCK.release()
            if path == '/api/export':
                config, receipts = export_policy423.validate(body, RUNS)
                payload,compiler_path,firmware,version = core.compile_config(config)
                memory = io.BytesIO()
                with zipfile.ZipFile(memory, 'w', zipfile.ZIP_DEFLATED) as archive:
                    archive.writestr('native_config.json', dump(body))
                    archive.writestr('R5NATIVE.BIN', payload)
                    archive.writestr('export_audit.json', dump(dict(schema='r5-web-export/1',
                        binary_sha256=core.sha(payload), bytes=len(payload), native_numbers=[e['number'] for e in body['entries']],
                        white_balance_in_binary=False, color_accuracy_accepted=False, firmware=firmware,format_version=version,
                        grid_required=True, config_numbers_are_independent=True, grid_sources=receipts,
                        SD_import_policy='replace-entire-set; missing selected configuration turns custom filter off',
                        compiler_sha256=core.sha(compiler_path.read_bytes()))))
                return self.respond(memory.getvalue(), 'application/zip', filename='r5-native-config.zip')
            if path == '/api/filter-library/pack':
                fmt = (body.get('format') or 'bin').lower()
                items = body.get('items') or []
                if fmt == 'project':
                    with LOCK:
                        return self.respond(filter_library.import_bundle_to_project(items, RUNS))
                payload, config, audit = filter_library.pack_bundle(items)
                if fmt == 'zip':
                    memory = io.BytesIO()
                    with zipfile.ZipFile(memory, 'w', zipfile.ZIP_DEFLATED) as archive:
                        archive.writestr('native_config.json', dump(config))
                        archive.writestr('R5NATIVE.BIN', payload)
                        archive.writestr('export_audit.json', dump(audit))
                    return self.respond(memory.getvalue(), 'application/zip', filename='r5-native-config.zip')
                return self.respond(payload, 'application/octet-stream', filename='R5NATIVE.BIN')
            if path == '/api/validate':
                value=export_policy423.configuration(body)
                if 'export_sources' in body:
                    value,_=export_policy423.validate(body,RUNS)
                data,_,_,_ = core.compile_config(value)
                return self.respond(dict(valid=True, bytes=len(data), sha256=core.sha(data)))
            if path == '/api/compare-slot':
                with RAW_LOCK:
                    result = core.compare_slot(body['saved'], body['draft'], body['endpoint'])
                return self.respond(result)
            if path == '/api/batches':
                return self.respond(batch_training.submit(body, sys.modules[__name__]), status=202)
            if path == '/api/batches/retry':
                return self.respond(batch_training.retry(body['id'], sys.modules[__name__]), status=202)
            if path == '/api/fit':
                return self.respond(queue_fit(body), status=202)
            if path == '/api/fit/retry':
                identifier = projects.identifier(body['id'])
                if identifier not in JOBS or JOBS[identifier]['status'] not in ('done','error'):
                    raise ValueError('请先选定已结束的任务')
                return self.respond(queue_fit(fit_request(identifier), retry=True), status=202)
            if path == '/api/cancel':
                job = JOBS.get(body.get('id'))
                if not job or job['status'] != 'running':
                    raise ValueError('任务未在运行')
                parent = JOBS.get(job.get('base_job'), {})
                if job.get('training_profile')=='native-joint/1':
                    from native_joint_workbench import request_cancel
                    request_cancel(job,parent)
                    return self.respond(dict(ok=True))
                process = job.get('process') or parent.get('process')
                if process is None:
                    raise ValueError('正在验证或转换，请稍候')
                process.terminate()
                job['phase'] = '正在取消，保留已有日志'
                return self.respond(dict(ok=True))
            self.respond(dict(error='Not found'), status=404)
        except projects.Conflict as error:
            self.respond(dict(error=str(error)), status=409)
        except Exception as error:
            self.respond(dict(error=str(error)), status=400)


def main():
    os.environ.setdefault('R5_GPU_TRAINING','1')
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=4180)
    parser.add_argument('--no-open', action='store_true')
    args = parser.parse_args()
    # Fail before opening the UI if local source files cannot be verified.
    core.presets()
    if RUNS.exists():
        for path in sorted(RUNS.glob('*/job.json')):
            if len(path.parent.name) != 32 or any(c not in '0123456789abcdef' for c in path.parent.name):
                continue
            try:
                job = json.loads(path.read_text())
                if job['id'] != path.parent.name:
                    continue
                if job['status']=='done':
                    native=json.loads((path.parent/'native_config.json').read_text())
                    core.compiler.pack(native)
                if job['status'] in ('running','queued'):
                    job.update(status='error',phase='服务重启中断',error='可使用原目标和设置重试',finished=time.time())
                JOBS[job['id']] = job
            except (ValueError, KeyError, OSError):
                continue
        for path in RUNS.glob('*/grid_training.json'):
            try:
                state=json.loads(path.read_text())
                if state['status'] in ('running','queued'):
                    state.update(status='error',phase='压缩训练被服务重启中断',error='请重新开始压缩训练')
                    path.write_bytes(dump(state))
            except (ValueError,KeyError,OSError):pass
        for path in RUNS.glob('*/photo_previews/*/preview.json'):
            try:
                item = json.loads(path.read_text())
                if item['id'] == path.parent.name and item['job'] == path.parents[2].name:
                    if item['status'] in ('queued','running'):
                        item.update(status='error',phase='预览被服务重启中断',error='请重新生成预览')
                        path.write_bytes(dump(item))
                    PREVIEWS[item['id']] = item
            except (ValueError, KeyError, OSError):
                continue
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    url = 'http://127.0.0.1:%d' % server.server_address[1]
    print('R5 色彩工作台：' + url, flush=True)
    if not args.no_open:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        for job in JOBS.values():
            if job.get('process'):
                job['process'].terminate()
        server.server_close()
        POOL.shutdown(wait=True)
        PREVIEW_POOL.shutdown(wait=True)


if __name__ == '__main__':
    main()
