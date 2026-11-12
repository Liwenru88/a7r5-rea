"""Monotone concave Gamma on the camera's fixed, nonuniform native axis.

The 128 native x coordinates already allocate dense controls to shadows and
sparse controls to highlights.  They are retained, not replaced by uniform
index or input sampling.  Each nonzero control contributes min(x/k, 1), a
nondecreasing concave ramp; nonnegative softmax masses (and one zero ramp)
therefore guarantee the continuous parameter curve is nondecreasing and has
no upward change of slope.  Piecewise linear corners have downward slope
jumps, rather than a classical second derivative at the corner itself.

Ordinate integer rounding can break concavity.  quantize_raw explicitly caps
each next integer slope and verifies cross-products using Python integers.
Its displacement audit must be retained: this deterministic downward pass
is not a nearest projection and can accumulate rounding error.  This module
does not claim the expanded integer-per-code lookup has a negative second
difference; quantizing a fractional slope itself creates 0/1 step patterns.
"""
import numpy as np


POLICY = 'native-fixed-axis-monotone-concave-gamma/1'


def _axis(value):
    x = np.asarray(value)
    if (x.ndim != 1 or len(x) < 2 or not np.isfinite(x).all()
            or np.any(x != np.trunc(x)) or x[0] != 0
            or np.any(np.diff(x) <= 0)):
        raise ValueError('Gamma requires an increasing integer zero-origin axis')
    return x.astype(np.int64)


def _decreasing_slopes(slopes, lengths):
    """Weighted pool-adjacent-violators seed encoding, no numerical optimizer."""
    blocks = []
    for i, (slope, length) in enumerate(zip(slopes, lengths)):
        blocks.append([i, i + 1, float(slope * length), float(length)])
        while len(blocks) > 1 and blocks[-2][2] / blocks[-2][3] < blocks[-1][2] / blocks[-1][3]:
            right = blocks.pop()
            left = blocks[-1]
            left[1] = right[1]
            left[2] += right[2]
            left[3] += right[3]
    result = np.empty(len(slopes), dtype=float)
    for begin, end, total, length in blocks:
        result[begin:end] = max(0., total / length)
    return result


class ConcaveGamma:
    def __init__(self, axis, control_count=128, parameter_count=128, max_output=16383.,
                 global_correction=False):
        self.axis = _axis(axis)
        if (isinstance(control_count, bool) or not isinstance(control_count, int)
                or not 2 <= control_count <= len(self.axis)):
            raise ValueError('Invalid Gamma control_count')
        if (isinstance(parameter_count, bool) or not isinstance(parameter_count, int)
                or parameter_count < control_count):
            raise ValueError('Gamma parameter_count must include ramps and zero slack')
        if not np.isfinite(max_output) or max_output <= 0:
            raise ValueError('Gamma max_output must be positive and finite')
        self.parameter_count = parameter_count
        self.max_output = float(max_output)
        if type(global_correction) is not bool:
            raise ValueError('Gamma global_correction must be boolean')
        # The global integer solve is explicitly called by the final Gamma
        # correction stage. Ordinary candidate construction is unchanged.
        self.global_correction = global_correction
        self.last_global_quantization_audit = None
        if control_count == len(self.axis):
            self.control_indices = np.arange(len(self.axis), dtype=int)
        else:
            # Optional coarser training controls still use native coordinates.
            # x=u^2 places more controls in shadows; endpoints are mandatory.
            desired = np.linspace(0., 1., control_count) ** 2 * self.axis[-1]
            indices = np.argmin(abs(self.axis[:, None] - desired[None, :]), axis=0)
            self.control_indices = np.unique(np.r_[0, indices, len(self.axis) - 1])
        self.control_axis = self.axis[self.control_indices].astype(float)
        ramps = np.minimum(self.axis[:, None] / self.control_axis[None, 1:], 1.)
        # At least one zero column allows the endpoint to remain below max.
        self.basis = np.pad(ramps, ((0, 0), (0, parameter_count - ramps.shape[1])))
        self.active_ramps = ramps.shape[1]

    def curve(self, values):
        v = np.asarray(values, dtype=float)
        if v.shape != (self.parameter_count,) or not np.isfinite(v).all():
            raise ValueError('Unexpected concave Gamma parameter vector')
        mass = np.exp(v - v.max())
        mass /= mass.sum()
        return self.max_output * (self.basis @ mass)

    def tensor_curve(self, torch, values):
        if values.ndim != 1 or values.shape[0] != self.parameter_count:
            raise ValueError('Unexpected tensor Gamma parameter vector')
        basis = torch.as_tensor(self.basis, dtype=values.dtype, device=values.device)
        return self.max_output * (basis @ torch.softmax(values, dim=0))

    def encode(self, y14):
        """Encode a seed; pool increasing slopes if it was not yet concave.

        Seed encoding is deterministic, performed once before fitting.  The
        hard concavity guarantee thereafter comes from the parameterization.
        """
        y = np.asarray(y14, dtype=float)
        if y.shape != self.axis.shape or not np.isfinite(y).all():
            raise ValueError('Unexpected Gamma seed ordinate shape')
        y = np.clip(y - y[0], 0., self.max_output)
        yc = y[self.control_indices]
        lengths = np.diff(self.control_axis)
        slopes = _decreasing_slopes(np.diff(yc) / lengths, lengths)
        endpoint = float(slopes @ lengths)
        if endpoint > self.max_output:
            slopes *= self.max_output / endpoint
        drops = np.r_[slopes[:-1] - slopes[1:], slopes[-1]]
        masses = np.maximum(0., drops * self.control_axis[1:] / self.max_output)
        slack = max(0., 1. - masses.sum())
        v = np.zeros(self.parameter_count, dtype=float)
        v[:self.active_ramps] = masses
        v[self.active_ramps:] = slack / (self.parameter_count - self.active_ramps)
        # A tiny mass gives finite seeds while preserving concavity exactly.
        v = np.maximum(v, 1e-12)
        v /= v.sum()
        return np.log(v)

    def audit_even(self, raw_y):
        y = np.asarray(raw_y)
        finite = y.shape == self.axis.shape and bool(np.isfinite(y).all())
        integral = finite and bool(np.all(y == np.trunc(y)))
        if not integral:
            return dict(passed=False, finite=finite, integral=False)
        yi = [int(v) for v in y]
        dx = [int(v) for v in np.diff(self.axis)]
        dy = [b-a for a, b in zip(yi[:-1], yi[1:])]
        products = [dy[i] * dx[i+1] - dy[i+1] * dx[i] for i in range(len(dy)-1)]
        even = all(v % 2 == 0 for v in yi)
        monotone = all(v >= 0 for v in dy)
        concave = all(v >= 0 for v in products)
        domain = yi[0] == 0 and min(yi) >= 0 and max(yi) <= 262142
        return dict(passed=even and monotone and concave and domain, finite=True,
            integral=True, even=even, monotone=monotone, concave=concave,
            zero_origin=yi[0] == 0, within_native_raw18=domain,
            minimum_cross_product=min(products, default=0),
            concavity_violations=sum(v < 0 for v in products),
            slope_domain='actual nonuniform native x; exact integer cross-products',
            scope='128 serialized native nodes; separate export endpoint and integer lookup not implied')

    def quantize_raw(self, raw_y, *, max_error_raw=None, return_audit=False):
        source = np.asarray(raw_y, dtype=float)
        if source.shape != self.axis.shape or not np.isfinite(source).all() or source[0] != 0:
            raise ValueError('Expected finite zero-origin raw Gamma ordinates')
        if np.any(source < 0) or np.any(source > 262143):
            raise ValueError('Raw Gamma outside 18-bit range')
        desired = np.rint(source / 2).astype(np.int64)
        output = [0]
        dx = [int(v) for v in np.diff(self.axis)]
        previous_delta = None
        for i, width in enumerate(dx):
            delta = max(0, int(desired[i+1]) - output[-1])
            if previous_delta is not None:
                delta = min(delta, previous_delta * width // dx[i-1])
            delta = min(delta, 131071 - output[-1])
            output.append(output[-1] + delta)
            previous_delta = delta
        result = np.asarray(output, dtype=np.int64) * 2
        audit = self.audit_even(result)
        audit.update(policy=POLICY, method='even-half-unit forward exact-slope cap; no numerical optimizer',
            maximum_absolute_quantization_raw=float(np.max(abs(result-source))),
            endpoint_shift_raw=float(result[-1]-source[-1]),
            total_absolute_quantization_raw=float(np.sum(abs(result-source))))
        if not audit['passed']:
            raise ValueError('Concave Gamma integer construction failed')
        if max_error_raw is not None:
            if not np.isfinite(max_error_raw) or max_error_raw < 0:
                raise ValueError('Invalid Gamma quantization displacement budget')
            audit['displacement_budget_raw'] = float(max_error_raw)
            audit['displacement_budget_passed'] = audit['maximum_absolute_quantization_raw'] <= max_error_raw
            if not audit['displacement_budget_passed']:
                raise ValueError('Concave Gamma quantization exceeds displacement budget')
        return (result, audit) if return_audit else result

    def integer_curve(self, values, *, max_error_raw=None, return_audit=False):
        return self.quantize_raw(self.curve(values) * 16,
            max_error_raw=max_error_raw, return_audit=return_audit)

    def quantize_global_raw(self, raw_y, *, max_error_raw=None,
                            return_audit=False, time_limit=1.):
        """Jointly distribute integer error over every native ordinate.

        Minimize equally weighted native-node L1 error, in stored half-units,
        with all ordinates integer and all nonuniform interval slopes
        nonnegative/nonincreasing. The existing forward construction supplies
        a known feasible objective bound, never a frozen early-node boundary.

        A bounded MILP may return a feasible incumbent without proving global
        optimality. Such a result is accepted only after exact integer slope
        checks and only if its L1 error is no worse than the known feasible
        seed. If the solver supplies no valid improvement, retain that seed
        explicitly in the audit. This is not an unconditional nearest-point
        or optimality claim.
        """
        import math
        import time
        from scipy import sparse
        from scipy.optimize import milp, Bounds, LinearConstraint

        if not np.isfinite(time_limit) or time_limit <= 0:
            raise ValueError('Global Gamma integer time_limit must be positive')
        source = np.asarray(raw_y, dtype=float)
        # Validation and the baseline feasible construction share the exact
        # legacy policy; no existing candidate is silently reinterpreted.
        baseline, _ = self.quantize_raw(source, return_audit=True)
        desired = source / 2
        baseline_error = float(np.sum(abs(baseline / 2 - desired)))
        result = baseline.copy()
        selected = 'known-feasible-forward-seed'
        reason = 'global solver did not improve the known feasible seed'
        solver = dict(status=None, message='not run', optimal=False,
                      mip_gap=None, mip_node_count=None, dual_bound=None)
        started = time.perf_counter()
        n = len(self.axis)
        if baseline_error == 0:
            reason = 'input is already an exact feasible integer curve'
            solver.update(status=0, message=reason, optimal=True, mip_gap=0.)
        else:
            # q[0:n] are integer stored half-ordinates, e[n:2n] are
            # nonnegative absolute-error epigraphs. Every q may move.
            matrix = sparse.lil_matrix((2*n - 3 + 2*n + 1, 2*n), dtype=float)
            low = np.full(matrix.shape[0], -np.inf)
            high = np.full(matrix.shape[0], np.inf)
            row = 0
            for i in range(1, n):
                matrix[row, i-1] = -1
                matrix[row, i] = 1
                low[row] = 0
                row += 1
            dx = [int(v) for v in np.diff(self.axis)]
            for i in range(1, n-1):
                left, right = dx[i], dx[i-1]
                divisor = math.gcd(left, right)
                left //= divisor
                right //= divisor
                matrix[row, i-1] = -left
                matrix[row, i] = left + right
                matrix[row, i+1] = -right
                low[row] = 0
                row += 1
            for i in range(n):
                matrix[row, i] = 1
                matrix[row, n+i] = -1
                high[row] = desired[i]
                row += 1
                matrix[row, i] = -1
                matrix[row, n+i] = -1
                high[row] = -desired[i]
                row += 1
            matrix[row, n:] = 1
            high[row] = baseline_error + 1e-7
            # The known feasible L1 total also bounds each coordinate's
            # displacement. This tightens the solve without fixing nodes.
            lower = np.r_[np.maximum(0, np.ceil(desired-baseline_error-1e-7)), np.zeros(n)]
            upper = np.r_[np.minimum(131071, np.floor(desired+baseline_error+1e-7)), np.full(n, np.inf)]
            lower[0] = upper[0] = 0
            try:
                fit = milp(np.r_[np.zeros(n), np.ones(n)],
                    integrality=np.r_[np.ones(n), np.zeros(n)],
                    bounds=Bounds(lower, upper),
                    constraints=LinearConstraint(matrix.tocsc(), low, high),
                    options=dict(time_limit=float(time_limit), mip_rel_gap=0.))
                def finite_or_none(value):
                    return float(value) if value is not None and np.isfinite(value) else None
                solver.update(status=int(fit.status), message=str(fit.message),
                    mip_gap=finite_or_none(getattr(fit, 'mip_gap', None)),
                    mip_node_count=finite_or_none(getattr(fit, 'mip_node_count', None)),
                    dual_bound=finite_or_none(getattr(fit, 'mip_dual_bound', None)))
                if fit.x is not None and np.isfinite(fit.x[:n]).all():
                    candidate = np.rint(fit.x[:n]).astype(np.int64) * 2
                    candidate_error = float(np.sum(abs(candidate / 2 - desired)))
                    exact = self.audit_even(candidate)
                    if exact['passed'] and candidate_error <= baseline_error + 1e-7:
                        result = candidate
                        selected = 'joint-all-node-MILP-incumbent'
                        reason = ('global L1 optimality proven' if fit.status == 0 else
                                  'bounded global solve; feasible incumbent, optimality not proven')
                        solver['optimal'] = bool(fit.status == 0)
                    else:
                        reason = ('global incumbent failed exact integer audit' if not exact['passed']
                                  else 'global incumbent exceeded known feasible L1 error')
                else:
                    reason = 'global solver returned no incumbent; retained known feasible seed'
            except (ValueError, RuntimeError) as error:
                solver.update(status=-1, message=str(error))
                reason = 'global solver error; retained known feasible seed'
        audit = self.audit_even(result)
        audit.update(policy=POLICY,
            method='simultaneous native-node integer L1 correction with explicit bounded-solver audit',
            maximum_absolute_quantization_raw=float(np.max(abs(result-source))),
            endpoint_shift_raw=float(result[-1]-source[-1]),
            total_absolute_quantization_raw=float(np.sum(abs(result-source))))
        audit['global_integer_projection'] = dict(
            enabled=True, objective='sum(abs(stored_half_ordinate - source_raw18/2))',
            weighting='equal native-node weights; retained dark-dense/highlight-sparse axis',
            all_nodes_joint=True, optimized_ordinates=n,
            fixed_nodes=[0], selected=selected, reason=reason, solver=solver,
            time_limit_seconds=float(time_limit), elapsed_seconds=time.perf_counter()-started,
            baseline_l1_error_raw18=2*baseline_error,
            selected_l1_error_raw18=float(np.sum(abs(result-source))),
            baseline_maximum_displacement_raw18=float(np.max(abs(baseline-source))),
            changed_from_forward_nodes=int(np.sum(result != baseline)),
            nodes_above_forward=int(np.sum(result > baseline)),
            nodes_below_forward=int(np.sum(result < baseline)))
        if not audit['passed']:
            raise ValueError('Global Gamma integer correction lost feasibility')
        if max_error_raw is not None:
            if not np.isfinite(max_error_raw) or max_error_raw < 0:
                raise ValueError('Invalid Gamma quantization displacement budget')
            audit['displacement_budget_raw'] = float(max_error_raw)
            audit['displacement_budget_passed'] = audit['maximum_absolute_quantization_raw'] <= max_error_raw
            if not audit['displacement_budget_passed']:
                raise ValueError('Global Gamma quantization exceeds displacement budget')
        self.last_global_quantization_audit = audit
        return (result, audit) if return_audit else result
