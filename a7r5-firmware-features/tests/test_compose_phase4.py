"""阶段四计划范围和实际 DAT 内部资源。"""
import io
import os
from pathlib import Path
import sys

import pytest

FEATURES = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(FEATURES), str(FEATURES.parent / 'a7r5-dat-tool')]
from a7r5dat.ext2read import Ext2
from a7r5dat.fat import FatImage
from core.plan import AVCAM_IMAGE, PART_SUM, WBI_IMAGE, make_plan, read_json, sha

AF, ASPECT = 'lens-af-compat', 'photo-aspect-ratios'
AP_IMAGE = '0700_part_image/dev/nflasha15'
CP_IMAGE = '0700_part_image/dev/nflasha8'
BASE = 'ilce-7rm5-4.00'


def test_selectable_capture_modules_use_only_expected_archive_members():
    all_options = read_json(FEATURES / 'presets/phase4-look24-lens-af-aspect.json')
    assert make_plan(all_options) == make_plan(dict(all_options, modules=all_options['modules'][::-1]))
    assert not make_plan(all_options)['native24']['disabled']
    for combination in ([AF], [ASPECT], [AF, ASPECT]):
        for with_24 in (False, True):
            modules = [*combination, *(['look24-core'] if with_24 else [])]
            plan = make_plan(dict(base=BASE, modules=modules))
            assert plan['capture_modules'] == {
                'aspect': ASPECT in combination, 'lens_af': AF in combination, 'wbi': 'invalidate-sector'}
            expected = {CP_IMAGE, WBI_IMAGE, PART_SUM}
            if ASPECT in combination or with_24:
                expected.add(AP_IMAGE)
            if ASPECT in combination:
                expected.add(AVCAM_IMAGE)
            assert set(plan['archive_targets']) == expected
            assert ('native24' in plan) == with_24
    with pytest.raises(ValueError, match='组合尚未验证'):
        make_plan(dict(base=BASE, modules=[ASPECT, 'look-factory-six']))


@pytest.mark.parametrize('bundle,runtime', [('af', 'af-runtime'), ('aspect', 'aspect-runtime'),
                                          ('look24-af-aspect', 'combined-runtime')])
def test_capture_components_and_snapshot_in_actual_dat(bundle, runtime):
    from elftools.elf.elffile import ELFFile

    path = os.environ.get('A7R5_PHASE4_WORK')
    if not path:
        pytest.skip('需要阶段四实际 DAT 的独立回读')
    phase = Path(path)
    stock = Path(os.environ['A7R5_PHASE4_STOCK'])
    readback = phase / (bundle + '-readback')
    expected = phase / runtime
    before = read_json(stock / 'manifest.json')
    after = read_json(readback / 'manifest.json')
    lock = read_json(phase / bundle / 'lock.json')
    assert after['source'] == lock['dat']
    modified = set(lock['plan']['archive_targets'])
    for left, right in zip(before['entries'], after['entries'], strict=True):
        assert left['name'] == right['name']
        assert (left != right) == (left['name'] in modified)

    wbi = readback / 'archive' / WBI_IMAGE
    with (stock / 'archive' / WBI_IMAGE).open('rb') as old, wbi.open('rb') as new:
        assert old.read(512).startswith(b'WBI2') and new.read(512) == bytes(512)
        for block in iter(lambda: old.read(1 << 20), b''):
            assert new.read(len(block)) == block
        assert not new.read(1)
    assert (readback / 'components/cpapp-b.bin').read_bytes() == (expected / 'cpapp-b.bin').read_bytes()
    if AP_IMAGE not in modified:
        return
    actual_ap = (readback / 'components/usr/lib/appFw.so').read_bytes()
    assert actual_ap == (expected / 'appFw.so').read_bytes()
    elf = ELFFile(io.BytesIO(actual_ap))
    loads = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
    assert len(loads) == (6 if bundle.startswith('look24-') else 4)
    for i, segment in enumerate(loads):
        lo, hi = segment['p_vaddr'], segment['p_vaddr'] + segment['p_memsz']
        assert segment['p_flags'] in (4, 5, 6) and segment['p_filesz'] <= segment['p_memsz']
        assert all(max(lo, s['p_vaddr']) >= min(hi, s['p_vaddr'] + s['p_memsz']) for s in loads[:i])
    assert [(s['p_vaddr'], s['p_flags']) for s in loads[-2:]] == [(0x8f00000, 5), (0x8f10000, 6)]
    assert FatImage((readback / 'archive' / AVCAM_IMAGE).read_bytes()).read('/AV-CAM.BIN') == (
        expected / 'AV-CAM.BIN').read_bytes()
    usr = Ext2(readback / 'archive' / AP_IMAGE)
    try:
        resources = read_json(expected / 'build.json')['resources']
        assert len(resources) == 70
        for name, pin in resources.items():
            assert sha(usr.read_inode(usr.walk('/share/app/' + name))) == pin
    finally:
        usr.mm.close()
        usr.f.close()
