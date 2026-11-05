"""使用训练色块生成 RGB 残差或整数网格提案。"""
import numpy as np


def fit_residual(native, current, target, *, seed=42, steps=768):
    import torch
    from torch import nn
    from gpu_runtime import available

    device = torch.device('mps' if available() else 'cpu')
    order = np.random.default_rng(seed)
    # 把初始化的随机状态限制在当前训练，批次顺序由局部生成器固定。
    with torch.random.fork_rng(devices=[]):
        torch.random.default_generator.manual_seed(seed)
        model = nn.Sequential(nn.Linear(3, 48), nn.SiLU(), nn.Linear(48, 48),
                              nn.SiLU(), nn.Linear(48, 3))
        nn.init.zeros_(model[-1].weight)
        nn.init.zeros_(model[-1].bias)
    model.to(device)
    x = torch.as_tensor(native, dtype=torch.float32, device=device)*2-1
    residual = torch.as_tensor((target-current)*8, dtype=torch.float32, device=device)
    optimizer = torch.optim.AdamW(model.parameters(), lr=.002, weight_decay=1e-4)
    model.train()
    for _ in range(steps):
        indices = torch.as_tensor(order.integers(len(native), size=1024), device=device)
        optimizer.zero_grad(set_to_none=True)
        loss = torch.nn.functional.smooth_l1_loss(model(x[indices]), residual[indices], beta=.1)
        loss.backward()
        optimizer.step()
    model.eval()
    with torch.inference_mode():
        correction = model(x).cpu().numpy()/8
    if not np.isfinite(correction).all():
        raise ValueError('神经残差拟合产生非有限结果')
    prediction = np.clip(current+correction, 0, 1)
    return prediction, dict(architecture=[3,48,48,3], activation='SiLU', device=device.type,
        seed=seed, steps=steps, batch_size=1024, train_samples=len(native),
        current_rgb_rmse=float(255*np.sqrt(np.mean((target-current)**2))),
        neural_rgb_rmse=float(255*np.sqrt(np.mean((target-prediction)**2))))


def fit_grid_update(native, target, table, response, gray_mask, saturation_probes, *,
                    seed=42, steps=320, deadline=None):
    """用节点坐标预测三通道增量，在网格插值和颜色响应之后计算训练损失。"""
    import torch
    from time import perf_counter
    from torch import nn
    from gpu_runtime import available
    from measured_response import get
    from perceptual import to_lab

    device = torch.device('mps' if available() else 'cpu')
    order = np.random.default_rng(seed)
    with torch.random.fork_rng(devices=[]):
        torch.random.default_generator.manual_seed(seed)
        network = nn.Sequential(nn.Linear(3,48), nn.SiLU(), nn.Linear(48,48),
                                nn.SiLU(), nn.Linear(48,3))
        nn.init.zeros_(network[-1].weight)
        nn.init.zeros_(network[-1].bias)
    network.to(device)
    optimizer = torch.optim.AdamW(network.parameters(), lr=.003, weight_decay=1e-4)

    def tensor(value, dtype=torch.float32):
        return torch.as_tensor(value, dtype=dtype, device=device)

    coords = np.stack(np.meshgrid(*(np.linspace(-1,1,n) for n in (5,9,9)), indexing='ij'), -1)
    nodes = tensor(coords.reshape(405,3))
    initial = tensor(table)
    model = get(response)
    probe_colors, triplets, allowance = saturation_probes
    colors = np.concatenate((native, probe_colors))
    _, index, interp = model.stencil(colors)
    indices, weights, mixing = tensor(index, torch.long), tensor(interp), tensor(model.response(colors))
    source, desired = tensor(colors), tensor(target)
    gray = np.flatnonzero(gray_mask)
    gray_target = desired[tensor(gray, torch.long)]
    reference = model.predict_cpu(probe_colors, table)
    chroma = to_lab(reference*255)[:, 1:]
    # 在本轮起点线性化 Lab 色度，将代价较高的色彩转换移出训练循环。
    epsilon = 1e-4
    jacobian = np.stack([(to_lab((reference+offset)*255)[:, 1:]-chroma)/epsilon
                         for offset in np.eye(3)*epsilon], axis=1)
    reference, chroma, jacobian = map(tensor, (reference, chroma, jacobian))

    def curvature(rgb):
        a, b, c = rgb.unbind(dim=1)
        return 2*b-a-c

    samples = order.integers(len(native), size=(steps,1024))
    probes = order.integers(len(triplets), size=(steps,192))
    probe_ids = tensor(triplets[probes], torch.long)
    rows = tensor(np.concatenate((samples, np.tile(gray, (steps,1)),
        triplets[probes].reshape(steps,-1)+len(native)), axis=1), torch.long)
    batch_target = desired[tensor(samples, torch.long)]
    limits = tensor(allowance[probes])
    max_update = 8
    completed = 0
    for step in range(steps):
        if deadline is not None and step % 16 == 0:
            if device.type == 'mps':
                torch.mps.synchronize()
            if perf_counter() >= deadline:
                break
        at, ids = rows[step], probe_ids[step]
        optimizer.zero_grad(set_to_none=True)
        continuous = (initial + max_update*network(nodes).tanh()).clamp(-64, 63)
        quantized = continuous + (continuous.round()-continuous).detach()
        stencil = indices.index_select(0, at)
        values = quantized.index_select(0, stencil.flatten()).reshape(*stencil.shape, 3)
        delta = (values*weights.index_select(0, at)[..., None]).sum(dim=1)
        prediction = (source.index_select(0, at) +
                      (delta[..., None]*mixing.index_select(0, at)).sum(dim=1)).clamp(0,1)
        color_rgb, gray_rgb, probe_rgb = prediction.split((1024,len(gray),ids.numel()))
        color = ((color_rgb-batch_target[step])*255).square().mean()
        gray_error = ((gray_rgb-gray_target)*255).square().mean()
        anchor_rgb = reference[ids]
        change = probe_rgb.reshape_as(anchor_rgb)-anchor_rgb
        anchor = chroma[ids]
        base_bend = curvature(anchor)
        bend = base_bend + curvature((change[..., None]*jacobian[ids]).sum(dim=-2))
        ceiling = torch.maximum(limits[step], base_bend.norm(dim=1))
        excess = (bend.norm(dim=1)-ceiling).clamp(min=0)
        loss = (color + 4*gray_error + 12*excess.square().mean()
                + 8*(255*curvature(change)).square().mean() + .01*(continuous-initial).square().mean())
        loss.backward()
        optimizer.step()
        completed += 1

    network.eval()
    with torch.inference_mode():
        updated = (initial + max_update*network(nodes).tanh()).clamp(-64,63).round().cpu().numpy()
    if not np.isfinite(updated).all():
        raise ValueError('神经网格训练产生非有限系数')
    return updated.astype(np.int8), dict(architecture=[3,48,48,3], input='grid node coordinates',
        device=device.type, seed=seed, steps=completed, batch_size=1024, train_samples=len(native),
        max_update=max_update, forward_quantized=True, gray_anchors=len(gray), saturation_triplets=len(triplets),
        gray_loss_weight=4, saturation_loss='RGB curvature and linearized Lab chroma excess',
        changed_coefficients=int(np.count_nonzero(updated!=table)))
