"""核对真实原厂 FAT 的簇链余量及超限拒绝，不改原分区文件。"""
from pathlib import Path
import os
import sys

import pytest

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'a7r5-dat-tool'))
from a7r5dat.fat import FatImage
from fat_avcam import replace
from test_avcam_views import views  # noqa: F401
from test_avcam import stock_avcam  # noqa: F401


def test_avcam_grows_only_inside_existing_chain_and_rejects_overflow(views):
    path = Path(os.environ.get('A7R5_ASPECT_STOCK_AVCAM_PARTITION',
        ROOT / 'a7r5-qemu/runs/verify-17-NqJEIq/dat/archive/0700_part_image/dev/nflasha3'))
    raw = path.read_bytes()
    fs = FatImage(raw)
    image, _ = views
    output, receipt = replace(raw, image)
    actual = FatImage(output)
    assert len(output) == len(raw) and actual.read('/av-cam.bin') == image
    assert actual.entries['/av-cam.bin']['extents'] == fs.entries['/av-cam.bin']['extents']
    assert output[fs.fat_start:fs.root_start] == raw[fs.fat_start:fs.root_start]
    for path, entry in fs.entries.items():
        if path == '/av-cam.bin': continue
        assert actual.entries[path] == entry
        if not entry['is_directory']: assert actual.read(path) == fs.read(path)
    assert receipt['allocation_chain_unchanged'] and receipt['unrelated_bytes_exact']
    with pytest.raises(ValueError, match='原有 FAT 簇链'):
        replace(raw, bytes(receipt['allocated_file_bytes'] + 1))
