"""Target-independent smoothness of the *applied* paired-grid correction.

For a frozen paired response the preclip correction is P(x) g, linear in the
1215 signed table coefficients. Fixed RGB paths turn first derivatives and
curvature of that correction into a sparse linear operator A. All optimizers
can therefore share exactly the quadratic raw_loss = ||A g||^2 = g.T Q g.

This constrains color-response derivatives, not image pixels, hue ordering or
bare table-neighbor differences. Native interpolation can still have kinks.
No training target, validation color or observed photograph constructs paths.
"""
from collections import Counter
from functools import cached_property, lru_cache
import colorsys
from itertools import product
import json

import numpy as np
from scipy import sparse


POLICY = 'paired-preclip-path-derivatives-v1'
FIRST_RATE = 1e-4
SECOND_RATE = 1e-6
FAMILIES = ('brightness', 'hue', 'saturation', 'neutral')


def fixed_paths():
    """Return fixed RGB straight segments; never differentiate across corners.

    Hue uses the six straight sides of each HSV hexagon separately. Brightness
    black-to-color and color-to-white segments also stay separate, so known
    RGB path corners are not mistaken for curvature of the correction field.
    Arc lengths below are actual Euclidean RGB distances, not HSV distances.
    """
    paths = []

    def add(family, name, start, end, samples=33):
        start, end = np.asarray(start, float), np.asarray(end, float)
        if np.linalg.norm(end-start) <= 1e-12:
            return
        t = np.linspace(0, 1, samples)[:, None]
        paths.append(dict(family=family, name=name, rgb=(1-t)*start+t*end))

    for h, saturation in product(np.arange(24)/24, (.25, .6, 1.)):
        color = np.asarray(colorsys.hsv_to_rgb(float(h), saturation, 1.))
        add('brightness', f'black-color:{h:.8f}:{saturation}', np.zeros(3), color)
        add('brightness', f'color-white:{h:.8f}:{saturation}', color, np.ones(3))
    for value, saturation, sector in product((.05, .2, .5, 1.), (.3, .7, 1.), range(6)):
        add('hue', f'hexagon:{value}:{saturation}:{sector}',
            colorsys.hsv_to_rgb(sector/6, saturation, value),
            colorsys.hsv_to_rgb((sector+1)/6 % 1, saturation, value), samples=17)
    for h, value in product(np.arange(24)/24, (.03, .12, .35, .65, 1.)):
        add('saturation', f'gray-color:{h:.8f}:{value}', np.full(3, value),
            colorsys.hsv_to_rgb(float(h), 1., value))
    add('neutral', 'black-white', np.zeros(3), np.ones(3), samples=65)
    return paths


def _geometry(paths):
    """Sparse derivative rows with arc-length quadrature and equal family mass."""
    family_counts = Counter(p['family'] for p in paths)
    all_rgb, start = [], 0
    first_rows, first_cols, first_values = [], [], []
    second_rows, second_cols, second_values = [], [], []
    n_first = n_second = 0
    for path in paths:
        rgb = np.asarray(path['rgb'], float)
        distance = np.linalg.norm(np.diff(rgb, axis=0), axis=1)
        if (rgb.ndim != 2 or rgb.shape[1] != 3 or len(rgb) < 3 or
                not np.isfinite(rgb).all() or np.any(distance <= 0)):
            raise ValueError('Grid regularization paths require finite distinct RGB points')
        family_mass = 1/(len(FAMILIES)*family_counts[path['family']])
        # Each family has equal total mass for each derivative order. Arc
        # quadrature prevents simply duplicating a short segment increasing
        # its influence; each output channel also receives equal mass.
        first_mass = distance/distance.sum()*family_mass/3
        width = (distance[:-1]+distance[1:])/2
        second_mass = width/width.sum()*family_mass/3
        for i, (step, mass) in enumerate(zip(distance, first_mass)):
            scale = np.sqrt(FIRST_RATE*mass)/step
            first_rows.extend([n_first, n_first]); first_cols.extend([start+i, start+i+1])
            first_values.extend([-scale, scale]); n_first += 1
        for i, (left, right, mass) in enumerate(zip(distance[:-1], distance[1:], second_mass)):
            scale = np.sqrt(SECOND_RATE*mass)*2/(left+right)
            second_rows.extend([n_second]*3); second_cols.extend([start+i, start+i+1, start+i+2])
            second_values.extend([scale/left, -scale*(1/left+1/right), scale/right]); n_second += 1
        all_rgb.append(rgb)
        start += len(rgb)
    first = sparse.coo_matrix((first_values, (first_rows, first_cols)), shape=(n_first, start)).tocsr()
    second = sparse.coo_matrix((second_values, (second_rows, second_cols)), shape=(n_second, start)).tocsr()
    return np.concatenate(all_rgb), first, second


class GridPenalty:
    """Frozen 405-node paired-response path operator, in integer table units.

    ``rows`` contains A; ``gram`` and ``dense_gram`` contain Q=A.T@A, with no
    UI strength or 255 scaling baked in. For a solver using v=g/256, its
    quadratic matrix is 256**2 * Q. ``max_row_sum_upper`` bounds ||Q||_2.
    ``tensor_loss`` returns cost/255**2, retaining gradients through table.
    """
    def __init__(self, response):
        from measured_response import get
        if not isinstance(response, dict):
            raise ValueError('Applied-response grid penalty requires a paired response identity')
        model = get(response)
        if not hasattr(model, 'affine'):
            raise ValueError('Applied-response grid penalty requires an R5 paired response')
        self.identity = json.loads(json.dumps(response, sort_keys=True, allow_nan=False))
        self.paths = fixed_paths()
        self.rgb, first, second = _geometry(self.paths)
        _, ids, weights = model.stencil(self.rgb)
        response_matrix = model.response(self.rgb)
        rows, cols, data = [], [], []
        for component, output in product(range(3), repeat=2):
            rows.append(np.repeat(np.arange(len(self.rgb))*3+output, 8))
            cols.append((ids*3+component).ravel())
            data.append((weights*response_matrix[:, component, output, None]).ravel())
        self.correction_matrix = sparse.coo_matrix(
            (np.concatenate(data), (np.concatenate(rows), np.concatenate(cols))),
            shape=(len(self.rgb)*3, 1215)).tocsr()
        self.first_rows = (sparse.kron(first, sparse.eye(3), format='csr')@self.correction_matrix).tocsr()
        self.second_rows = (sparse.kron(second, sparse.eye(3), format='csr')@self.correction_matrix).tocsr()
        self.rows = sparse.vstack([self.first_rows, self.second_rows], format='csr')
        self.rows.eliminate_zeros()
        self.gram = (self.rows.T@self.rows).tocsr()
        self.gram.eliminate_zeros()
        self.max_row_sum_upper = float(np.max(np.asarray(abs(self.gram).sum(axis=1))))
        self._tensor_grams = {}
        import hashlib
        self.metadata = dict(policy=POLICY, identity=self.identity,
            input_sha256=hashlib.sha256(self.rgb.tobytes()).hexdigest(),
            families=list(FAMILIES), family_path_counts=dict(Counter(p['family'] for p in self.paths)),
            path_count=len(self.paths), rgb_samples=len(self.rgb), native_grid_shape=[5, 9, 9],
            coefficient_units='signed integer table; node-major, three components per node',
            first_rate=FIRST_RATE, curvature_rate=SECOND_RATE,
            derivative_units='actual Euclidean RGB arc length; per-path arc quadrature, equal family and output mass',
            output='preclip applied grid correction; source identity not penalized',
            target_independent=True, zero_grid_exact=True,
            curvature_scope='fixed straight segments; does not assert global C1 or monotone hue')

    @cached_property
    def dense_gram(self):
        return self.gram.toarray()

    def _flat(self, grid):
        values = np.asarray(grid, float)
        if values.size != 1215 or not np.isfinite(values).all():
            raise ValueError('Grid penalty requires 1215 finite table coefficients')
        return values.reshape(-1)

    def raw_loss(self, grid):
        """Normalized RGB² quadratic, before optimizer/UI strength."""
        value = self.rows@self._flat(grid)
        return float(value@value)

    @staticmethod
    def scale(value):
        from parameter_smoothing import strength, multiplier
        value = strength(value)
        return .01*multiplier(value) if value else 0.

    def cost(self, grid, value):
        """Exact float64 acceptance cost in 8-bit RGB² units."""
        scale = self.scale(value)
        return scale*self.raw_loss(grid)*255**2 if scale else 0.

    def tensor_loss(self, tools, table_integer, value):
        """Same quadratic /255², with CPU float64 or GPU float32 autograd."""
        scale = self.scale(value)
        flat = table_integer.reshape(-1)
        if flat.numel() != 1215:
            raise ValueError('Grid penalty requires 1215 tensor table coefficients')
        if not scale:
            return flat.sum()*0
        key = (str(tools.device), str(tools.dtype))
        if key not in self._tensor_grams:
            self._tensor_grams[key] = tools.tensor(self.dense_gram)
        return (flat@(self._tensor_grams[key]@flat))*scale


@lru_cache(maxsize=4)
def _cached(serialized):
    return GridPenalty(json.loads(serialized))


def get_penalty(response):
    """Cache by complete fixed snapshot identity, including its SHA256."""
    if not isinstance(response, dict):
        raise ValueError('Applied-response grid penalty requires a paired response identity')
    return _cached(json.dumps(response, sort_keys=True, allow_nan=False, separators=(',', ':')))
