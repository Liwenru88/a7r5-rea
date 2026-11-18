"""16色相区真实参考构表、旧模式切回与独立身份；仅运行宿主数值代码。"""
import ctypes as c
import hashlib
import struct

import pytest

from grid_support import Progress
from joint_support import Recipe
from test_edit_joint import Parameters, source
from test_reference_joint import api as reference_api, Info, setup, predict


Sector = c.c_int16*288


@pytest.fixture(scope="module")
def api(reference_api):
    result = reference_api
    result.af_edit_joint_parameters.argtypes = [c.c_void_p]*3
    result.af_edit_joint_parameters_sector.argtypes = [c.c_void_p]*4
    result.af_edit_joint_prepare_sector.argtypes = [c.c_void_p]*5+[Progress, c.c_void_p]
    result.af_reference_joint_prepare_sector.argtypes = [c.c_void_p]*3+[Progress, c.c_void_p]
    result.af_reference_joint_predict_sector.argtypes = [c.c_void_p]*5
    result.af_reference_joint_info_sector.argtypes = [c.c_void_p, c.POINTER(Info)]
    return result


def sector_predict(api, state, recipe, sectors, point):
    rgb = (c.c_float*3)(*point)
    output = (c.c_float*3)(77, 77, 77)
    assert api.af_reference_joint_predict_sector(state, c.byref(recipe), sectors, rgb, output) == 0
    return tuple(output)


def coefficient(payload, row, sector):
    return struct.unpack_from('<h', bytes(payload), 24+2*((row*16+sector)^1))[0] >> 2


def test_all_sixteen_sectors_and_three_endpoints_reach_native_parameter_payload(api):
    _, value, owners, recipe = source()
    sectors = Sector()
    for endpoint in range(3):
        for sector in range(16):
            sectors[(endpoint*16+sector)*6] = (sector+1)*(endpoint+1)*(-1 if endpoint == 2 else 1)
    weights = ((0, 0, 0, 0), (256, 0, 0, 0), (0, 0, 256, 256))
    for endpoint, weight in enumerate(weights):
        value.matrix_weights[:] = weight
        before, after = Parameters(), Parameters()
        assert api.af_edit_joint_parameters(c.byref(value), c.byref(recipe), c.byref(before)) == 0
        assert api.af_edit_joint_parameters_sector(c.byref(value), c.byref(recipe), sectors, c.byref(after)) == 0
        assert bytes(after.gamma) == bytes(before.gamma) and bytes(after.cc1) == bytes(before.cc1)
        for sector in range(16):
            expected = sectors[(endpoint*16+sector)*6]
            assert coefficient(after.matrix_payload, 0, sector)-coefficient(before.matrix_payload, 0, sector) == expected
            for row in range(1, 6):
                assert coefficient(after.matrix_payload, row, sector) == coefficient(before.matrix_payload, row, sector)
        # 模板配置、每系数低两位及未写范围保持。
        assert bytes(after.matrix_payload[:24]) == bytes(before.matrix_payload[:24])
        assert bytes(after.matrix_payload[216:]) == bytes(before.matrix_payload[216:])
        for offset in range(24, 216, 2):
            assert after.matrix_payload[offset] & 3 == before.matrix_payload[offset] & 3


def test_uniform_sector_model_matches_legacy_eighteen_increments(api):
    _, value, owners, recipe = source()
    recipe.matrix[:] = [2, -3, 4, -5, 6, -7, 17, -19, 23, -29, 31, -37, -2, 3, -4, 5, -6, 7]
    legacy = Parameters()
    assert api.af_edit_joint_parameters(c.byref(value), c.byref(recipe), c.byref(legacy)) == 0
    sectors = Sector()
    for endpoint in range(3):
        for sector in range(16):
            for index in range(6):
                sectors[(endpoint*16+sector)*6+index] = recipe.matrix[endpoint*6+index]
    recipe.matrix[:] = [0]*18
    expanded = Parameters()
    assert api.af_edit_joint_parameters_sector(c.byref(value), c.byref(recipe), sectors, c.byref(expanded)) == 0
    assert bytes(expanded) == bytes(legacy)


def test_zero_sector_identity_cache_and_legacy_switchback_are_separate(api):
    state, config, work, baseline, candidate, recipe, keep = setup(api)
    points = ((.2, .3, .8), (.75, .25, .1), (.4, .7, .2))
    legacy = [predict(api, state, recipe, point) for point in points]
    old_info, sector_info = Info(), Info()
    assert api.af_reference_joint_info(state, c.byref(old_info)) == 0
    assert api.af_reference_joint_info_sector(state, c.byref(sector_info)) == 0
    assert bytes(sector_info.model_sha256) == hashlib.sha256(
        b'A7R5_REFERENCE_SECTOR_MATRIX406_V1\0'+bytes(old_info.model_sha256)).digest()
    assert sector_info.research_only == 1 and sector_info.camera_apply_allowed == 0
    sectors = Sector()
    before_hash, before_builds = bytes(candidate.recipe_sha256), candidate.builds
    assert [sector_predict(api, state, recipe, sectors, point) for point in points] == legacy
    assert candidate.builds == before_builds+1 and bytes(candidate.recipe_sha256) != before_hash
    built = candidate.builds
    assert [sector_predict(api, state, recipe, sectors, point) for point in points] == legacy
    assert candidate.builds == built
    # 只改未选端点也须进入身份并重构；不能把288项hash退化成当前18项。
    sectors[0] = 5
    assert [sector_predict(api, state, recipe, sectors, point) for point in points] == legacy
    assert candidate.builds == built+1
    # 当前参考Q8权重选择端点1；其16区系数实际进入整数构表和像素。
    for sector in range(16):
        sectors[(16+sector)*6] = 128
    changed = [sector_predict(api, state, recipe, sectors, point) for point in points]
    assert changed != legacy
    built = candidate.builds
    assert [predict(api, state, recipe, point) for point in points] == legacy
    assert candidate.builds == built+1 and bytes(candidate.recipe_sha256) == before_hash
    current_info = Info()
    assert api.af_reference_joint_info(state, c.byref(current_info)) == 0
    assert bytes(current_info) == bytes(old_info)


def test_sector_cancel_bad_range_double_matrix_and_alias_preserve_candidate(api):
    state, config, work, baseline, candidate, recipe, keep = setup(api)
    sectors = Sector()
    for sector in range(16):
        sectors[(16+sector)*6] = 32
    point = (.2, .3, .8)
    expected = sector_predict(api, state, recipe, sectors, point)
    before_state, before_cache = bytes(state), bytes(candidate)
    trial = Sector.from_buffer_copy(sectors)
    trial[96] = 48
    cancel = Progress(lambda _, done, total: done == total)
    assert api.af_reference_joint_prepare_sector(state, c.byref(recipe), trial, cancel, None) == -20
    assert bytes(state) == before_state and bytes(candidate) == before_cache
    rgb, output = (c.c_float*3)(*point), (c.c_float*3)(77, 77, 77)
    trial[96] = 1025
    assert api.af_reference_joint_predict_sector(state, c.byref(recipe), trial, rgb, output) == -1
    assert list(output) == [77]*3 and bytes(candidate) == before_cache
    trial[96] = 48
    recipe.matrix[0] = 1
    assert api.af_reference_joint_predict_sector(state, c.byref(recipe), trial, rgb, output) == -1
    recipe.matrix[0] = 0
    assert api.af_reference_joint_predict_sector(state, c.byref(recipe), None, rgb, output) == -1
    assert api.af_reference_joint_predict_sector(state, c.byref(recipe), sectors, rgb, c.cast(sectors, c.POINTER(c.c_float))) == -1
    assert bytes(state) == before_state and bytes(candidate) == before_cache
    assert sector_predict(api, state, recipe, sectors, point) == expected
