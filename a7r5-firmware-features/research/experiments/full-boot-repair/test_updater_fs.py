import io
from pathlib import Path
import sys

import pytest

from updater_fs import replace_script
from shell_status import repair_status
from fixtures import updater_image

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'a7r5-firmware-features/native24-combined/dependencies/native12-combined/upstream/firmware/r5/src/lib'))
from fwtool.archive.squashfs import readSquashfs, SquashfsSuper



def snapshot(raw):
    return {f.path: (f.mode, f.uid, f.gid, f.mtime, None if f.contents is None else f.contents.read())
            for f in readSquashfs(io.BytesIO(raw))}


def test_new_nor_script_is_visible_without_changing_other_files():
    raw = updater_image()
    before = snapshot(raw)
    content = Path(__file__).with_name('nor_loader_writer.sh').read_bytes()
    result = replace_script(raw, content)
    after = snapshot(result)
    path = '/bin/nor_loader_writer.sh'
    assert after[path][-1] == content
    assert set(before) == set(after)
    assert after[path][:-1] == before[path][:-1]
    assert all(before[p] == after[p] for p in before if p != path)
    left, right = SquashfsSuper.unpack(raw), SquashfsSuper.unpack(result)
    for field in ('inodeCount', 'rootInodeRef', 'compressionId', 'blockSize', 'flags'):
        assert getattr(left, field) == getattr(right, field)
    assert right.bytesUsed <= len(result) and len(result) % 4096 == 0


@pytest.mark.parametrize('raw,content', [(b'', b'x'), (b'bad', b'x'), (None, b'')], ids=['empty-image','wrong-image','empty-script'])
def test_unknown_image_or_empty_script_is_rejected(raw, content):
    if raw is None:
        raw = updater_image()
    with pytest.raises(ValueError):
        replace_script(raw, content)


def test_rebuilt_tables_keep_native_squashfs_order():
    result = replace_script(updater_image(), Path(__file__).with_name('nor_loader_writer.sh').read_bytes())
    superblock = SquashfsSuper.unpack(result)
    offsets = [superblock.inodeTableStart, superblock.directoryTableStart,
               superblock.fragmentTableStart, superblock.exportTableStart,
               superblock.idTableStart, superblock.bytesUsed]
    assert offsets == sorted(offsets)


def test_shell_status_library_replacement_preserves_other_updater_files():
    raw = updater_image()
    before = snapshot(raw)
    library = repair_status(before['/bodylib/libupdaterbody.so'][-1])
    script = Path(__file__).with_name('nor_loader_writer.sh').read_bytes()
    result = replace_script(raw, script, library)
    after = snapshot(result)
    assert after['/bodylib/libupdaterbody.so'][-1] == library
    assert after['/bin/nor_loader_writer.sh'][-1] == script
    changed = {p for p in before if before[p] != after.get(p)}
    assert changed == {'/bodylib/libupdaterbody.so', '/bin/nor_loader_writer.sh'}
    assert set(before) == set(after)
    assert all(before[p][:-1] == after[p][:-1] for p in changed)
