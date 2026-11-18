"""验证照片标记与滤镜启动的唯一组合、拒绝路径和原AP精确逆还原。"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import struct
import sys

import pytest

FEATURE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FEATURE/'experiments/packaging406'))
import aspect_merge as merge
from candidate_preflight import compose, read_cpio


def bootstrap():
    return [dict(offset=at, before=b.hex(), after=(a if a is not None else b'\x01'*len(b)).hex())
            for at, (b, a) in merge.bootstrap_contract().items()]


def merged():
    return sorted(bootstrap()+merge.aspect_contract(), key=lambda r:r['offset'])


def test_exact_plan_has_shared_extent_once_and_disjoint_code_ranges():
    rows, meta = merged(), merge.aspect_metadata()
    assert len(rows) == 42 and merge.validate_plan(rows, meta)
    assert len(merge.aspect_contract()) == 35
    for at in (0x60, 0x68):
        found = [r for r in rows if r['offset'] == at]
        assert len(found) == 1 and found[0]['after'] == struct.pack('<Q', merge.COMBINED_END).hex()
    code = [r for r in rows if r['offset'] in (0x500fc10, 0x500fc70, 0x500fdfc)]
    assert [(r['offset'], len(bytes.fromhex(r['after']))) for r in code] == [
        (0x500fc10, 96), (0x500fc70, 396), (0x500fdfc, 400)]
    assert meta['photo_overlay_verified'] is False


@pytest.mark.parametrize('case', ['missing', 'duplicate', 'outside', 'extent', 'support', 'registration',
                                  'wrapper', 'before', 'length', 'offset_bool', 'bytes_bool'])
def test_bad_patch_never_passes_as_complete_merge(case):
    rows = merged()
    support = next(r for r in rows if r['before'] == '0000')
    if case == 'missing':
        rows.pop()
    elif case == 'duplicate':
        rows[-1] = deepcopy(rows[-2])
    elif case == 'outside':
        rows[-1]['offset'] += 2
    elif case == 'extent':
        next(r for r in rows if r['offset'] == 0x60)['after'] = struct.pack('<Q', merge.END).hex()
    elif case == 'support':
        support['after'] = '0000'
    elif case == 'registration':
        next(r for r in rows if r['offset'] == 89458432)['after'] = struct.pack('<Q', 0x2905250).hex()
    elif case == 'wrapper':
        next(r for r in rows if r['offset'] == merge.START)['after'] = '00'*96
    elif case == 'before':
        support['before'] = '0100'
    elif case == 'length':
        support['after'] += '00'
    elif case == 'offset_bool':
        support['offset'] = True
    else:
        support['bytes'] = True
    with pytest.raises(ValueError):
        merge.validate_plan(rows, merge.aspect_metadata())


@pytest.mark.parametrize('case', ['claim', 'false_int', 'missing_pin', 'changed_pin', 'windows'])
def test_metadata_does_not_authorize_unknown_source_or_fake_acceptance(case):
    meta = merge.aspect_metadata()
    if case == 'claim':
        meta['photo_overlay_verified'] = True
    elif case == 'false_int':
        meta['camera_io'] = 0
    elif case == 'missing_pin':
        meta['source_sha256'].pop(next(iter(meta['source_sha256'])))
    elif case == 'changed_pin':
        meta['source_sha256'][next(iter(meta['source_sha256']))] = '0'*64
    else:
        meta['aspect_patch_windows'] = 37
    with pytest.raises(ValueError):
        merge.validate_plan(merged(), meta)


def test_fixed_source_changes_fail_before_contract_generation(monkeypatch):
    pins = dict(merge.SOURCE_SHA256)
    pins[next(iter(pins))] = '0'*64
    monkeypatch.setattr(merge, 'SOURCE_SHA256', pins)
    with pytest.raises(ValueError, match='来源发生变化'):
        merge.aspect_contract()


def test_full_real_ap_static_composition_reverses_and_preserves_all_other_bytes():
    root = merge.ROOT
    source = root/'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio'
    if not source.exists():
        pytest.skip('固定AP材料未提供；不得替用其他固件')
    raw = read_cpio(source, {'usr/lib/appFw.so'})['usr/lib/appFw.so']
    rows, meta = merge.compose_plan(raw, bootstrap())
    assert merge.validate_plan(rows, meta)
    candidate = compose(raw, merge.AP_SHA, rows)
    assert len(candidate) == len(raw) == 97368304
    inverse = bytearray(candidate)
    for row in rows:
        at, before = row['offset'], bytes.fromhex(row['before'])
        assert candidate[at:at+len(before)] == bytes.fromhex(row['after'])
        inverse[at:at+len(before)] = before
    assert bytes(inverse) == raw
    assert hashlib.sha256(inverse).hexdigest() == merge.AP_SHA
    with pytest.raises(ValueError, match='固定原4.06'):
        merge.compose_plan(candidate, bootstrap())
