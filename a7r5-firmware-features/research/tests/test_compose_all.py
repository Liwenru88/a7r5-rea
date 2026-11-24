"""验证全功能预设及最终 DAT 的新增功能。"""
import importlib.util
import os
from pathlib import Path
import struct
import sys

import pytest

FEATURES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FEATURES))
from core.plan import AVCAM_IMAGE, BACKUP_SUM, FULL_OPTIONAL, PART_SUM, WBI_IMAGE, make_plan, read_json, sha

SOUND = 'photo-electronic-shutter-sound'
CP = 'cpapp-b.bin'
AP = 'usr/lib/appFw.so'


def test_full_preset_resolves_sound_once_and_combines_templates():
    full = read_json(FEATURES / 'presets/full-stock400.json')
    plan = make_plan(full)
    assert plan == make_plan(dict(full, modules=list(reversed(full['modules']))))
    assert plan['native24']['sound_layout'] == 'relocated-fl23'
    assert CP not in plan['component_patches']
    assert {row['module'] for row in plan['component_patches'][AP]} == {
        'photo-framing-markers', 'video-ntsc-prompt'}
    assert len(plan['template_fields']) == 3
    assert set(plan['base']['gl_templates']) | {BACKUP_SUM} <= set(plan['archive_targets'])
    single = make_plan(dict(full, modules=[SOUND]))
    assert len(single['component_patches'][CP]) == 3
    assert 'native24' not in single


@pytest.fixture(scope='module')
def work():
    folder = os.environ.get('A7R5_ALL_WORK')
    if not folder:
        pytest.skip('需要全功能和逐项加配的 DAT 回执')
    return Path(folder)


def expected_ap(raw, *options):
    result = bytearray(raw)
    phoff, = struct.unpack_from('<Q', raw, 32)
    for module in options:
        for row in read_json(FEATURES / module / 'module.json')['changes'][0]['patches']:
            at = row['offset']
            before, after = (bytes.fromhex(row[key]) for key in ('before', 'after'))
            if row.get('address') == 'primary-rx-header':
                at += phoff - 64
                before = struct.pack('<Q', 0x500fc10)
            assert result[at:at+len(before)] == before
            result[at:at+len(after)] = after
    return result


@pytest.fixture(scope='module')
def base424():
    folder = Path(os.environ['A7R5_ALL_424_READBACK'])
    pin = read_json(FEATURES / 'tests/full-native24-color-capture-verification.json')['dat']
    assert read_json(folder / 'manifest.json')['source'] == pin
    return folder


def test_final_ap_contains_only_marker_and_ntsc_additions(work, base424):
    actual = (work / 'all-readback/components' / AP).read_bytes()
    before = (base424 / 'components' / AP).read_bytes()
    assert actual == expected_ap(before, 'photo-framing-markers', 'video-ntsc-prompt')
    at, = struct.unpack_from('<Q', actual, 32)
    assert struct.unpack_from('<QQ', actual, at+32) == (0x500fc70, 0x500fc70)
    spec = importlib.util.spec_from_file_location('all_marker_instructions',
        FEATURES / 'firmware-runtime/dependencies/native12-combined/tests/test_integration.py')
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    legacy.test_marker_registration_executes_original_range_validator((None, None, actual))


def test_final_cp_sound_reuses_the_417_helper_without_touching_color_or_capture(work, base424):
    actual = (work / 'all-readback/components' / CP).read_bytes()
    before = (base424 / 'components' / CP).read_bytes()
    reference = Path(os.environ['A7R5_ALL_417_READBACK']) / 'components' / CP
    donor = reference.read_bytes()
    assert sha(donor) == '35eb911d27be4a8aab8a0a5fe9a8f028c16453d5ab79605fe36dbd199b833300'
    expected = bytearray(before)
    # 0xbef700 的声音入口紧接着是 0xbef720 的矩阵入口。
    for va, size in ((0x47f622, 4), (0xbef700, 32)):
        at = va - 0x108000
        assert before[at:at+size] != donor[at:at+size]
        expected[at:at+size] = donor[at:at+size]
    assert actual == expected


def test_final_archive_changes_only_expected_members_and_keeps_424_resources(work, base424):
    readback = work / 'all-readback'
    bundle = work / 'all'
    lock = read_json(bundle / 'lock.json')
    manifest = read_json(readback / 'manifest.json')
    prior = read_json(base424 / 'manifest.json')
    gl = lock['plan']['base']['gl_templates']
    assert manifest['source'] == lock['dat'] and len(manifest['entries']) == 147
    assert len(lock['plan']['archive_targets']) == 18
    delta = {*gl, BACKUP_SUM, PART_SUM, '0700_part_image/dev/nflasha15', '0700_part_image/dev/nflasha8'}
    for before, after in zip(prior['entries'], manifest['entries'], strict=True):
        assert before['name'] == after['name']
        assert (before != after) == (after['name'] in delta)
    unchanged = {key: row for key, row in manifest['components'].items() if key not in (AP, CP)}
    assert len(unchanged) == 68 and all(prior['components'][key] == row for key, row in unchanged.items())
    assert (readback / 'archive' / WBI_IMAGE).read_bytes() == (base424 / 'archive' / WBI_IMAGE).read_bytes()
    assert (readback / 'archive' / AVCAM_IMAGE).read_bytes() == (base424 / 'archive' / AVCAM_IMAGE).read_bytes()
    legacy = Path(os.environ['A7R5_ALL_GL_READBACK'])
    pin = read_json(FEATURES / 'tests/phase1-verification.json')['builds']['all-four']['dat']
    assert read_json(legacy / 'manifest.json')['source'] == pin
    for name in (*gl, BACKUP_SUM):
        assert (readback / 'archive' / name).read_bytes() == (legacy / 'archive' / name).read_bytes()


def test_five_standalone_packages_match_history_and_each_424_addition_is_isolated(work, base424):
    old = read_json(FEATURES / 'tests/phase1-verification.json')['builds']
    pins = {'photo-framing-markers': read_json(FEATURES / 'tests/phase2-verification.json')['bundles']['markers']['dat'],
            'video-ntsc-prompt': old['ntsc']['dat'], SOUND: old['electronic-shutter']['dat'],
            'color-r6-st': old['r6-st']['dat'], 'color-awb-priority': old['awb-priority']['dat']}
    prior = read_json(base424 / 'manifest.json')
    prior_hashes = {row['name']: row['sha256'] for row in prior['entries'] if 'sha256' in row}
    all_lock = read_json(work / 'all/lock.json')
    for option in FULL_OPTIONAL:
        single = read_json(work / ('single-' + option) / 'lock.json')
        added = read_json(work / ('add-' + option) / 'lock.json')
        assert single['dat'] == pins[option]
        assert set(added['plan']['requested']) - FULL_OPTIONAL == set(all_lock['plan']['requested']) - FULL_OPTIONAL
        assert set(added['plan']['requested']) & FULL_OPTIONAL == {option}
        changes = {name for name, row in added['expected']['archive'].items() if row['sha256'] != prior_hashes[name]}
        assert changes == set(single['expected']['archive'])
        if option in ('photo-framing-markers', 'video-ntsc-prompt'):
            before = (base424 / 'components' / AP).read_bytes()
            assert added['expected']['components'][AP]['sha256'] == sha(expected_ap(before, option))
        elif option == SOUND:
            assert added['expected']['components'][CP] == all_lock['expected']['components'][CP]
        else:
            assert all(added['expected']['archive'][name] == row
                       for name, row in single['expected']['archive'].items())
