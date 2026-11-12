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


def compress(base, weights, teacher, response, probe_side=33, sweeps=1, progress=None, parameter_smoothing=0, continuity=None, target_neighborhood=None, training_penalties=True):
    """Only training inputs and synthetic teacher queries enter the solve."""
    if type(training_penalties) is not bool:
        raise ValueError('training_penalties must be a boolean')
    if not training_penalties:
        parameter_smoothing, continuity, target_neighborhood = 0, None, None
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
    strengths = (0.,) if not training_penalties or target_neighborhood is not None else np.array((.0001, .001, .01))*multiplier(parameter_smoothing)
    for round_index,strength in enumerate(strengths,1):
        if progress:progress(stage='压缩网格求解',round=round_index,total_rounds=len(strengths),state='running',sweep=None,point=None)
        grid, audit = pc_stages.fit_response_grid(inputs, desired, mass, response, strength=strength)
        grid, refinement = refine_grid(grid, inputs, desired, np.ones(len(inputs)), mass,
                                       sweeps=sweeps, perceptual_weight=.35, response=response,
                                       progress=(lambda **v:progress(stage='压缩网格量化微调',**v)) if progress else None,parameter_smoothing=parameter_smoothing)
        continuity_audit=None
        if continuity is not None or target_neighborhood is not None:
            from continuity_grid import constrain
            grid,continuity_audit=constrain(grid,inputs,desired,mass,response,parameter_smoothing,continuity,progress,target_neighborhood=target_neighborhood)
        predicted = evaluate(inputs, grid, response)
        score = float(display_cost_rows(predicted, desired, .35)@mass)+grid_cost(grid,parameter_smoothing,response=response)
        if continuity is not None:
            from continuity_grid import penalty
            score+=penalty(grid,response,continuity)
        if target_neighborhood is not None:
            from continuity_grid import neighborhood_penalty
            score+=neighborhood_penalty(grid,response,target_neighborhood)
        candidates.append((score, grid, dict(smoothness=strength, score=score,
                                            solver=audit, quantization_refinement=refinement,output_continuity=continuity_audit)))
    best = min(candidates, key=lambda item: item[0])
    grid = unpack(pack(best[1]))  # Report the bytes users actually download.
    return grid, dict(probe_side=probe_side, synthetic_probes=len(probes), training_inputs=len(base),
                     train_probe_mass=[.5,.5], selected_smoothness=best[2]['smoothness'],
                     candidates=[item[2] for item in candidates], training_only=True,parameter_smoothing=parameter_smoothing,
                     training_shape_penalties=bool(training_penalties),
                     teacher='frozen complete PC transform; curves + tint + gated color grid + final clipping',
                     runtime=('source + F(q + trilinear(q, grid)*scale) - F(q); clip' if isinstance(response,dict) else 'legacy input + trilinear(input coordinates, packed grid)/256 @ response; clip'),
                     limit_fraction=float(np.mean((grid==-64)|(grid==63))))


def fit_target(base, target, weights, response, progress=None, parameter_smoothing=0,
               continuity=None, target_neighborhood=None, hue_direction=None,
               training_penalties=True, polish_rounds=0):
    """Fit the exported single grid to actual targets, using training rows only.

    No PC teacher or synthetic teacher targets contribute to this objective.
    Candidate selection uses the same training loss and smoothness policy as
    historical compression; holdout metrics are computed only afterwards.
    """
    if type(training_penalties) is not bool:
        raise ValueError('training_penalties must be a boolean')
    if not training_penalties:
        parameter_smoothing, continuity, target_neighborhood, hue_direction = 0, None, None, None
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
    strengths = (0.,) if not training_penalties or target_neighborhood is not None or hue_direction is not None else np.array((.0001, .001, .01))*multiplier(parameter_smoothing)
    for index, strength in enumerate(strengths, 1):
        if progress: progress(stage='富士目标直接拟合网格', round=index, total_rounds=len(strengths), state='running', sweep=None, point=None)
        grid, solver = pc_stages.fit_response_grid(base, target, mass, response, strength=strength)
        grid, refinement = refine_grid(grid, base, target, np.ones(len(base)), mass,
            sweeps=1, perceptual_weight=.35, response=response,
            progress=(lambda **v: progress(stage='目标网格整数量化微调', **v)) if progress else None,
            parameter_smoothing=parameter_smoothing)
        continuity_audit=None
        if continuity is not None or target_neighborhood is not None or hue_direction is not None:
            from continuity_grid import constrain
            grid,continuity_audit=constrain(grid,base,target,weights,response,parameter_smoothing,
                continuity,progress,target_neighborhood=target_neighborhood,hue_direction=hue_direction)
        # Score exactly the signed-7-bit coefficients that will be exported.
        grid = unpack(pack(grid))
        prediction = evaluate(base, grid, response)
        score = float(display_cost_rows(prediction, target, .35)@mass)+grid_cost(grid, parameter_smoothing,response=response)
        if continuity is not None:
            from continuity_grid import penalty
            score+=penalty(grid,response,continuity)
        if target_neighborhood is not None:
            from continuity_grid import neighborhood_penalty
            score+=neighborhood_penalty(grid,response,target_neighborhood)
        if hue_direction is not None:
            from continuity_grid import hue_direction_penalty
            score+=hue_direction_penalty(grid,response,hue_direction)
        candidates.append((score, grid, dict(smoothness=float(strength), score=score,
            solver=solver, quantization_refinement=refinement,output_continuity=continuity_audit)))
    best = min(candidates, key=lambda value: value[0])
    grid = best[1]
    return grid, dict(objective='fuji-target', training_inputs=len(base), synthetic_probes=0,
        train_probe_mass=[1.0, 0.0], selected_smoothness=best[2]['smoothness'],
        candidates=[value[2] for value in candidates], training_only=True,
        parameter_smoothing=parameter_smoothing, teacher=None, training_shape_penalties=bool(training_penalties),
        selection=('training RGB/perceptual data loss only; no shape penalty or holdout fitting' if not training_penalties else
                   'training target loss plus target-neighborhood antiringing; no validation or test fitting'
                   if target_neighborhood is not None else 'training target loss plus actual-response path slope/curvature; no validation or test fitting'),
        limit_fraction=float(np.mean((grid == -64) | (grid == 63))))


def generate(job, response, progress=None, post_gray_refinement=False, objective='pc-teacher', fitted_target=None):
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
    from edit_native_recipe import read
    from fit_anchor_native import training_plan
    recipe, model = __import__('baseline').read_job(job)
    neighbor_bank=None;target_neighborhood=None;hue_bank=None;hue_direction=None
    fitting_options=recipe.get('fitting',{}).get('search_options',{})
    postfit=bool(fitting_options.get('postfit_deburr',False))
    with np.load(job/'pairs.npz', allow_pickle=False) as p:
        split, ids = p['split'], p['anchor_index']
        target = p['0_target']/16383
        base = white_balance.render_pairs(model,p,recipe)/16383
        random_selection=np.flatnonzero((split=='train')&(ids<0)&(p['sector16_index']<0)) if 'design_srgb' in p else None
        train, _, _, weights = training_plan(split, ids, recipe.get('fitting',{}).get('group_total_weights'),p['sector16_index'] if 'sector16_index' in p else None,p['baseline_tonal_index'] if recipe.get('fitting',{}).get('tonal_balance') else None,random_selection,p.get('sample_kind'),recipe.get('fitting',{}).get('search_options',{}))
        if postfit:
            if 'design_srgb' not in p or 'sample_kind' not in p:
                raise ValueError('拟合后去毛刺需要包含24色相轨道的生成色卡')
            postfit_design=np.array(p['design_srgb'],copy=True)
            postfit_kind=np.array(p['sample_kind'],copy=True)
        neighbor_amount=0 if postfit else fitting_options.get('target_neighborhood',0)
        if neighbor_amount:
            if 'design_srgb' not in p:raise ValueError('Target-neighborhood fitting requires generated chart design_srgb')
            from target_neighborhood import TargetNeighborhoodBank
            neighbor_bank=TargetNeighborhoodBank(p['design_srgb'],target,split)
            if neighbor_bank.metadata['enabled']:
                target_neighborhood=(neighbor_bank,base[neighbor_bank.source_indices],neighbor_amount)
        hue_amount=fitting_options.get('hue_direction_strength',0)
        if hue_amount:
            from hue_direction import HueDirectionBank
            hue_bank=HueDirectionBank(p['design_srgb'],target,split,p['sample_kind'])
            hue_direction=(hue_bank,base[hue_bank.source_indices],hue_amount)
    smoothing = 0 if postfit else fitting_options.get('parameter_smoothing',0)
    amount = 0 if postfit else fitting_options.get('output_continuity',0)
    fit_policy={'training_penalties':False} if postfit else {}
    continuity=None
    if amount:
        from output_continuity import ProbeBank
        from patch_sampling import center_mean
        from compute_backend import render_native
        bank=ProbeBank()
        # Fitting changes CC1/block13/Gamma only; RAW/ITP/SSCS stay source-bound.
        front=bank.inputs(model,white_balance.from_recipe(recipe))
        continuity=(bank,center_mean(render_native(model,front))/16383,amount)
    if fitted_target is not None:
        if objective != 'fuji-target' or fitted_target[1].get('training_only') is not True:
            raise ValueError('Prefitted grid requires training-only direct-target provenance')
        if continuity is not None and not fitted_target[1].get('output_continuity'):
            raise ValueError('Prefitted grid is missing the requested output continuity constraint')
        if target_neighborhood is not None and not fitted_target[1].get('target_neighborhood'):
            raise ValueError('Prefitted grid is missing the requested target-neighborhood constraint')
        if postfit and fitted_target[1].get('training_shape_penalties') is not False:
            raise ValueError('拟合后去毛刺模式需要无形状惩罚的拟合来源')
        grid, audit = unpack(pack(fitted_target[0])), copy.deepcopy(fitted_target[1])
    elif objective == 'fuji-target':
        grid, audit = fit_target(base[train], target[train], weights, response,
            progress=progress, parameter_smoothing=smoothing,continuity=continuity,
            target_neighborhood=target_neighborhood,hue_direction=hue_direction,
            polish_rounds=fitting_options.get('target_polish_rounds',0),
            **({} if hue_direction is not None else fit_policy))
    else:
        grid, audit = compress(base[train], weights, teacher, response, progress=progress, parameter_smoothing=smoothing,continuity=continuity,target_neighborhood=target_neighborhood,**fit_policy)
        if target_neighborhood is not None or postfit:
            # Explicitly opt-in two-stage profile: the compressed teacher is
            # the starting table; refine that same packed table against real
            # targets. Post-fit repair mode retains this stage with data
            # fidelity and hard coefficient limits, before the FC repair.
            from continuity_grid import constrain
            initial_payload=pack(grid)
            grid,second_stage=constrain(grid,base[train],target[train],weights,response,
                smoothing,continuity,progress,target_neighborhood=target_neighborhood,
                **({'training_penalties':False} if postfit else {}))
            grid=unpack(pack(grid))
            audit['constrained_target_refinement']=dict(second_stage,
                initial_payload_sha256=core.sha(initial_payload),final_payload_sha256=core.sha(pack(grid)),
                target='actual train target',teacher_stage_initialization=True,
                native_parameters_frozen=True,packed_integer_acceptance=True)
    if postfit:
        from postfit_deburr import deburr
        postfit_before_payload=pack(grid)
        mass=np.ones(len(base),dtype=float)
        mass[train]=weights
        grid,postfit_audit=deburr(grid,base,target,response,
            design_srgb=postfit_design,split=split,sample_kind=postfit_kind,
            anchor_index=ids,weights=mass,progress=progress)
        if postfit_audit.get('original_payload_sha256') != core.sha(postfit_before_payload):
            raise ValueError('拟合后去毛刺原表身份不一致')
        grid=unpack(pack(grid))
        audit['postfit_deburr']=postfit_audit
        audit['limit_fraction']=float(np.mean((grid==-64)|(grid==63)))
    if neighbor_bank is not None:
        neighbor_base=base[neighbor_bank.source_indices]
        audit['target_neighborhood']=dict(native=neighbor_bank.report(neighbor_base,neighbor_amount),
            final_grid=neighbor_bank.report(evaluate(neighbor_base,grid,response),neighbor_amount),
            source='complete real train target; no synthetic target interpolation')
    if hue_bank is not None:
        hue_base=base[hue_bank.source_indices]
        audit['hue_direction']=dict(native=hue_bank.report(hue_base,hue_amount),
            final_grid=hue_bank.report(evaluate(hue_base,grid,response),hue_amount),
            source='24 complete real TRAIN hue-tonal rays; target-relative adjacent direction')
    if continuity is not None:
        bank,probe_base,amount=continuity
        audit['output_continuity']=dict(native=bank.report(probe_base,amount),
            final_grid=bank.report(evaluate(probe_base,grid,response),amount))
    audit['post_gray_refinement']=dict(enabled=False)
    if progress:progress(stage='压缩效果验证',round=3,total_rounds=3,state='round_done',sweep=None,point=None)
    combined = teacher(base)
    student = evaluate(base, grid, response)
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
    if postfit:
        identity['postfit_deburr_implementation_sha256']=core.sha(Path(__file__).with_name('postfit_deburr.py').read_bytes())
        identity['shape_preserving_implementation_sha256']=core.sha(Path(__file__).with_name('shape_preserving.py').read_bytes())
        identity['postfit_before_payload_sha256']=core.sha(postfit_before_payload)
    if neighbor_bank is not None:
        identity['target_neighborhood_implementation_sha256']=core.sha(Path(__file__).with_name('target_neighborhood.py').read_bytes())
    if hue_bank is not None:
        identity['hue_direction_implementation_sha256']=core.sha(Path(__file__).with_name('hue_direction.py').read_bytes())
    if objective != 'pc-teacher': identity['objective'] = objective
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
    destination = job/'grid_distillation'/key
    destination.mkdir(parents=True, exist_ok=True)
    (destination/'teacher.json').write_bytes(source)
    (destination/'result.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
    (destination/'grid.payload').write_bytes(pack(grid))
    if postfit:
        (destination/'postfit-before.payload').write_bytes(postfit_before_payload)
    return dict(key=key, **report)

