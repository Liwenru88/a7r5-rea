"""Final-grid optimization with optional output continuity objectives.

One fixed native model, actual training targets, no native/grid alternation.
Candidate acceptance always scores the signed integer table. The explicit
data-only mode retains data fidelity and hard limits before post-fit repair.
Continuous optimizer loss alone cannot accept a candidate.
"""
import hashlib
import numpy as np
from output_continuity import TensorPenalty


def penalty(grid, response, continuity):
    if continuity is None:
        return 0.
    from residual_grid import evaluate
    bank, base, amount = continuity
    return bank.cost(evaluate(base, grid, response), amount)


def neighborhood_penalty(grid, response, target_neighborhood):
    """Exact packed-grid target-shape cost on frozen, real TRAIN colors."""
    if target_neighborhood is None:return 0.
    from residual_grid import evaluate
    bank, base, amount = target_neighborhood
    return bank.cost(evaluate(base,grid,response),amount)


def hue_direction_penalty(grid, response, hue_direction):
    if hue_direction is None:return 0.
    from residual_grid import evaluate
    bank, base, amount = hue_direction
    return bank.cost(evaluate(base,grid,response),amount)


def constrain(grid, base, target, weights, response, smoothing, continuity, progress=None, *,
              evaluations=160, device=None, target_neighborhood=None, hue_direction=None,
              training_penalties=True):
    from optimizer_policy import display_cost_rows
    from parameter_smoothing import grid_cost, multiplier
    from residual_grid import evaluate, pack, unpack
    from gpu_runtime import available
    from gpu_tensor import TensorTools, stencil_tensor, provisional_coordinates
    from scipy.optimize import minimize
    from gpu_grid import edges
    import torch
    if device is None: device = 'mps' if available() else 'cpu'
    tools = TensorTools(device=device, dtype=torch.float64 if device == 'cpu' else torch.float32)
    if not training_penalties:
        smoothing,continuity,target_neighborhood,hue_direction=0,None,None,None
    if training_penalties and continuity is None and target_neighborhood is None and hue_direction is None:
        raise ValueError('At least one output constraint is required')
    bank, probe_base, amount = continuity if continuity is not None else (None,None,0)
    source, desired = tools.tensor(base), tools.tensor(target).clamp(0, 1)
    mass = tools.tensor(np.asarray(weights) / np.sum(weights))
    probes = tools.tensor(probe_base) if bank is not None else None
    target_lab = tools.lab(desired).detach()
    output_penalty = TensorPenalty(bank, tools, amount) if bank is not None else None
    edge = tools.tensor(edges((5, 9, 9)), True)
    actual_penalty = None
    if training_penalties and isinstance(response,dict):
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
    render_probes = renderer(probes, probe_base) if bank is not None else None
    neighbor_bank, neighbor_base, neighbor_amount = target_neighborhood if target_neighborhood is not None else (None,None,0)
    render_neighbors = renderer(tools.tensor(neighbor_base),neighbor_base) if neighbor_bank is not None else None
    hue_bank, hue_base, hue_amount = hue_direction if hue_direction is not None else (None,None,0)
    render_hue = renderer(tools.tensor(hue_base),hue_base) if hue_bank is not None else None

    def value_gradient(values):
        table = tools.tensor(values.reshape(405, 3)).requires_grad_(True)
        pred = render_train(table)
        loss = (((pred - desired).square().mean(dim=1) +
            ((tools.lab(pred) - target_lab) / 100).square().sum(dim=1) * .35) * mass).sum()
        if smoothing:
            loss = loss + (actual_penalty.tensor_loss(tools,table,smoothing) if actual_penalty is not None else
                (table[edge[:, 1]] - table[edge[:, 0]]).square().sum() * (.01 * multiplier(smoothing)) / (405 * 3 * 256**2))
        if output_penalty is not None:loss = loss + output_penalty.loss(render_probes(table))
        if neighbor_bank is not None:loss = loss + neighbor_bank.tensor_loss(tools,render_neighbors(table),neighbor_amount)
        if hue_bank is not None:loss = loss + hue_bank.tensor_loss(tools,render_hue(table),hue_amount)
        loss.backward()
        value = float(loss.detach().cpu())
        grad = table.grad.detach().cpu().numpy().astype(float).ravel()
        if not np.isfinite(value) or not np.isfinite(grad).all():
            raise ValueError('Nonfinite continuity grid loss/gradient')
        return value, grad

    def exact_cost(table):
        rows = display_cost_rows(evaluate(base, table, response), target, .35)
        value=float(rows @ np.asarray(weights) / np.sum(weights))
        if training_penalties:
            value+=(grid_cost(table,smoothing,response=response)+penalty(table,response,continuity)
                +neighborhood_penalty(table,response,target_neighborhood)
                +hue_direction_penalty(table,response,hue_direction))
        return value
    original = unpack(pack(grid)) if not training_penalties else np.array(grid, dtype=np.int8, copy=True)
    # Independent float64 value gate before trusting the accelerated gradient.
    from perceptual import to_lab
    prediction=evaluate(base,original,response)
    data=np.mean((prediction-np.clip(target,0,1))**2,axis=1)
    data+=.35*np.sum(((to_lab(prediction*255)-to_lab(np.clip(target,0,1)*255))/100)**2,axis=1)
    expected=float(data@np.asarray(weights)/np.sum(weights))
    if training_penalties:
        expected+=(grid_cost(original,smoothing,response=response)+penalty(original,response,continuity)
            +neighborhood_penalty(original,response,target_neighborhood)
            +hue_direction_penalty(original,response,hue_direction))/255**2
    value,_=value_gradient(original.astype(float).ravel())
    if abs(value-expected)>max(1e-8,abs(expected)*1e-4):
        raise ValueError(f'Grid continuity loss gate failed: {value} versus {expected}')
    before = exact_cost(original)
    best_loss = current_loss = value
    calls = 0
    stage=('最终网格色相-亮度偏移同向约束' if hue_bank is not None else
           '最终网格输出连续性约束') if training_penalties else '压缩网格真实目标数据微调'
    solver = device.upper()+(' 网格连续性 L-BFGS-B' if training_penalties else ' 网格目标 L-BFGS-B')
    if progress:
        progress(stage=stage, state='running', evaluations=0,
                 max_evaluations=evaluations, loss_sample=(solver, 0, value, value))

    def observed_value_gradient(values):
        nonlocal calls, current_loss, best_loss
        current_loss, gradient = value_gradient(values)
        calls += 1
        best_loss = min(best_loss, current_loss)
        if calls % 10 == 0:
            progress(evaluations=calls, loss_sample=(solver, calls, current_loss, best_loss))
        return current_loss, gradient

    # Data-only losses and gradients are small in normalized RGB units. Scale
    # both equally for L-BFGS stopping tests; exact integer acceptance below
    # remains in the original CPU float64 display-loss units.
    loss_scale=1. if training_penalties else 1e8
    def optimizer_value_gradient(values):
        value,gradient=observed_value_gradient(values) if progress else value_gradient(values)
        return value*loss_scale,gradient*loss_scale
    fit = minimize(optimizer_value_gradient, original.astype(float).ravel(), jac=True, method='L-BFGS-B',
        bounds=[(-64, 63)] * 1215,
        options=dict(maxiter=evaluations, maxfun=evaluations, maxls=12, ftol=1e-8 if training_penalties else 1e-12, gtol=1e-8))
    if progress and calls%10:
        progress(evaluations=calls,loss_sample=(solver,calls,current_loss,best_loss))
    choices = [(before, original)]
    for alpha in (1., .75, .5, .25):
        candidate = np.clip(np.rint(original + alpha * (fit.x.reshape(405, 3) - original)), -64, 63).astype(np.int8)
        if not training_penalties: candidate=unpack(pack(candidate))
        choices.append((exact_cost(candidate), candidate))
    after, result = min(choices, key=lambda item: item[0])
    return result, dict(enabled=True, backend=device, evaluations=int(fit.nfev), before=before, after=after,
        accepted=bool(after < before), training_only=True, integer_output_acceptance=True,
        training_shape_penalties=bool(training_penalties),optimizer_loss_scale=loss_scale,
        optimizer_success=bool(fit.success),optimizer_message=str(fit.message),
        initial_payload_sha256=hashlib.sha256(pack(original)).hexdigest(),
        final_payload_sha256=hashlib.sha256(pack(result)).hexdigest(),
        coefficient_bounds=[-64,63],cpu_float64_integer_acceptance=True,
        native_parameters_frozen=True, target='actual training target; no photo target',
        output=bank.report(evaluate(probe_base, result, response), amount) if bank is not None else None,
        target_neighborhood=neighbor_bank.report(evaluate(neighbor_base,result,response),neighbor_amount) if neighbor_bank is not None else None,
        hue_direction=hue_bank.report(evaluate(hue_base,result,response),hue_amount) if hue_bank is not None else None)
