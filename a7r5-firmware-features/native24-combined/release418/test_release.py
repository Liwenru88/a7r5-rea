"""覆盖 4.18 的归档范围、WBI 失效和缺项失败路径。"""

import io
from pathlib import Path
import sys
import tarfile
import zlib

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'release417'))
import container_package as packaging


@pytest.mark.parametrize('invalid', [None, 'missing', 'duplicate'])
def test_archive_updates_four_partitions_with_exact_membership(tmp_path, monkeypatch, invalid):
    parent = packaging.load(packaging.PARENT / 'build.py', 'test_native24_418_parent')
    lib = packaging.PARENT / 'upstream/firmware/r5/src/lib'
    monkeypatch.syspath_prepend(str(lib))
    target = {f'dev/nflasha{i}': tmp_path / f'nflasha{i}' for i in (3, 5, 8, 15)}
    replacements = {'0700_part_image/'+name: path for name, path in target.items()}
    wbi = target['dev/nflasha5']
    original_wbi = tmp_path / 'original-wbi'
    before = b'WBI3' + b'a' * 508 + b'b' * 512
    original_wbi.write_bytes(before)
    for number in (3, 8, 15):
        p = target[f'dev/nflasha{number}']
        p.write_bytes(p.name.encode().ljust(32, b'+'))
    packaging.prepare_wbi(original_wbi, wbi, invalidate=True)
    entries = list(target)
    if invalid == 'missing':
        entries.remove('dev/nflasha3')
    elif invalid == 'duplicate':
        entries[-1] = entries[0]
    entries.append('dev/nflasha2')
    sizes = {name: path.stat().st_size for name, path in target.items()}
    original_sum = ''.join(
        f'0,12345678,{sizes.get(name, 32):08x},0,0,0,root,root,0,0,{name},\n'
        for name in entries
    ).encode()
    tar_path = tmp_path / 'original.tar'
    sum_name = '0701_part_image_sum/part_image.sum'
    with tarfile.open(tar_path, 'w') as tar:
        for name, data in [(k, bytes(p.stat().st_size)) for k, p in replacements.items()] + [(sum_name, original_sum)]:
            item = tarfile.TarInfo(name)
            item.size = len(data)
            tar.addfile(item, io.BytesIO(data))
    report = tmp_path / 'part_image.sum'
    if invalid:
        with pytest.raises(ValueError, match='更新集合不符'):
            parent.archive_overlay(tar_path, replacements, target, report)
        assert not report.exists()
        return
    view, final = parent.archive_overlay(tar_path, replacements, target, report)
    assert final == {**replacements, sum_name: report}
    with view.open('rb') as stream, tarfile.open(fileobj=stream, mode='r:') as rebuilt:
        for name, path in replacements.items():
            expected = bytes(512) + before[512:] if path == wbi else path.read_bytes()
            assert rebuilt.extractfile(name).read() == expected
        assert original_wbi.read_bytes() == before
        lines = [row.split(',') for row in rebuilt.extractfile(sum_name).read().decode().splitlines()]
        for row in lines:
            if row[10] in target:
                assert row[1] == f'{zlib.crc32(target[row[10]].read_bytes()):08x}'
            else:
                assert row[10] == 'dev/nflasha2' and row[1] == '12345678'
