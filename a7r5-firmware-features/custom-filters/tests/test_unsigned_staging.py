"""准备清单不能扩大改写范围或伪装已发布；实际镜像由独立staging回执验证。"""
from copy import deepcopy
from pathlib import Path
import sys
import json
import struct
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments/packaging406'))
import stage_unsigned_usr as staging
from aspect_merge import aspect_contract, aspect_metadata


def test_manifest_checksum_and_parse_use_the_same_read_snapshot(tmp_path):
    path = tmp_path/'manifest.json'
    raw = json.dumps({'status': 'original'}).encode()
    path.write_bytes(raw)
    class ChangingPath:
        def read_bytes(self):
            data = path.read_bytes()
            path.write_bytes(b'{"status":"changed"}')
            return data
    assert staging.frozen_manifest(ChangingPath(), staging.sha(raw)) == {'status': 'original'}
    with pytest.raises(ValueError, match='摘要'):
        staging.frozen_manifest(path, staging.sha(raw))


def ap_patches(version=1):
    end = 0x500fdfc if version == 1 else 0x500ff8c
    rows = [(0x500fc70, bytes(396), b'\x01'*396),
            (0x17feac0, bytes.fromhex('fd7bbaa9'), bytes.fromhex('6c44e014'))]
    if version == 2:
        rows += [(0x500fdfc, bytes(400), b'\x02'*400),
                 (0x5010388, struct.pack('<Q', 0x16fbfc0), struct.pack('<Q', 0x500fdfc)),
                 (0x10c68, struct.pack('<Q', 0x16fbfc0), struct.pack('<Q', 0x500fdfc))]
    rows += [(offset, struct.pack('<Q', 0x500fc10), struct.pack('<Q', end)) for offset in (0x60, 0x68)]
    return [dict(offset=offset, before=before.hex(), after=after.hex()) for offset, before, after in rows]


def manifest(version=1):
    names = [f'/share/app/string_test{chr(97+i//26)}{chr(97+i%26)}_{orientation}.uxc'
             for i in range(34) for orientation in ('horizontal', 'vertical')]
    names += list(staging.AppendImagePatch._bindings)
    return dict(schema=f'a7r5-406-unsigned-staging-input/{version}', status='FROZEN_PREPARE_ONLY_DEFAULT_CLOSED',
                installable_firmware=False, CP_gates_installed=False, UI_gates_installed=False,
                source_usr={'sha256': staging.USR_SHA},
                ap={'source_sha256': staging.AP_SHA, 'includes_aspect_changes': False, 'patches': ap_patches(version)},
                dsos=[{'target': n, 'bytes': 64, 'sha256': '1'*64} for n in staging.DSOS],
                resource_replacements=[{'target': n, 'source_member': n, 'bytes': 64, 'sha256': '2'*64}
                                       for n in names])


@pytest.mark.parametrize('scope', ['published', 'aspect', 'protected_library', 'resource_path', 'duplicate_resource'])
def test_refuses_published_or_widened_manifest_before_any_file_access(scope):
    original = manifest()
    assert len(staging.validate_manifest(original)) == 70
    m = deepcopy(original)
    if scope == 'published':
        m['UI_gates_installed'] = True
    elif scope == 'aspect':
        m['ap']['includes_aspect_changes'] = True
    elif scope == 'protected_library':
        m['dsos'][0]['target'] = '/lib/libObj.so'
    elif scope == 'resource_path':
        m['resource_replacements'][0]['target'] = '/share/app/../protected'
    else:
        m['resource_replacements'][0] = m['resource_replacements'][1]
    with pytest.raises(ValueError):
        staging.validate_manifest(m)


@pytest.mark.parametrize('change', ['outside', 'duplicate', 'length', 'constructor', 'extent'])
def test_constructor_bootstrap_accepts_only_the_seven_fixed_windows(change):
    m = manifest(2)
    assert len(staging.validate_manifest(m)) == 70
    patches = m['ap']['patches']
    if change == 'outside':
        patches[0]['offset'] += 4
    elif change == 'duplicate':
        patches[1] = deepcopy(patches[0])
    elif change == 'length':
        patches[2]['before'] += '00'
        patches[2]['after'] += '00'
    elif change == 'constructor':
        patches[3]['after'] = struct.pack('<Q', 0x16fbfc0).hex()
    else:
        patches[-1]['after'] = struct.pack('<Q', 0x5010004).hex()
    with pytest.raises(ValueError):
        staging.validate_manifest(m)


@pytest.mark.parametrize('fault', [None, 'old_schema', 'bool_integer', 'missing_metadata', 'missing_window'])
def test_photo_markers_require_explicit_combined_manifest(fault):
    m = manifest(2)
    m['schema'] = 'a7r5-406-unsigned-staging-input/3'
    m['ap'].update(includes_aspect_changes=True, aspect_merge=aspect_metadata())
    m['ap']['patches'] += aspect_contract()
    if fault == 'old_schema':
        m['schema'] = 'a7r5-406-unsigned-staging-input/2'
    elif fault == 'bool_integer':
        m['ap']['includes_aspect_changes'] = 1
    elif fault == 'missing_metadata':
        m['ap'].pop('aspect_merge')
    elif fault == 'missing_window':
        m['ap']['patches'].pop()
    if fault is None:
        assert len(staging.validate_manifest(m)) == 70
    else:
        with pytest.raises(ValueError):
            staging.validate_manifest(m)
