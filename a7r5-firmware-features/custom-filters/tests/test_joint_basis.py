"""17维原生基函数与网格的完整量化搜索；合成后端只验证求解契约。"""
import ctypes as c
from pathlib import Path
import subprocess

import pytest

from grid_support import Cube, Limits, Progress, Sample, cube, samples
from joint_support import Fit, Model, Predict, Recipe, Work, model, seed


HOME = Path(__file__).resolve().parents[1]


class Options(c.Structure):
    _fields_ = [('evaluations', c.c_uint32)] + [
        (name, c.c_uint16) for name in ('tone_step', 'matrix_step', 'cc1_step', 'grid_step')
    ] + [('tone_bound', c.c_uint16 * 3), ('matrix_bound', c.c_uint16), ('cc1_bound', c.c_uint16)]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    destination = tmp_path_factory.mktemp('joint-basis') / 'native.so'
    sources = [HOME / 'native' / name for name in
               ('af_joint.c', 'af_joint_fit.c', 'af_cube.c', 'af_joint_basis.c')]
    result = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
                             '-shared', '-fPIC', *map(str, sources), '-o', str(destination)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    library = c.CDLL(str(destination))
    library.af_cube_parse.argtypes = [c.c_void_p, c.c_size_t, c.POINTER(Cube),
                                     c.c_void_p, c.c_size_t, Limits]
    library.af_joint_basis_state_bytes.restype = c.c_size_t
    library.af_joint_basis_recipe.argtypes = [c.POINTER(Recipe), c.c_void_p, c.POINTER(Recipe)]
    library.af_joint_gamma.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p]
    library.af_joint_basis_start.argtypes = [c.c_void_p, c.POINTER(Model), c.c_uint32,
        c.POINTER(Cube), c.POINTER(Sample), c.c_size_t, c.POINTER(Recipe), c.POINTER(Options),
        c.POINTER(Work), c.POINTER(Recipe), c.POINTER(Fit), Progress, c.c_void_p]
    library.af_joint_basis_step.argtypes = [c.c_void_p, c.c_uint32]
    library.af_joint_basis_fit.argtypes = library.af_joint_basis_start.argtypes[1:]
    return library


def setup(api, failure=None):
    state = c.create_string_buffer(api.af_joint_basis_state_bytes())
    original = seed()
    violations = []
    def predict(_, recipe, rgb, output):
        if failure and failure():
            return -6
        value = recipe.contents
        for count, field in ((6, value.matrix), (8, value.cc1)):
            for index in range(count):
                if len({field[index + count * endpoint] for endpoint in range(3)}) != 1:
                    violations.append('端点增量不一致')
                    return -6
        gain = value.gamma[128] / 131072
        r, g, b = (rgb[index] for index in range(3))
        values = (r * gain + value.matrix[0] * (g-r) / 1024,
                  g * gain + value.cc1[0] * (b-g) / 1024,
                  b * gain + value.grid[0] * r*b / 256)
        for index in range(3):
            output[index] = values[index]
        return 0
    callback = Predict(predict)
    backend = model(callback)
    target, storage, _ = cube(api, lambda r, g, b:
        (r * 1.015625 + (g-r)/64, g * 1.015625 + (b-g)/64,
         b * 1.015625 + r*b/64))
    training = samples([(.1+.6*r, .15+.55*g, .12+.5*b)
                        for b in range(2) for g in range(2) for r in range(2)])
    options = Options(65, 16, 16, 16, 4, (64, 128, 128), 64, 64)
    workspace = Work()
    output = Recipe.from_buffer_copy(b'\x5a' * c.sizeof(Recipe))
    statistics = Fit.from_buffer_copy(b'\xa5' * c.sizeof(Fit))
    args = (c.byref(backend), 0, c.byref(target), training, len(training), c.byref(original),
            c.byref(options), c.byref(workspace), c.byref(output), c.byref(statistics))
    return state, callback, backend, original, target, storage, training, options, workspace, output, statistics, violations, args


@pytest.mark.parametrize('batch', [1, 7, 64])
def test_shared_basis_improves_all_four_families_and_yields_identical_integer_result(api, batch):
    state, callback, backend, original, target, storage, training, options, workspace, output, stats, violations, args = setup(api)
    before = bytes(output), bytes(stats)
    assert api.af_joint_basis_start(state, *args, Progress(), None) == 1
    assert (bytes(output), bytes(stats)) == before
    assert api.af_joint_basis_step(state, 0) == -1
    assert api.af_joint_basis_step(state, 65) == -1
    for _ in range(65):
        result = api.af_joint_basis_step(state, batch)
        if result == 0:
            break
        assert result == 1 and (bytes(output), bytes(stats)) == before
    else:
        pytest.fail('超过有界候选预算仍未完成')
    assert not violations
    assert stats.evaluations == 65 and stats.attempted_components == 15
    assert all(value > 0 for value in stats.accepted)
    assert stats.final_mse < stats.initial_mse * .1
    assert stats.research_only == 1
    assert api.af_joint_basis_step(state, 1) == -5
    actual = bytes(output), bytes(stats)
    assert api.af_joint_basis_fit(*args, Progress(), None) == 0
    assert (bytes(output), bytes(stats)) == actual


@pytest.mark.parametrize('kind', ['cancel', 'model', 'reentry'])
def test_failed_or_reentrant_work_never_publishes_partial_candidate(api, kind):
    broken = [False]
    items = setup(api, lambda: broken[0] and kind == 'model')
    state, callback, backend, original, target, storage, training, options, workspace, output, stats, violations, args = items
    before = bytes(output), bytes(stats)
    reentries = []
    def progress(_, done, total):
        if broken[0] and kind == 'reentry':
            reentries.append(api.af_joint_basis_step(state, 1))
        return int(broken[0] and kind == 'cancel')
    watch = Progress(progress)
    assert api.af_joint_basis_start(state, *args, watch, None) == 1
    assert api.af_joint_basis_start(state, *args, watch, None) == -4
    assert api.af_joint_basis_step(state, 1) == 1
    broken[0] = True
    expected = -20 if kind == 'cancel' else -22 if kind == 'model' else 0
    assert api.af_joint_basis_step(state, 64) == expected
    if kind != 'reentry':
        assert (bytes(output), bytes(stats)) == before
        broken[0] = False
        assert api.af_joint_basis_start(state, *args, watch, None) == 1
        assert api.af_joint_basis_step(state, 64) == 0
    else:
        assert reentries and set(reentries) == {-4}
    assert not violations


def test_basis_builds_from_seed_preserves_endpoint_differences_and_rejects_overflow(api):
    source = seed()
    source.matrix[:] = [endpoint*7 + index for endpoint in range(3) for index in range(6)]
    source.cc1[:] = [endpoint*5 - index for endpoint in range(3) for index in range(8)]
    source.grid[21] = -7
    controls = (c.c_int16*17)(16, -8, 12, *range(1, 7), *range(-4, 4))
    output = Recipe()
    assert api.af_joint_basis_recipe(c.byref(source), controls, c.byref(output)) == 0
    expected_gamma = (c.c_uint32*129)()
    assert api.af_joint_gamma(source.gamma, controls, expected_gamma) == 0
    assert list(output.gamma) == list(expected_gamma)
    assert list(output.matrix) == [source.matrix[i] + controls[3+i % 6] for i in range(18)]
    assert list(output.cc1) == [source.cc1[i] + controls[9+i % 8] for i in range(24)]
    assert bytes(output.grid) == bytes(source.grid)
    before = bytes(output)
    source.matrix[12] = 1024
    assert api.af_joint_basis_recipe(c.byref(source), controls, c.byref(output)) == -21
    assert bytes(output) == before
    assert api.af_joint_basis_recipe(c.byref(source), controls, c.byref(source)) == -1


def test_invalid_admission_or_alias_is_rejected_before_predicting(api):
    items = setup(api)
    state, callback, backend, original, target, storage, training, options, workspace, output, stats, violations, args = items
    before = bytes(output), bytes(stats)
    backend.components = 8
    assert api.af_joint_basis_start(state, *args, Progress(), None) == -1
    backend.components = 15
    options.tone_bound[0] = 1025
    assert api.af_joint_basis_start(state, *args, Progress(), None) == -1
    options.tone_bound[0] = 64
    alias = list(args)
    alias[-2] = c.cast(c.byref(workspace), c.POINTER(Recipe))
    assert api.af_joint_basis_start(state, *alias, Progress(), None) == -1
    assert (bytes(output), bytes(stats)) == before


def test_minimum_import_budget_covers_all_families_and_enforces_shared_limits(api):
    items = setup(api)
    state, callback, backend, original, target, storage, training, options, workspace, output, stats, violations, args = items
    options.evaluations = 9
    options.matrix_bound = options.cc1_bound = 8
    assert api.af_joint_basis_start(state, *args, Progress(), None) == 1
    assert api.af_joint_basis_step(state, 8) == 0
    assert stats.evaluations == 9 and stats.attempted_components == 15
    assert stats.rejected >= 4
    assert list(output.matrix) == list(original.matrix)
    assert list(output.cc1) == list(original.cc1)
    assert stats.final_mse <= stats.initial_mse
    assert not violations
