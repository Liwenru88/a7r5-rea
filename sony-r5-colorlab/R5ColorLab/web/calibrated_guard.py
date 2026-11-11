"""为离线联合拟合校准双域约束和候选验收。"""
import colorsys
import hashlib

import numpy as np

from adaptive_gpu import FitGuard
from integer_grid import PROBE_AXES
from native_scoring import COLOR, PROTECTED, color_metrics
from output_continuity import ProbeBank
from perceptual import de2000, to_lab


# 预先固定上限。相位实验给出码值尺度的扰动估计，不给出人眼可见阈值。
CAPS = dict(gray_rmse=.05, delta_e00_p95=.05, ramp_p95=.05, peak=.75, local=.5)
PHASES = ((.25, .25, .25), (-.25, -.25, -.25), (.25, -.25, .25), (-.25, .25, -.25))


def phase_rgb(rgb, phase=0):
    """模拟小于半个 8 位码值的舍入边界变化。"""
    return np.floor(np.clip(np.asarray(rgb, float)*255+phase, 0, 255)+.5)/255


class SceneProtection:
    """对每个冻结的场景区域独立评分，使用原配方确定上限。"""

    def __init__(self, baseline, target, groups):
        if (baseline.ndim != 2 or baseline.shape[1] != 3 or baseline.shape != target.shape
                or not groups or not np.isfinite(target).all()):
            raise ValueError('照片保护需要非空、对齐的 RGB 和区域')
        self.target = phase_rgb(target) * 255
        self.target_lab = to_lab(self.target)
        self.groups = groups
        self.baseline = self.score(baseline)
        variations = [self.score(baseline, phase) for phase in PHASES]
        self.limits = {}
        for name, row in self.baseline.items():
            self.limits[name] = {}
            for key in ('delta_e00_mean', 'delta_e00_p95', 'rgb_rmse'):
                margin = max(abs(sample[name][key] - row[key]) for sample in variations)
                self.limits[name][key] = row[key] + min(.05, margin)

    def score(self, rgb, phase=0):
        if rgb.shape != self.target.shape or not np.isfinite(rgb).all():
            raise ValueError('照片输出与冻结的区域数据不一致')
        quantized = phase_rgb(rgb, phase) * 255
        delta = de2000(to_lab(quantized), self.target_lab)
        mse = np.mean((quantized - self.target)**2, axis=1)
        return {name: dict(samples=len(at), delta_e00_mean=float(delta[at].mean()),
                           delta_e00_p95=float(np.percentile(delta[at], 95)),
                           rgb_rmse=float(np.sqrt(mse[at].mean())))
                for name, at in self.groups.items()}

    def failures(self, metrics):
        return [f'{group}:{key}' for group, limits in self.limits.items()
                for key, limit in limits.items()
                if not np.isfinite(metrics[group][key]) or metrics[group][key] > limit + 1e-10]


def chroma_jumps(lines):
    return np.linalg.norm(np.diff(to_lab(lines*255)[..., 1:], n=2, axis=1), axis=2)


class RampBank:
    """连续渐变路径，以不同采样相位隔离校准、筛选和最终复验。"""

    inputs = ProbeBank.inputs

    def __init__(self, phase):
        if not 0 < phase < 1:
            raise ValueError('渐变采样相位必须位于 0 和 1 之间')
        positions = (np.arange(73)+phase)/73
        hues = (np.arange(12)+phase)/12
        levels = (.031+phase*.01, .19+phase*.04, .47+phase*.08, .81+phase*.06)
        ranges = ((.001, .135), (.145, .995))
        axes = {}
        for name, (lo, hi) in zip(PROBE_AXES[:2], ranges):
            axes[name] = [[(hue, saturation, lo+(hi-lo)*t) for t in positions]
                          for hue in hues for saturation in (.19, .49, .82)]
        axes['hue'] = [[((t+offset)%1, saturation, value) for t in positions]
                       for offset in (0., .19) for saturation in (.29, .66, .88) for value in levels]
        axes['saturation'] = [[(hue, .02+.95*t, value) for t in positions]
                              for hue in hues for value in levels]
        gray = [[(0., 0., .002+.993*t) for t in positions]]
        single = []
        self.sections = {}
        offset = 0
        for name, lines in (*axes.items(), ('gray', gray)):
            rgb = np.asarray([[colorsys.hsv_to_rgb(*point) for point in line] for line in lines])
            flat = rgb.reshape(-1, 3)
            self.sections[name] = (slice(offset, offset+len(flat)), rgb.shape[:2])
            single.append(flat)
            offset += len(flat)
        self.domain_size = offset
        self.rgb = np.tile(np.concatenate(single), (2, 1))
        self.sha256 = hashlib.sha256(self.rgb.tobytes()).hexdigest()

    def span(self, axis):
        native = axis.startswith('native-')
        section, shape = self.sections[axis.removeprefix('native-')]
        offset = self.domain_size if native else 0
        return slice(section.start+offset, section.stop+offset), shape

    def lines(self, rgb, axis):
        section, shape = self.span(axis)
        return np.asarray(rgb)[section].reshape(*shape, 3)

    def jumps(self, rgb):
        return {axis: chroma_jumps(self.lines(rgb, axis)) for axis in PROBE_AXES}


def calibrate(bank, rendered, photos):
    """用原配方输出和独立照片估计各项容差，先于候选训练冻结。"""
    if not photos:
        raise ValueError('至少需要一张独立校准照片')
    rounded = phase_rgb(rendered)
    reference = bank.jumps(rounded)
    variants = [bank.jumps(phase_rgb(rendered, phase)) for phase in PHASES]
    gray_margins = []
    for axis in ('gray', 'native-gray'):
        gray = bank.lines(rendered, axis)
        rmse = lambda value: float(np.sqrt(np.mean(((value-gray)*255)**2)))
        base = rmse(phase_rgb(gray))
        gray_margins.extend(abs(rmse(phase_rgb(gray, phase))-base) for phase in PHASES)
    photo_rows = []
    for scene, photo, target in photos:
        original = color_metrics(photo, target)
        differences = [abs(color_metrics(phase_rgb(photo, phase), target)['delta_e00_p95']
                           -original['delta_e00_p95']) for phase in PHASES]
        photo_rows.append(dict(scene=scene, samples=len(target), baseline=original, p95_span=max(differences)))
    measured = {}
    axes = {}
    for axis, jumps in reference.items():
        pointwise = np.concatenate([np.abs(value[axis]-jumps).ravel() for value in variants])
        observed = dict(p95=max(abs(np.percentile(value[axis], 95)-np.percentile(jumps, 95)) for value in variants),
                        peak=float(np.percentile(pointwise, 99.9)), local=float(np.percentile(pointwise, 99)))
        measured[axis] = {key: float(value) for key, value in observed.items()}
        axes[axis] = dict(p95=min(CAPS['ramp_p95'], observed['p95']),
                          peak=min(CAPS['peak'], observed['peak']),
                          local=min(CAPS['local'], observed['local']))
    gray = max(gray_margins)
    p95 = max(row['p95_span'] for row in photo_rows)
    return dict(gray_rmse=min(gray, CAPS['gray_rmse']), delta_e00_p95=min(p95, CAPS['delta_e00_p95']),
                axes=axes, measured=dict(gray_rmse=gray, delta_e00_p95=p95, axes=measured),
                photos=photo_rows, caps=CAPS, phases=PHASES, ramp_sha256=bank.sha256)


def metric_failures(metrics, baseline, margins):
    if any(not np.isfinite(metrics.get(name, np.nan)) for name in (*PROTECTED, *COLOR, 'color_score')):
        return ['nonfinite_or_missing_metrics']
    failures = [name for name in COLOR if metrics[name] >= baseline[name]-1e-10]
    for name in ('gray_rmse', 'delta_e00_p95'):
        if metrics[name] > baseline[name]+margins[name]+1e-10:
            failures.append(name)
    for axis, limits in margins['axes'].items():
        for stat, bound in (('p95', limits['p95']), ('max', limits['peak'])):
            name = f'{axis}_{stat}'
            if metrics[name] > baseline[name]+bound+1e-10:
                failures.append(name)
    return failures


def ramp_report(baseline, candidate, margins):
    """保留单点严重突变和同一渐变路径连续异常的否决。"""
    results = {}
    failures = []
    for axis, start in baseline.items():
        end = candidate[axis]
        if start.shape != end.shape or not np.isfinite(end).all():
            raise ValueError('独立渐变的形状或数值无效')
        limits = margins['axes'][axis]
        increase = end-start
        p95 = float(np.percentile(end, 95)-np.percentile(start, 95))
        peak = float(increase.max())
        over = increase > limits['local']+1e-10
        clusters = over[:, :-2] & over[:, 1:-1] & over[:, 2:]
        results[axis] = dict(p95_increase=p95, peak_local_increase=peak,
                             over_local=int(over.sum()), runs_of_three=int(clusters.sum()))
        for check, failed in (('p95', p95 > limits['p95']+1e-10),
                              ('peak', peak > limits['peak']+1e-10), ('cluster', clusters.any())):
            if failed:
                failures.append(f'ramp:{axis}:{check}')
    return results, failures


class CalibratedTrainingGuard(FitGuard):
    """每步用固定训练探针约束两个域的尾部色度跳变。"""

    def __init__(self, tools, bank, baseline_probes, baseline_gray, gray_target, margins):
        super().__init__(tools, bank, baseline_probes, baseline_gray, gray_target)
        torch = tools.torch
        self.gray_limit = (self.gray_limit.sqrt()+margins['gray_rmse']/255).square()
        self.limits = []
        with torch.no_grad():
            baseline = self.jumps(tools.tensor(baseline_probes))
            for (axis, count), (section, _, weight) in zip(bank.groups, self.axes):
                size = max(1, int(np.ceil(count*.05)))
                top = torch.topk(baseline[section], size).values
                axis_margin = margins['axes'][axis]
                self.limits.append((section, weight, size,
                    top.mean()+axis_margin['p95']/100, top.max()+axis_margin['peak']/100))

    def loss(self, gray, probes):
        torch = self.tools.torch
        loss = super().loss(gray, probes)
        jumps = self.jumps(probes)
        for section, weight, size, tail_limit, peak_limit in self.limits:
            tail = torch.topk(jumps[section], size).values
            loss = loss + weight*(2*(tail.mean()-tail_limit).clamp(min=0).square()
                                 + .1*(tail.max()-peak_limit).clamp(min=0).square())
        return loss


class FocusedRampLoss:
    """用单独采样的渐变对指定轴施加可微的 P95 与尾部约束。"""

    def __init__(self, tools, groups, baseline, margins):
        self.tools = tools
        self.groups = []
        offset = 0
        with tools.torch.no_grad():
            for axis, (lines, samples) in groups:
                end = offset+lines*samples
                span = slice(offset, end)
                size = lines*(samples-2)
                position = (size-1)*.95
                lower = int(np.floor(position))
                count = size-lower
                fraction = position-lower
                p95, tail = self.tail(tools.tensor(baseline[span]), (lines, samples), count, fraction)
                reserve = margins['axes'][axis]['p95']*.25
                self.groups.append((span, (lines, samples), count, fraction, p95+reserve, tail+reserve))
                offset = end
        if not self.groups or offset != len(baseline):
            raise ValueError('定向训练渐变与基准行数不一致')
        self.length = offset

    def tail(self, rgb, shape, count, fraction):
        torch = self.tools.torch
        lab = self.tools.lab(rgb).reshape(*shape, 3)[..., 1:]
        curvature = lab[:, 2:]-2*lab[:, 1:-1]+lab[:, :-2]
        norm = (curvature.square().sum(dim=-1)+1e-12).sqrt()
        top = torch.topk(norm.flatten(), count).values
        quantile = top[-1] if not fraction else (1-fraction)*top[-1]+fraction*top[-2]
        return quantile, top.mean()

    def __call__(self, predicted):
        rgb = predicted[-self.length:]
        loss = rgb.new_zeros(())
        for span, shape, count, fraction, p95_limit, tail_limit in self.groups:
            p95, tail = self.tail(rgb[span], shape, count, fraction)
            loss = loss + .4*(p95-p95_limit).clamp(min=0).square()
            loss = loss + .1*(tail-tail_limit).clamp(min=0).square()
        return loss / len(self.groups)
