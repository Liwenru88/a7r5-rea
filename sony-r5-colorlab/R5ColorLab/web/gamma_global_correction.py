"""Train-only whole-Gamma correction; complementary native parameters stay fixed.

Direct simplex masses can reopen a previously zero curvature component.  They
use the same concave hinge basis as the normal logit parameterization, then
return to that parameterization before any integer/native acceptance check.
"""
import os
import time

import numpy as np


POLICY = 'train-only-global-concave-gamma-mass-correction/1'


def normalized_masses(values):
    mass = np.maximum(np.asarray(values, dtype=float), 0.)
    if mass.ndim != 1 or not np.isfinite(mass).all() or mass.sum() <= 0:
        raise ValueError('Invalid Gamma simplex masses')
    return mass / mass.sum()


def logits_for_masses(shape, values):
    mass = normalized_masses(values)
    logits = np.log(np.maximum(mass, 1e-12))
    expected = shape.max_output * (shape.basis @ mass)
    delta = float(np.max(np.abs(shape.curve(logits) - expected)))
    if delta > 1e-5:
        raise ValueError('Gamma mass/logit reconstruction differs')
    return logits, delta


class MassGrayObjective:
    def __init__(self, gray_model, fixed, target, *, device='mps', dtype=None):
        from apple_gpu import SmoothGPU
        self.gpu = SmoothGPU(gray_model, device=device, dtype=dtype)
        self.torch = self.gpu.torch
        self.fixed = self.gpu.tensor(fixed)
        self.target = self.gpu.tensor(np.asarray(target) / 16383)
        self.basis = self.gpu.tensor(gray_model.gamma_shape.basis)
        self.scale = gray_model.gamma_shape.max_output
        self.luma = self.gpu.tensor(__import__('pc_stages').LUMA)
        self.samples = len(target)
        # This is a private GPU renderer: do not change the shared Gamma shape.
        self.gpu.gamma = lambda v: self.scale * (self.basis @ (v[104:] / v[104:].sum()))

    def value_gradient(self, masses):
        torch = self.torch
        value = self.gpu.tensor(masses).requires_grad_(True)
        full = torch.cat((self.fixed[:104], value))
        delta = (self.gpu.render(full) / 16383 - self.target) @ self.luma
        loss = delta.square().mean() * 255**2
        loss.backward()
        scalar = float(loss.detach().cpu())
        gradient = value.grad.detach().cpu().numpy().astype(float)
        if not np.isfinite(scalar) or not np.isfinite(gradient).all():
            raise ValueError('Nonfinite whole-Gamma loss or gradient')
        return scalar, gradient


def solve(gray_model, fixed, target, max_evaluations, *, progress=None, device=None, dtype=None):
    from scipy.optimize import minimize
    from gpu_runtime import available
    if device is None:
        if not available() and os.environ.get('R5_GPU_STRICT') == '1':
            raise ValueError('Whole-Gamma correction requires actual MPS')
        device = 'mps' if available() else 'cpu'
    fixed = np.asarray(fixed, dtype=float).copy()
    shape = gray_model.gamma_shape
    objective = MassGrayObjective(gray_model, fixed, target, device=device, dtype=dtype)
    seed = np.exp(fixed[104:] - np.max(fixed[104:]))
    seed = normalized_masses(seed)
    before, initial_gradient = objective.value_gradient(seed)
    best, best_value = seed.copy(), before
    calls = 0
    started = time.perf_counter()

    class BudgetReached(Exception):
        pass

    def evaluate(values):
        nonlocal calls, best, best_value
        if calls >= max_evaluations:
            raise BudgetReached()
        result = objective.value_gradient(values)
        calls += 1
        if abs(np.sum(values) - 1) <= 1e-6 and result[0] < best_value:
            best, best_value = normalized_masses(values), result[0]
        if progress and calls % 10 == 0:
            progress(evaluations=calls, gpu_loss=result[0])
        return result

    try:
        result = minimize(evaluate, seed, jac=True, method='SLSQP',
            bounds=[(0., 1.)] * len(seed),
            constraints=[dict(type='eq', fun=lambda x: x.sum() - 1,
                              jac=lambda x: np.ones_like(x))],
            options=dict(maxiter=max_evaluations, ftol=1e-8))
        converged, message, status = bool(result.success), str(result.message), int(result.status)
    except BudgetReached:
        converged, message, status = False, 'Gamma mass objective evaluation budget reached', 9
    logits, reconstruction = logits_for_masses(shape, best)
    audit = dict(policy=POLICY, executed=True, backend='Apple Metal/MPS' if device == 'mps' else str(device),
        samples=len(target), objective='mean squared native gray luminance error, in 8-bit units',
        parameterization='all 127 nonnegative concave hinge masses plus endpoint slack; simplex sum=1',
        frozen104=True, controls=len(shape.axis), max_evaluations=max_evaluations,
        evaluations=calls, converged=converged, status=status, message=message,
        budget_exhausted=calls >= max_evaluations,
        initial_gray_luma_mse_8bit=before, best_float_gray_luma_mse_8bit=best_value,
        initial_gradient_max=float(np.max(np.abs(initial_gradient))),
        mass_to_logit_maximum_reconstruction_14bit=reconstruction,
        seconds=time.perf_counter() - started,
        data_scope='256 train gray targets only; no validation or test samples')
    return seed, best, audit


def integer_candidates(shape, fixed, source_mass, target_mass):
    """Finite feasible whole-curve steps; only Gamma changes in each proposal."""
    for alpha in (1., .5, .25, .125, .0625, .03125, .015625):
        proposal = np.asarray(fixed, dtype=float).copy()
        logits, reconstruction = logits_for_masses(shape,
            (1-alpha) * source_mass + alpha * target_mass)
        proposal[104:] = logits
        if not np.array_equal(proposal[:104], np.asarray(fixed)[:104]):
            raise ValueError('Whole-Gamma correction changed complementary parameters')
        yield alpha, proposal, reconstruction
