"""Continue a packed target-fit grid through at most five total rounds.

Import after putting the frozen runtime and its scripts on sys.path. Only
``continuity_grid.constrain`` fits parameters; acceptance/selection below use
explicit NumPy float64 prediction and the CPU display-cost formula. No FC or
test-set access occurs here. Caller owns immutable input/source provenance.
"""
import copy
import hashlib

import numpy as np


def cpu_prediction(base, grid, response):
    """Evaluate packed integer coefficients without automatic MPS dispatch."""
    from residual_grid import coefficients, evaluate
    base = np.asarray(base, dtype=np.float64)
    grid = coefficients(grid)
    if isinstance(response, dict):
        from measured_response import get
        model = get(response)
        if not hasattr(model, 'predict_cpu'):
            raise ValueError('Explicit predict_cpu is required for measured responses')
        result = model.predict_cpu(base, grid, clip=True)
    else:
        # The explicit 3x3 branch of residual_grid.evaluate is NumPy-only.
        result = evaluate(base, grid, np.asarray(response, dtype=np.float64))
    result = np.asarray(result, dtype=np.float64)
    if result.shape != base.shape or not np.isfinite(result).all():
        raise ValueError('Nonfinite or mismatched CPU64 prediction')
    return result


def cpu_cost_rows(predicted, target, perceptual_weight=.35):
    """Exact NumPy branch of frozen optimizer_policy.display_cost_rows."""
    from perceptual import to_lab, de2000
    predicted, target = [np.asarray(v, dtype=np.float64) for v in (predicted, target)]
    if (predicted.ndim != 2 or predicted.shape[1] != 3 or target.shape != predicted.shape
            or not np.isfinite(predicted).all() or not np.isfinite(target).all()):
        raise ValueError('Expected finite matching Nx3 prediction and target')
    if not np.isfinite(perceptual_weight) or perceptual_weight < 0:
        raise ValueError('Expected nonnegative finite perceptual weight')
    p, t = [np.clip(v, 0, 1) * 255 for v in (predicted, target)]
    rows = np.mean((p - t)**2, axis=1)
    if perceptual_weight:
        rows += perceptual_weight * (2.55 * de2000(to_lab(p), to_lab(t)))**2
    if not np.isfinite(rows).all():
        raise ValueError('Nonfinite CPU64 display cost')
    return rows


def cpu_cost(predicted, target, weights=None, perceptual_weight=.35):
    """Weighted CPU64 mean display cost; validation defaults to uniform rows."""
    rows = cpu_cost_rows(predicted, target, perceptual_weight)
    if not len(rows):
        raise ValueError('At least one score row is required')
    mass = np.ones(len(rows), dtype=np.float64) if weights is None else np.asarray(weights, dtype=np.float64)
    if mass.shape != rows.shape or not np.isfinite(mass).all() or np.any(mass <= 0):
        raise ValueError('Expected matching positive finite scoring weights')
    return float(rows @ mass / np.sum(mass))


def _samples(base, target, weights, name):
    base, target = [np.array(v, dtype=np.float64, copy=True) for v in (base, target)]
    if (base.ndim != 2 or base.shape[1] != 3 or len(base) < 1 or target.shape != base.shape
            or not np.isfinite(base).all() or not np.isfinite(target).all()):
        raise ValueError('Expected finite matching ' + name + ' Nx3 arrays')
    weights = np.ones(len(base), dtype=np.float64) if weights is None else np.array(weights, dtype=np.float64, copy=True)
    if weights.shape != (len(base),) or not np.isfinite(weights).all() or np.any(weights <= 0):
        raise ValueError('Expected positive finite ' + name + ' weights')
    return base, target, weights


def run(initial_grid, first_round_audit, train_base, train_target, train_weights,
        validation_base, validation_target, response, total_rounds=5, progress=None,
        save_round=None, *, validation_weights=None, device=None, hue_direction=None):
    """Return ``(selected_grid, audit)`` after continuing rounds 2..5.

    ``initial_grid`` is the already completed round-1 packed result, before FC.
    ``save_round(round_audit, accepted_packed_grid)`` is called for round 1
    and every attempted continuation. It may persist each payload and audit.
    Optimization receives TRAIN only, 160 evaluations, no shape penalties.
    Every next attempt starts at the last CPU64-accepted packed result,
    independently of which round validation eventually selects. A worse
    TRAIN proposal is rejected and does not alter that chain. Validation
    selects among accepted candidates including round 1; exact ties prefer
    the earlier round. A byte-identical returned proposal stops early.
    """
    from continuity_grid import constrain
    from residual_grid import pack, unpack
    if type(total_rounds) is not int or not 1 <= total_rounds <= 5:
        raise ValueError('Total rounds must be between 1 and 5')
    if not isinstance(first_round_audit, dict):
        raise ValueError('Round-1 audit must be a dictionary')
    base, target, weights = _samples(train_base, train_target, train_weights, 'TRAIN')
    vb, vt, vw = _samples(validation_base, validation_target, validation_weights, 'validation')
    response = copy.deepcopy(response)
    first_round_audit = copy.deepcopy(first_round_audit)
    current_payload = bytes(pack(initial_grid))
    current = unpack(current_payload)

    def score(grid, x, desired, mass, include_hue=False):
        value=cpu_cost(cpu_prediction(x, grid, response), desired, mass, .35)
        if include_hue and hue_direction is not None:
            bank,hue_base,amount=hue_direction
            value+=bank.cost(cpu_prediction(hue_base,grid,response),amount)
        return value

    train_score = score(current, base, target, weights, True)
    valid_score = score(current, vb, vt, vw)
    selected = current.copy()
    selected_round, selected_validation = 1, valid_score
    selected_train = train_score
    rounds = []

    def emit(index, payload, record):
        rounds.append(copy.deepcopy(record))
        if save_round is not None:
            save_round(copy.deepcopy(record), unpack(payload))

    emit(1, current_payload, dict(round=1, supplied_completed_round=True,
        accepted=True, changed_from_seed=None, train_score_before=None,
        train_score=train_score, validation_score=valid_score,
        accepted_payload_sha256=hashlib.sha256(current_payload).hexdigest(),
        fitter=first_round_audit, cpu_float64_integer_acceptance=True))
    stopped_reason = 'completed_requested_rounds'
    for index in range(2, total_rounds + 1):
        before_payload, before_score = current_payload, train_score

        def report(**values):
            if progress is not None:
                values.update(round=index, total_rounds=total_rounds)
                progress(**values)

        # Give the fitter private arrays and response; external inputs and the
        # immutable scoring bank cannot be modified by an optimizer/callback.
        candidate, fitter_audit = constrain(current.copy(), base.copy(), target.copy(),
            weights.copy(), copy.deepcopy(response), 0, None, report if progress is not None else None,
            evaluations=160, device=device, hue_direction=hue_direction,
            training_penalties=hue_direction is not None)
        candidate_payload = bytes(pack(candidate))
        candidate = unpack(candidate_payload)
        proposal_score = score(candidate, base, target, weights, True)
        accepted = bool(proposal_score <= before_score)
        changed = candidate_payload != before_payload
        if accepted:
            current, current_payload, train_score = candidate, candidate_payload, proposal_score
        valid_score = score(current, vb, vt, vw)
        record = dict(round=index, supplied_completed_round=False, accepted=accepted,
            rejection_reason=None if accepted else 'cpu64_train_display_cost_regression',
            changed_from_seed=changed, train_score_before=before_score,
            proposal_train_score=proposal_score, train_score=train_score,
            validation_score=valid_score,
            initial_payload_sha256=hashlib.sha256(before_payload).hexdigest(),
            proposal_payload_sha256=hashlib.sha256(candidate_payload).hexdigest(),
            accepted_payload_sha256=hashlib.sha256(current_payload).hexdigest(),
            fitter=copy.deepcopy(fitter_audit), cpu_float64_integer_acceptance=True)
        emit(index, current_payload, record)
        if accepted and valid_score < selected_validation:
            selected, selected_round = current.copy(), index
            selected_train, selected_validation = train_score, valid_score
        if not changed:
            stopped_reason = 'no_integer_change'
            break
    audit = dict(schema='packed-grid-five-target-rounds/1', total_round_limit=total_rounds,
        supplied_completed_rounds=1, attempted_total_rounds=len(rounds),
        new_optimizer_calls=len(rounds)-1, evaluations_per_new_round=160,
        training_shape_penalties=bool(hue_direction), native_parameters_frozen=True,
        hue_direction_enabled=bool(hue_direction),
        chain='last CPU64-accepted packed integer result; never validation-selected rollback',
        selection='minimum CPU64 validation weighted display cost; earlier round on exact tie',
        perceptual_weight=.35, train_inputs=len(base), validation_inputs=len(vb),
        test_consumed=False, fc_executed=False, cpu_scoring='NumPy float64 predict_cpu + RGB MSE + CIEDE2000',
        stopped_reason=stopped_reason, rounds=rounds, selected_round=selected_round,
        selected_train_score=selected_train, selected_validation_score=selected_validation,
        selected_payload_sha256=hashlib.sha256(pack(selected)).hexdigest(),
        last_accepted_payload_sha256=hashlib.sha256(current_payload).hexdigest())
    return unpack(pack(selected)), audit
