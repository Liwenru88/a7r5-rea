"""Read-only comparison of the two effective native MainGamma lookup tables.

This is an internal integer stage, before CC1, secondary YGamma and display
encoding. It is deliberately independent of PC compensation/tone curves.
"""
import hashlib

import numpy as np


POINTS = 128
INPUT_MAX = 16383
AXIS_DIVISOR = 128
ORDINATE_DIVISOR = 16


def _parameters(model):
    try:
        axis = np.frombuffer(model.raw, dtype='<i4', count=POINTS,
                             offset=0x5d8).astype(np.int64)
        values = np.frombuffer(model.raw, dtype='<i4', count=POINTS,
                               offset=0x7d8).astype(np.int64)
    except (AttributeError, TypeError, ValueError) as error:
        raise ValueError('MainGamma requires complete captured RAW parameters') from error
    if (axis[0] != 0 or np.any(np.diff(axis) <= 0)
            or np.any(axis > 32767 * AXIS_DIVISOR)):
        raise ValueError('Unsupported MainGamma native input axis')
    if np.any(values < 0) or np.any(values > 262143):
        raise ValueError('MainGamma ordinates must be native 18-bit values')
    return axis, values


def _step_audit(values):
    values = np.asarray(values, dtype=np.int64)
    steps = np.diff(values)
    zero = steps == 0
    boundaries = np.diff(np.r_[False, zero, False].astype(np.int8))
    starts, ends = np.flatnonzero(boundaries == 1), np.flatnonzero(boundaries == -1)
    return dict(
        scope='all 16384 effective integer input codes, adjacent one-code steps',
        dense_samples=int(values.size), monotone=bool(np.all(steps >= 0)),
        negative_steps=int(np.sum(steps < 0)), zero_increments=int(np.sum(zero)),
        min_step=int(steps.min()), max_step=int(steps.max()),
        minimum=int(values.min()), maximum=int(values.max()),
        plateau_runs=int(len(starts)),
        longest_plateau_input_codes=int(np.max(ends - starts) + 1) if len(starts) else 0,
        table_sha256=hashlib.sha256(np.asarray(values, dtype='<u2').tobytes()).hexdigest())


def _effective(model, dense_input, node_input):
    # Use the actual RuntimeColor stage, including the captured/rebuilt contrast
    # mapping and integer table expansion, rather than interpolating raw y/16.
    pixels = np.repeat(dense_input[:, None], 3, axis=1)
    output = np.asarray(model.main_gamma(pixels))
    if (output.shape != pixels.shape or not np.all(np.isfinite(output))
            or np.any(output != np.trunc(output))
            or np.any(output < 0) or np.any(output > 65535)
            or not np.array_equal(output[:, 0], output[:, 1])
            or not np.array_equal(output[:, 0], output[:, 2])):
        raise ValueError('MainGamma must return one shared finite native integer table')
    values = output[:, 0].astype(np.int64)
    nodes = values[node_input]
    series = dict(output_14bit=nodes.tolist(),
                  adjacent_steps_14bit=np.diff(nodes).tolist(),
                  adjacent_steps_scope='128 sampled integer nodes, not dense one-code steps',
                  audit=dict(_step_audit(values),shared_neutral_rgb_response=True))
    return values, series


def _shape_audit(axis, values):
    # Exact integer cross products account for the nonuniform native abscissae.
    dx, dy = np.diff(axis), np.diff(values)
    cross = dy[:-1] * dx[1:] - dy[1:] * dx[:-1]
    return dict(monotone=bool(np.all(dy >= 0)),
                concave=bool(np.all(cross >= 0)),
                negative_intervals=int(np.sum(dy < 0)),
                convex_transitions=int(np.sum(cross < 0)),
                convex_transition_nodes=(np.flatnonzero(cross < 0) + 1).tolist(),
                slope_raw_ratio=(dy / dx).tolist(),
                zero_start=bool(values[0] == 0),
                audit_scope='exact nonuniform 128-knot slopes before integer expansion/contrast')


def compare(baseline, fitted):
    """Return JSON-safe exact MainGamma samples and original 128 control points.

    input_14bit contains floor(x_raw/128), clipped to the matrix stage's reachable
    0..16383 domain. The last stored x can be 16383.75; its unrounded coordinate
    remains in parameter_knots. *_output_14bit means internal code units, not an
    sRGB transfer function or a clipping operation. Effective values above the
    nominal 14-bit domain are retained.
    """
    axis, before_parameters = _parameters(baseline)
    fitted_axis, after_parameters = _parameters(fitted)
    if not np.array_equal(axis, fitted_axis):
        raise ValueError('Baseline and fitted MainGamma input axes differ')
    node_input = np.clip(axis // AXIS_DIVISOR, 0, INPUT_MAX).astype(np.int64)
    dense_input = np.arange(INPUT_MAX + 1, dtype=np.int64)
    before, before_series = _effective(baseline, dense_input, node_input)
    after, after_series = _effective(fitted, dense_input, node_input)
    return dict(
        schema='native-main-gamma-comparison/1',
        encoding=dict(
            title='原生主 Gamma：原厂基线与拟合结果',
            input_label='Gamma 内部输入码值', output_label='Gamma 内部输出码值',
            scope='MainGamma only; not sRGB, final gray output, PC tone curve or secondary YGamma',
            runtime_samples='exact RuntimeColor.main_gamma lookup; integer expansion and contrast included',
            stored_points=POINTS, stored_input_record='0x7805 signed int32',
            stored_output_record='0x7806 signed int32, nonnegative 18-bit ordinates',
            stored_input_divisor=AXIS_DIVISOR, stored_output_divisor=ORDINATE_DIVISOR,
            stored_output_scaling='raw y/16 is nominal control-point code units, not effective runtime output',
            runtime_input_domain=[0, INPUT_MAX], runtime_table_input_domain=[0, 32767],
            node_input_policy='floor(raw x/128), clipped to reachable 0..16383',
            normalized_divisor=INPUT_MAX, output_clipped=False,
            display_note='内部码值，不是 sRGB；实际曲线包含原生整数展开及对比度表影响。'),
        input_14bit=node_input.tolist(),
        input_normalized=(node_input / INPUT_MAX).tolist(),
        baseline=before_series, fitted=after_series,
        runtime_samples=dict(input_14bit=dense_input.tolist(),
                             baseline_output_14bit=before.tolist(),
                             fitted_output_14bit=after.tolist()),
        parameter_knots=dict(
            input_raw=axis.tolist(), input_14bit=(axis / AXIS_DIVISOR).tolist(),
            input_normalized=(axis / AXIS_DIVISOR / INPUT_MAX).tolist(),
            baseline_output_raw=before_parameters.tolist(),
            fitted_output_raw=after_parameters.tolist(),
            baseline_output_14bit=(before_parameters / ORDINATE_DIVISOR).tolist(),
            fitted_output_14bit=(after_parameters / ORDINATE_DIVISOR).tolist(),
            audit=dict(scope='128 stored parameter knots, before native table expansion/contrast',
                       same_axis=True,
                       baseline_monotone=bool(np.all(np.diff(before_parameters) >= 0)),
                       fitted_monotone=bool(np.all(np.diff(after_parameters) >= 0)),
                       baseline_shape=_shape_audit(axis,before_parameters),
                       fitted_shape=_shape_audit(axis,after_parameters),
                       input_interval_width_raw=np.diff(axis).tolist(),
                       dark_to_highlight_spacing_nondecreasing=bool(np.all(np.diff(np.diff(axis)) >= 0)),
                       fractional_input_nodes=int(np.sum(axis % AXIS_DIVISOR != 0)),
                       input_nodes_beyond_reachable_domain=int(np.sum(axis / AXIS_DIVISOR > INPUT_MAX)))),
        display_output_max=int(max(INPUT_MAX, before.max(), after.max())))
