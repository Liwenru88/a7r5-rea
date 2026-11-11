"""核对合并后的 24 槽入口和历史计划兼容性。"""
from pathlib import Path
import sys

import pytest

FEATURES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FEATURES))
from core.plan import make_plan, read_json


@pytest.mark.parametrize('preset', ['look24', 'full-stock400'])
def test_unified_module_preserves_the_legacy_build_plan(preset):
    current = read_json(FEATURES / 'presets' / (preset + '.json'))
    legacy = read_json(FEATURES / 'presets/phase2-look24.json')
    expanded = [*legacy['modules'], *(name for name in current['modules'] if name != 'look24')]
    plan = make_plan(current)
    original = make_plan(dict(current, modules=expanded))
    assert 'look24' in plan['requested']
    assert not any(row['id'].startswith('look24-') for row in plan['modules'])
    assert plan['claims'].keys() == original['claims'].keys()
    metadata = {'modules', 'requested', 'claims'}
    assert {k: v for k, v in plan.items() if k not in metadata} == {
        k: v for k, v in original.items() if k not in metadata}


def test_canonical_and_legacy_options_cannot_be_selected_together():
    config = read_json(FEATURES / 'presets/look24.json')
    with pytest.raises(ValueError, match='互斥'):
        make_plan(dict(config, modules=['look24', 'look24-tuning']))
