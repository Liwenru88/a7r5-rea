"""4.19 全功能声音变体必须明确选择，且不能退回旧声音补丁。"""
import sys
from pathlib import Path

import pytest

FEATURES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FEATURES))
from core.plan import make_plan, read_json

SOUND = 'photo-electronic-shutter-sound'


def config():
    return dict(read_json(FEATURES / 'presets/full-stock400.json'),
                variants={SOUND: 'custom-dual-full'})


def test_full419_explicitly_selects_dual_sound_without_old_sound_patch():
    selected = config()
    plan = make_plan(selected)
    assert plan == make_plan(dict(selected, modules=list(reversed(selected['modules']))))
    assert len(plan['modules']) == 10
    assert plan['variants'] == selected['variants']
    assert plan['native24']['sound_layout'] == 'custom-dual-full'
    assert 'cpapp-b.bin' not in plan['component_patches']
    assert plan['claims']['ap.custom-shutter-sound'] == SOUND
    assert len(plan['template_fields']) == 3


@pytest.mark.parametrize('variants', [
    {SOUND: 'unknown'}, {'look24': 'custom-dual-full'}, {SOUND: True},
])
def test_unknown_sound_variants_fail_before_build(variants):
    with pytest.raises(ValueError, match='变体'):
        make_plan(dict(config(), variants=variants))


def test_dual_sound_layout_is_bounded_to_verified_full_combination():
    with pytest.raises(ValueError, match='全功能'):
        make_plan(dict(config(), modules=['look24', SOUND]))


def test_legacy_sound_recipe_is_preserved():
    plan = make_plan(read_json(FEATURES / 'presets/full-stock400.json'))
    assert plan['native24']['sound_layout'] == 'relocated-fl23'
    single = make_plan(dict(base='ilce-7rm5-4.00', modules=[SOUND]))
    assert len(single['component_patches']['cpapp-b.bin']) == 3
