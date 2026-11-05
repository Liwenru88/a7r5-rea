"""由真实参考颜色链生成代表性域表；报告近似残差而非相机标定精度。"""
import ctypes as c
import hashlib
from pathlib import Path
import subprocess

import pytest

from grid_support import Progress
from test_edit_joint import Cache, Work as BuildWork, SOURCES, source, evaluate
from test_reference_joint import Map

HOME = Path(__file__).resolve().parents[1]


class Config(c.Structure):
    _fields_ = [(name, c.c_uint32) for name in ('schema', 'policy', 'base', 'dimension', 'evaluations_per_node')]+[
        ('native_minimum', c.c_uint16*3), ('native_maximum', c.c_uint16*3),
        ('unreachable_tolerance', c.c_float), ('context_sha256', c.c_uint8*32), ('baseline', c.c_void_p)]


class Report(c.Structure):
    _fields_ = [(name, c.c_uint32) for name in ('nodes', 'evaluations', 'unreachable', 'research_only', 'camera_apply_allowed')]+[
        (name, c.c_float) for name in ('mean_max_abs_rgb', 'max_abs_rgb', 'unreachable_tolerance')]+[
        ('native_minimum', c.c_uint16*3), ('native_maximum', c.c_uint16*3)]+[
        (name, c.c_uint8*32) for name in ('context_sha256', 'policy_sha256', 'source_sha256')]


class Buffers(c.Structure):
    _fields_ = [('input_values', c.POINTER(c.c_float)), ('output_values', c.POINTER(c.c_float)),
        ('input_capacity', c.c_size_t), ('output_capacity', c.c_size_t),
        ('input_map', c.POINTER(Map)), ('output_map', c.POINTER(Map)), ('report', c.POINTER(Report))]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    path = tmp_path_factory.mktemp('reference-domain')/'native.so'
    result = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-ffp-contract=off', '-shared', '-fPIC', *[str(HOME/'native'/name) for name in
        [*SOURCES, 'af_reference_domain.c']], '-o', str(path)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    lib = c.CDLL(str(path))
    lib.af_reference_domain_state_bytes.restype = c.c_size_t
    lib.af_reference_domain_work_bytes.restype = c.c_size_t
    lib.af_reference_domain_start.argtypes = [c.c_void_p]*4+[Progress, c.c_void_p]
    lib.af_reference_domain_step.argtypes = [c.c_void_p, c.c_uint32]
    lib.af_edit_joint_init.argtypes = [c.c_void_p]
    lib.af_edit_joint_prepare.argtypes = [c.c_void_p]*4+[Progress, c.c_void_p]
    lib.af_edit_joint_eval.argtypes = [c.c_void_p]*4
    return lib


def setup(api, dimension=3, budget=96):
    _, edit, owners, recipe = source(); baseline = Cache(); build = BuildWork()
    assert api.af_edit_joint_init(c.byref(baseline)) == 0
    assert api.af_edit_joint_prepare(c.byref(edit), c.byref(recipe), c.byref(build), c.byref(baseline), Progress(), None) == 0
    config = Config(1, 1, 0, dimension, budget, (c.c_uint16*3)(0, 0, 0),
        (c.c_uint16*3)(16383, 16383, 16383), .02, baseline.source_sha256, c.addressof(baseline))
    state = c.create_string_buffer(api.af_reference_domain_state_bytes())
    work = c.create_string_buffer(api.af_reference_domain_work_bytes())
    values = (c.c_float*(dimension**3*3))(); output_values = (c.c_float*24)()
    incoming = Map.from_buffer_copy(b'\x5a'*c.sizeof(Map)); outgoing = Map.from_buffer_copy(b'\x6a'*c.sizeof(Map))
    report = Report.from_buffer_copy(b'\xa5'*c.sizeof(Report))
    buffers = Buffers(values, output_values, len(values), len(output_values), c.pointer(incoming), c.pointer(outgoing), c.pointer(report))
    return state, config, work, buffers, baseline, (values, output_values, incoming, outgoing, report), (edit, owners, recipe, build)


def run(api, job, batch, progress=Progress()):
    state, config, work, buffers, _, outputs, keep = job
    before = tuple(bytes(v) for v in outputs[2:])
    assert api.af_reference_domain_start(state, c.byref(config), c.byref(buffers), work, progress, None) == 1
    for _ in range(125+config.dimension**3*config.evaluations_per_node):
        result = api.af_reference_domain_step(state, batch)
        if result == 0: return
        assert result == 1 and tuple(bytes(v) for v in outputs[2:]) == before
    pytest.fail('超过已声明的有限候选预算')


@pytest.mark.parametrize('batch', [1, 7, 64])
def test_actual_reference_chain_generates_hashed_maps_and_honest_inverse_errors(api, batch):
    job = setup(api); state, config, work, buffers, baseline, outputs, keep = job
    history=[]; run(api, job, batch, Progress(lambda _, done, total: history.append((done, total)) or 0))
    values, output_values, incoming, outgoing, report = outputs
    assert incoming.dimension == 3 and incoming.input_domain == 1 and incoming.output_domain == 2
    assert outgoing.dimension == 2 and outgoing.input_domain == 3 and outgoing.output_domain == 1
    assert bytes(incoming.context_sha256) == bytes(baseline.source_sha256) == bytes(outgoing.context_sha256)
    assert bytes(incoming.data_sha256) == hashlib.sha256(bytes(values)).digest()
    assert bytes(outgoing.data_sha256) == hashlib.sha256(bytes(output_values)).digest()
    assert bytes(incoming.source_sha256) == bytes(outgoing.source_sha256) == bytes(report.source_sha256)
    assert bytes(report.policy_sha256).hex() == 'c3d987644e9de046837c830a32dc3b451c8c699e0c020b141d2f3c1099406788'
    assert report.research_only == 1 and report.camera_apply_allowed == 0 and report.nodes == 27
    assert 125 <= report.evaluations <= 125+27*96
    assert all(a[0] <= b[0] <= b[1] for a, b in zip(history, history[1:]))
    assert history[-1][0] == history[-1][1]
    errors=[]
    for index in range(27):
        point=[values[index*3+i] for i in range(3)]
        assert all(v == int(v) and 0 <= v <= 16383 for v in point)
        actual=evaluate(api, baseline, [int(v) for v in point])
        target=(index%3/2, index//3%3/2, index//9/2)
        errors.append(max(abs(actual[i]/16383-target[i]) for i in range(3)))
    assert report.mean_max_abs_rgb == pytest.approx(sum(errors)/27, abs=1e-7)
    assert report.max_abs_rgb == pytest.approx(max(errors), abs=1e-7)
    assert report.unreachable == sum(error > config.unreachable_tolerance for error in errors)
    assert api.af_reference_domain_step(state, batch) == -5


@pytest.mark.parametrize('failure', ['cancel', 'stale', 'alias', 'bounds'])
def test_cancel_bad_inputs_and_source_change_do_not_publish_maps(api, failure):
    job=setup(api, dimension=2, budget=12)
    state, config, work, buffers, baseline, outputs, keep=job
    before=tuple(bytes(v) for v in outputs[2:])
    if failure == 'alias':
        buffers.output_values=buffers.input_values
        assert api.af_reference_domain_start(state, c.byref(config), c.byref(buffers), work, Progress(), None) == -1
    elif failure == 'bounds':
        config.native_minimum[2]=config.native_maximum[2]
        assert api.af_reference_domain_start(state, c.byref(config), c.byref(buffers), work, Progress(), None) == -1
    else:
        cancelled=[False]; callback=Progress(lambda _, done, total: int(cancelled[0]))
        assert api.af_reference_domain_start(state, c.byref(config), c.byref(buffers), work, callback, None) == 1
        assert api.af_reference_domain_start(state, c.byref(config), c.byref(buffers), work, callback, None) == -4
        assert api.af_reference_domain_step(state, 7) == 1
        if failure == 'cancel': cancelled[0]=True; expected=-20
        else: baseline.source_sha256[0] ^= 1; expected=-5
        assert api.af_reference_domain_step(state, 7) == expected
    assert tuple(bytes(v) for v in outputs[2:]) == before
