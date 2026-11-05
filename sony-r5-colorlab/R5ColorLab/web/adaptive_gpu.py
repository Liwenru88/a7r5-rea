"""在 GPU 求解期间限制灰阶误差与两个输入域的色度跳变。"""
import numpy as np
from scipy.optimize import minimize

from apple_gpu import SmoothGPU
from compressed_alternation import CompressedGridObjective
from gpu_tensor import TensorTools


class FitGuard:
    def __init__(self, tools, bank, baseline_probes, baseline_gray, gray_target):
        self.tools = tools
        self.at = tools.tensor(bank.triplets, integer=True)
        self.mix = tools.tensor(bank.mix)
        self.gray_target = tools.tensor(gray_target)
        self.gray_limit = (tools.tensor(baseline_gray)-self.gray_target).square().mean()
        with tools.torch.no_grad():
            original = self.jumps(tools.tensor(baseline_probes))
        self.axes = []
        offset = 0
        for name, size in bank.groups:
            section = slice(offset, offset+size)
            base = original[section]
            allowance = tools.tensor(bank.allowance[section]) / 100
            # 每组分别处理；用基准尾部和探针容差约束新跳变，双域饱和度权重更高。
            ceiling = tools.torch.minimum(base.max(), tools.torch.maximum(base, allowance))
            self.axes.append((section, ceiling, 4. if name.endswith('saturation') else 1.))
            offset += size

    def jumps(self, rgb):
        lab = self.tools.lab(rgb.clamp(0, 1))[:, 1:] / 100
        a, b, c = lab[self.at].unbind(1)
        return self.tools.torch.linalg.vector_norm(2*(b-a*(1-self.mix)-c*self.mix), dim=1)

    def loss(self, gray, probes):
        excess_gray = ((gray.clamp(0, 1)-self.gray_target).square().mean()-self.gray_limit).clamp(min=0)
        jumps = self.jumps(probes)
        # 二次罚项在边界连续，避免优化器从灰阶基准出发就被硬折点卡住。
        loss = .25*excess_gray.square() / (self.gray_limit + 1e-4)
        for section, ceiling, weight in self.axes:
            excess = (jumps[section]-ceiling).clamp(min=0).square()
            loss = loss + weight*(.25*excess.mean()+.01*excess.max())
        return loss


class GuardedMatrixObjective(CompressedGridObjective):
    def __init__(self, smooth, target, weights, initial, grid, response, perceptual,
                 smoothing, *, bank, probe_smooth, gray_rows, baseline_gray, baseline_probes):
        super().__init__(smooth, target, weights, initial, grid, response, perceptual, smoothing)
        self.probe_gpu = SmoothGPU(probe_smooth, device=self.gpu.device)
        self.gray_rows = self.gpu.tensor(gray_rows, integer=True)
        self.guard = FitGuard(self.gpu, bank, baseline_probes, baseline_gray,
                              np.asarray(target)[gray_rows]/16383)
        # 用整数基准对齐浮点渲染器，只由浮点模型估计每次矩阵改动的增量。
        with self.torch.no_grad():
            initial = self.gpu.tensor(initial)
            self.gray_offset = self.gpu.tensor(baseline_gray)-self.render_gray(initial)
            self.probe_offset = self.gpu.tensor(baseline_probes)-self.render_probes(initial)

    def render_gray(self, vector):
        return self.corrected(self.gpu.render(vector)[self.gray_rows]/16383)

    def render_probes(self, vector):
        return self.corrected(self.probe_gpu.render(vector)/16383)

    def loss(self, vector):
        predicted = self.corrected(self.gpu.render(vector)/16383)
        constraint = self.guard.loss(predicted[self.gray_rows]+self.gray_offset,
                                     self.render_probes(vector)+self.probe_offset)
        return self.data_loss(predicted) + self.smoothing_loss(vector) + constraint


def fit_grid(base, target, weights, grid, response, strength, perceptual, *,
             bank, gray_rows, probes, baseline_gray, baseline_probes):
    """从基准整数网格热启动，在拟合过程中约束灰阶和过渡。"""
    from grid_regularization import get_penalty
    from measured_response import get

    tools = TensorTools()
    model = get(response)
    source = np.concatenate((base, probes))
    _, nodes, interpolation = model.stencil(source)
    x, ids = tools.tensor(source), tools.tensor(nodes, integer=True)
    w, mixing = tools.tensor(interpolation), tools.tensor(model.response(source)*256)
    desired, mass = tools.tensor(target), tools.tensor(weights/weights.sum())
    desired_lab = tools.lab(desired)
    gram = tools.tensor(get_penalty(response).dense_gram * (256**2*strength))
    guard = FitGuard(tools, bank, baseline_probes, baseline_gray, target[gray_rows])
    gray_ids = tools.tensor(gray_rows, integer=True)
    initial = grid.astype(float).ravel()/256
    before = None

    def value_gradient(values):
        nonlocal before
        v = tools.tensor(values).requires_grad_(True)
        delta = (v.reshape(405, 3)[ids]*w[:, :, None]).sum(dim=1)
        rgb = (x+tools.torch.einsum('nc,nco->no', delta, mixing)).clamp(0, 1)
        predicted = rgb[:len(base)]
        error = (predicted-desired).square().mean(dim=1)
        error = error+perceptual*((tools.lab(predicted)-desired_lab)/100).square().sum(dim=1)
        loss = (mass @ error) + v @ gram @ v + guard.loss(rgb[gray_ids], rgb[len(base):])
        gradient, = tools.torch.autograd.grad(loss, v)
        score = float(loss.detach().cpu())
        grad = gradient.detach().cpu().numpy().astype(float)
        if not np.isfinite(score) or not np.isfinite(grad).all():
            raise ValueError('Nonfinite constrained grid loss or gradient')
        if before is None:
            before = score
        return score, grad

    result = minimize(value_gradient, initial, jac=True, method='L-BFGS-B',
                      bounds=[(-64/256, 63/256)]*len(initial),
                      options=dict(maxiter=42, maxfun=52, ftol=1e-10))
    values = result.x if result.fun < before else initial
    return np.clip(np.rint(values.reshape(405, 3)*256), -64, 63).astype(np.int8), dict(
        evaluations=result.nfev, loss_before=before, loss_after=float(min(result.fun, before)))
