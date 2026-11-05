"""Distill the complete frozen PC transform into one native-sized grid.

The packed format is native-sized; pixel coordinates/response are provisional.
No camera or firmware output is generated here.
"""
import io
import copy
import json
from pathlib import Path
import zipfile
import core
import white_balance
import numpy as np
import pc_stages
from pc_compensation import load
from residual_grid import evaluate, pack, unpack, response_matrix, response_json

INTEGER_REFINEMENT_POLICY = 'guarded-integer-grid/2'


def compress(base, weights, teacher, response, probe_side=33, sweeps=1, progress=None, parameter_smoothing=0, continuity=None):
    """Only training inputs and synthetic teacher queries enter the solve."""
    base = np.asarray(base, dtype=float)
    weights = np.asarray(weights, dtype=float)
    response = response_matrix(response)
    if (base.ndim != 2 or base.shape[1] != 3 or len(base) < 2
            or weights.shape != (len(base),) or not np.isfinite(base).all()
            or not np.isfinite(weights).all() or np.any(weights <= 0)):
        raise ValueError('Expected finite training RGB and positive weights')
    axis = np.linspace(0, 1, probe_side)
    probes = np.stack(np.meshgrid(axis, axis, axis, indexing='ij'), axis=-1).reshape(-1, 3)
    if isinstance(response,dict):
        from measured_response import get
        probes=get(response).probes(probe_side**3)
    inputs = np.r_[base, probes]
    mass = np.r_[weights/weights.sum()*.5, np.full(len(probes), .5/len(probes))]
    desired = teacher(inputs)
    from optimizer_policy import display_cost_rows, refine_grid
    candidates = []
    from parameter_smoothing import multiplier, grid_cost
    for round_index,strength in enumerate(np.array((.0001, .001, .01))*multiplier(parameter_smoothing),1):
        if progress:progress(stage='压缩网格求解',round=round_index,total_rounds=3,state='running',sweep=None,point=None)
        grid, audit = pc_stages.fit_response_grid(inputs, desired, mass, response, strength=strength)
        grid, refinement = refine_grid(grid, inputs, desired, np.ones(len(inputs)), mass,
                                       sweeps=sweeps, perceptual_weight=.35, response=response,
                                       progress=(lambda **v:progress(stage='压缩网格量化微调',**v)) if progress else None,parameter_smoothing=parameter_smoothing)
        continuity_audit=None
        if continuity is not None:
            from continuity_grid import constrain
            grid,continuity_audit=constrain(grid,inputs,desired,mass,response,parameter_smoothing,continuity,progress)
        predicted = evaluate(inputs, grid, response)
        score = float(display_cost_rows(predicted, desired, .35)@mass)+grid_cost(grid,parameter_smoothing,response=response)
        if continuity is not None:
            from continuity_grid import penalty
            score+=penalty(grid,response,continuity)
        candidates.append((score, grid, dict(smoothness=strength, score=score,
                                            solver=audit, quantization_refinement=refinement,output_continuity=continuity_audit)))
    best = min(candidates, key=lambda item: item[0])
    grid = unpack(pack(best[1]))  # Report the bytes users actually download.
    return grid, dict(probe_side=probe_side, synthetic_probes=len(probes), training_inputs=len(base),
                     train_probe_mass=[.5,.5], selected_smoothness=best[2]['smoothness'],
                     candidates=[item[2] for item in candidates], training_only=True,parameter_smoothing=parameter_smoothing,
                     teacher='frozen complete PC transform; curves + tint + gated color grid + final clipping',
                     runtime=('source + F(q + trilinear(q, grid)*scale) - F(q); clip' if isinstance(response,dict) else 'legacy input + trilinear(input coordinates, packed grid)/256 @ response; clip'),
                     limit_fraction=float(np.mean((grid==-64)|(grid==63))))


def fit_target(base, target, weights, response, progress=None, parameter_smoothing=0, continuity=None):
    """Fit the exported single grid to actual targets, using training rows only.

    No PC teacher or synthetic teacher targets contribute to this objective.
    Candidate selection uses the same training loss and smoothness policy as
    historical compression; holdout metrics are computed only afterwards.
    """
    from optimizer_policy import display_cost_rows, refine_grid
    from parameter_smoothing import multiplier, grid_cost
    base, target, weights = [np.asarray(v, dtype=float) for v in (base, target, weights)]
    if (base.ndim != 2 or base.shape[1] != 3 or target.shape != base.shape
            or len(base) < 2 or weights.shape != (len(base),)
            or not all(np.isfinite(v).all() for v in (base, target, weights))
            or np.any(weights <= 0)):
        raise ValueError('Expected matching finite training RGB targets and positive weights')
    response = response_matrix(response)
    mass = weights / weights.sum()
    candidates = []
    for index, strength in enumerate(np.array((.0001, .001, .01))*multiplier(parameter_smoothing), 1):
        if progress:
            progress(stage='富士目标直接拟合网格', round=index, total_rounds=3, state='running', sweep=None, point=None)
            def loss_progress(solver, evaluations, current, best):
                progress(evaluations=evaluations, loss_sample=(solver, evaluations, current, best))
            solver_options = dict(loss_progress=loss_progress)
        else:
            solver_options = {}
        grid, solver = pc_stages.fit_response_grid(base, target, mass, response, strength=strength, **solver_options)
        grid, refinement = refine_grid(grid, base, target, np.ones(len(base)), mass,
            sweeps=1, perceptual_weight=.35, response=response,
            progress=(lambda **v: progress(stage='目标网格整数量化微调', **v)) if progress else None,
            parameter_smoothing=parameter_smoothing)
        continuity_audit=None
        if continuity is not None:
            from continuity_grid import constrain
            grid,continuity_audit=constrain(grid,base,target,weights,response,parameter_smoothing,continuity,progress)
        # Score exactly the signed-7-bit coefficients that will be exported.
        grid = unpack(pack(grid))
        prediction = evaluate(base, grid, response)
        score = float(display_cost_rows(prediction, target, .35)@mass)+grid_cost(grid, parameter_smoothing,response=response)
        if continuity is not None:
            from continuity_grid import penalty
            score+=penalty(grid,response,continuity)
        candidates.append((score, grid, dict(smoothness=float(strength), score=score,
            solver=solver, quantization_refinement=refinement,output_continuity=continuity_audit)))
    best = min(candidates, key=lambda value: value[0])
    grid = best[1]
    return grid, dict(objective='fuji-target', training_inputs=len(base), synthetic_probes=0,
        train_probe_mass=[1.0, 0.0], selected_smoothness=best[2]['smoothness'],
        candidates=[value[2] for value in candidates], training_only=True,
        parameter_smoothing=parameter_smoothing, teacher=None,
        selection='training target loss plus actual-response path slope/curvature; no validation or test fitting',
        limit_fraction=float(np.mean((grid == -64) | (grid == 63))))


def generate(job, response, progress=None, post_gray_refinement=False, objective='pc-teacher', fitted_target=None,
             *, guarded_selection=None, adaptive_color=False):
    # Removed from the training pipeline, including requests from older browser tabs.
    post_gray_refinement=False
    job = Path(job)
    if objective not in ('pc-teacher', 'fuji-target'):
        raise ValueError('Unknown grid training objective')
    source = (job/'pc_compensation.json').read_bytes()
    value, source_grid = load(job)
    if value['schema'] != 'r5-PC-compensation/2' or value['curves'].get('mode','tone-tint') != 'tone-tint':
        raise ValueError('请载入包含明暗曲线＋灰阶染色的 PC 补偿任务')
    response = response_matrix(response)
    teacher = lambda rgb: pc_stages.render(rgb, value['curves'], source_grid)
    from fit_anchor_native import training_plan
    import baseline
    recipe, model = baseline.read_job(job)
    with np.load(job/'pairs.npz', allow_pickle=False) as p:
        split, ids = p['split'], p['anchor_index']
        target = p['0_target']/16383
        base = white_balance.render_pairs(model,p,recipe)/16383
        random_selection=np.flatnonzero((split=='train')&(ids<0)&(p['sector16_index']<0)) if 'design_srgb' in p else None
        train, _, _, weights = training_plan(split, ids, recipe.get('fitting',{}).get('group_total_weights'),p['sector16_index'] if 'sector16_index' in p else None,p['baseline_tonal_index'] if recipe.get('fitting',{}).get('tonal_balance') else None,random_selection,p.get('sample_kind'),recipe.get('fitting',{}).get('search_options',{}))
    smoothing = recipe.get('fitting',{}).get('search_options',{}).get('parameter_smoothing',0)
    amount = recipe.get('fitting',{}).get('search_options',{}).get('output_continuity',0)
    continuity=None
    if amount:
        from output_continuity import ProbeBank
        from patch_sampling import center_mean
        from compute_backend import render_native
        bank=ProbeBank()
        # Fitting changes CC1/block13/Gamma only; RAW/ITP/SSCS stay source-bound.
        front=bank.inputs(model,white_balance.from_recipe(recipe))
        continuity=(bank,center_mean(render_native(model,front))/16383,amount)
    selected_identity = {}
    selected_config = None
    if guarded_selection is not None:
        from fit_bin_joint import grid_from
        from gpu_runtime import cpu_reference
        config, selection = guarded_selection
        selected_binary = core.compiler.pack(config)
        selected_config = core.compiler.unpack(selected_binary)
        entry, = selected_config['entries']
        grid = grid_from(entry)
        selected_identity = dict(selected_bin_sha256=core.sha(selected_binary),
            baseline_grid_key=selection['baseline_key'], candidate_grid_key=selection['source_key'],
            native_config_sha256=core.sha((job/'native_config.json').read_bytes()),
            grid_payload_sha256=core.sha(pack(grid)))
        audit = dict(objective=objective, guarded_adam=selection)
        with cpu_reference(), np.load(job/'pairs.npz', allow_pickle=False) as pairs:
            selected_model = model_for_config(job, selected_config)
            selected_base = white_balance.render_pairs(selected_model,pairs,recipe)/16383
            if continuity is not None:
                from compute_backend import render_native
                from patch_sampling import center_mean
                bank, _, amount = continuity
                continuity = (bank, center_mean(render_native(selected_model,bank.inputs(selected_model)))/16383, amount)
    elif fitted_target is not None:
        if objective != 'fuji-target' or fitted_target[1].get('training_only') is not True:
            raise ValueError('Prefitted grid requires training-only direct-target provenance')
        if continuity is not None and not fitted_target[1].get('output_continuity'):
            raise ValueError('Prefitted grid is missing the requested output continuity constraint')
        grid, audit = unpack(pack(fitted_target[0])), copy.deepcopy(fitted_target[1])
    elif objective == 'fuji-target':
        grid, audit = fit_target(base[train], target[train], weights, response,
            progress=progress, parameter_smoothing=smoothing,continuity=continuity)
    else:
        grid, audit = compress(base[train], weights, teacher, response, progress=progress, parameter_smoothing=smoothing,continuity=continuity)
    integer_identity = {}
    if objective == 'fuji-target' and selected_config is None:
        from measured_response import get
        from paired_response import PairedModel
        gray_mask = (ids >= 4) & (ids < 260) & (split == 'train')
        validation = split == 'valid'
        if not isinstance(response, dict) or not isinstance(get(response), PairedModel):
            audit['integer_refinement'] = dict(enabled=False, reason='unsupported-response')
        elif white_balance.active(white_balance.from_recipe(recipe)):
            audit['integer_refinement'] = dict(enabled=False, reason='experimental-white-balance')
        elif not validation.any():
            audit['integer_refinement'] = dict(enabled=False, reason='missing-validation-split')
        else:
            from compute_backend import render_native
            from edit_parameter_context import ParameterContext, RuntimeColor
            from gpu_runtime import available, cpu_reference
            from integer_grid import refine
            from output_continuity import ProbeBank
            from patch_sampling import center_mean

            native_path = job/'native_config.json'
            native_bytes = native_path.read_bytes()
            config = core.compiler.unpack(core.compiler.pack(json.loads(native_bytes)))
            entry, = config['entries']
            context = ParameterContext(RuntimeColor.from_capture(*baseline.for_job(job)))
            bin_model = context.build(**core.slot_native_parameters(context, entry))
            bank = continuity[0] if continuity is not None else ProbeBank()
            perceptual = recipe['fitting']['search_options'].get('perceptual_weight', .35)
            with cpu_reference(), np.load(job/'pairs.npz', allow_pickle=False) as pairs:
                bin_base = center_mean(render_native(bin_model, pairs['input']))/16383
                bin_probes = center_mean(render_native(bin_model, bank.inputs(bin_model)))/16383
                grid, audit['integer_refinement'] = refine(grid, bin_base, target, train, gray_mask,
                    validation, response, (bank, bin_probes, amount or 30), perceptual, progress,
                    strategy='extended')
            if adaptive_color:
                from adaptive_color import POLICY, refine as focus

                audit['adaptive_color'] = dict(policy=POLICY, accepted=False, reason='mps-unavailable')
                if available() and all(matrix == entry['block13'][0] for matrix in entry['block13'][1:]):
                    with np.load(job/'pairs.npz', allow_pickle=False) as pairs:
                        eligible = ids[train] < 0
                        if 'sector16_index' in pairs:
                            eligible &= pairs['sector16_index'][train] < 0
                        selected_config, grid, audit['adaptive_color'] = focus(config, grid, context,
                            pairs['input'], target, train, weights, eligible, gray_mask, validation,
                            response, bank, bin_probes, bin_base, amount or 30, perceptual, smoothing, progress)
                        if selected_config is not None:
                            chosen, = selected_config['entries']
                            selected_model = context.build(**core.slot_native_parameters(context, chosen))
                            with cpu_reference():
                                selected_base = center_mean(render_native(selected_model, pairs['input']))/16383
                                if continuity is not None:
                                    continuity = (bank, center_mean(render_native(
                                        selected_model, bank.inputs(selected_model)))/16383, amount)
                            selected_identity = dict(selected_bin_sha256=core.sha(core.compiler.pack(selected_config)),
                                                     native_config_sha256=core.sha(native_bytes))
                elif available():
                    audit['adaptive_color']['reason'] = 'independent-illuminant-matrices'
            integer_identity = dict(integer_refinement_policy=INTEGER_REFINEMENT_POLICY,
                integer_refinement_sha256=core.sha(Path(__file__).with_name('integer_grid.py').read_bytes()),
                native_config_sha256=core.sha(native_bytes), grid_payload_sha256=core.sha(pack(grid)))
    if continuity is not None:
        bank,probe_base,amount=continuity
        audit['output_continuity']=dict(native=bank.report(probe_base,amount),
            final_grid=bank.report(evaluate(probe_base,grid,response),amount))
    audit['post_gray_refinement']=dict(enabled=False)
    if progress:progress(stage='压缩效果验证',round=3,total_rounds=3,state='round_done',sweep=None,point=None)
    combined = teacher(base)
    student = evaluate(selected_base if selected_config is not None else base, grid, response)
    metrics = {}
    for name, mask in [('gray_training',(ids>=4)&(ids<260)&(split=='train')),
                       ('primaries_training',(ids>=0)&(ids<4)&(split=='train')),
                       ('colorchecker24_training',(ids>=260)&(ids<284)&(split=='train')),
                       ('validation',split=='valid'), ('test',split=='test')]:
        if not np.any(mask): continue
        metrics[name] = dict(samples=int(mask.sum()),
            combined_vs_lut=core.tonal_comparison(target[mask],combined[mask]),
            grid_vs_lut=core.tonal_comparison(target[mask],student[mask]),
            grid_vs_combined=core.tonal_comparison(combined[mask],student[mask]))
    probes = np.random.default_rng(20261021).random((4096,3))
    if isinstance(response,dict):
        from measured_response import get
        probes=get(response).probes(4096,seed=20261023)
    metrics['unseen_synthetic'] = dict(samples=len(probes),
        grid_vs_combined=core.tonal_comparison(teacher(probes),evaluate(probes,grid,response)))
    identity = dict(teacher_sha256=core.sha(source), recipe_sha256=value['recipe_sha256'],
                    target_source=core.target_identity(job), pairs_sha256=value['pairs_sha256'],
                    implementation_sha256=core.sha(Path(__file__).read_bytes()), response=response_json(response),
                    response_implementation_sha256=core.sha(Path(__file__).with_name('measured_response.py').read_bytes()) if isinstance(response,dict) else None)
    if isinstance(response,dict):
        from measured_response import runtime_fingerprint
        identity['response_runtime_sha256']=runtime_fingerprint(identity['response'])
    identity['post_gray_refinement']=post_gray_refinement
    if objective != 'pc-teacher': identity['objective'] = objective
    if 'adaptive_color' in audit:
        identity['adaptive_color_policy'] = audit['adaptive_color']['policy']
        identity['adaptive_color_sha256'] = core.sha(Path(__file__).with_name('adaptive_color.py').read_bytes())
        if audit['adaptive_color'].get('constrained'):
            identity['adaptive_gpu_sha256'] = core.sha(Path(__file__).with_name('adaptive_gpu.py').read_bytes())
    identity.update(integer_identity)
    identity.update(selected_identity)
    key = core.sha(json.dumps(identity, sort_keys=True).encode())
    report = dict(schema='r5-native-sized-grid-distillation/1', camera_apply_allowed=False,
                  coordinate_model=('measured-inverse-bspline-forward-TPS' if isinstance(response,dict) else 'provisional-bt601-limited'), stage='after-color-subchain-PC-only',
                  white_balance=recipe.get('white_balance'),grid_shape=[5,9,9], coefficient_range=[-64,63], payload_bytes=1215,
                  payload_hex=pack(grid).hex(), identity=identity, fitting=audit, metrics=metrics,
                  samples=dict(gray_combined=combined[(ids>=4)&(ids<260)&(split=='train')].tolist(),
                               gray_grid=student[(ids>=4)&(ids<260)&(split=='train')].tolist()),
                  limits=[('Author A7C2 measured proxy applied to R5; R5 response and physical colors not calibrated.' if isinstance(response,dict) else 'Legacy provisional R5 coordinates/response; uncalibrated.'),
                          'This approximates the entire frozen PC effect in one grid; errors and bound clipping remain.',
                          'No separate tone/tint curves or gray gate at runtime.',
                          'Not a R5NATIVE.BIN; no firmware or camera changes.'])
    if source != (job/'pc_compensation.json').read_bytes():
        raise ValueError('压缩期间 PC 参数发生变化，请重试')
    if integer_identity and native_bytes != native_path.read_bytes():
        raise ValueError('压缩期间原生配置发生变化，请重试')
    if selected_config is not None:
        if selected_identity['native_config_sha256'] != core.sha((job/'native_config.json').read_bytes()):
            raise ValueError('候选发布期间基准配置发生变化，请重试')
        report['selected_config'] = selected_config
    destination = job/'grid_distillation'/key
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'teacher.json').write_bytes(source)
    (destination/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    (destination/'grid.payload').write_bytes(pack(grid))
    return dict(key=key, **report)


def download(job, key):
    if not isinstance(key,str) or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):
        raise ValueError('Invalid compression identity')
    folder = Path(job)/'grid_distillation'/key
    memory = io.BytesIO()
    with zipfile.ZipFile(memory,'w',zipfile.ZIP_DEFLATED) as archive:
        for name in ['result.json','teacher.json','grid.payload']:
            archive.write(folder/name,name)
        archive.writestr('说明.txt','单一5×9×9网格，共405×3个7位系数，1215字节平面排列。\n'
            '实测模型或旧暂定模型身份、来源及适用范围见result.json；模型不写入BIN。\n'
            '运行时不叠加原明暗曲线、染色曲线和灰阶门控。误差见result.json。\n')
    return memory.getvalue()


def load_result(job, key):
    if not isinstance(key,str) or len(key)!=64 or any(c not in '0123456789abcdef' for c in key):
        raise ValueError('Invalid compression identity')
    job=Path(job)
    path=job/'grid_distillation'/key/'result.json'
    value=json.loads(path.read_text())
    identity=value['identity']
    if not core.target_matches(identity,job):
        raise ValueError('压缩目标来源不一致，请重新训练')
    for field,name in [('teacher_sha256','pc_compensation.json'),('recipe_sha256','fit/recipe.json'),
                       ('pairs_sha256','pairs.npz')]:
        if identity[field]!=core.sha((job/name).read_bytes()):
            raise ValueError('压缩参数与当前任务来源不一致，请重新压缩训练')
    if core.sha(json.dumps(identity,sort_keys=True).encode())!=key or value['camera_apply_allowed'] is not False:
        raise ValueError('Compression identity mismatch')
    if isinstance(identity['response'],dict):
        from measured_response import verify_saved_runtime
        verify_saved_runtime(identity)
    payload = bytes.fromhex(value['payload_hex'])
    if 'native_config_sha256' in identity and identity['native_config_sha256'] != core.sha((job/'native_config.json').read_bytes()):
        raise ValueError('纯整数网格的原生配置发生变化，请重新训练')
    if 'grid_payload_sha256' in identity and identity['grid_payload_sha256'] != core.sha(payload):
        raise ValueError('纯整数网格的系数摘要不符，请重新训练')
    grid=unpack(payload)
    if 'selected_bin_sha256' in identity:
        from fit_bin_joint import grid_from
        config = value['selected_config']
        entry, = config['entries']
        if (core.sha(core.compiler.pack(config)) != identity['selected_bin_sha256']
                or not np.array_equal(grid_from(entry), grid)):
            raise ValueError('通过验收的原生参数与网格不匹配，请重新训练')
    response_matrix(identity['response'])
    return value,grid,core.sha(path.read_bytes())


def model_for_config(job, config):
    import baseline
    from edit_parameter_context import ParameterContext, RuntimeColor
    entry, = config['entries']
    context = ParameterContext(RuntimeColor.from_capture(*baseline.for_job(job)))
    return context.build(**core.slot_native_parameters(context, entry))


def firmware_config(job, key, configuration_only=False):
    """Export the selected frozen grid with its own native look parameters."""
    import copy
    job = Path(job)
    report, grid, report_sha = load_result(job, key)
    native_bytes = (job/'native_config.json').read_bytes()
    native_sha = report['identity'].get('native_config_sha256')
    if native_sha is not None and native_sha != core.sha(native_bytes):
        raise ValueError('纯整数网格的原生配置发生变化，请重新训练')
    config = report.get('selected_config') if 'selected_bin_sha256' in report['identity'] else json.loads(native_bytes)
    core.compiler.pack(config)
    if len(config['entries']) != 1:
        raise ValueError('压缩网格只能绑定本任务的一项原生拟合参数')
    config['entries'][0]['grid_5x9x9'] = dict(
        coefficients=grid.T.reshape(3,5,9,9).astype(int).tolist())
    payload, _, firmware, version = core.compile_config(config)
    if configuration_only:
        return config
    audit = dict(schema=f'r5-custom-filter-grid-export/{version}', firmware_required=firmware,
                 format_version=version,
                 SD_import_policy='replace-entire-set; missing selected configuration turns custom filter off',
        grid_required=True, config_numbers_are_independent=True,
        compatible_with_stock_418=False, camera_tested=False, grid_key=key,
        compression_report_sha256=report_sha, binary_sha256=core.sha(payload),
        pc_response=report['identity']['response'],
        response_is_PC_surrogate_only=True, response_in_binary=False,
        white_balance=report.get('white_balance'),white_balance_in_binary=False,
        limits=['实验白平衡未压入网格，BIN不含白平衡；非零偏移PC图不等于该BIN输出。','仅写入1215字节网格系数；不加入PC response、明暗或染色曲线。',
                '沿用开机导入和持久保存；不支持拍摄中热更新。',
                '原厂网格坐标/响应及自定义实际成像未验收，PC压缩图不保证等于机内效果。'])
    memory = io.BytesIO()
    with zipfile.ZipFile(memory,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('R5NATIVE.BIN',payload)
        project=copy.deepcopy(config)
        project['export_sources']={str(config['entries'][0]['number']):dict(kind='compressed',job=job.name,key=key)}
        archive.writestr('native_config.json',json.dumps(project,indent=2,ensure_ascii=False)+'\n')
        archive.writestr('export_audit.json',json.dumps(audit,indent=2,ensure_ascii=False)+'\n')
    return memory.getvalue()


def latest(job):
    job=Path(job)
    for path in sorted((job/'grid_distillation').glob('*/result.json'),key=lambda p:p.stat().st_mtime,reverse=True):
        try:
            load_result(job,path.parent.name)
            return path.parent.name
        except (ValueError,KeyError,OSError):
            continue
    return None


def apply(job, rgb, key):
    value,grid,_=load_result(job,key)
    a=np.asarray(rgb,dtype=float)
    return evaluate(a.reshape(-1,3),grid,value['identity']['response']).reshape(a.shape)
