"""从灰阶初始化直接拟合BIN，用可微内层网格求解消除高维搜索变量。"""
import copy
import time

import numpy as np

from joint_fit import JointObjective, solve

POLICY = 'profiled-native-core/1'


def conditional_grid(tools, rgb, target, mass, response, gram, steps=40):
    """可微展开有界二次求解，每次原生参数评估都重新计算网格。"""
    from gpu_tensor import stencil_tensor
    from measured_response import get

    t = tools.torch
    model = get(response)
    nodes, weights = stencil_tensor(tools, model.coordinates_tensor(tools, rgb))
    mixing = model.response_tensor(tools, rgb) * 256
    # 对称正规算子的绝对行和构造对角上界，作为逐系数预条件。
    row_mass = (mixing.abs() * mixing.abs().sum(dim=1)[:, None, :]).sum(dim=2)
    contributions = weights[:, :, None] * (mass[:, None, None] * row_mass[:, None, :]) / 3
    bound = t.zeros((405, 3), device=tools.device, dtype=tools.dtype)
    bound = bound.index_add(0, nodes.reshape(-1), contributions.reshape(-1, 3))
    bound = bound + gram.abs().sum(dim=1).reshape(405, 3)
    step = 1 / (2 * bound + 1e-7)
    current = t.zeros_like(bound)
    extrapolated = current
    momentum = 1.
    for _ in range(steps):
        delta = (extrapolated[nodes] * weights[:, :, None]).sum(dim=1)
        prediction = rgb + t.einsum('nc,nco->no', delta, mixing)
        residual = (prediction - target) * mass[:, None] / 3
        local = t.einsum('no,nco->nc', residual, mixing)
        contributions = weights[:, :, None] * local[:, None, :]
        gradient = t.zeros_like(current).index_add(0, nodes.reshape(-1), contributions.reshape(-1, 3))
        gradient = 2 * (gradient + (gram @ extrapolated.reshape(-1)).reshape(405, 3))
        updated = (extrapolated - step * gradient).clamp(-64 / 256, 63 / 256)
        next_momentum = (1 + np.sqrt(1 + 4 * momentum**2)) / 2
        extrapolated = updated + (momentum - 1) / next_momentum * (updated - current)
        current, momentum = updated, next_momentum
    return current * 256


class ProfiledObjective(JointObjective):
    def table(self, controls, steps=40):
        native = self.native(controls)[:self.ntrain]
        return conditional_grid(self.tools, native, self.target, self.grid_mass,
                                self.response, self.gram * 256**2, steps)

    def profiled_loss(self, controls):
        native = self.native(controls)
        table = conditional_grid(self.tools, native[:self.ntrain], self.target, self.grid_mass,
                                 self.response, self.gram * 256**2)
        return self.loss(native, table, self.vector(controls), 30.)


def fit(reference, data, *, seconds=60, progress=None):
    """使用原厂上下文与训练灰阶启动，旧配方只提供验收界限。"""
    import core
    from adaptive_gpu import FitGuard
    from compute_backend import render_native
    from fit_anchor_native import SmoothNative, vector_for
    from fit_bin_joint import grid_from, projected
    from fit_native_proxy import curve_fit
    from gpu_runtime import available, cpu_reference
    from integer_grid import candidate_metrics, selection_failures
    from measured_response import get
    from patch_sampling import center_mean

    if not available():
        raise RuntimeError('核心联合拟合需要Metal/MPS')
    if not np.isfinite(seconds) or seconds <= 0:
        raise ValueError('核心求解预算必须为正数')
    started = time.perf_counter()
    deadline = started + seconds
    from edit_parameter_context import ParameterContext
    context = ParameterContext(data['context'].base,native_gamma=True)
    inputs, target, train = data['inputs'], data['target'], data['train']
    gray, valid, bank = data['gray'], data['validation'], data['bank']
    if valid[train].any() or not np.isin(np.flatnonzero(gray), train).all():
        raise ValueError('核心训练集与验证集必须独立')
    # 明暗初始化只读取训练灰阶，旧配方的Gamma、CC1、矩阵和网格均不作起点。
    initial = vector_for(context)
    gray_matrix = center_mean(context.base.matrix16(inputs[gray])) / 16383
    curve = curve_fit(gray_matrix, target[gray], context.axis / 128 / 16383)
    ordinates = np.maximum.accumulate(np.maximum(curve, 0)) * 16383
    initial[104:] = np.log(np.r_[np.maximum(np.diff(ordinates), 1.), max(16383 - ordinates[-1], 1.)])
    probes = bank.inputs(context.base)
    smooth = SmoothNative(context, np.concatenate((inputs[train], probes)))
    params = smooth.params(initial)
    native_model = context.build(**params)
    with cpu_reference():
        exact = center_mean(render_native(native_model, smooth.x)) / 16383
    objective = ProfiledObjective(smooth, initial, exact, target[train], np.ones(len(train)),
        np.flatnonzero(gray[train]), bank, np.zeros((405, 3), dtype=np.int8),
        data['response'], data['perceptual'], data['smoothing'], data['strength'])
    grid_mass = np.ones(len(train))
    grid_mass[gray[train]] = len(train) / (4 * int(gray.sum()))
    objective.grid_mass = objective.tools.tensor(grid_mass / grid_mass.sum())
    model = get(data['response'])
    reference_grid = grid_from(reference['entries'][0])
    reference_gray = model.predict_cpu(data['bin_base'][gray], reference_grid)
    reference_probes = model.predict_cpu(data['probe_base'], reference_grid)
    objective.guard = FitGuard(objective.tools, bank, reference_probes, reference_gray, target[gray])
    objective.continuity_limit = objective.continuity.loss(objective.tools.tensor(reference_probes)).detach()
    ncontrols = objective.basis.shape[1]
    records = []

    def loss(values):
        return objective.profiled_loss(values)

    def log(**event):
        records.append({key: value for key, value in event.items() if key != 'loss_sample'})
        if progress:
            progress(**event)

    values, optimization = solve((objective.tools, loss), np.zeros(ncontrols),
        [(-8., 8.)] * ncontrols, deadline - 4, 400, log,
        '核心联合拟合：原生参数搜索与内层网格重解')
    controls = objective.tools.tensor(values)
    vector = objective.vector(controls).detach().cpu().numpy().astype(float)
    with objective.torch.no_grad():
        continuous_table = objective.table(controls).cpu().numpy().astype(float)
    candidate = projected(reference['entries'][0], smooth.params(vector))
    candidate['grid_5x9x9'] = dict(coefficients=np.clip(np.rint(continuous_table), -64, 63)
                                 .astype(int).T.reshape(3, 5, 9, 9).tolist())
    config = core.compiler.config([candidate], core.compiler.format_version(reference))
    config = core.compiler.unpack(core.compiler.pack(config))
    measure = candidate_metrics(target[gray], target[valid], data['response'], bank,
                                data['strength'], data['perceptual'])
    baseline = measure(reference_grid, data['bin_base'][gray], data['bin_base'][valid], data['probe_base'])
    native_model = context.build(**core.slot_native_parameters(context, config['entries'][0]))
    with cpu_reference():
        bases = [center_mean(render_native(native_model, x)) / 16383 for x in
                 (inputs[gray], inputs[valid], bank.inputs(native_model))]
    metrics = measure(grid_from(config['entries'][0]), *bases)
    failures = selection_failures(metrics, baseline, baseline['color_score'])
    selected = copy.deepcopy(reference if failures else config)
    audit = dict(policy=POLICY, initialization='factory context + training gray only',
        old_fit_used_for_initialization=False, independent_grid_search_variables=0,
        outer_native_controls=ncontrols, inner_grid_coefficients=1215, inner_iterations=40,
        native_change_from_gray_initial_l2=float(np.linalg.norm(vector - initial)),
        inner_gradient='autograd through all projected iterations, coordinates and response',
        training_samples=len(train), validation_used_for_gradient=False, test_used_for_selection=False,
        backend='Apple Metal/MPS', optimization=optimization, stages=records,
        validation_before=baseline, validation_candidate=metrics, rejected_by=failures,
        selected='legacy' if failures else 'profiled', seconds=time.perf_counter() - started)
    return selected, config, audit
