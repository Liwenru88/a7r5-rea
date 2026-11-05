"""Pinned stock04 table/compact identity and packing self-check for calibration.

This verifies a mathematical tensor-linear operator and a native byte layout.
It does NOT establish the camera's pixel coordinates, interpolation, numerical
scale, integer pixel rounding, or an equivalent active Edit rendering stage.
No source files are rewritten and no camera or application is accessed.
"""
from fractions import Fraction
from hashlib import sha256
from itertools import product
from pathlib import Path
from random import Random
import struct

SHAPE = (5, 9, 9)
RAW_SHA256 = '783d2e58e24bfd04515ff04ed07bcf26049ade990781c5f8770bc3a30da032ba'
PACKED_SHA256 = '728010abe7a27c813b20103cb7180a8fc840109b1fe014e51c95b0ea9291908c'
PERMUTATION_SHA256 = '7073168e25aad9fbb9c6924dad4ebdbd1ac187a7807ebdabbc04bfb47bb49bc1'
SOURCE = Path(__file__).resolve().parent / 'data/r5-stock-02a40004.raw.bin'
COUNTS = (75, 60, 60, 48, 50, 40, 40, 32)


def read_stock04():
    """Return unmodified, digest-checked original planar signed8 source bytes."""
    raw = SOURCE.read_bytes()
    if len(raw) != 1215 or sha256(raw).hexdigest() != RAW_SHA256:
        raise ValueError('stock04 reference identity mismatch')
    return raw


def _point(value):
    if len(value) != 3:
        raise ValueError('Expected three node-index coordinates')
    try:
        point = tuple(Fraction(t) for t in value)
    except (ValueError, TypeError, OverflowError, ZeroDivisionError) as exc:
        raise ValueError('Invalid node-index coordinate') from exc
    if any(t < 0 or t > size - 1 for t, size in zip(point, SHAPE)):
        raise ValueError('Node-index coordinate outside 5x9x9 box')
    return point


def _ramp(t):
    return max(Fraction(0), min(Fraction(1), t))


def _hat(center, t):
    return max(Fraction(0), 1 - abs(t - center))


def compact(point):
    """Exact continuous compact04 value under the same tensor-linear basis.

    Coordinates are node indices, not RGB. Fraction input preserves exact
    rational arithmetic; output components are Fractions in source-table units.
    """
    a, b, c = _point(point)
    av = 15 - 12 * _ramp(a) - 3 * _ramp(a - 2)
    bv = -16 + 12 * _ramp(a) + 4 * _ramp(a - 2)
    p = lambda t: _ramp(t - 1) - _ramp(t - 3)
    n = lambda t: _ramp(t - 4) - _ramp(t - 6)
    w = lambda t: _ramp(t - 1) - _ramp(t - 6)
    return (Fraction(0), (av * p(b) + bv * n(b)) * w(c),
            w(b) * (av * p(c) + bv * n(c))
            + _hat(1, a) * _hat(4, b) * _hat(3, c))


def dense(point, raw=None):
    """Independent eight-corner interpolation of the original stored table."""
    point = _point(point)
    raw = read_stock04() if raw is None else raw
    if len(raw) != 1215:
        raise ValueError('Expected 1215 planar signed8 coefficients')
    values = struct.unpack('<1215b', raw)
    choices = []
    for t, size in zip(point, SHAPE):
        left = min(t.numerator // t.denominator, size - 2)
        f = t - left
        choices.append(((left, 1 - f), (left + 1, f)))
    out = [Fraction(0)] * 3
    for (a, wa), (b, wb), (c, wc) in product(*choices):
        index = a * 81 + b * 9 + c
        for channel in range(3):
            out[channel] += values[channel * 405 + index] * wa * wb * wc
    return tuple(out)


def _position(index):
    a, b, c = index // 81, index // 9 % 9, index % 9
    group = ((a & 1) * 2 + (b & 1)) * 2 + (c & 1)
    return (sum(COUNTS[:group])
            + ((a // 2) * (5 - (b & 1)) + b // 2) * (5 - (c & 1)) + c // 2)


def pack_hardware(raw, level=8):
    """Known source-byte conversion only; not an ISP pixel renderer.

    Three signed7 components occupy word bits22..28,12..18,2..8. Levels1..7
    apply native arithmetic-shift scaling. Other uint8 levels preserve values.
    """
    if len(raw) != 1215:
        raise ValueError('Expected 1215 planar signed8 coefficients')
    if type(level) is not int or not 0 <= level <= 255:
        raise ValueError('Expected uint8 strength level')
    values = struct.unpack('<1215b', raw)
    if min(values) < -64 or max(values) > 63:
        raise ValueError('Expected signed7 coefficients')
    words = [0] * 405
    for index in range(405):
        triple = [values[channel * 405 + index] for channel in range(3)]
        if 1 <= level <= 7:
            triple = [value * level >> 3 for value in triple]
        words[_position(index)] = sum((value & 127) << shift
                                      for value, shift in zip(triple, (22, 12, 2)))
    return struct.pack('<405I', *words)


def verify_candidate(evaluator=compact, raw=None, random_points=64):
    """Reject a formula/axis regression against stored nodes and exact interiors.

    The truth is the pinned dense table. Evaluators receive an (a,b,c) tuple.
    Raises ValueError at the first mismatch rather than returning a soft warning.
    """
    raw = read_stock04() if raw is None else raw
    if type(random_points) is not int or not 0 <= random_points <= 4096:
        raise ValueError('Invalid rational sample count')
    groups = [('nodes', product(range(5), range(9), range(9))),
              ('half_step_faces_edges_and_cell_centers',
               product((Fraction(i, 2) for i in range(9)),
                       (Fraction(i, 2) for i in range(17)),
                       (Fraction(i, 2) for i in range(17))))]
    rng = Random(20261102)
    groups.append(('rational_interiors',
                   [(Fraction(rng.randrange(125), 31), Fraction(rng.randrange(297), 37),
                     Fraction(rng.randrange(329), 41)) for _ in range(random_points)]))
    counts = {}
    for name, points in groups:
        count = 0
        for point in points:
            expected = dense(point, raw)
            actual = tuple(evaluator(point))
            if actual != expected:
                raise ValueError(f'stock04 {name} mismatch at {point}: {actual} != {expected}')
            count += 1
        counts[name] = count
    return counts


def audit():
    """Run once before fitting; return a JSON-safe limited-scope certificate."""
    raw = read_stock04()
    counts = verify_candidate(raw=raw)
    # Formula-generated nodes must reproduce the original channel-planar bytes.
    triples = [compact(point) for point in product(range(5), range(9), range(9))]
    planar = struct.pack('<1215b', *(int(point[channel]) for channel in range(3) for point in triples))
    if planar != raw:
        raise ValueError('stock04 channel-planar layout mismatch')
    permutation = [_position(i) for i in range(405)]
    if (sorted(permutation) != list(range(405))
            or sha256(struct.pack('<405H', *permutation)).hexdigest() != PERMUTATION_SHA256):
        raise ValueError('stock04 native parity permutation mismatch')
    packed = pack_hardware(raw)
    if sha256(packed).hexdigest() != PACKED_SHA256:
        raise ValueError('stock04 native packed bank mismatch')
    # Independent parity-major enumeration and field extraction, not _position.
    words = struct.unpack('<405I', packed)
    physical_order = [a * 81 + b * 9 + c for pa, pb, pc in product(range(2), repeat=3)
                      for a in range(pa, 5, 2) for b in range(pb, 9, 2) for c in range(pc, 9, 2)]
    decoded = [0] * 1215
    for word, index in zip(words, physical_order):
        for channel, shift in enumerate((22, 12, 2)):
            value = word >> shift & 127
            decoded[channel * 405 + index] = value - 128 if value >= 64 else value
    if struct.pack('<1215b', *decoded) != raw:
        raise ValueError('stock04 independent native bank decode mismatch')
    return dict(schema='r5-stock04-training-audit/1', passed=True,
                raw_sha256=RAW_SHA256, shape=list(SHAPE), components=3,
                exact_point_counts=counts, arithmetic='exact rational equality',
                planar_bytes_equal=True, native_parity_indices=405,
                native_packed_bytes=len(packed), native_packed_sha256=PACKED_SHA256,
                independent_parity_decode_equal=True,
                scope='original04 table and compact tensor-linear operator plus known byte layout only',
                native_ISP_pixel_algorithm_proven=False, Edit_equivalence_proven=False)
