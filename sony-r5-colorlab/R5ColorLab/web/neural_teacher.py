"""训练端连续颜色教师；参数不进入相机BIN。"""
import copy
import time

import numpy as np

POLICY = 'continuous-color-teacher/1'


def color_metrics(predicted, target):
    from perceptual import de2000, to_lab
    p, t = [np.floor(np.clip(v, 0, 1) * 255 + .5) for v in (predicted, target)]
    de = de2000(to_lab(p), to_lab(t))
    return dict(rgb_rmse=float(np.sqrt(np.mean((p-t)**2))),
                delta_e00_mean=float(de.mean()), delta_e00_p95=float(np.percentile(de, 95)))


def create_model(seed=42):
    import torch
    from torch import nn

    class ColorTeacher(nn.Module):
        def __init__(self):
            super().__init__()
            self.net = nn.Sequential(nn.Linear(3, 96), nn.SiLU(), nn.Linear(96, 96),
                                     nn.SiLU(), nn.Linear(96, 3))
            nn.init.zeros_(self.net[-1].weight)
            nn.init.zeros_(self.net[-1].bias)

        def forward(self, rgb):
            shaped = torch.log1p(31 * rgb.clamp(min=0)) / np.log(32)
            return shaped + self.net(shaped * 2 - 1)

    with torch.random.fork_rng(devices=[]):
        torch.random.default_generator.manual_seed(seed)
        return ColorTeacher()


def fit(inputs, target, train, gray, validation, bank, probe_inputs, baseline_probes,
        baseline_gray, limits, strength, perceptual, progress=None, *, steps=2000,
        guard_steps=1000, device='mps'):
    """只使用训练样本反传，验证集选择受保护教师；测试集不传入此入口。"""
    import torch
    from adaptive_gpu import FitGuard
    from gpu_tensor import TensorTools
    from integer_grid import guard_failures, transition_metrics
    from joint_fit import delta_e_squared
    from output_continuity import TensorPenalty

    started = time.perf_counter()
    tools = TensorTools(device)
    model = create_model().to(device)
    x, y = tools.tensor(inputs), tools.tensor(target)
    ids = tools.tensor(train, True)
    gray_ids = tools.tensor(np.flatnonzero(gray), True)
    valid_ids = tools.tensor(np.flatnonzero(validation), True)
    tx, ty, vy = x[ids], y[ids], y[valid_ids]
    train_lab, valid_lab = tools.lab(ty), tools.lab(vy)
    optimizer = torch.optim.Adam(model.parameters(), lr=.002)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, steps, eta_min=.0002)
    best_score, initial_state = float('inf'), None
    best_train_loss = float('inf')
    trace = []

    def color_loss(prediction, desired, lab):
        return (prediction-desired).square().mean() + perceptual * .0001 * delta_e_squared(
            tools, tools.lab(prediction.clamp(0, 1)), lab).mean()

    for step in range(steps):
        optimizer.zero_grad(set_to_none=True)
        loss = color_loss(model(tx), ty, train_lab)
        if not bool(torch.isfinite(loss)):
            raise ValueError('神经教师产生非有限损失')
        current_loss=float(loss.detach().cpu())
        best_train_loss=min(best_train_loss,current_loss)
        loss.backward()
        optimizer.step()
        scheduler.step()
        if step == 0 or (step+1) % 100 == 0:
            with torch.no_grad():
                score = float(color_loss(model(x[valid_ids]).clamp(0, 1), vy, valid_lab).cpu())
            if score < best_score:
                best_score, initial_state = score, copy.deepcopy(model.state_dict())
            trace.append(dict(stage='color', step=step+1, validation_score=score))
            if progress:
                progress(stage='神经教师：学习连续颜色映射', state='running',
                    loss_sample=('teacher-Adam', step+1, current_loss, best_train_loss))
    model.load_state_dict(initial_state)
    guard = FitGuard(tools, bank, baseline_probes, baseline_gray, target[gray])
    continuity = TensorPenalty(bank, tools, strength)
    continuity_limit = continuity.loss(tools.tensor(baseline_probes)).detach()
    probes = tools.tensor(probe_inputs)
    optimizer = torch.optim.Adam(model.parameters(), lr=.0005)
    selected_state, selected_metrics, selected_cost = None, None, float('inf')
    best_guard_loss=float('inf')
    for step in range(guard_steps+1):
        optimizer.zero_grad(set_to_none=True)
        predicted = model(tx)
        gray_rgb, probe_rgb = model(x[gray_ids]).clamp(0, 1), model(probes).clamp(0, 1)
        penalty = guard.loss(gray_rgb, probe_rgb)
        penalty = penalty + 10 * ((gray_rgb-y[gray_ids]).square().mean()-guard.gray_limit).clamp(min=0)
        penalty = penalty + (continuity.loss(probe_rgb)-continuity_limit).clamp(min=0)
        loss = color_loss(predicted, ty, train_lab) + 30 * penalty
        if not bool(torch.isfinite(loss)):
            raise ValueError('受约束教师产生非有限损失')
        current_loss=float(loss.detach().cpu())
        best_guard_loss=min(best_guard_loss,current_loss)
        if step % 100 == 0 or step == guard_steps:
            with torch.no_grad():
                valid_rgb = model(x[valid_ids]).clamp(0, 1).cpu().numpy()
            metrics = color_metrics(valid_rgb, target[validation])
            metrics['gray_rmse'] = color_metrics(gray_rgb.detach().cpu().numpy(), target[gray])['rgb_rmse']
            metrics.update(transition_metrics(bank, probe_rgb.detach().cpu().numpy(), strength))
            failures = guard_failures(metrics, limits)
            cost = metrics['rgb_rmse']**2 + perceptual * (2.55*metrics['delta_e00_mean'])**2
            trace.append(dict(stage='guard', step=step, metrics=metrics, rejected_by=failures))
            if not failures and cost < selected_cost:
                selected_state, selected_metrics, selected_cost = copy.deepcopy(model.state_dict()), metrics, cost
            if progress:
                progress(stage='神经教师：灰阶与双域过渡约束', state='running',
                    loss_sample=('guarded-teacher-Adam', step, current_loss, best_guard_loss))
        if step < guard_steps:
            loss.backward()
            optimizer.step()
    accepted = selected_state is not None
    model.load_state_dict(selected_state if accepted else initial_state)
    model.eval()
    with torch.no_grad():
        # 学生只拿到训练样本上的教师值，验证和测试目标始终不参与蒸馏梯度。
        prediction = model(tx).clamp(0, 1).detach()
    return prediction, dict(policy=POLICY, accepted=accepted, validation=selected_metrics,
        architecture=[3, 96, 96, 3], seed=42, steps=steps, guard_steps=guard_steps,
        backend=device, full_batch=True, trace=trace, seconds=time.perf_counter()-started,
        validation_used_for_gradient=False, test_used_for_selection=False)
