from pathlib import Path
import struct
import sys
import zlib

from build import update_header
from fixtures import header

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'a7r5-dat-tool'))
from a7r5dat.codec import header_info


def test_updated_filesystem_keeps_updater_and_archive_bounds_consistent():
    raw = header()
    old_size, = struct.unpack_from('<I', raw, 72)
    result = update_header(raw, old_size + 4096)
    assert result[32:34] == b'\x21\x04'
    assert struct.unpack_from('<I', result, 8)[0] == zlib.crc32(result[12:])
    total = sum(struct.unpack_from('<II', result, 48))
    info = header_info(result, total)
    assert info['updater_bytes'] == old_size + 4096
    assert info['tar_offset'] == 512 + old_size + 4096
    changed = {i for i, (a, b) in enumerate(zip(raw, result)) if a != b}
    assert changed <= set(range(8, 12)) | {32, 33} | set(range(48, 52)) | set(range(72, 76))
