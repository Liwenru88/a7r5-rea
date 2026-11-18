"""真实原生CUBE解析/求值契约，不把三线性插值当作ISP拟合。"""
import ctypes as c
from pathlib import Path
import shutil
import subprocess

import pytest

NATIVE = Path(__file__).resolve().parents[1] / 'native'


class Cube(c.Structure):
    _fields_ = [('dimension', c.c_uint32), ('domain_min', c.c_float*3),
                ('domain_max', c.c_float*3), ('values', c.POINTER(c.c_float))]


class Limits(c.Structure):
    _fields_ = [('max_dimension', c.c_uint32), ('max_bytes', c.c_size_t)]


@pytest.fixture(scope='module')
def lib(tmp_path_factory):
    compiler = shutil.which('clang') or shutil.which('cc')
    assert compiler
    output = tmp_path_factory.mktemp('af-cube') / 'af_cube.so'
    subprocess.run([compiler, '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                    '-fPIC', '-shared', str(NATIVE/'af_cube.c'), '-o', str(output)],
                   check=True, capture_output=True, text=True)
    api = c.CDLL(str(output))
    api.af_cube_parse.argtypes = [c.c_char_p, c.c_size_t, c.POINTER(Cube),
                                 c.POINTER(c.c_float), c.c_size_t, Limits]
    api.af_cube_eval.argtypes = [c.POINTER(Cube), c.POINTER(c.c_float), c.POINTER(c.c_float)]
    return api


def source():
    # 各输出通道来自不同输入轴，独立期望可捕获CUBE红轴最快的排序错误。
    lines = ['# 非对称参考', 'TITLE "axis test"', 'LUT_3D_SIZE 2']
    for b in (0, 1):
        for g in (0, 1):
            for r in (0, 1):
                lines.append(f'{0.1+0.5*b} {0.2+0.4*r} {0.3+0.3*g}')
    return ('\r\n'.join(lines)+'\n').encode()


def parse(lib, raw, *, capacity=24, dimension=33, max_bytes=65536):
    storage = (c.c_float*capacity)()
    cube = Cube()
    result = lib.af_cube_parse(raw, len(raw), c.byref(cube), storage, capacity, Limits(dimension, max_bytes))
    return result, cube, storage


def evaluate(lib, cube, rgb):
    output = (c.c_float*3)()
    assert lib.af_cube_eval(c.byref(cube), (c.c_float*3)(*rgb), output) == 0
    return list(output)


def test_axis_order_interpolation_and_domain_clamp(lib):
    raw = source()
    result, cube, storage = parse(lib, raw)
    assert result == 0 and cube.dimension == 2
    assert evaluate(lib, cube, (0.25, 0.5, 0.75)) == pytest.approx((0.475,0.3,0.45), abs=1e-6)
    assert evaluate(lib, cube, (-1, 2, 0)) == pytest.approx((0.1,0.2,0.6), abs=1e-6)
    domain = raw.replace(b'LUT_3D_SIZE 2', b'DOMAIN_MIN -1 0 0\nDOMAIN_MAX 1 2 4\nLUT_3D_SIZE 2')
    result, cube, storage = parse(lib, domain)
    assert result == 0
    assert evaluate(lib, cube, (0, 1, 2)) == pytest.approx((0.35,0.4,0.45), abs=1e-6)


@pytest.mark.parametrize('change', [
    lambda raw: raw.replace(b'LUT_3D_SIZE 2', b'LUT_1D_SIZE 2'),
    lambda raw: raw.replace(b'LUT_3D_SIZE 2', b'LUT_3D_SIZE 2\nLUT_3D_SIZE 2'),
    lambda raw: raw+b'0 0 0\n',
    lambda raw: raw.rsplit(b'\r\n', 1)[0]+b'\n',
    lambda raw: raw.replace(b'LUT_3D_SIZE 2', b'DOMAIN_MIN 1 0 0\nLUT_3D_SIZE 2'),
    lambda raw: raw.replace(b'0.1 ', b'nan ', 1),
    lambda raw: raw.replace(b'0.1 ', b'1e99 ', 1),
    lambda raw: raw+b'\x00',
    lambda raw: raw+b'LUT_3D_INPUT_RANGE 0 1\n',
], ids=['1d','duplicate-size','extra-row','missing-row','bad-domain','nan','overflow','nul','unknown-directive'])
def test_rejects_invalid_cube_without_publishing_it(lib, change):
    result, cube, storage = parse(lib, change(source()))
    assert result < 0
    assert cube.dimension == 0 and not cube.values


def test_budget_and_capacity_rejection_before_sample_write(lib):
    raw = source()
    for kwargs in ({'dimension':1}, {'max_bytes':len(raw)-1}, {'capacity':23}):
        assert parse(lib, raw, **kwargs)[0] < 0
    storage = (c.c_float*23)(*([42]*23))
    cube = Cube()
    assert lib.af_cube_parse(raw, len(raw), c.byref(cube), storage, 23, Limits(33, 65536)) < 0
    assert list(storage) == [42]*23


def test_rejects_nonfinite_evaluation(lib):
    result, cube, storage = parse(lib, source())
    assert result == 0
    for number in (float('nan'), float('inf'), -float('inf')):
        output = (c.c_float*3)(42,42,42)
        assert lib.af_cube_eval(c.byref(cube), (c.c_float*3)(number,0,0), output) < 0
        assert list(output) == [42,42,42]
