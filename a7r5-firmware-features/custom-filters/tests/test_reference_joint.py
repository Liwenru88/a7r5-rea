"""显式域查表、真实参考颜色链和经验网格的整体近似；不授予机身资格。"""
import ctypes as c
import hashlib
from pathlib import Path
import struct
import subprocess

import pytest

from grid_support import Model as GridModel, Progress, reference_model
from joint_support import Recipe, Model as JointModel
from test_native_slots import Preset
from test_edit_joint import Cache, Work as EditWork, EvalWork, SOURCES, source, evaluate

HOME = Path(__file__).resolve().parents[1]


class Map(c.Structure):
    _fields_ = [(k, c.c_uint32) for k in ('schema', 'input_domain', 'output_domain', 'dimension', 'base')]+[
        ('minimum', c.c_float*3), ('maximum', c.c_float*3), ('values', c.POINTER(c.c_float)),
        ('count', c.c_size_t), ('source_sha256', c.c_uint8*32),
        ('context_sha256', c.c_uint8*32), ('data_sha256', c.c_uint8*32)]


class Config(c.Structure):
    _fields_ = [(k, c.c_uint32) for k in ('schema', 'flags', 'base', 'grid_base')]+[
        ('reference_params', c.c_int8*8), ('target_cp_sha256', c.c_uint8*32),
        ('edit_source_sha256', c.c_uint8*32), ('grid_source_sha256', c.c_uint8*32)]+[
        (k, c.c_void_p) for k in ('edit', 'seed', 'baseline', 'input_map', 'output_map', 'grid')]


class Info(c.Structure):
    _fields_ = [(k, c.c_uint32) for k in ('schema', 'flags', 'base', 'grid_base', 'research_only', 'camera_apply_allowed')]+[
        ('reference_params', c.c_int8*8)]+[(k, c.c_uint8*32) for k in (
            'target_cp_sha256', 'model_sha256', 'edit_source_sha256', 'grid_source_sha256',
            'input_map_sha256', 'output_map_sha256')]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    output = tmp_path_factory.mktemp('reference-joint')/'native.so'
    names = [*SOURCES, 'af_grid.c', 'af_cube.c', 'af_slots.c', 'af_reference_joint.c']
    result = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-ffp-contract=off', '-shared', '-fPIC', *[str(HOME/'native'/n) for n in names],
        '-o', str(output)], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    lib = c.CDLL(str(output))
    lib.af_reference_joint_state_bytes.restype = c.c_size_t
    lib.af_reference_joint_work_bytes.restype = c.c_size_t
    lib.af_reference_joint_init.argtypes = [c.c_void_p]*4+[Progress, c.c_void_p]
    lib.af_reference_joint_prepare.argtypes = [c.c_void_p]*2+[Progress, c.c_void_p]
    lib.af_reference_joint_predict.argtypes = [c.c_void_p]*4
    lib.af_reference_joint_info.argtypes = [c.c_void_p, c.POINTER(Info)]
    lib.af_reference_joint_model.argtypes = [c.c_void_p, c.POINTER(Preset), c.POINTER(JointModel)]
    lib.af_grid_model_valid.argtypes = [c.POINTER(GridModel)]
    lib.af_reference_map_eval.argtypes = [c.POINTER(Map), c.c_void_p, c.c_void_p]
    lib.af_edit_joint_init.argtypes = [c.c_void_p]
    lib.af_edit_joint_prepare.argtypes = [c.c_void_p]*4+[Progress, c.c_void_p]
    lib.af_edit_joint_eval.argtypes = [c.c_void_p]*4
    return lib


def digest(label):
    return hashlib.sha256(label.encode()).digest()


def table(context, *, incoming):
    dimension = 3
    rows = []
    for z in range(dimension):
        for y in range(dimension):
            for x in range(dimension):
                p = (x/2, y/2, z/2)
                if incoming:
                    rows += [1000+5000*p[0], 900+4500*p[1], 700+6000*p[2]]
                else:
                    # 明确的测试域映射，故意不等同于码值除16383。
                    rows += [.04+.85*p[0]**2, .03+.9*p[1], .02+.9*p[2]**.5]
    values = (c.c_float*len(rows))(*rows)
    value = Map(1, 1 if incoming else 3, 2 if incoming else 1, dimension, 0,
        (c.c_float*3)(0, 0, 0), (c.c_float*3)(*([1]*3 if incoming else [16383]*3)), values, len(rows),
        (c.c_uint8*32).from_buffer_copy(digest('independent-domain-test-only')),
        (c.c_uint8*32).from_buffer_copy(context),
        (c.c_uint8*32).from_buffer_copy(hashlib.sha256(bytes(values)).digest()))
    return value, values


def paired_table(api, baseline):
    native_points=((1736, 1000, 9000), (4000, 1100, 2000), (6000, 11000, 5000),
        (8000, 8000, 8000), (2000, 9000, 500))
    pairs={}
    for native in native_points:
        encoded=evaluate(api, baseline, native)
        rgb=tuple(c.c_float(v/16383).value for v in encoded)
        pairs.setdefault(rgb, native)
    rows=[(*rgb, *pairs[rgb]) for rgb in sorted(pairs)]
    flat=[v for row in rows for v in row];values=(c.c_float*len(flat))(*flat)
    result=Map(2, 1, 2, 0, 0, (c.c_float*3)(0, 0, 0), (c.c_float*3)(1, 1, 1), values, len(values),
        (c.c_uint8*32).from_buffer_copy(digest('actual-C-context4-forward-plus-explicit-upstream-preview-policy')),
        baseline.source_sha256,
        (c.c_uint8*32).from_buffer_copy(hashlib.sha256(bytes(values)).digest()))
    return result, values, rows


def setup(api):
    data, edit, owners, seed = source()
    baseline = Cache(); candidate = Cache(); construction = EditWork()
    assert api.af_edit_joint_init(c.byref(baseline)) == 0
    assert api.af_edit_joint_prepare(c.byref(edit), c.byref(seed), c.byref(construction),
        c.byref(baseline), Progress(), None) == 0
    incoming, input_values = table(bytes(baseline.source_sha256), incoming=True)
    outgoing, output_values = table(bytes(baseline.source_sha256), incoming=False)
    grid, grid_source = reference_model()
    config = Config(1, 15, 0, 1, (c.c_int8*8)(0, 0, 0, 0, 0, 0, 1, 0),
        (c.c_uint8*32).from_buffer_copy(bytes.fromhex('18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97')),
        baseline.source_sha256, (c.c_uint8*32).from_buffer_copy(bytes.fromhex(grid_source['source_sha256'])),
        *[c.addressof(v) for v in (edit, seed, baseline, incoming, outgoing, grid)])
    state = c.create_string_buffer(api.af_reference_joint_state_bytes())
    work = c.create_string_buffer(api.af_reference_joint_work_bytes())
    assert api.af_reference_joint_init(state, c.byref(config), work, c.byref(candidate), Progress(), None) == 0
    keep = (data, edit, owners, construction, incoming, input_values, outgoing, output_values, grid, grid_source)
    return state, config, work, baseline, candidate, seed, keep


def predict(api, state, recipe, point):
    rgb = (c.c_float*3)(*point); result = (c.c_float*3)(99, 99, 99)
    assert api.af_reference_joint_predict(state, c.byref(recipe), rgb, result) == 0
    return tuple(result)


def interpolate(value, point):
    # 独立逐节点三线性权重，用于检查通道和红轴最快的排列。
    n = value.dimension
    result = [0., 0., 0.]
    q = [(point[i]-value.minimum[i])/(value.maximum[i]-value.minimum[i])*(n-1) for i in range(3)]
    for z in range(n):
        for y in range(n):
            for x in range(n):
                weight = max(0, 1-abs(q[0]-x))*max(0, 1-abs(q[1]-y))*max(0, 1-abs(q[2]-z))
                index = ((z*n+y)*n+x)*3
                for channel in range(3):
                    result[channel] += weight*value.values[index+channel]
    return result


def grid_prediction(model, table_values, point):
    coordinate = [sum(model.coordinates[i*4+j]*point[j] for j in range(3))+
        model.coordinates[i*4+3] for i in range(3)]
    at = [min(limit, max(0., coordinate[i]*limit+(4 if i else 0)))
        for i, limit in enumerate((4, 8, 8))]
    low = [min(int(value), limit-1) for value, limit in zip(at, (4, 8, 8))]
    fraction = [value-index for value, index in zip(at, low)]
    delta = [0., 0., 0.]
    for y in (0, 1):
        for u in (0, 1):
            for v in (0, 1):
                index = (low[0]+y)*81+(low[1]+u)*9+low[2]+v
                weight = (fraction[0] if y else 1-fraction[0])*(fraction[1] if u else 1-fraction[1])*(fraction[2] if v else 1-fraction[2])
                for channel in range(3): delta[channel] += weight*table_values[channel*405+index]
    result = list(point)
    for channel in range(3):
        for output in range(3):
            response = model.response[channel*3+output]
            if model.smooth:
                response += sum((point[j]-.5)*model.response[(3+3*channel+j)*3+output] for j in range(3))
            result[output] += delta[channel]*response/256
    return [min(1., max(0., value)) for value in result]


def test_explicit_mapping_and_zero_delta_anchor_retain_input_without_camera_claim(api):
    state, config, work, baseline, candidate, seed, keep = setup(api)
    for point in ((.2, .3, .8), (.75, .25, .1), (0., 0., 0.), (1., 1., 1.)):
        assert predict(api, state, seed, point) == pytest.approx(point, abs=1e-7)
    info = Info()
    assert api.af_reference_joint_info(state, c.byref(info)) == 0
    assert info.research_only == 1 and info.camera_apply_allowed == 0
    assert info.base == 0 and info.grid_base == 1 and info.flags == 15
    assert bytes(info.grid_source_sha256) == bytes(keep[8].sha256)
    assert api.af_grid_model_valid(c.byref(keep[8])) == -1
    assert bytes(info.edit_source_sha256) == bytes(baseline.source_sha256)
    assert any(info.model_sha256) and bytes(info.model_sha256) != bytes(info.target_cp_sha256)
    incoming, _, outgoing = keep[4:7]
    point = (.12, .63, .84); rgb = (c.c_float*3)(*point); output = (c.c_float*3)()
    assert api.af_reference_map_eval(c.byref(incoming), rgb, output) == 0
    assert list(output) == pytest.approx(interpolate(incoming, point), abs=.001)
    native = (c.c_float*3)(1736, 1000, 9000)
    assert api.af_reference_map_eval(c.byref(outgoing), native, output) == 0
    assert list(output) == pytest.approx(interpolate(outgoing, list(native)), abs=1e-7)
    assert list(output) != pytest.approx([x/16383 for x in native], abs=1e-4)
    before_table = bytes(keep[7])
    assert api.af_reference_joint_info(state, c.cast(keep[7], c.POINTER(Info))) == -1
    assert bytes(keep[7]) == before_table
    preset = Preset(); preset.base = 0; preset.params[:] = config.reference_params
    model = JointModel()
    assert api.af_reference_joint_model(state, c.byref(preset), c.byref(model)) == 0
    assert model.base_mask == 1 and model.components == 15 and model.domain == 1
    assert bytes(model.model_sha256) == bytes(info.model_sha256)
    preset.params[0] = 1
    unchanged = bytes(model)
    assert api.af_reference_joint_model(state, c.byref(preset), c.byref(model)) == -5
    assert bytes(model) == unchanged


def test_each_quantized_component_and_mixed_recipe_use_actual_reference_chain(api):
    state, config, work, baseline, candidate, seed, keep = setup(api)
    points = ((.2, .3, .8), (.75, .25, .1), (.4, .7, .2))
    outputs = {}
    for family in ('gamma', 'matrix', 'cc1', 'grid', 'mixed'):
        recipe = Recipe.from_buffer_copy(seed)
        if family in ('gamma', 'mixed'): recipe.gamma[:] = [v*3//4 for v in seed.gamma]
        if family in ('matrix', 'mixed'): recipe.matrix[6] = 128
        if family in ('cc1', 'mixed'): recipe.cc1[8] = 32; recipe.cc1[12] = 8
        if family in ('grid', 'mixed'): recipe.grid[:] = [8]*1215
        outputs[family] = [predict(api, state, recipe, p) for p in points]
        assert any(abs(actual-expected)>1e-6 for row, point in zip(outputs[family], points)
            for actual, expected in zip(row, point)), family
        # 候选缓存原生部分独立构建；网格不会被三组件适配器静默忽略。
        assert api.af_reference_joint_prepare(state, c.byref(recipe), Progress(), None) == 0
        incoming, _, outgoing = keep[4:7]
        for point, actual in zip(points, outputs[family]):
            native = [int(v+.5) for v in interpolate(incoming, point)]
            old = interpolate(outgoing, evaluate(api, baseline, native))
            new = interpolate(outgoing, evaluate(api, candidate, native))
            anchored = [min(1., max(0., point[i]+new[i]-old[i])) for i in range(3)]
            if family in ('grid', 'mixed'):
                expected = grid_prediction(keep[8], list(recipe.grid), anchored)
            else:
                expected = anchored
            assert actual == pytest.approx(expected, abs=2e-6)
    assert outputs['mixed'] != outputs['grid']


@pytest.mark.parametrize('failure', ['domain', 'context', 'data', 'cross-base', 'source', 'grid-source', 'grid-base'])
def test_bad_mapping_context_or_undeclared_cross_base_never_publishes_state(api, failure):
    state, config, work, baseline, candidate, seed, keep = setup(api)
    state2 = c.create_string_buffer(api.af_reference_joint_state_bytes())
    candidate2 = Cache(); work2 = c.create_string_buffer(api.af_reference_joint_work_bytes())
    if failure == 'domain': keep[4].input_domain = 3
    elif failure == 'context': keep[6].context_sha256[0] ^= 1
    elif failure == 'data': keep[5][0] += 1
    elif failure == 'cross-base': config.flags = 7
    elif failure == 'source': config.edit_source_sha256[0] ^= 1
    elif failure == 'grid-source': config.grid_source_sha256[0] ^= 1
    else: config.grid_base = 0
    before = bytes(state2)
    assert api.af_reference_joint_init(state2, c.byref(config), work2, c.byref(candidate2), Progress(), None) != 0
    assert bytes(state2) == before


def test_cancel_and_invalid_candidate_preserve_last_published_recipe_and_output(api):
    state, config, work, baseline, candidate, seed, keep = setup(api)
    point = (.2, .3, .8); before = predict(api, state, seed, point)
    alternative = Recipe.from_buffer_copy(seed); alternative.matrix[6] = 16
    cached = bytes(candidate)
    cancelled = Progress(lambda _, done, total: done == total)
    assert api.af_reference_joint_prepare(state, c.byref(alternative), cancelled, None) == -20
    assert bytes(candidate) == cached and predict(api, state, seed, point) == before
    alternative.cc1[12] = -1024
    rgb = (c.c_float*3)(*point); output = (c.c_float*3)(77, 77, 77)
    assert api.af_reference_joint_predict(state, c.byref(alternative), rgb, output) == -21
    assert list(output) == [77]*3 and predict(api, state, seed, point) == before
    rgb[0] = float('nan')
    assert api.af_reference_joint_predict(state, c.byref(seed), rgb, output) == -1
    assert list(output) == [77]*3


def test_actual_forward_pairs_exact_queries_and_full_model_without_inverse_interpolation(api):
    state, config, work, baseline, candidate, seed, keep=setup(api)
    mapping, values, rows=paired_table(api, baseline)
    for row in rows:
        source_rgb=(c.c_float*3)(*row[:3]);output=(c.c_float*3)(77, 77, 77)
        assert api.af_reference_map_eval(c.byref(mapping), source_rgb, output)==0
        assert list(output)==list(row[3:])
    source_rgb=(c.c_float*3)(.123, .456, .789);output=(c.c_float*3)(77, 77, 77)
    assert api.af_reference_map_eval(c.byref(mapping), source_rgb, output)==-21
    assert list(output)==[77]*3
    assert api.af_reference_map_eval(c.byref(mapping), (c.c_float*3)(*rows[0][:3]), values)==-1
    config.input_map=c.addressof(mapping)
    paired_state=c.create_string_buffer(api.af_reference_joint_state_bytes())
    paired_work=c.create_string_buffer(api.af_reference_joint_work_bytes());paired_candidate=Cache()
    assert api.af_reference_joint_init(paired_state,c.byref(config),paired_work,c.byref(paired_candidate),Progress(),None)==0
    mixed=Recipe.from_buffer_copy(seed);mixed.gamma[:]=[v*3//4 for v in seed.gamma]
    mixed.matrix[6]=128;mixed.cc1[8]=32;mixed.cc1[12]=8;mixed.grid[:]=[8]*1215
    for row in rows:
        assert predict(api,paired_state,seed,row[:3])==pytest.approx(row[:3],abs=1e-7)
        actual=predict(api,paired_state,mixed,row[:3])
        old=interpolate(keep[6],evaluate(api,baseline,row[3:]))
        new=interpolate(keep[6],evaluate(api,paired_candidate,row[3:]))
        anchored=[min(1.,max(0.,row[i]+new[i]-old[i]))for i in range(3)]
        assert actual==pytest.approx(grid_prediction(keep[8],list(mixed.grid),anchored),abs=2e-6)


@pytest.mark.parametrize('failure',['order','duplicate','fractional-native','hash','wrong-domain'])
def test_paired_map_semantics_and_hash_reject_before_output(api,failure):
    state,config,work,baseline,candidate,seed,keep=setup(api)
    mapping,values,rows=paired_table(api,baseline)
    if failure=='order':
        first=list(values[:6]);values[:6]=values[6:12];values[6:12]=first
    elif failure=='duplicate':values[6:9]=values[:3]
    elif failure=='fractional-native':values[3]+=.5
    elif failure=='hash':mapping.data_sha256[0]^=1
    else:mapping.input_domain=3;mapping.output_domain=1
    if failure!='hash':mapping.data_sha256[:]=hashlib.sha256(bytes(values)).digest()
    output=(c.c_float*3)(77,77,77)
    assert api.af_reference_map_eval(c.byref(mapping),(c.c_float*3)(*rows[0][:3]),output)==-1
    assert list(output)==[77]*3
