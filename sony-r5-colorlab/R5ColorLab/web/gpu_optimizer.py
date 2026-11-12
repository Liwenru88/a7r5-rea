"""GPU objectives for every floating native-fit stage, with CPU loss gates."""
import time
import numpy as np
from gpu_alternation import BlockObjective
from apple_gpu import SmoothGPU


class StageObjective(BlockObjective):
    def __init__(self, smooth, gray_model, target, gray_target, weights, native_start,
                 pc_bundle, perceptual_weight, parameter_smoothing, *, mode='joint',
                 fixed=None, indices=slice(None), reference=None, device='mps', dtype=None):
        super().__init__(smooth, target, weights, native_start, pc_bundle if mode == 'joint' else None,
            perceptual_weight, parameter_smoothing, device=device, dtype=dtype)
        self.mode = mode
        self.native_strict_stopping = bool(getattr(smooth.ctx, 'native_strict_stopping', False))
        self.fixed = self.gpu.tensor(native_start if fixed is None else fixed)
        self.indices = indices
        self.gray_gpu = SmoothGPU(gray_model, device=device, dtype=dtype) if mode != 'joint' else None
        self.gray_target = self.gpu.tensor(np.asarray(gray_target) / 16383)
        self.reference = self.gpu.tensor(np.asarray(reference) / 16383) if reference is not None else None
        self.normalization = len(weights)
        self.gamma_global_tone = (mode == 'tone' and bool(getattr(smooth.ctx, 'gamma_global_correction', False)))
        if self.gamma_global_tone:
            self.normalization = len(gray_target)

    def stage_loss(self, values):
        torch = self.torch
        full = self.fixed.clone()
        full[self.indices] = values
        if self.mode == 'joint':
            return super().loss(full)
        gray_delta = self.gray_gpu.render(full) / 16383 - self.gray_target
        if self.mode == 'tone':
            loss = (gray_delta @ self.luma).square().sum()
        elif self.mode == 'gray':
            predicted = self.gpu.render(full) / 16383
            loss = gray_delta.square().sum()
            loss = loss + (full[:104] - self.native_start[:104]).square().sum() * .0001**2
            loss = loss + (predicted - self.reference).square().sum() * .5**2
        elif self.mode == 'chroma':
            predicted = self.gpu.render(full) / 16383
            delta = predicted - self.target
            chroma = delta - (delta @ self.luma)[:, None]
            loss = (chroma.square().sum(dim=1) * self.weights).sum()
            loss = loss + (gray_delta @ self.luma).square().sum()
            loss = loss + (predicted - self.reference).square().sum() * .1**2
            loss = loss + (full[:104] - self.native_start[:104]).square().sum() * .0001**2
        else:
            raise ValueError('Unknown GPU objective stage')
        penalty = self.smoothing_loss(full) + self.target_neighborhood_loss(full)
        if self.gamma_global_tone:
            penalty = penalty * len(self.weights) / self.normalization
        result = loss / self.normalization + penalty
        return result * 255**2 if self.gamma_global_tone else result

    def value_gradient_stage(self, values):
        tensor = self.gpu.tensor(values).requires_grad_(True)
        value = self.stage_loss(tensor)
        value.backward()
        scalar = float(value.detach().cpu())
        gradient = tensor.grad.detach().cpu().numpy().astype(float)
        if not np.isfinite(scalar) or not np.isfinite(gradient).all():
            raise ValueError('Nonfinite GPU training value or gradient')
        return scalar, gradient


def projected_gradient(gradient, values, lower, upper):
    """L-BFGS-B box projection x - clip(x-g, lower, upper), without cancellation."""
    gradient = np.asarray(gradient, float)
    values = np.asarray(values, float)
    return np.where(gradient < 0, np.maximum(values - upper, gradient),
                    np.minimum(values - lower, gradient))


def minimize_stage(factory, residual, initial, options, progress):
    from scipy.optimize import minimize, OptimizeResult
    objective = factory()
    seed = np.asarray(initial, float)
    normalization = objective.normalization
    before_rows = residual(seed)
    before = float(before_rows @ before_rows)
    value, initial_gradient = objective.value_gradient_stage(seed)
    objective_scale = 255**2 if getattr(objective, 'gamma_global_tone', False) else 1.
    strict = bool(getattr(objective, 'native_strict_stopping', False))
    # A single overall constant preserves the complete objective and every
    # existing regularizer's ratio. Tone already returns squared 8-bit units.
    stopping_scale = 255**2 / objective_scale if strict else 1.
    ftol = min(options.get('ftol', 1e-7), 1e-9 if strict else 1e-7)
    gtol = min(options.get('gtol', 1e-8), 1e-5) if strict else options.get('gtol', 1e-8)
    maxls = 30 if strict else 15
    expected = before / normalization * objective_scale
    if abs(value - expected) > max(1e-8, abs(expected) * 1e-4):
        raise ValueError(f'GPU loss gate failed: {value} versus {expected}')
    lower, upper = options['bounds']
    lower = np.broadcast_to(lower, seed.shape)
    upper = np.broadcast_to(upper, seed.shape)
    limit = options.get('max_nfev', 200)
    calls = 0
    best = seed.copy()
    best_value = value
    best_gradient = initial_gradient
    current_value = value
    started = time.perf_counter()

    class BudgetReached(Exception):
        pass

    def value_gradient(values):
        nonlocal calls, best, best_value, best_gradient, current_value
        if calls >= limit:
            raise BudgetReached()
        result = objective.value_gradient_stage(values)
        calls += 1
        current_value = result[0]
        if result[0] < best_value:
            best = values.copy()
            best_value = result[0]
            best_gradient = result[1].copy()
        if calls % 10 == 0:
            progress.update(evaluations=calls, gpu_loss=result[0])
            progress.record_loss('MPS L-BFGS-B', calls, current_value, best_value)
        return result[0] * stopping_scale, result[1] * stopping_scale

    def callback(values):
        progress.update(iteration=progress.value['iteration'] + 1, evaluations=calls)

    progress.update(gpu_backend='Apple Metal/MPS', gpu_loss=value,
        gradient_method='autograd; one shared forward/backward pass')
    progress.record_loss('MPS L-BFGS-B', 0, value, best_value)
    if strict:
        progress.update(native_strict_stopping=True, stopping_scale=stopping_scale,
            optimizer_loss_units='squared 8-bit equivalent; full objective times one constant',
            optimizer_ftol=ftol, optimizer_gtol=gtol, optimizer_maxls=maxls,
            gpu_loss_raw=value / objective_scale,
            gpu_loss_8bit=value / objective_scale * 255**2)
    solver_result = None
    try:
        result = minimize(value_gradient, seed, jac=True, method='L-BFGS-B',
            bounds=list(zip(lower, upper)), callback=callback,
            options=dict(maxfun=limit, maxiter=limit, maxls=maxls,
                ftol=ftol, gtol=gtol, maxcor=20))
        solver_result = result
        success = bool(result.success)
        message = str(result.message)
        solver_status = int(result.status)
        budget_exhausted = bool(solver_status == 1)
        status = 2 if success else (0 if result.status == 1 else -1)
    except BudgetReached:
        success = False
        status = 0
        solver_status = None  # The wrapper stopped before SciPy could return.
        budget_exhausted = True
        message = 'GPU objective evaluation budget reached'
    if calls % 10 != 0:
        progress.record_loss('MPS L-BFGS-B', calls, current_value, best_value)
    after_rows = residual(best)
    after = float(after_rows @ after_rows)
    accepted = bool(np.isfinite(after) and after < before)
    if not accepted:
        best, after = seed, before
    audit = {}
    if strict:
        gradient = best_gradient if accepted else initial_gradient
        returned_value = best_value if accepted else value
        raw_gradient = gradient / objective_scale
        projected = projected_gradient(raw_gradient, best, lower, upper)
        projected_8bit = projected_gradient(raw_gradient * 255**2, best, lower, upper)
        upper_message = message.upper()
        reason = ('projected_gradient' if success and 'GRADIENT' in upper_message
                  else 'relative_objective_change' if success and ('REL_REDUCTION' in upper_message or 'FACTR' in upper_message)
                  else 'solver_success' if success
                  else 'evaluation_budget' if 'EVALUATION' in upper_message or 'F AND G EVALUATIONS' in upper_message
                  else 'iteration_budget' if budget_exhausted
                  else 'line_search_failure' if 'ABNORMAL' in upper_message or 'LINE SEARCH' in upper_message
                  else 'solver_failure')
        audit = dict(native_strict_stopping=True,
            stopping_policy='native-full-objective-8bit-strict/1',
            stopping_scale=stopping_scale, full_objective_scale=255**2,
            optimizer_ftol=ftol, optimizer_gtol=gtol, optimizer_maxls=maxls,
            solver_status=solver_status, stopping_reason=reason,
            termination_source='scipy-lbfgsb' if solver_result is not None else 'wrapper-evaluation-budget',
            budget_exhausted=budget_exhausted,
            loss_before_raw=value / objective_scale,
            loss_after_raw=returned_value / objective_scale,
            loss_before_8bit=value / objective_scale * 255**2,
            loss_after_8bit=returned_value / objective_scale * 255**2,
            gradient_inf_raw=float(np.max(np.abs(raw_gradient))),
            gradient_inf_8bit=float(np.max(np.abs(raw_gradient))) * 255**2,
            projected_gradient_inf_raw=float(np.max(np.abs(projected))),
            projected_gradient_inf_8bit=float(np.max(np.abs(projected_8bit))),
            solver_projected_gradient_inf_8bit=(float(np.max(np.abs(projected_gradient(
                solver_result.jac, solver_result.x, lower, upper)))) if solver_result is not None else None),
            solver_point_equals_returned=(bool(np.array_equal(solver_result.x, best))
                if solver_result is not None else None),
            diagnostic_point='returned best GPU proposal' if accepted else 'returned original CPU-accepted seed')
    return OptimizeResult(x=best, cost=after / 2, optimality=float(np.max(np.abs(best_gradient))),
        nfev=calls, success=success, status=status, message=message, backend='Apple Metal/MPS',
        cpu_objective_before=before, cpu_objective_after=after, cpu_objective_accepted=accepted,
        seconds=time.perf_counter() - started, **audit)
