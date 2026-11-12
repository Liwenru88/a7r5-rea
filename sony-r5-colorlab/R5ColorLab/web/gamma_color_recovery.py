"""Restore color with CC1/block13 while the corrected integer Gamma is fixed.

The proposal objective is the original train RGB/Lab objective with frozen PC.
Only the caller's subsequent exact integer and rebuilt-PC gates can accept a
proposal.  This module never sees validation or test arrays.
"""
import hashlib
import os
import time

import numpy as np


POLICY = 'fixed-integer-gamma-train-cc1-block13-color-recovery/1'


class RecoveryProblem:
    def __init__(self, ctx, smooth_model, gray_model, target, gray_target, weights,
                 chosen_params, candidate_params, native_start, pc_bundle, options,
                 *, device='mps', dtype=None):
        from edit_parameter_context import ParameterContext
        from fit_anchor_native import SmoothNative, vector_for
        from gpu_optimizer import StageObjective
        self.options = options
        self.target = np.asarray(target, dtype=float)
        self.weights = np.asarray(weights, dtype=float)
        self.pc_bundle = pc_bundle
        self.gamma = np.asarray(candidate_params['gamma_y'], dtype=np.int64).copy()
        if not ctx.gamma_shape.audit_even(self.gamma)['passed']:
            raise ValueError('Color recovery requires the audited corrected integer Gamma')
        if not (candidate_params['matrix_payload'] == chosen_params['matrix_payload']
                and np.array_equal(candidate_params['cc1'], chosen_params['cc1'])):
            raise ValueError('Gamma-only candidate changed CC1 or block13 before color recovery')
        # Decode the actual quantized winner, rather than its potentially older
        # floating vector, as the starting point of the new complementary fit.
        self.ctx = ParameterContext(ctx.build(**chosen_params))
        self.ctx.gamma_shape = ctx.gamma_shape
        self.ctx.gamma_global_correction = False
        self.seed = vector_for(self.ctx)
        self.seed[104:] = ctx.gamma_shape.encode(self.gamma / 16)

        def model(inputs):
            value = SmoothNative(self.ctx, inputs)
            value.gamma = lambda vector: self.gamma.astype(float) / 16
            return value

        self.model = model(smooth_model.x)
        self.gray_model = model(gray_model.x)
        if getattr(smooth_model, 'output_continuity', None) is not None:
            bank, probe_model, amount = smooth_model.output_continuity
            self.model.output_continuity = (bank, model(probe_model.x), amount)
        if getattr(smooth_model, 'target_neighborhood', None) is not None:
            bank, probe_model, amount = smooth_model.target_neighborhood
            self.model.target_neighborhood = (bank, model(probe_model.x), amount)
        if self.target.shape != (len(self.model.x), 3) or self.weights.shape != (len(self.model.x),):
            raise ValueError('Color recovery requires one complete train target/weight per input')
        self.objective = StageObjective(self.model, self.gray_model, self.target, gray_target,
            self.weights, native_start, pc_bundle, options['perceptual_weight'],
            options['parameter_smoothing'], mode='joint', fixed=self.seed,
            indices=slice(0, 104), device=device, dtype=dtype)
        # SmoothGPU normally dispatches through gamma_shape, so an override on
        # the CPU model alone would silently use the floating reconstruction.
        # Every private renderer must use the SAME actual integer ordinates.
        for name in ('gpu', 'gray_gpu', 'continuity_gpu', 'neighbor_gpu'):
            renderer = getattr(self.objective, name, None)
            if renderer is not None:
                ordinates = renderer.tensor(self.gamma.astype(float) / 16)
                renderer.gamma = lambda vector, y=ordinates: y

    def full(self, color):
        value = self.seed.copy()
        value[:104] = color
        return value

    def corrected(self, prediction):
        if self.pc_bundle is None:
            return prediction
        import pc_stages
        return pc_stages.render(prediction, self.pc_bundle[0], self.pc_bundle[1])

    def cpu_rows(self, color):
        from optimizer_policy import smooth_loss_rows
        from parameter_smoothing import native_rows
        full = self.full(color)
        prediction = self.corrected(self.model.render(full) / 16383)
        rows = (smooth_loss_rows(prediction, self.target / 16383,
            self.options['perceptual_weight']) * np.sqrt(self.weights)[:, None]).ravel()
        penalty = native_rows(full[8:104], self.gamma, self.ctx.axis,
            self.options['parameter_smoothing'], cc1=full[:8], config=self.ctx.base.config)
        if getattr(self.model, 'output_continuity', None) is not None:
            bank, probe, amount = self.model.output_continuity
            penalty = np.r_[penalty, bank.rows(probe.render(full) / 16383, amount)]
        if getattr(self.model, 'target_neighborhood', None) is not None:
            bank, probe, amount = self.model.target_neighborhood
            penalty = np.r_[penalty, bank.rows(self.corrected(probe.render(full) / 16383), amount)]
        return np.r_[rows, penalty * np.sqrt(len(self.weights))]

    def params(self, color):
        full = self.full(color)
        parameters = self.model.params(full)
        parameters['gamma_y'] = self.gamma.copy()
        return full, parameters


def solve(ctx, smooth_model, gray_model, target, gray_target, weights, chosen_params,
          candidate_params, native_start, pc_bundle, options, lower104, upper104,
          max_evaluations, progress=None, *, device=None, dtype=None):
    """Return finite CC1/block13 proposals; caller performs actual acceptance.

    proposals contain ``alpha``, ``vector`` and ``params``.  No Gamma value is
    changed, including when matrix/CC1 is quantized for exact candidate replay.
    """
    from scipy.optimize import minimize
    from gpu_runtime import available
    if device is None:
        if not available() and os.environ.get('R5_GPU_STRICT') == '1':
            raise ValueError('Fixed-Gamma color recovery requires actual MPS')
        device = 'mps' if available() else 'cpu'
    problem = RecoveryProblem(ctx, smooth_model, gray_model, target, gray_target,
        weights, chosen_params, candidate_params, native_start, pc_bundle, options,
        device=device, dtype=dtype)
    lower, upper = np.asarray(lower104, dtype=float), np.asarray(upper104, dtype=float)
    if (lower.shape != (104,) or upper.shape != (104,)
            or not np.isfinite(lower).all() or not np.isfinite(upper).all()
            or np.any(lower >= upper)):
        raise ValueError('Expected 104 original native color bounds')
    seed = problem.seed[:104].copy()
    # Native quantization can put a legal decoded endpoint slightly beyond its
    # former floating bound. Include only that exact endpoint; never clip the
    # original selected color parameters or silently change the alpha-0 case.
    bound_extension = np.maximum(lower - seed, 0) + np.maximum(seed - upper, 0)
    lower, upper = np.minimum(lower, seed), np.maximum(upper, seed)
    cpu = problem.cpu_rows(seed)
    cpu_before = float(cpu @ cpu) / len(weights)
    before, gradient = problem.objective.value_gradient_stage(seed)
    if abs(before - cpu_before) > max(1e-8, abs(cpu_before) * 1e-4):
        raise ValueError('Fixed-Gamma GPU color loss differs from original CPU objective')
    best, best_value, calls = seed.copy(), before, 0
    started = time.perf_counter()
    scale = 1e6  # Constant scale only changes stopping units, never the optimum.

    class BudgetReached(Exception):
        pass

    def evaluate(color):
        nonlocal best, best_value, calls
        if calls >= max_evaluations:
            raise BudgetReached()
        value, grad = problem.objective.value_gradient_stage(color)
        calls += 1
        if value < best_value:
            best, best_value = color.copy(), value
        if progress and calls % 10 == 0:
            progress(evaluations=calls, gpu_loss=value)
        return value * scale, grad * scale

    try:
        result = minimize(evaluate, seed, jac=True, method='L-BFGS-B',
            bounds=list(zip(lower, upper)),
            options=dict(maxfun=max_evaluations, maxiter=max_evaluations,
                         maxls=20, maxcor=20, ftol=1e-10, gtol=1e-9))
        success, message, status = bool(result.success), str(result.message), int(result.status)
    except BudgetReached:
        success, message, status = False, 'Fixed-Gamma color evaluation budget reached', 1
    after_rows = problem.cpu_rows(best)
    cpu_after = float(after_rows @ after_rows) / len(weights)
    cpu_accepted = bool(np.isfinite(cpu_after) and cpu_after < cpu_before)
    if not cpu_accepted:
        best, cpu_after = seed, cpu_before
    proposals = []
    seen = set()
    for alpha in (1., .5, .25, .125, .0625, 0.):
        vector, parameters = problem.params(seed + alpha * (best - seed))
        if not np.array_equal(parameters['gamma_y'], candidate_params['gamma_y']):
            raise ValueError('Color recovery changed the fixed integer Gamma')
        identity = parameters['matrix_payload'] + np.asarray(parameters['cc1'], dtype='<i2').tobytes()
        if identity in seen:
            continue
        seen.add(identity)
        proposals.append(dict(alpha=alpha, vector=vector, params=parameters))
    audit = dict(policy=POLICY, executed=True, accepted=False,
        acceptance='proposal only; caller must verify integer gray improvement and rebuilt-PC train fidelity',
        frozen_gamma=True, fixed_gamma_sha256=hashlib.sha256(np.asarray(problem.gamma, dtype='<i4').tobytes()).hexdigest(),
        source104='decoded exact chosen integer CC1 and block13; not stale floating vector',
        opened_parameters=104, fixed_gamma_points=128, training_samples=len(weights),
        bounds_extended_parameters=int(np.count_nonzero(bound_extension)),
        maximum_bound_extension=float(np.max(bound_extension)),
        objective='unchanged weighted RGB/Lab76 joint fitting objective; frozen PC; no new gray/color weights',
        backend='Apple Metal/MPS' if device == 'mps' else str(device),
        evaluations=calls, max_evaluations=max_evaluations, converged=success,
        budget_exhausted=calls >= max_evaluations, status=status, message=message,
        initial_gradient_max=float(np.max(np.abs(gradient))), stopping_scale=scale,
        cpu_objective_before=cpu_before, cpu_objective_after=cpu_after,
        gpu_best_objective=best_value, cpu_objective_accepted=cpu_accepted,
        integer_proposals=len(proposals), seconds=time.perf_counter() - started,
        data_scope='complete supplied TRAIN; no validation/test samples or selection')
    return proposals, audit
