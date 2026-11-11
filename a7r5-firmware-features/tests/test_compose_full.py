"""验证全组合计划和独立解包的共享资源。"""
import os
from pathlib import Path
import struct
import sys

import pytest

FEATURES = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FEATURES))
from core.plan import AVCAM_IMAGE, PART_SUM, WBI_IMAGE, digest, make_plan, read_json, sha


def test_full_preset_selects_both_color_and_capture_without_changing_other_combinations():
    config = read_json(FEATURES / 'presets/full-native24-color-capture.json')
    plan = make_plan(config)
    assert make_plan(dict(config, modules=config['modules'][::-1])) == plan
    assert plan['native24'] == {'disabled': [], 'wbi': 'invalidate-sector', 'companion': 'R5NATIVE.BIN'}
    assert plan['color_modules'] == {'fl23': True, 'factory_six': True}
    assert plan['capture_modules'] == {'aspect': True, 'lens_af': True, 'wbi': 'invalidate-sector'}
    assert set(plan['archive_targets']) == {
        AVCAM_IMAGE, WBI_IMAGE, PART_SUM, '0700_part_image/dev/nflasha8', '0700_part_image/dev/nflasha15'}
    reduced = [name for name in config['modules'] if name != 'look-factory-six']
    for modules in (reduced, [*reduced, 'photo-framing-markers']):
        with pytest.raises(ValueError, match='组合尚未验证'):
            make_plan(dict(config, modules=modules))


@pytest.fixture(scope='module')
def full_bundle():
    folder = os.environ.get('A7R5_FULL_WORK')
    if not folder:
        pytest.skip('需要全组合 DAT 的独立解包')
    return Path(folder)


def test_all_language_banks_keep_color_names_and_add_aspect_labels(full_bundle):
    recipe = read_json(FEATURES / 'materials/recipes.json')
    readback = full_bundle / 'full-readback'
    labels = ('17:6', '65:24', '5:4', '7:6', '1.91:1', '2.35:1')
    assert len(recipe['resources']) == 68
    for row in recipe['resources']:
        raw = (readback / row['path']).read_bytes()
        count, remainder = divmod(struct.unpack_from('<I', raw, 12)[0], 0x1001)
        assert (count, remainder) == (3038, 0)
        base = 16 + count * 2
        first = struct.unpack_from('<H', raw, 10)[0] << 13
        prior = bytearray(raw[:row['after_bytes']])
        for index, expected in enumerate(labels):
            entry = 0xab60 + index
            pointer = 16 + (entry - first) * 2
            at = base + struct.unpack_from('<H', raw, pointer)[0] * 4
            assert row['after_bytes'] <= at < len(raw)
            assert struct.unpack_from('<I', raw, at)[0] == 0x1e000000 + entry
            assert raw[at+4:].split(b'\0', 1)[0].decode('ascii') == expected
            prior[pointer:pointer+2] = b'\xff\xff'
        assert sha(prior) == row['after_sha256']
        for index, expected in enumerate(recipe['names']):
            at = base + struct.unpack_from('<H', raw, 16 + (3032 + index) * 2)[0] * 4
            assert struct.unpack_from('<I', raw, at)[0] == 0x1e00abd8 + index
            assert raw[at+4:].split(b'\0', 1)[0].decode() == expected


def test_final_ap_cp_avcam_icons_and_snapshot_match_independent_build(full_bundle):
    sys.path.insert(0, str(FEATURES.parent / 'a7r5-dat-tool'))
    from a7r5dat.ext2read import Ext2
    from a7r5dat.fat import FatImage

    stock = Path(os.environ['A7R5_FULL_STOCK'])
    readback = full_bundle / 'full-readback'
    compiled = full_bundle / 'capture-components'
    record = read_json(compiled / 'build.json')
    lock = read_json(full_bundle / 'full/lock.json')
    manifest = read_json(readback / 'manifest.json')
    assert manifest['source'] == lock['dat']
    originals = read_json(stock / 'manifest.json')
    changed = set(lock['plan']['archive_targets'])
    for before, after in zip(originals['entries'], manifest['entries'], strict=True):
        assert before['name'] == after['name']
        assert (before != after) == (before['name'] in changed)
    assert digest(readback / 'components/usr/lib/appFw.so') == record['AP']['target_sha256']
    assert digest(readback / 'components/cpapp-b.bin') == record['CP_sha256']
    avcam = FatImage((readback / 'archive' / AVCAM_IMAGE).read_bytes()).read('/AV-CAM.BIN')
    assert sha(avcam) == record['AVCAM']['target_sha256']
    ext2 = Ext2(readback / 'archive/0700_part_image/dev/nflasha15')
    try:
        assert len(record['resources']) == 70
        for name, pin in record['resources'].items():
            assert sha(ext2.read_inode(ext2.walk('/share/app/' + name))) == pin
    finally:
        ext2.mm.close()
        ext2.f.close()
    wbi_before = (stock / 'archive' / WBI_IMAGE).read_bytes()
    wbi_after = (readback / 'archive' / WBI_IMAGE).read_bytes()
    assert wbi_before[:4] == b'WBI2' and wbi_after[:512] == bytes(512)
    assert wbi_after[512:] == wbi_before[512:]
    assert digest(full_bundle / 'full/R5NATIVE.BIN') == lock['expected']['companion']['sha256']
