"""实际CUBE导入流程使用受约束求解，仍输出完整配方与独立误差。"""
import ctypes as c
import hashlib
from pathlib import Path
import subprocess

import pytest

from grid_support import Progress
from import_support import Asset, Candidate, ImportWork, bind
from joint_support import Predict
from test_native_import import request

HOME = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    output = tmp_path_factory.mktemp('basis-import') / 'native.so'
    names = ('af_joint.c', 'af_joint_fit.c', 'af_joint_basis.c', 'af_joint_asset.c',
        'af_joint_report.c', 'af_import.c', 'af_grid.c', 'af_grid_fit.c', 'af_cube.c',
        'af_sha256.c', 'af_slots.c', 'af_document.c', 'af_record.c', 'af_store.c',
        'af_persist.c', 'af_posix.c', 'af_ui.c')
    run = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-DAF_JOINT_BASIS406', '-shared', '-fPIC',
        *[str(HOME / 'native' / n) for n in names],
        str(HOME / 'tests/native_joint_target.c'), '-o', str(output)],
        capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    lib = bind(c.CDLL(str(output)))
    lib.af_import_state_bytes.restype = c.c_size_t
    lib.af_import_start.argtypes = [c.c_void_p, c.c_void_p, c.c_void_p, c.c_size_t,
        c.c_void_p, c.c_void_p, Progress, c.c_void_p]
    lib.af_import_step.argtypes = [c.c_void_p, c.c_uint32]
    return lib


def execute(api, batch, cancel=False):
    q = request(api)
    violations = []

    def predict(ctx, recipe, rgb, out):
        r = recipe.contents
        if (list(r.matrix[:6]) != list(r.matrix[6:12]) or
            list(r.matrix[:6]) != list(r.matrix[12:18]) or
            list(r.cc1[:8]) != list(r.cc1[8:16]) or
            list(r.cc1[:8]) != list(r.cc1[16:24])):
            violations.append('端点增量没有共享')
        return api.af_joint_synthetic_predict(ctx, recipe, rgb, out)

    callback = Predict(predict)
    q._model.predict = callback
    state = c.create_string_buffer(api.af_import_state_bytes())
    storage, work = (c.c_float * 24)(), ImportWork()
    out = Candidate.from_buffer_copy(b'\x5a' * c.sizeof(Candidate))
    previous = bytes(out)
    progress = Progress(lambda _, done, total: int(cancel and done > 1))
    assert api.af_import_start(state, c.byref(q), storage, 24,
        c.byref(work), c.byref(out), progress, None) == 1
    for _ in range(100):
        result = api.af_import_step(state, batch)
        if result != 1:
            break
        assert bytes(out) == previous
    else:
        pytest.fail('导入没有在预算内完成')
    if cancel:
        assert result == -20 and bytes(out) == previous
    else:
        assert result == 0
        assert out.fit.evaluations == 65 and out.fit.attempted_components == 15
        assert out.fit.final_mse <= out.fit.initial_mse
        assert out.validation.samples == 4
        asset = Asset()
        assert api.af_joint_asset_decode(out.image, 1943, c.byref(asset)) == 0
        assert bytes(out.initial.payload_sha256) == hashlib.sha256(bytes(out.image)).digest()
    assert not violations
    return bytes(out)


def test_basis_is_used_by_real_import_and_batch_size_does_not_change_saved_candidate(api):
    assert execute(api, 1) == execute(api, 64)


def test_basis_import_cancel_does_not_publish(api):
    execute(api, 3, cancel=True)
