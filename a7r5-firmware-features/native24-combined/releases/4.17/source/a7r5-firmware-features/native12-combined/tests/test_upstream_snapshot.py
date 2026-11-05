"""集中归档后的来源合同；只在临时副本中测试篡改拒绝。"""
import importlib.util
from pathlib import Path
import shutil

import pytest

HERE = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('native12_archive_builder', HERE/'build.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


def test_archived_snapshot_is_usable_without_git_metadata():
    upstream = HERE/'upstream'
    assert not (upstream/'.git').exists()
    firmware, lock = builder.check_upstream(upstream)
    assert firmware == upstream/'firmware/r5'
    assert len(lock) == 188


@pytest.mark.parametrize('change', ['source', 'manifest', 'extra'])
def test_archived_snapshot_rejects_modified_or_unlisted_sources(tmp_path, change):
    upstream = tmp_path/'upstream'
    shutil.copytree(HERE/'upstream', upstream)
    if change == 'source':
        with (upstream/'firmware/r5/build.py').open('a') as stream:
            stream.write('\n# 非原始来源\n')
    elif change == 'manifest':
        with (upstream/'UPSTREAM_SNAPSHOT.json').open('a') as stream:
            stream.write(' ')
    else:
        (upstream/'firmware/r5/src/lib/numpy.py').write_text('# 未登记的遮蔽模块\n')
    with pytest.raises(ValueError, match='快照'):
        builder.check_upstream(upstream)


def test_build_source_receipt_excludes_archives_and_generated_work(tmp_path, monkeypatch):
    module = tmp_path/'module'
    module.mkdir()
    (module/'tests').mkdir()
    for name in ('build.py', 'patches.py', 'integration.S', 'integration.ld', 'selection.S',
                 'menu_font.py', 'menu-font.c', 'tests/test_case.py', 'tests/runtime_case.c'):
        (module/name).write_text('# 测试材料\n')
    for folder in ('build', 'releases', 'upstream'):
        (module/folder).mkdir()
        (module/folder/'not_a_source.py').write_text('# 不属于本模块的实施源\n')
    monkeypatch.setattr(builder, 'HERE', module)
    monkeypatch.setattr(builder, 'ROOT', tmp_path)
    files = builder.implementation_sources()
    assert len(files) == 9
    assert 'module/menu_font.py' in files and 'module/menu-font.c' in files
    assert 'module/build.py' in files and 'module/tests/test_case.py' in files
    assert 'module/tests/runtime_case.c' in files
    assert all('not_a_source.py' not in name for name in files)
