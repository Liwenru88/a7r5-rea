"""Apply the 4187 packed-grid continuation to one completed batch job.

The native fit and first fuji-target grid fit are completed by ``server.work``.
This module then runs rounds 1..5 from the first pre-FC packed table, selects
the validation winner, and performs the existing FC/deburr gate once.  Test
rows are never read.  The original result remains in the job directory and a
new immutable result identity is published when the continuation succeeds.
"""
from pathlib import Path
import copy, hashlib, json, time


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def save(path, value, server):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + '.pending')
    tmp.write_bytes(server.dump(value))
    tmp.replace(path)


def first_round_source(parent,folder):
    """Resolve a verified pre-FC payload from both target-fit report formats.

    Current direct fuji-target fits store their audit at the fitting root;
    older compress-then-polish fits used constrained_target_refinement.
    Both must bind exactly the already saved pre-FC payload.
    """
    path=Path(folder)/'postfit-before.payload'
    if not path.is_file() or path.stat().st_size!=1215:
        raise ValueError('4187 requires the first pre-FC target-refinement payload')
    fitting=parent.get('fitting',{})
    audit=fitting.get('constrained_target_refinement')
    expected=parent.get('identity',{}).get('postfit_before_payload_sha256')
    if not isinstance(audit,dict):
        if parent.get('identity',{}).get('objective')!='fuji-target' or fitting.get('training_only') is not True:
            raise ValueError('4187 requires a training-only direct-target fit')
        audit=copy.deepcopy(fitting)
        audit.update(first_round_source='direct-fuji-target-pre-FC',final_payload_sha256=expected,
            initial_payload_sha256=None,teacher_stage_initialization=False,
            initial_payload_provenance='not recorded by the direct-target fitter; pre-FC output is SHA-bound')
    actual=sha(path)
    if not expected or actual!=expected or actual!=audit.get('final_payload_sha256'):
        raise ValueError('first target-refinement payload identity mismatch')
    return audit,path


def continue_job(job_id, server, total_rounds=5):
    if type(total_rounds) is not int or not 1 <= total_rounds <= 5:
        raise ValueError('4187 continuation rounds must be between 1 and 5')
    import numpy as np
    import core
    import grid_distillation as gd
    import white_balance
    import baseline
    import pc_stages
    from pc_compensation import load
    from fit_anchor_native import training_plan
    from residual_grid import pack, unpack
    from postfit_deburr import deburr
    from training_progress import TrainingProgress
    import multiround
    from gpu_runtime import available

    job = Path(server.RUNS) / job_id
    state = json.loads((job / 'job.json').read_text())
    if state.get('status') != 'done':
        raise ValueError('native fit is not complete: ' + str(state.get('status')))
    key = state.get('result', {}).get('grid_key')
    if not isinstance(key, str):
        raise ValueError('completed job has no packed-grid key')
    parent, original_final, _ = gd.load_result(job, key)
    folder = job / 'grid_distillation' / key
    first_audit,first_path = first_round_source(parent,folder)
    if not parent.get('fitting', {}).get('postfit_deburr'):
        raise ValueError('4187 continuation requires postfit_deburr mode')
    if not available():
        raise RuntimeError('4187 batch continuation requires Apple Metal/MPS')

    evidence = job / 'grid_4187_five_rounds'
    evidence.mkdir(exist_ok=True)
    protected = [job / n for n in ('job.json', 'native_config.json', 'fit/recipe.json',
                                   'pc_compensation.json', 'pairs.npz', folder / 'result.json')]
    protected += [folder / n for n in ('grid.payload', 'postfit-before.payload')]
    protected_hashes = {str(p): sha(p) for p in protected}
    original_state = (job / 'grid_training.json').read_bytes() if (job / 'grid_training.json').exists() else None
    progress = TrainingProgress(job / 'grid_progress.json', total_rounds)
    save(job / 'grid_training.json', dict(status='running', phase='4187方案：压缩后网格接续微调，最多5轮',
        started=time.time(), key=key, parent_grid_key=key, total_target_rounds=total_rounds), server)
    recipe, model = baseline.read_job(job)
    with np.load(job / 'pairs.npz', allow_pickle=False) as arrays:
        data = {name: arrays[name] for name in arrays.files}
    base = white_balance.render_pairs(model, data, recipe) / 16383
    target = data['0_target'] / 16383
    split, ids = data['split'], data['anchor_index']
    random_selection = np.flatnonzero((split == 'train') & (ids < 0) & (data['sector16_index'] < 0))
    fitting = recipe['fitting']
    train, _, _, weights = training_plan(split, ids, fitting.get('group_total_weights'),
        data['sector16_index'], data['baseline_tonal_index'] if fitting.get('tonal_balance') else None,
        random_selection, data['sample_kind'], fitting['search_options'])
    valid = np.flatnonzero(split == 'valid')
    response = parent['identity']['response']
    hue_direction=None;hue_bank=None
    hue_amount=fitting.get('search_options',{}).get('hue_direction_strength',0)
    if hue_amount:
        from hue_direction import HueDirectionBank
        hue_bank=HueDirectionBank(data['design_srgb'],target,split,data['sample_kind'])
        hue_direction=(hue_bank,base[hue_bank.source_indices],hue_amount)

    def save_round(row, grid):
        (evidence / ('round-%d.payload' % row['round'])).write_bytes(pack(grid))
        save(evidence / ('round-%d.json' % row['round']), row, server)

    try:
        selected, audit = multiround.run(unpack(first_path.read_bytes()), first_audit,
            base[train], target[train], weights, base[valid], target[valid], response,
            total_rounds=total_rounds, progress=progress.update, save_round=save_round,
            device='mps',hue_direction=hue_direction)
        save(evidence / 'multiround.json', audit, server)
        before_fc = pack(selected)
        mass = np.ones(len(base), dtype=float); mass[train] = weights
        repaired, fc_audit = deburr(selected, base, target, response,
            design_srgb=data['design_srgb'], split=split, sample_kind=data['sample_kind'],
            anchor_index=ids, weights=mass, progress=progress.update, device='mps')
        if fc_audit.get('original_payload_sha256') != core.sha(before_fc):
            raise ValueError('FC source does not match selected round')

        def validation_cost(grid):
            return multiround.cpu_cost(multiround.cpu_prediction(base[valid], grid, response), target[valid])
        pre_cost, fc_cost, fallback_cost = map(validation_cost, (selected, repaired, original_final))
        fc_selected = fc_cost <= pre_cost and bool(fc_audit.get('accepted', False))
        proposed = repaired if fc_selected else selected
        proposed_cost = fc_cost if fc_selected else pre_cost
        fallback = fallback_cost <= proposed_cost
        final = original_final if fallback else proposed
        selection = dict(metric='CPU64 mean encoded RGB MSE + 0.35*(2.55*DE00)^2 on validation only',
            test_used=False, selected_pre_fc_round=audit['selected_round'],
            selected_pre_fc_validation=pre_cost, fc_validation=fc_cost,
            original_final_validation=fallback_cost, fc_selected=bool(fc_selected and not fallback),
            fc_guard_passed=bool(fc_cost <= pre_cost), original_final_selected=bool(fallback),
            final_validation=min(proposed_cost, fallback_cost), validation_non_regression=True)
        save(evidence / 'selection.json', selection, server)
        if fallback:
            final_before_fc = first_path.read_bytes()
            selected_fc_audit = copy.deepcopy(parent['fitting'].get('postfit_deburr', {}))
        elif fc_selected:
            final_before_fc, selected_fc_audit = before_fc, copy.deepcopy(fc_audit)
        else:
            final_before_fc = before_fc
            selected_fc_audit = dict(fc_audit, accepted=False, selected_final=False,
                reason='validation guard retained selected pre-FC table',
                final_payload_sha256=core.sha(before_fc), changed_coefficients=0)
        payload = pack(final)
        (evidence / 'postfit-attempt.json').write_bytes(server.dump(fc_audit))
        (evidence / 'selected.payload').write_bytes(payload)

        report = copy.deepcopy(parent)
        _, pc_grid = load(job)
        pc_value = json.loads((job / 'pc_compensation.json').read_text())
        teacher = lambda rgb: pc_stages.render(rgb, pc_value['curves'], pc_grid)
        student = multiround.cpu_prediction(base, final, response)
        metrics = {}
        for name, mask in [('gray_training',(ids >= 4) & (ids < 260) & (split == 'train')),
                           ('primaries_training',(ids >= 0) & (ids < 4) & (split == 'train')),
                           ('colorchecker24_training',(ids >= 260) & (ids < 284) & (split == 'train')),
                           ('validation', split == 'valid'), ('test', split == 'test')]:
            metrics[name] = dict(samples=int(mask.sum()),
                combined_vs_lut=core.tonal_comparison(target[mask], teacher(base[mask])),
                grid_vs_lut=core.tonal_comparison(target[mask], student[mask]),
                grid_vs_combined=core.tonal_comparison(teacher(base[mask]), student[mask]))
        identity = report['identity']
        identity['postfit_before_payload_sha256'] = core.sha(final_before_fc)
        identity['multiround_target_refinement'] = dict(parent_grid_key=key,
            parent_result_sha256=sha(folder / 'result.json'), first_round_payload_sha256=sha(first_path),
            maximum_rounds=total_rounds, evaluations_per_extra_round=160,
            helper_sha256=sha(Path(multiround.__file__)), continuation_runtime='4187-canonical',
            final_payload_sha256=core.sha(payload), selection_policy=selection['metric'])
        new_key = core.sha(json.dumps(identity, sort_keys=True).encode())
        report.update(payload_hex=payload.hex(), metrics=metrics)
        report['fitting']['first_round_target_refinement'] = copy.deepcopy(first_audit)
        report['fitting']['constrained_target_refinement'] = dict(audit,
            enabled=True, target='actual train target', teacher_stage_initialization=first_audit.get('teacher_stage_initialization',True),
            native_parameters_frozen=True, packed_integer_acceptance=True,
            initial_payload_sha256=first_audit['initial_payload_sha256'],
            final_payload_sha256=core.sha(final_before_fc), effective_final_payload_sha256=core.sha(payload), selection=selection)
        report['fitting']['postfit_deburr'] = selected_fc_audit
        if hue_bank is not None:
            report['fitting']['hue_direction']=dict(
                final_grid=hue_bank.report(multiround.cpu_prediction(
                    base[hue_bank.source_indices],final,response),hue_amount),
                source='24 complete real TRAIN hue-tonal rays; applied in every target-refinement round')
        report['fitting']['limit_fraction'] = float(np.mean((final == -64) | (final == 63)))
        staging = job / 'grid_distillation' / ('pending-' + new_key)
        destination = job / 'grid_distillation' / new_key
        staging.mkdir()
        (staging / 'teacher.json').write_bytes((job / 'pc_compensation.json').read_bytes())
        (staging / 'postfit-before.payload').write_bytes(final_before_fc)
        (staging / 'grid.payload').write_bytes(payload)
        save(staging / 'result.json', report, server)
        if any(sha(Path(path)) != value for path, value in protected_hashes.items()):
            raise ValueError('protected parent source changed during continuation')
        staging.rename(destination)
        loaded, decoded, _ = gd.load_result(job, new_key)
        np.testing.assert_array_equal(decoded, final)
        # Keep the old job result immutable; only the job's selected pointer moves.
        new_state = dict(state)
        new_state['result'] = dict(state.get('result', {}), grid_key=new_key)
        new_state['phase'] = '4187方案完成：5轮网格微调，验证集选优后去毛刺守门'
        new_state['finished'] = time.time()
        save(job / 'job.json', new_state, server)
        save(job / 'grid_training.json', dict(status='done', phase=new_state['phase'], key=new_key,
            parent_grid_key=key, finished=time.time(), maximum_target_rounds=total_rounds), server)
        progress.update(stage='4187方案完成：已按验证集选优', state='done')
        return new_key, dict(selected_round=audit['selected_round'], selection=selection,
            old_key=key, new_key=new_key, payload_sha256=sha(destination / 'grid.payload'),
            evidence=str(evidence))
    except Exception:
        if original_state is not None:
            (job / 'grid_training.json').write_bytes(original_state)
        raise
