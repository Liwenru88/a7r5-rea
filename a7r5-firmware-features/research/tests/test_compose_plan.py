"""模块计划、局部前像和组合拒绝的定向回归。"""
from itertools import combinations
from pathlib import Path
import sys

import pytest

FEATURES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FEATURES))
from core.plan import make_plan, merge_component, read_json, require_base, resolve_modules

BASE = 'ilce-7rm5-4.00'
IDS = read_json(FEATURES / 'presets/phase1-all.json')['modules']


def test_all_phase1_subsets_have_deterministic_plans():
    for count in range(1, len(IDS) + 1):
        for group in combinations(IDS, count):
            plan = make_plan(dict(base=BASE, modules=list(group)))
            assert make_plan(dict(base=BASE, modules=list(reversed(group)))) == plan
            assert {row['id'] for row in plan['modules']} == set(group)
            assert len(plan['template_fields']) == 2 * ('color-r6-st' in group) + ('color-awb-priority' in group)
            assert plan['base']['wbi'] == 'preserve-stock'
            assert '0700_part_image/dev/nflasha5' not in plan['archive_targets']


@pytest.mark.parametrize('config,reason', [
    (dict(base='ilce-7rm5-9.99', modules=[IDS[0]]), '未知原厂基线'),
    (dict(base=BASE, modules=['missing']), '缺少模块'),
    (dict(base=BASE, modules=[IDS[0]] * 2), '重复'),
])
def test_invalid_config_is_refused(config, reason):
    with pytest.raises(ValueError, match=reason):
        make_plan(config)


def test_unrecognized_dat_fails_before_extracting(tmp_path):
    dat = tmp_path / 'BODYDATA.DAT'
    dat.write_bytes(b'unknown firmware')
    with pytest.raises(ValueError, match='DAT 摘要或长度不匹配'):
        require_base(dat, make_plan(dict(base=BASE, modules=[IDS[0]])))


def node(*, deps=(), conflicts=(), claims=()):
    return dict(supported_bases=[BASE], requires=deps, conflicts=conflicts, claims=claims)


def test_dependency_is_included_before_request():
    ordered, claims = resolve_modules(['top'], {'top': node(deps=['base']), 'base': node(claims=['ap'])}, BASE)
    assert ordered == ['base', 'top'] and claims == {'ap': 'base'}


@pytest.mark.parametrize('first,second,reason', [
    (node(deps=['missing']), node(), '缺少模块或依赖'),
    (node(deps=['two']), node(deps=['one']), '依赖成环'),
    (node(), node(conflicts=['one']), '互斥'),
    (node(claims=['ap']), node(claims=['ap']), '同时由'),
])
def test_dependency_and_semantic_conflicts_are_refused(first, second, reason):
    with pytest.raises(ValueError, match=reason):
        resolve_modules(['one', 'two'], {'one': first, 'two': second}, BASE)


def test_overlapping_writes_require_identical_preimage_and_result():
    first = dict(module='one', offset=0, before='1122', after='aabb')
    second = dict(module='two', offset=1, before='2233', after='bbcc')
    combined = merge_component([first, second], 3)
    assert bytes(value[1] for value in combined.values()) == bytes.fromhex('aabbcc')
    for incompatible in (dict(second, before='0033'), dict(second, after='ddcc')):
        with pytest.raises(ValueError, match='组件补丁冲突'):
            merge_component([first, incompatible], 3)
    with pytest.raises(ValueError, match='范围'):
        merge_component([second], 2)


def test_local_preimage_mismatch_preserves_original_component(tmp_path):
    from core.package import apply_components
    from core.plan import sha

    original = b'original'
    component = tmp_path / 'components/app'
    component.parent.mkdir()
    component.write_bytes(original)
    pin = dict(bytes=len(original), sha256=sha(original))
    manifest = dict(components={'app': pin})
    plan = dict(base=manifest, component_patches={
        'app': [dict(module='example', offset=0, before='6f', after='4f'),
                dict(module='example', offset=2, before='00', after='49')]
    })
    with pytest.raises(ValueError, match='局部前像'):
        apply_components(tmp_path, manifest, plan)
    assert component.read_bytes() == original
