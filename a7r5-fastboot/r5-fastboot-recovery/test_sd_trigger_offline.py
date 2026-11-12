import importlib.util
import json
from pathlib import Path
import sys

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
ROOT = HERE.parents[1]
REFERENCE = ROOT / 'a7r5-firmware-images/标准固件_19项/明文分区_17项/cnflasha2.img'


def module():
    path = HERE / 'sd_trigger_offline.py'
    assert path.is_file(), 'Offline-only trigger generator is missing'
    spec = importlib.util.spec_from_file_location('sd_trigger_offline', path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_generate_roundtrip_without_changing_inputs(tmp_path):
    mod = module()
    before = REFERENCE.read_bytes()
    image = tmp_path / 'fresh.logical.img'
    image.write_bytes(before)
    package = tmp_path / 'BODYDATA.DAT'
    package.write_bytes(b'test package identity only')
    output = tmp_path / 'candidate'
    report = mod.generate(image, package, output)
    after = (output / 'OFFLINE_ONLY.settings.logical.img').read_bytes()
    sparse = (output / 'OFFLINE_ONLY.trigger.sparse.img').read_bytes()
    assert mod.apply_sparse(before, sparse) == (after, report['plan']['changed_sectors'])
    assert mod.make_trigger(after)[0] == after
    assert image.read_bytes() == before
    assert package.read_bytes() == b'test package identity only'
    assert report['camera_io'] is False
    assert report['flash_authorized'] is False
    assert report['package_compatibility_verified'] is False
    assert json.loads((output / 'report.json').read_text()) == report


def test_reject_short_settings_before_creating_output(tmp_path):
    mod = module()
    image = tmp_path / 'bad.img'
    image.write_bytes(b'bad')
    package = tmp_path / 'BODYDATA.DAT'
    package.write_bytes(b'package')
    output = tmp_path / 'candidate'
    with pytest.raises(ValueError):
        mod.generate(image, package, output)
    assert not output.exists()


def test_refuse_existing_output(tmp_path):
    mod = module()
    output = tmp_path / 'candidate'
    output.mkdir()
    marker = output / 'keep'
    marker.write_text('untouched')
    with pytest.raises(FileExistsError):
        mod.generate(REFERENCE, REFERENCE, output)
    assert marker.read_text() == 'untouched'


def test_conflicting_mode_is_rejected():
    mod = module()
    before = REFERENCE.read_bytes()
    after, _ = mod.make_trigger(before)
    fs = mod.FatImage(after)
    bad = bytearray(after)
    off = fs.entries['/updater/mode5']['directory_entry_offset']
    bad[off:off + 8] = b'MODE1   '
    with pytest.raises(ValueError, match='Conflicting'):
        mod.make_trigger(bytes(bad))
