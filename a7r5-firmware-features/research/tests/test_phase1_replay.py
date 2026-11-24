"""对独立解包所得的四项组合组件和模板做定向验证。"""
import importlib.util
import json
import os
from pathlib import Path
import sys

import pytest

FEATURES = Path(__file__).resolve().parents[1]
LEGACY = FEATURES / 'firmware-runtime/dependencies/native12-combined'
GL = LEGACY / 'upstream/firmware/r5/src'


@pytest.fixture(scope='module')
def readback():
    path = os.environ.get('A7R5_PHASE1_READBACK')
    if not path:
        pytest.skip('需要四项组合 DAT 独立解包工作区')
    return Path(path)


@pytest.mark.parametrize('component,check', [
    ('usr/lib/appFw.so', 'test_ntsc_branches_execute_to_original_continuations'),
    ('cpapp-b.bin', 'test_sound_selector_keeps_non_type1_inhibit_and_callee_state'),
])
def test_packaged_component_cpu_behavior(readback, component, check):
    spec = importlib.util.spec_from_file_location('legacy_phase1_instructions', LEGACY / 'tests/test_integration.py')
    legacy = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(legacy)
    payload = (readback / 'components' / component).read_bytes()
    getattr(legacy, check)((None, None, payload, payload))


def test_all_12_templates_contain_both_selected_modules(readback, monkeypatch):
    monkeypatch.syspath_prepend(str(GL / 'templates'))
    import prepare_templates as template

    fields = [row for row in json.loads((GL / 'dependencies/colour_fields.json').read_text())
              if row['purpose'] in ('R6 ST', 'AWB priority')]
    assert len(fields) == 3 and len(template.STOCK_HASHES) == 12
    for name in template.STOCK_HASHES:
        raw = (readback / 'archive' / template.PREFIX / name).read_bytes()
        _, props = template.property_map(raw)
        for row in fields:
            expected = bytes.fromhex(row['hex'])
            offset = row['offset']
            assert props[row['key']][1].data[offset:offset + len(expected)] == expected
