"""冻结材料恢复必须匹配原清单，不得吞掉未知漂移。"""
import importlib.util
import json
from pathlib import Path
import shutil

import pytest

FEATURES = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('snapshot_repair', FEATURES / 'materials/restore_snapshot.py')
repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(repair)


@pytest.fixture
def source(tmp_path):
    root = tmp_path / 'frozen'
    root.mkdir()
    shutil.copyfile(repair.DEFAULT_ROOT / 'UPSTREAM_SNAPSHOT.json', root / 'UPSTREAM_SNAPSHOT.json')
    return root


def test_missing_materials_restore_exactly_then_skip(source):
    result = repair.restore(source, source_dir=repair.DEFAULT_ROOT)
    assert len(result['restored']) == len(repair.ALLOWED)
    assert repair.restore(source)['restored'] == []
    pins = json.loads((source / 'UPSTREAM_SNAPSHOT.json').read_text())['files']
    for name in result['restored']:
        assert repair.digest((source / name).read_bytes()) == pins[name]['sha256']


def test_unknown_binary_preimage_stops_before_any_write(source):
    target = source / 'R5FlashWorkbench/engine/templates/capture.so'
    target.parent.mkdir(parents=True)
    target.write_bytes(b'unknown')
    with pytest.raises(ValueError, match='未知前像'):
        repair.restore(source, source_dir=repair.DEFAULT_ROOT)
    assert target.read_bytes() == b'unknown' and not (source / '.gitignore').exists()


def test_gitignore_drift_requires_explicit_restore_and_backup(source, tmp_path):
    target = source / '.gitignore'
    target.write_bytes(b'drift')
    with pytest.raises(ValueError, match='未知前像'):
        repair.restore(source, source_dir=repair.DEFAULT_ROOT)
    backup = tmp_path / 'backup'
    repair.restore(source, backup=backup, restore_gitignore=True, source_dir=repair.DEFAULT_ROOT)
    assert (backup / 'gitignore.before').read_bytes() == b'drift'
    assert target.read_bytes() != b'drift'


def test_tampered_capsule_and_symlink_are_refused_before_write(source, tmp_path):
    capsule = json.loads(repair.CAPSULE.read_text())
    capsule['files'][0]['sha256'] = '0' * 64
    path = tmp_path / 'capsule.json'
    path.write_text(json.dumps(capsule))
    with pytest.raises(ValueError):
        repair.restore(source, capsule=path, source_dir=repair.DEFAULT_ROOT)
    external = tmp_path / 'external'
    external.mkdir()
    (source / 'R5FlashWorkbench').symlink_to(external, target_is_directory=True)
    with pytest.raises(ValueError, match='链接'):
        repair.restore(source, source_dir=repair.DEFAULT_ROOT)
    assert not list(external.iterdir()) and not (source / '.gitignore').exists()


def test_missing_material_does_not_implicitly_access_network(source, monkeypatch):
    monkeypatch.setattr(repair.urllib.request, 'urlopen', lambda *a, **k: pytest.fail('未显式授权下载'))
    with pytest.raises(ValueError, match='显式 --download'):
        repair.restore(source)
    assert not (source / '.gitignore').exists()
