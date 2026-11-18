"""阶段三共享选择计划、实包名称与原厂捕获组件保护。"""
import importlib.util
import io
import os
from pathlib import Path
import struct
import sys

import pytest

FEATURES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FEATURES))
from core.plan import make_plan, read_json, sha

BASE = 'ilce-7rm5-4.00'


def test_color_modules_are_selectable_without_aspect_and_plan_is_order_independent():
    config = read_json(FEATURES / 'presets/phase3-look24-fl23-factory-six.json')
    plan = make_plan(config)
    assert plan == make_plan(dict(config, modules=list(reversed(config['modules']))))
    assert plan['color_modules'] == {'fl23': True, 'factory_six': True}
    assert '0700_part_image/dev/nflasha3' not in plan['archive_targets']
    assert not plan['native24']['disabled']
    for name, option in (('look-fl2-fl3', 'fl23'), ('look-factory-six', 'factory_six')):
        single = make_plan(dict(base=BASE, modules=[name]))
        assert single['color_modules'][option]
        assert 'native24' not in single and '0700_part_image/dev/nflasha5' not in single['archive_targets']


@pytest.fixture(scope='module')
def readback():
    path = os.environ.get('A7R5_PHASE3_READBACK')
    if not path:
        pytest.skip('需要阶段三组合包独立解包')
    return Path(path)


def test_all_factory_name_banks_and_native_avcam(readback):
    recipe = read_json(FEATURES / 'materials/recipes.json')
    assert len(recipe['resources']) == 68
    for row in recipe['resources']:
        raw = (readback / row['path']).read_bytes()
        assert sha(raw) == row['after_sha256']
        count = struct.unpack_from('<I', raw, 12)[0] // 0x1001
        assert count == 3038
        base = 16 + 2 * count
        for i, name in enumerate(recipe['names']):
            ptr = struct.unpack_from('<H', raw, 16 + 2 * (3032 + i))[0]
            offset = base + 4 * ptr
            assert struct.unpack_from('<I', raw, offset)[0] == 0x1e00abd8 + i
            assert raw[offset + 4:].split(b'\0', 1)[0].decode() == name
    source = read_json(Path(os.environ['A7R5_PHASE3_STOCK']) / 'manifest.json')
    after = read_json(readback / 'manifest.json')
    originals = {row['name']: row for row in source['entries']}
    for row in after['entries']:
        if row['name'] not in {'0700_part_image/dev/nflasha15', '0700_part_image/dev/nflasha8',
                               '0700_part_image/dev/nflasha5', '0701_part_image_sum/part_image.sum'}:
            assert originals[row['name']] == row


def test_marker_and_ntsc_preserve_stage3_color_code(readback):
    from elftools.elf.elffile import ELFFile

    native = Path(os.environ['A7R5_PHASE3_RUNTIME'])
    raw = (readback / 'components/usr/lib/appFw.so').read_bytes()
    assert (readback / 'components/cpapp-b.bin').read_bytes() == (native / 'cpapp-b.bin').read_bytes()
    elf = ELFFile(io.BytesIO(raw))
    assert elf.get_segment(0)['p_filesz'] == elf.get_segment(0)['p_memsz'] == 0x500fc70
    reversed_ap = bytearray(raw)
    for name in ('photo-framing-markers', 'video-ntsc-prompt'):
        for row in read_json(FEATURES / name / 'module.json')['changes'][0]['patches']:
            offset = row['offset']
            before, after = (bytes.fromhex(row[key]) for key in ('before', 'after'))
            if row.get('address') == 'primary-rx-header':
                offset += elf['e_phoff'] - 64
                before = struct.pack('<Q', 0x500fc10)
            assert reversed_ap[offset:offset + len(after)] == after
            reversed_ap[offset:offset + len(before)] = before
    assert reversed_ap == (native / 'appFw.so').read_bytes()
    path = FEATURES / 'native24-combined/dependencies/native12-combined/tests/test_integration.py'
    spec = importlib.util.spec_from_file_location('legacy_stage3_instructions', path)
    checks = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checks)
    checks.test_marker_registration_executes_original_range_validator((None, None, raw))
    checks.test_ntsc_branches_execute_to_original_continuations((None, None, raw))
