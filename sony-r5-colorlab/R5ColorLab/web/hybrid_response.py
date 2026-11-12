"""Nonlinear grid-response base plus three input-hue C1 residual experts.

This is a new, explicitly named operator shape.  It keeps the original
nonlinear 30x3 response and adds three gated 81x3 C1 residual fields.  The
strict RGB gray axis is unchanged because every expert gate is zero there.
"""
from numbers import Real
import numpy as np
from paired_response import PairedModel, _c1_basis, _c1_basis_tensor

KIND = 'rgb-hue3-nonlinear/1'
GATE = dict(kappa=2., s0=.25, c0=.04)
EXPERT_DIRECTIONS = np.array([[1., 0.], [-.5, np.sqrt(3)/2], [-.5, -np.sqrt(3)/2]])


def validate_gate(value=None):
    value = GATE.copy() if value is None else value
    if not isinstance(value, dict) or set(value) != set(GATE):
        raise ValueError('hybrid gate requires exactly kappa, s0 and c0')
    for key, item in value.items():
        if isinstance(item, (bool, np.bool_)) or not isinstance(item, Real) or not np.isfinite(item) or item <= 0:
            raise ValueError('hybrid gate values must be finite positive numbers')
    return {key: float(item) for key, item in value.items()}


def gate_weights(rgb, gate=None):
    x = np.asarray(rgb, float); gate = validate_gate(gate)
    z = np.column_stack([x[:, 0] - (x[:, 1] + x[:, 2]) / 2,
                         np.sqrt(3) / 2 * (x[:, 1] - x[:, 2])])
    q = np.sum(z * z, axis=1)
    logits = gate['kappa'] * (z @ EXPERT_DIRECTIONS.T) / gate['s0']
    logits -= logits.max(axis=1, keepdims=True)
    p = np.exp(logits); p /= p.sum(axis=1, keepdims=True)
    return (q / (q + gate['c0'] ** 2))[:, None] * p


def gate_weights_tensor(tools, rgb, gate=None):
    t = tools.torch; gate = validate_gate(gate)
    z = t.stack([rgb[:, 0] - (rgb[:, 1] + rgb[:, 2]) / 2,
                 t.sqrt(tools.tensor(3.0)) / 2 * (rgb[:, 1] - rgb[:, 2])], dim=1)
    q = (z * z).sum(dim=1)
    logits = gate['kappa'] * (z @ tools.tensor(EXPERT_DIRECTIONS).T) / gate['s0']
    logits = logits - logits.max(dim=1, keepdim=True).values
    p = t.softmax(logits, dim=1)
    return (q / (q + gate['c0'] ** 2))[:, None] * p


class HybridModel:
    def __init__(self, value, digest, identity=None):
        self.value = dict(value)
        self.sha256 = digest
        self.identity = identity
        self.expert_weights = np.asarray(value['expert_weights'], float)
        if self.expert_weights.shape != (3, 81, 3) or not np.isfinite(self.expert_weights).all():
            raise ValueError('hybrid expert weights must be finite 3x81x3')
        self.gate = validate_gate(value.get('expert_gate'))
        base = dict(value)
        base['response_basis'] = 'rgb-quadratic'
        base['response_weights'] = value.get('base_response_weights', value['response_weights'])
        base['smooth'] = True
        self.base = PairedModel(base, digest, identity=identity)
        self.affine = self.base.affine
        self.proxy = False

    def coordinates(self, rgb):
        return self.base.coordinates(rgb)

    def stencil(self, rgb):
        return self.base.stencil(rgb)

    def coordinates_tensor(self, tools, rgb):
        return self.base.coordinates_tensor(tools, rgb)

    def response(self, rgb):
        x = np.asarray(rgb, float)
        base = self.base.response(x)
        b = _c1_basis(x)
        extra = np.einsum('nb,ecbo->neco', b, self.expert_weights.reshape(3, 3, 27, 3))
        return base + np.einsum('ne,neco->nco', gate_weights(x, self.gate), extra) / 256

    def response_tensor(self, tools, rgb):
        base = self.base.response_tensor(tools, rgb)
        b = _c1_basis_tensor(tools, rgb)
        extra = tools.torch.einsum('nb,ecbo->neco', b,
            tools.tensor(self.expert_weights.reshape(3, 3, 27, 3)))
        return base + tools.torch.einsum('ne,neco->nco', gate_weights_tensor(tools, rgb, self.gate), extra) / 256

    def predict_cpu(self, rgb, table, clip=True):
        x = np.asarray(rgb, float); _, ids, w = self.stencil(x)
        d = (np.asarray(table)[ids] * w[..., None]).sum(1)
        out = x + np.einsum('nc,nco->no', d, self.response(x))
        return np.clip(out, 0, 1) if clip else out

    def predict(self, rgb, table, clip=True):
        return self.predict_cpu(rgb, table, clip)

    def probes(self, count, seed=20261022):
        return self.base.probes(count, seed)

    def fit(self, base, target, weights, strength=.01):
        from gpu_runtime import available
        if available():
            from gpu_grid import fit
            result, audit = fit(base, target, weights, strength, response=self.identity)
            audit.update(model_sha256=self.sha256, response_basis=KIND,
                         new_scene_camera_verified=False)
            return result, audit
        # CPU bounded least squares fallback.  Inference and CPU selection use
        # the same response matrix as the Metal path.
        from scipy.optimize import least_squares
        from scipy import sparse
        x = np.asarray(base, float); y = np.asarray(target, float)
        w = np.asarray(weights, float)
        _, ids, interp = self.stencil(x)
        R = self.response(x)
        mass = np.sqrt(w / w.sum())
        rows, cols, data = [], [], []
        for c in range(3):
            for o in range(3):
                rows.append(np.repeat(np.arange(len(x)) * 3 + o, 8))
                cols.append((ids * 3 + c).ravel())
                data.append((interp * R[:, c, o, None] * mass[:, None]).ravel())
        design = sparse.coo_matrix((np.concatenate(data), (np.concatenate(rows), np.concatenate(cols))), shape=(len(x) * 3, 1215)).tocsr()
        regularizer = sparse.eye(1215, format='csr') * np.sqrt(strength / 405) / 256
        def func(v):
            raw = x + (design @ v).reshape(-1, 3) / mass[:, None]
            return np.r_[((np.clip(raw, 0, 1) - y) * mass[:, None]).ravel(), regularizer @ v]
        result = least_squares(func, np.zeros(1215), bounds=(-64, 63), max_nfev=60, ftol=1e-6)
        table = np.clip(np.rint(result.x.reshape(405, 3)), -64, 63).astype(np.int8)
        return table, dict(model_sha256=self.sha256, response_basis=KIND, training_only=True,
                           regularization=strength, evaluations=result.nfev, converged=bool(result.success))
