"""参考颜色子链事务；单色公开捕获不代替完整JPG或场景验收。"""
import ctypes as c
import json
from pathlib import Path
import subprocess

import pytest

from test_edit_reference import (Matrix, Area, Chroma, YGamma, matrix_parameters,
                                 u16, unpack)

HOME = Path(__file__).resolve().parents[1]


class Chain(c.Structure):
    _fields_ = [('matrix', Matrix), ('main_gamma', c.c_void_p), ('y_gamma', c.c_void_p),
                ('main_entries', c.c_size_t), ('y_entries', c.c_size_t),
                ('cc1', c.c_int16*8), ('luma', c.c_int16*3), ('keep_unclipped', c.c_uint16),
                ('area', Area), ('chroma', Chroma), ('levels', YGamma)]


class Work(c.Structure):
    _fields_ = [('a', c.c_uint16*(4096*3)), ('b', c.c_uint16*(4096*3))]


def parameters(data):
    matrix, table, angles = matrix_parameters(data)
    main = u16(unpack(data['main_gamma']))
    y = u16(unpack(data['y_gamma']))
    area = data['area_parameters']
    chain = Chain(matrix, c.addressof(main), c.addressof(y), len(main), len(y),
                  (c.c_int16*8)(*data['cc1']), (c.c_int16*3)(*data['luma']),
                  data['keep_unclipped'],
                  Area((c.c_float*16)(*area['coefficients']), area['selector']),
                  Chroma(**data['chroma_expected']), YGamma(**data['y_parameters']))
    return chain, (table, angles, main, y)


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    target = tmp_path_factory.mktemp('edit-chain')/'chain.so'
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                          '-ffp-contract=off', '-shared', '-fPIC',
                          str(HOME/'native/af_edit_reference.c'), str(HOME/'native/af_edit_chain.c'),
                          '-o', str(target)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    lib = c.CDLL(str(target))
    lib.af_edit_ref_color.argtypes = [c.c_void_p, c.c_void_p, c.c_size_t, c.c_size_t,
                                     c.c_void_p, c.c_void_p]
    return lib


def fixture():
    return json.loads((HOME/'tests/fixtures/edit_reference_context4.json').read_text())


def test_explicit_seven_stage_chain_matches_the_published_single_color_patch(api):
    data = fixture()
    chain, tables = parameters(data)
    original = unpack(data['goldens']['matrix16']['input'])
    expected = unpack(data['goldens']['ycc-rgb']['output'])
    # 这里只对原捕获恰好相邻的单色patch作组合回归。
    order = ('matrix16', 'main-gamma', 'rgb-ycc', 'area-comp', 'chroma-suppress', 'y-gamma', 'ycc-rgb')
    for first, second in zip(order, order[1:]):
        assert unpack(data['goldens'][first]['output']) == unpack(data['goldens'][second]['input'])
    assert len({original[i:i+6] for i in range(0, len(original), 6)}) == 1
    source = u16(original)
    result = (c.c_uint16*(len(source)+16))(*([0xa5a5]*(len(source)+16)))
    out = c.byref(result, 16)
    work = Work()
    before = [bytes(v) for v in tables]
    height, width = data['goldens']['matrix16']['shape']
    assert api.af_edit_ref_color(c.byref(chain), source, width, height, c.byref(work), out) == 0
    assert bytes(result)[16:-16] == expected
    assert bytes(result)[:16] == bytes(result)[-16:] == b'\xa5'*16
    assert bytes(source) == original and [bytes(v) for v in tables] == before
    assert c.sizeof(work) == 49152


def test_late_stage_error_overlap_or_invalid_dimensions_never_publish(api):
    data = fixture()
    chain, tables = parameters(data)
    source = u16(unpack(data['goldens']['matrix16']['input']))
    output = (c.c_uint16*len(source))(*([0xa5a5]*len(source)))
    before, work = bytes(output), Work()
    height, width = data['goldens']['matrix16']['shape']
    chain.levels.gain = float('nan')
    assert api.af_edit_ref_color(c.byref(chain), source, width, height, c.byref(work), output) == -1
    assert bytes(output) == before
    chain.levels.gain = data['y_parameters']['gain']
    assert api.af_edit_ref_color(c.byref(chain), source, width, height, c.byref(work), source) == -1
    assert api.af_edit_ref_color(c.byref(chain), source, 4097, 1, c.byref(work), output) == -1
    assert api.af_edit_ref_color(c.byref(chain), source, 1, 0, c.byref(work), output) == -1
    assert api.af_edit_ref_color(c.byref(chain), source, width, height, c.byref(work), c.byref(work)) == -1
    assert bytes(output) == before
