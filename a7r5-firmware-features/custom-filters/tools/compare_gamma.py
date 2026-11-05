#!/usr/bin/env python3
"""固定ST/context4的三tone与完整Gamma宿主数值对照；不导出机身滤镜。"""
from __future__ import annotations

import argparse
import ctypes as c
import hashlib
import json
import math
import os
from pathlib import Path
import sys
import time

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))
import fit_recipe

CURVE = c.c_uint32 * 129
FitError = fit_recipe.FitError
FitCancelled = fit_recipe.FitCancelled


def bind(solver):
    api = solver.api
    api.desktop_gamma_seed.argtypes = [c.c_void_p] * 5
    api.desktop_gamma_source.argtypes = [c.c_void_p, c.c_void_p]
    for name in ('desktop_gamma_loss', 'desktop_gamma_report'):
        getattr(api, name).argtypes = [c.c_void_p] * 4 + [c.c_uint, c.c_void_p]
    api.af_edit_cp_gamma.argtypes = [c.c_void_p, c.c_size_t, c.c_void_p, c.c_size_t,
                                    c.c_void_p, c.c_void_p, c.c_void_p]
    return solver


def seed(solver, vector, grid):
    curve, axis = CURVE(), CURVE()
    fit_recipe._check(solver.api.desktop_gamma_seed(
        solver.state, solver.vector(*vector), fit_recipe.GRID(*grid), curve, axis))
    return list(curve), list(axis)


def expand_curve(baseline, axis, controls):
    """17个可调结点加固定原点；按原非均匀轴采样，最后显式重建61440。"""
    if len(baseline) != 129 or len(axis) != 129 or len(controls) != 17:
        raise FitError('曲线／横轴／控制点长度不匹配')
    if axis[0] != 0 or axis[127:] != [61440, 65535] or any(
            a >= b for a, b in zip(axis, axis[1:])):
        raise FitError('不是固定ST的非均匀横轴')
    if any(type(x) is not int or not -16384 <= x <= 16384 for x in controls):
        raise FitError('完整曲线控制量须为±16384内的整数')
    knots = [0] + [(65535 * i + 8) // 17 for i in range(1, 18)]
    values = [0] + list(controls)
    curve, left = [], 0
    for i, x in enumerate(axis):
        while left < 16 and x > knots[left + 1]:
            left += 1
        width = knots[left + 1] - knots[left]
        numerator = values[left] * width + (values[left + 1] - values[left]) * (x - knots[left])
        # 有符号四舍五入在Python中显式定义，随后所有候选均经真实C校验和预测。
        delta = (abs(numerator) + width // 2) // width
        delta = -delta if numerator < 0 else delta
        curve.append(max(0, min(131071, baseline[i] + delta)))
    curve[0] = 0
    width, offset = axis[128] - axis[126], axis[127] - axis[126]
    edit_y = 2 * curve[126] + 2 * (curve[128] - curve[126]) * offset // width
    curve[127] = (edit_y + 1) // 2
    return curve


def compare(solver, cube, *, additional_budget=96, cancel=None, progress=None):
    """两臂独立使用同一额外评估预算；test只在两臂选择冻结之后计算。"""
    if type(additional_budget) is not int or not 16 <= additional_budget <= 16384:
        raise FitError('额外预算须为16～16384')
    if not isinstance(cube, bytes) or not 0 < len(cube) <= 4 * 1024 * 1024:
        raise FitError('CUBE须为4MiB内的字节')
    bind(solver)
    began = time.monotonic()
    tool_sha = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()

    def check_cancel(stage):
        if cancel and cancel():
            raise FitCancelled('对照已取消，未发布结果')
        if progress:
            progress(stage)

    check_cancel('原257候选联合基准')
    raw = c.create_string_buffer(cube)
    fit_recipe._check(solver.api.desktop_load_cube(solver.state, raw, len(cube)))
    vector, grid = solver.vector(), fit_recipe.GRID()
    interrupted = []

    def callback(_, done, total):
        try:
            return int(bool(cancel and cancel()))
        except BaseException as error:
            interrupted.append(error)
            return 1

    status = solver.api.desktop_baseline(solver.state, vector, grid, fit_recipe.PROGRESS(callback))
    if interrupted or status == -20:
        raise FitCancelled('基准拟合已取消，未发布结果')
    fit_recipe._check(status)
    base_vector, base_grid = list(vector), list(grid)
    baseline_curve, axis = seed(solver, base_vector, base_grid)
    histories = {}

    def search(kind):
        used, rejected = 0, 0
        current = base_vector[:3] if kind == 'three_tone' else [0] * 17
        selected = current[:]
        count = len(current)
        steps = (16, 8, 4, 2, 1) if kind == 'three_tone' else (1024, 512, 256, 128, 64, 32, 16)
        schedule = [(i, sign, step) for step in steps for i in range(count) for sign in (1, -1)]
        at = 0
        history = []

        def loss(candidate, split):
            nonlocal used, rejected
            check_cancel(kind)
            used += 1
            result = (c.c_double * 2)()
            v = base_vector[:]
            if kind == 'three_tone':
                v[:3] = candidate
                status = solver.api.desktop_loss(solver.state, solver.vector(*v), grid, split, result)
            else:
                curve = CURVE(*expand_curve(baseline_curve, axis, candidate))
                status = solver.api.desktop_gamma_loss(
                    solver.state, vector, grid, curve, split, result)
            if status in (-21, -1):
                rejected += 1
                return math.inf, math.inf
            fit_recipe._check(status)
            if not all(math.isfinite(x) for x in result):
                raise FitError('模型返回非有限误差')
            return tuple(result)

        best_train = loss(current, 0)
        best_selection = loss(selected, 1)
        initial_train, initial_selection = best_train, best_selection
        if not all(math.isfinite(x) for x in best_train + best_selection):
            raise FitError('固定基准在参考模型中不可表示')
        # 等额预算包括训练和选优调用；选优频率不随控制维数改变。
        interval = max(4, additional_budget // 8)
        while used < additional_budget:
            if used == additional_budget - 1 or used % interval == interval - 1:
                score = loss(current, 1)
                if score < best_selection:
                    best_selection, selected = score, current[:]
                history.append({'evaluations': used, 'selection_mse': score[0] if math.isfinite(score[0]) else None})
                continue
            index, sign, step = schedule[at % len(schedule)]
            at += 1
            trial = current[:]
            bound = 1024 if kind == 'three_tone' else 16384
            trial[index] = max(-bound, min(bound, trial[index] + sign * step))
            score = loss(trial, 0)
            if score < best_train:
                best_train, current = score, trial
        histories[kind] = history
        return {'controls': selected, 'evaluations': used, 'rejected': rejected,
                'baseline_training_mse': initial_train[0], 'baseline_selection_mse': initial_selection[0],
                'selected_selection_mse': best_selection[0]}

    tone = search('three_tone')
    full = search('full_gamma')
    check_cancel('冻结两臂，最终独立测试')
    tone_vector = base_vector[:]
    tone_vector[:3] = tone['controls']
    tone_curve, _ = seed(solver, tone_vector, base_grid)
    full_curve = expand_curve(baseline_curve, axis, full['controls'])

    def report(curve):
        check_cancel('最终独立测试')
        output = (c.c_double * 8)()
        fit_recipe._check(solver.api.desktop_gamma_report(
            solver.state, vector, grid, CURVE(*curve), 2, output))
        return {'samples': int(output[0]), 'clipped': int(output[1]),
                'delta_e76': list(output[2:7]), 'rgb_rmse': output[7]}

    # 以下3次报告全部发生在选择冻结后；不以测试表现重选、续搜或调整预算。
    baseline_test, tone_test, full_test = map(report, (baseline_curve, tone_curve, full_curve))
    result = {
        'schema': 'a7r5-gamma-comparison/1', 'research_only': True, 'camera_apply_allowed': False,
        'scope': '固定ST/context4整数参考链＋固定PT经验残差；不是EVF/JPG或实拍误差',
        'matrix_sectors': solver.matrix_sectors, 'baseline_optimizer': '同源原257候选联合拟合',
        'baseline_budget': 257, 'additional_budget_per_arm': additional_budget,
        'fixed_controls': base_vector, 'fixed_grid_hex': bytes(x & 255 for x in base_grid).hex(),
        'frozen_components': ['matrix', 'cc1', 'grid'],
        'three_tone': {**tone, 'test': tone_test}, 'full_gamma': {**full, 'test': full_test},
        'baseline_test': baseline_test, 'splits': solver.splits,
        'test_used_for_selection': False, 'test_reports_per_candidate': 1,
        'optimizer': '有界整数坐标搜索；训练接受、独立selection选优；两臂等额预算',
        'full_gamma_policy': {'cp_points': 129, 'adjustable_knots': 17,
                              'fixed_origin': 0, 'reconstructed_index': 127, 'reconstructed_x': 61440,
                              'cp_legal_bits': 18, 'edit_representable_max': 131071,
                              'policy': '2倍Edit纵值线性向下插值，再(Y+1)//2；独立61440变化拒绝'},
        'axis': axis, 'baseline_curve': baseline_curve, 'three_tone_curve': tone_curve,
        'full_gamma_curve': full_curve, 'history': histories,
        'model_sha256': solver.digests[0], 'target_cp_sha256': solver.digests[1],
        'reference_asset_sha256': solver.asset_sha, 'source_sha256': solver.sources,
        'comparison_tool_sha256': tool_sha,
        'lut_sha256': hashlib.sha256(cube).hexdigest(), 'seconds': time.monotonic() - began,
        'limitations': [
            '129点中原点固定、61440由其余点重建，当前适配最多127个独立纵值；此次只搜索17个结点',
            'CP合法18bit曲线超出Edit可表示范围仍拒绝；不是任意129点已全面评估',
            '固定上下文与参数桥不证明机身逐路由曲线、sRGB域或硬件舍入',
            '最终测试允许退步，不能据此宣称完整Gamma必然优于三tone',
            '不产生.a7filter、AJR4、机身准入或原厂外观修改'],
    }
    check_cancel('结果就绪')
    if hashlib.sha256(Path(__file__).read_bytes()).hexdigest() != tool_sha:
        raise FitError('对照期间工具源码改变，不能发布')
    return result


def publish(result, destination, *, cancel=None):
    if cancel and cancel():
        raise FitCancelled('已取消，未发布结果')
    if result.get('research_only') is not True or result.get('camera_apply_allowed') is not False:
        raise FitError('不是离线研究结果')
    curves = {key: result[key] for key in ('axis', 'baseline_curve', 'three_tone_curve', 'full_gamma_curve')}
    files = {'gamma-comparison.json': result, 'gamma-curves.json': curves}
    encoded = {name: (json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n').encode()
               for name, value in files.items()}
    destination = Path(destination)
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    for name, data in encoded.items():
        fd = os.open(destination / name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('cube', type=Path)
    parser.add_argument('--output', type=Path, required=True, help='尚不存在的研究结果目录')
    parser.add_argument('--additional-budget', type=int, default=96)
    parser.add_argument('--matrix-sectors', type=int, choices=(1, 16), default=16)
    args = parser.parse_args(argv)
    try:
        if args.output.exists() or args.output.is_symlink():
            raise FitError('输出路径已存在，拒绝覆盖')
        cube = fit_recipe.recipe_file.read_regular(args.cube, 4 * 1024 * 1024)
        with fit_recipe.native_solver(args.matrix_sectors) as solver:
            result = compare(solver, cube, additional_budget=args.additional_budget)
        publish(result, args.output)
        print(json.dumps({'output': str(args.output), 'camera_apply_allowed': False,
                          'three_tone': result['three_tone']['test'],
                          'full_gamma': result['full_gamma']['test']}, ensure_ascii=False))
        return 0
    except (FitError, fit_recipe.recipe_file.RecipeFileError, OSError, KeyboardInterrupt) as error:
        print(str(error) or '已取消，未发布新结果', file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
