"""参考整数颜色链与真实导入器联验，域查表为明确的数学用例。"""
import ctypes as c
from pathlib import Path
import subprocess

import pytest

from grid_support import Progress
from import_support import bind
from joint_support import Model
from test_native_import import request, convert
import test_reference_joint as reference

HOME = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    output = tmp_path_factory.mktemp('reference-import') / 'native.so'
    names = list(dict.fromkeys([*reference.SOURCES, 'af_reference_joint.c', 'af_joint_basis.c',
        'af_joint_fit.c', 'af_joint_asset.c', 'af_joint_report.c', 'af_import.c',
        'af_grid.c', 'af_grid_fit.c', 'af_cube.c', 'af_slots.c', 'af_document.c',
        'af_record.c', 'af_store.c', 'af_persist.c', 'af_posix.c', 'af_ui.c']))
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-ffp-contract=off', '-DAF_JOINT_BASIS406', '-shared', '-fPIC',
        *[str(HOME / 'native' / n) for n in names], str(HOME / 'tests/native_joint_target.c'),
        '-o', str(output)], capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    lib = bind(c.CDLL(str(output)))
    for name in ('af_reference_joint_state_bytes', 'af_reference_joint_work_bytes'):
        getattr(lib, name).restype = c.c_size_t
    lib.af_reference_joint_init.argtypes = [c.c_void_p] * 4 + [Progress, c.c_void_p]
    lib.af_reference_joint_model.argtypes = [c.c_void_p, c.c_void_p, c.POINTER(Model)]
    lib.af_reference_joint_info.argtypes = [c.c_void_p, c.c_void_p]
    lib.af_edit_joint_init.argtypes = [c.c_void_p]
    lib.af_edit_joint_prepare.argtypes = [c.c_void_p] * 4 + [Progress, c.c_void_p]
    return lib


def test_real_reference_stages_feed_integer_import_and_preserve_research_identity(api):
    state, config, workspace, baseline, candidate, seed, owners = reference.setup(api)
    q = request(api, lambda r, g, b: (r * .97, g * .99, b * .98))
    q.initial.params[:] = config.reference_params
    model = Model()
    assert api.af_reference_joint_model(state, c.byref(q.initial), c.byref(model)) == 0
    q._model = model
    q.model = c.pointer(model)
    q._seed = seed
    q.seed = c.pointer(seed)
    result = convert(api, q)
    assert result.fit.attempted_components == 15
    assert result.fit.final_mse <= result.fit.initial_mse
    assert result.validation.samples == q.validation_count
    assert bytes(result.report.model_sha256) == bytes(model.model_sha256)
    info = reference.Info()
    assert api.af_reference_joint_info(state, c.byref(info)) == 0
    assert info.research_only == 1 and info.camera_apply_allowed == 0
    assert bytes(info.grid_source_sha256) == bytes(config.grid_source_sha256)
    assert bytes(info.input_map_sha256) == bytes(owners[4].data_sha256)
    assert baseline.builds == 1 and candidate.builds > 1


def test_reference_model_binding_rejects_a_different_working_parameter_context(api):
    state, config, workspace, baseline, candidate, seed, owners = reference.setup(api)
    q = request(api)
    q.initial.params[:] = config.reference_params
    q.initial.params[0] = 1
    output = Model.from_buffer_copy(b'\x5a' * c.sizeof(Model))
    before = bytes(output)
    assert api.af_reference_joint_model(state, c.byref(q.initial), c.byref(output)) == -5
    assert bytes(output) == before
