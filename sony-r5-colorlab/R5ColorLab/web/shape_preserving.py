"""Fritsch--Carlson C1 cubic interpolation for offline repair controls.

Interpolation preserves each control interval's direction and value range.
It retains turns already present in controls; callers must remove unwanted
control-point spikes first. This does not change native LUT interpolation.
"""
import numpy as np

POLICY = 'fritsch-carlson-monotone-cubic/1'


def _controls(x, y):
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if (x.ndim != 1 or len(x) < 2 or y.ndim not in (1, 2)
            or y.shape[0] != len(x) or (y.ndim == 2 and y.shape[1] == 0)
            or not np.isfinite(x).all() or not np.isfinite(y).all()
            or np.any(np.diff(x) <= 0)):
        raise ValueError('Expected at least two finite, strictly increasing x controls and matching y')
    return x, y[:, None] if y.ndim == 1 else y, y.ndim == 1


def fritsch_carlson_tangents(x, y):
    """Limit endpoint tangents in every channel using the FC radius-3 rule."""
    x, values, scalar = _controls(x, y)
    secant = np.diff(values, axis=0) / np.diff(x)[:, None]
    tangent = np.empty_like(values)
    tangent[0], tangent[-1] = secant[0], secant[-1]
    if len(x) > 2:
        same = ((secant[:-1] > 0) & (secant[1:] > 0)) | ((secant[:-1] < 0) & (secant[1:] < 0))
        tangent[1:-1] = np.where(same, (secant[:-1] + secant[1:]) / 2, 0.)
    for i, slope in enumerate(secant):
        flat = slope == 0
        tangent[i, flat] = 0.
        tangent[i + 1, flat] = 0.
        active = ~flat
        a = np.divide(tangent[i], slope, out=np.zeros_like(slope), where=active)
        b = np.divide(tangent[i + 1], slope, out=np.zeros_like(slope), where=active)
        radius = np.hypot(a, b)
        limited = active & (radius > 3)
        factor = np.divide(3., radius, out=np.ones_like(radius), where=limited)
        tangent[i, limited] *= factor[limited]
        tangent[i + 1, limited] *= factor[limited]
    return tangent[:, 0] if scalar else tangent


def fritsch_carlson(x, y, query):
    """Evaluate a shape-preserving cubic; queries outside controls clamp.

    y is N or NxC. Result shape is query.shape (scalar channel) or
    query.shape+(C,). Two controls reduce exactly to linear interpolation.
    """
    x, values, scalar = _controls(x, y)
    q = np.asarray(query, dtype=float)
    if not np.isfinite(q).all():
        raise ValueError('Interpolation queries must be finite')
    tangent = fritsch_carlson_tangents(x, values)
    points = np.clip(q.reshape(-1), x[0], x[-1])
    index = np.clip(np.searchsorted(x, points, side='right') - 1, 0, len(x) - 2)
    span = x[index + 1] - x[index]
    t = ((points - x[index]) / span)[:, None]
    t2, t3 = t*t, t*t*t
    result = ((2*t3 - 3*t2 + 1)*values[index]
        + (t3 - 2*t2 + t)*span[:, None]*tangent[index]
        + (-2*t3 + 3*t2)*values[index + 1]
        + (t3 - t2)*span[:, None]*tangent[index + 1])
    if scalar:
        return result[:, 0].reshape(q.shape)
    return result.reshape(q.shape + (values.shape[1],))
