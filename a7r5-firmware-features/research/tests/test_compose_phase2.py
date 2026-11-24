"""新模块解析与从实包回读的 AP 共享布局。"""
import importlib.util
import io
import json
import os
from pathlib import Path
import sys

import pytest

FEATURES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FEATURES))
from core.plan import make_plan, read_json, sha

BASE = 'ilce-7rm5-4.00'


def test_group_memory_pulls_in_preview_and_core():
    plan = make_plan(dict(base=BASE, modules=['look24-group-memory']))
    assert [m['id'] for m in plan['modules']] == ['look24-core', 'look24-preview', 'look24-group-memory']
    assert plan['native24'] == dict(disabled=['sd-import', 'selection-restore', 'tuning'],
                                    wbi='marker-2-to-3', companion=None)


def test_unverified_cp_combination_is_rejected():
    with pytest.raises(ValueError, match='组合尚未验证'):
        make_plan(dict(base=BASE, modules=['look24-core', 'photo-electronic-shutter-sound']))


@pytest.fixture(scope='module')
def images():
    candidate = os.environ.get('A7R5_PHASE2_READBACK')
    runtime = os.environ.get('A7R5_PHASE2_NATIVE_REFERENCE')
    if not candidate or not runtime:
        pytest.skip('需要四项组合回读与全开 24 槽参考构建')
    after = Path(candidate)
    before = Path(runtime)
    return (before / 'appFw.so').read_bytes(), (after / 'components/usr/lib/appFw.so').read_bytes(), after


def test_relocated_marker_header_and_ntsc_preserve_native24_binary(images):
    from elftools.elf.elffile import ELFFile

    old, actual, after = images
    pin = read_json(FEATURES / 'independent/profiles/native24-stock/components.json')['components']
    assert sha(old) == pin['appFw.so']['sha256']
    assert sha((after / 'components/cpapp-b.bin').read_bytes()) == pin['cpapp-b.bin']['sha256']
    before = ELFFile(io.BytesIO(old))
    final = ELFFile(io.BytesIO(actual))
    assert final['e_phoff'] == before['e_phoff'] != 64
    assert final.num_segments() == before.num_segments()
    assert final.get_segment(0)['p_filesz'] == final.get_segment(0)['p_memsz'] == 0x500fc70
    reverse = bytearray(actual)
    for name in ('photo-framing-markers', 'video-ntsc-prompt'):
        for row in read_json(FEATURES / name / 'module.json')['changes'][0]['patches']:
            offset = row['offset']
            if row.get('address') == 'primary-rx-header':
                offset += final['e_phoff'] - 64
            old_bytes, new_bytes = (bytes.fromhex(row[key]) for key in ('before', 'after'))
            assert reverse[offset:offset + len(new_bytes)] == new_bytes
            reverse[offset:offset + len(new_bytes)] = old_bytes
    assert reverse == old


def test_markers_and_ntsc_execute_from_combination(images):
    _, raw, _ = images
    path = FEATURES / 'firmware-runtime/dependencies/native12-combined/tests/test_integration.py'
    spec = importlib.util.spec_from_file_location('legacy_phase2_instructions', path)
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    legacy.test_marker_registration_executes_original_range_validator((None, None, raw))
    legacy.test_ntsc_branches_execute_to_original_continuations((None, None, raw))
