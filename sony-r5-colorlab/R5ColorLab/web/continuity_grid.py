"""Optional final-grid optimization with an output continuity objective.

One fixed native model, actual training targets, no native/grid alternation.
Candidate acceptance always scores the signed integer table, including the
continuity penalty; continuous optimizer loss alone cannot accept a candidate.
"""
import numpy as np
from output_continuity import TensorPenalty


def penalty(grid, response, continuity):
    if continuity is None:
        return 0.
    from residual_grid import evaluate
    from gpu_runtime import cpu_reference
    bank, base, amount = continuity
    with cpu_reference():
        return bank.cost(evaluate(base, grid, response), amount)


def constrain(grid, base, target, weights, response, smoothing, continuity, progress=None, *,
              evaluations=160, device=None):
    from optimizer_policy import display_cost_rows
    from parameter_smoothing import grid_cost, multiplier
    from residual_grid import evaluate
    from gpu_runtime import available
    from gpu_tensor import TensorTools, stencil_tensor, provisional_coordinates
    from scipy.optimize import minimize
    from gpu_grid import edges
    import torch
    if device is None: device = 'mps' if available() else 'cpu'
    tools = TensorTools(device=device, dtype=torch.float64 if device == 'cpu' else torch.float32)
    bank, probe_base, amount = continuity
    source, desired = tools.tensor(base), tools.tensor(target).clamp(0, 1)
    mass = tools.tensor(np.asarray(weights) / np.sum(weights))
    probes = tools.tensor(probe_base)
    target_lab = tools.lab(desired).detach()
    output_penalty = TensorPenalty(bank, tools, amount)
    edge = tools.tensor(edges((5, 9, 9)), True)
    actual_penalty = None
    if isinstance(response,dict):
        from grid_regularization import get_penalty
        actual_penalty = get_penalty(response)

    # Native output is fixed, so cache coordinates and the response at each row.
    def renderer(rgb, original):
        if isinstance(response, dict):
            from measured_response import get
            model = get(response)
            if not hasattr(model, 'affine'):
                raise ValueError('Output continuity requires the R5 paired grid response')
            coords = model.coordinates_tensor(tools,rgb)
            mixing = tools.tensor(model.response(np.asarray(original)))
        else:
            coords = provisional_coordinates(tools, rgb)
            mixing = tools.tensor(response).expand(len(rgb), 3, 3) / 256
        ids, w = stencil_tensor(tools, coords)
        def render(table):
            delta = (table[ids] * w[:, :, None]).sum(dim=1)
            return (rgb + torch.einsum('nc,nco->no', delta, mixing)).clamp(0, 1)
        return render
    render_train = renderer(source, base)
    render_probes = renderer(probes, probe_base)

    def value_gradient(values):
        table = tools.tensor(values.reshape(405, 3)).requires_grad_(True)
        pred = render_train(table)
        loss = (((pred - desired).square().mean(dim=1) +
            ((tools.lab(pred) - target_lab) / 100).square().sum(dim=1) * .35) * mass).sum()
        if smoothing:
            loss = loss + (actual_penalty.tensor_loss(tools,table,smoothing) if actual_penalty is not None else
                (table[edge[:, 1]] - table[edge[:, 0]]).square().sum() * (.01 * multiplier(smoothing)) / (405 * 3 * 256**2))
        loss = loss + output_penalty.loss(render_probes(table))
        loss.backward()
        value = float(loss.detach().cpu())
        grad = table.grad.detach().cpu().numpy().astype(float).ravel()
        if not np.isfinite(value) or not np.isfinite(grad).all():
            raise ValueError('Nonfinite continuity grid loss/gradient')
        return value, grad

    def exact_cost(table):
        from gpu_runtime import cpu_reference
        with cpu_reference():
            rows = display_cost_rows(evaluate(base, table, response), target, .35)
            return float(rows @ np.asarray(weights) / np.sum(weights)) + grid_cost(table, smoothing,response=response) + penalty(table, response, continuity)
    original = np.array(grid, dtype=np.int8, copy=True)
    # Independent float64 value gate before trusting the accelerated gradient.
    from perceptual import to_lab
    from gpu_runtime import cpu_reference
    with cpu_reference():
        prediction=evaluate(base,original,response)
    data=np.mean((prediction-np.clip(target,0,1))**2,axis=1)
    data+=.35*np.sum(((to_lab(prediction*255)-to_lab(np.clip(target,0,1)*255))/100)**2,axis=1)
    expected=float(data@np.asarray(weights)/np.sum(weights))+(grid_cost(original,smoothing,response=response)+penalty(original,response,continuity))/255**2
    value,_=value_gradient(original.astype(float).ravel())
    if abs(value-expected)>max(1e-8,abs(expected)*1e-4):
        raise ValueError(f'Grid continuity loss gate failed: {value} versus {expected}')
    before = exact_cost(original)
    best_loss = current_loss = value
    calls = 0
    solver = device.upper()+' 网格连续性 L-BFGS-B'
    if progress:
        progress(stage='最终网格输出连续性约束', state='running', evaluations=0,
                 max_evaluations=evaluations, loss_sample=(solver, 0, value, value))

    def observed_value_gradient(values):
        nonlocal calls, current_loss, best_loss
        current_loss, gradient = value_gradient(values)
        calls += 1
        best_loss = min(best_loss, current_loss)
        if calls % 10 == 0:
            progress(evaluations=calls, loss_sample=(solver, calls, current_loss, best_loss))
        return current_loss, gradient

    fit = minimize(observed_value_gradient if progress else value_gradient,
        original.astype(float).ravel(), jac=True, method='L-BFGS-B',
        bounds=[(-64, 63)] * 1215,
        options=dict(maxiter=evaluations, maxfun=evaluations, maxls=12, ftol=1e-8, gtol=1e-8))
    if progress and calls % 10:
        progress(evaluations=calls, loss_sample=(solver, calls, current_loss, best_loss))
    choices = [(before, original)]
    for alpha in (1., .75, .5, .25):
        candidate = np.clip(np.rint(original + alpha * (fit.x.reshape(405, 3) - original)), -64, 63).astype(np.int8)
        choices.append((exact_cost(candidate), candidate))
    after, result = min(choices, key=lambda item: item[0])
    return result, dict(enabled=True, backend=device, evaluations=int(fit.nfev), before=before, after=after,
        accepted=bool(after < before), training_only=True, integer_output_acceptance=True,
        native_parameters_frozen=True, target='actual training target; no photo target',
        output=bank.report(evaluate(probe_base, result, response), amount))
