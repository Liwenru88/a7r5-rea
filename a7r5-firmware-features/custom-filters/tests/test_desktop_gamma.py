"""完整Gamma宿主研究：真实数值链、表示拒绝与不覆盖输出；不执行目标。"""
import ctypes as c
import importlib.util
from pathlib import Path

import pytest

HOME = Path(__file__).resolve().parents[1]


@pytest.fixture(scope='module')
def tool():
    spec = importlib.util.spec_from_file_location('desktop_gamma_tool', HOME / 'tools/compare_gamma.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope='module')
def solver(tool):
    with tool.fit_recipe.native_solver(16) as value:
        yield tool.bind(value)


def cube(warm=False):
    rows = ['LUT_3D_SIZE 2']
    for b in range(2):
        for g in range(2):
            for r in range(2):
                rows.append(f'{r * .94 if warm else r} {g * .98 if warm else g} {b * .90 if warm else b}')
    return ('\n'.join(rows) + '\n').encode()


def load_identity(solver, tool):
    source = cube()
    raw = c.create_string_buffer(source)
    assert not solver.api.desktop_load_cube(solver.state, raw, len(source))
    vector, grid = solver.vector(), tool.fit_recipe.GRID()
    curve, axis = tool.seed(solver, vector, grid)
    return vector, grid, curve, axis


def test_complete_curve_uses_real_model_and_native_axis(solver, tool):
    vector, grid, curve, axis = load_identity(solver, tool)
    assert axis[127:] == [61440, 65535]
    assert len(set(b - a for a, b in zip(axis, axis[1:]))) > 3
    original, changed = (c.c_double * 2)(), (c.c_double * 2)()
    assert not solver.api.desktop_gamma_loss(solver.state, vector, grid, tool.CURVE(*curve), 0, original)
    trial = tool.expand_curve(curve, axis, [1024] * 17)
    assert trial != curve
    assert not solver.api.desktop_gamma_loss(solver.state, vector, grid, tool.CURVE(*trial), 0, changed)
    assert original[0] == 0 and changed[0] > 0


@pytest.mark.parametrize('bad', ['origin', 'decreasing', '18bit', 'edit_range', 'independent_61440', 'source'])
def test_bad_curve_or_source_never_publishes_output(solver, tool, bad):
    vector, grid, curve, _ = load_identity(solver, tool)
    record = (c.c_uint8 * 576)()
    assert not solver.api.desktop_gamma_source(solver.state, record)
    if bad == 'origin':
        curve[0] = 1
    elif bad == 'decreasing':
        curve[64] = curve[63] - 1
    elif bad == '18bit':
        curve[128] = 262144
    elif bad == 'edit_range':
        curve[128] = 131072
    elif bad == 'independent_61440':
        curve[127] += 1
    else:
        record[575] ^= 1
    converted = (c.c_uint8 * 1024)(*[0xa5] * 1024)
    before = bytes(converted)
    assert solver.api.af_edit_cp_gamma(record, 576, tool.CURVE(*curve), 129, converted, None, None) != 0
    assert bytes(converted) == before
    if bad != 'source':
        output = (c.c_double * 2)(17.0, 23.0)
        assert solver.api.desktop_gamma_loss(solver.state, vector, grid, tool.CURVE(*curve), 0, output) != 0
        assert list(output) == [17.0, 23.0]
        report = (c.c_double * 8)(*[31.0] * 8)
        assert solver.api.desktop_gamma_report(solver.state, vector, grid, tool.CURVE(*curve), 2, report) != 0
        assert list(report) == [31.0] * 8


def test_holdout_cannot_be_used_as_gamma_training_loss(solver, tool):
    vector, grid, curve, _ = load_identity(solver, tool)
    output = (c.c_double * 2)(17, 23)
    assert solver.api.desktop_gamma_loss(solver.state, vector, grid, tool.CURVE(*curve), 2, output) != 0
    assert list(output) == [17, 23]


def test_identity_comparison_equal_budget_and_exclusive_output(solver, tool, tmp_path, monkeypatch):
    stages, reports = [], []
    original = solver.api.desktop_gamma_report

    def observe(*args):
        assert '冻结两臂，最终独立测试' in stages
        reports.append(1)
        return original(*args)

    monkeypatch.setattr(solver.api, 'desktop_gamma_report', observe)
    result = tool.compare(solver, cube(), additional_budget=16, progress=stages.append)
    assert len(reports) == 3
    assert result['research_only'] and result['camera_apply_allowed'] is False
    assert result['test_used_for_selection'] is False
    assert result['three_tone']['evaluations'] == result['full_gamma']['evaluations'] == 16
    assert all(result[key]['test']['delta_e76'][0] == 0 for key in ('three_tone', 'full_gamma'))
    masks = [int(result['splits'][key]['cells'], 16) for key in ('training', 'selection', 'test')]
    assert all(masks) and all(not a & b for i, a in enumerate(masks) for b in masks[:i])
    destination = tmp_path / 'result'
    tool.publish(result, destination)
    files = {p.name: p.read_bytes() for p in destination.iterdir()}
    assert set(files) == {'gamma-comparison.json', 'gamma-curves.json'}
    with pytest.raises(FileExistsError):
        tool.publish(result, destination)
    assert files == {p.name: p.read_bytes() for p in destination.iterdir()}


def test_nonidentity_deterministic_selection_and_cancellation(solver, tool, tmp_path):
    one = tool.compare(solver, cube(True), additional_budget=32)
    two = tool.compare(solver, cube(True), additional_budget=32)
    for kind in ('three_tone', 'full_gamma'):
        assert one[kind] == two[kind]
        assert one[kind]['selected_selection_mse'] <= one[kind]['baseline_selection_mse']
    assert one['full_gamma_curve'] == two['full_gamma_curve']
    assert one['baseline_test']['samples'] > 0
    destination = tmp_path / 'cancelled'
    with pytest.raises(tool.FitCancelled):
        tool.compare(solver, cube(True), additional_budget=16, cancel=lambda: True)
    with pytest.raises(tool.FitCancelled):
        tool.publish(one, destination, cancel=lambda: True)
    assert not destination.exists()
    with pytest.raises(tool.FitError):
        tool.compare(solver, b'LUT_3D_SIZE 2\n0 0 0\n', additional_budget=16)
    assert not destination.exists()


def test_cli_invalid_file_leaves_no_output(tool, tmp_path):
    source = tmp_path / 'identity.cube'
    source.write_bytes(cube())
    link = tmp_path / 'link.cube'
    link.symlink_to(source)
    destination = tmp_path / 'result'
    assert tool.main([str(link), '--output', str(destination)]) == 2
    assert not destination.exists()
