import sys
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parents[1] / 'web'
if str(WEB_DIR) not in sys.path:
    sys.path.insert(0, str(WEB_DIR))

import pytest
import core
import export_policy423
import filter_library


def test_catalog_scans_all_filters():
    cat = filter_library.catalog()
    assert cat['slot_limit'] == 24
    assert len(cat['categories']) >= 9
    assert len(cat['filters']) >= 101
    by_key = {item['key']: item for item in cat['filters']}
    assert 'Kodak/Gold200' in by_key
    assert 'Kodak/500T' in by_key
    assert 'Fuji Negative/PRO400H' in by_key
    # Verify generated JPG samples and base samples are linked and readable
    assert len(cat['base_samples']) == 2
    for url in cat['base_samples']:
        from urllib.parse import unquote
        rel = unquote(url.split('/api/filter-samples/', 1)[1])
        assert filter_library.sample_file(rel).is_file()
    for key in ('Kodak/Gold200', 'Kodak/500T', 'Fuji Negative/PRO400H', '富士数码/CC'):
        samples = by_key[key]['samples']
        assert len(samples) == 2
        for url in samples:
            from urllib.parse import unquote
            rel = unquote(url.split('/api/filter-samples/', 1)[1])
            assert filter_library.sample_file(rel).is_file()


def test_pack_v4_and_v5_bundles():
    cat = filter_library.catalog()
    all_keys = [item['key'] for item in cat['filters']]

    # 3 filters -> v4
    payload_v4, cfg_v4, audit_v4 = filter_library.pack_bundle(all_keys[:3])
    assert len(payload_v4) == 128 + 2452 * 3
    assert audit_v4['format_version'] == 4
    unpacked_v4 = core.compiler.unpack(payload_v4)
    assert [e['number'] for e in unpacked_v4['entries']] == [1, 2, 3]

    # 24 filters -> v5
    payload_v5, cfg_v5, audit_v5 = filter_library.pack_bundle(all_keys[:24])
    assert len(payload_v5) == 128 + 2452 * 24
    assert audit_v5['format_version'] == 5
    unpacked_v5 = core.compiler.unpack(payload_v5)
    assert [e['number'] for e in unpacked_v5['entries']] == list(range(1, 25))


def test_pack_rejects_out_of_range_counts():
    cat = filter_library.catalog()
    all_keys = [item['key'] for item in cat['filters']]
    with pytest.raises(ValueError):
        filter_library.pack_bundle([])
    with pytest.raises(ValueError):
        filter_library.pack_bundle(all_keys[:25])


def test_import_bundle_to_project_validates(tmp_path):
    cat = filter_library.catalog()
    sample_keys = [item['key'] for item in cat['filters'][:15]]
    imported = filter_library.import_bundle_to_project(sample_keys, tmp_path)
    validated_cfg, receipts = export_policy423.validate(imported['project'], tmp_path)
    assert len(validated_cfg['entries']) == 15
    assert len(receipts) == 15
