"""用独立解码器核对新增资源及原有资源载荷。"""

import io
import os
from pathlib import Path
import struct
import types

import pytest

from build_ap import FIRST_LABEL, FIRST_SMALL_ICON, FIRST_PLAYBACK_ICON, FIRST_PIXEL_ICON, LABELS
from aspect_sizes import PIXEL_LABELS
from build_resources import Ext2, IMAGE_SHA, LANGUAGE_FILE, icons, pixels, strings, text_records
from test_geometry import HERE, ROOT


def test_every_horizontal_and_vertical_language_bank_preserves_its_old_records():
    path = Path(os.environ.get('A7R5_ASPECT_STOCK_USR',
        ROOT/'a7r5-qemu/runs/verify-17-NqJEIq/baseline/inputs/nflasha15'))
    if not path.is_file():
        pytest.skip('需要已核对的 A7R5 原厂 USR')
    app = Ext2(path)
    total = 0
    try:
        for inode, name, _ in app.dir_entries(app.walk('/share/app')):
            if not LANGUAGE_FILE.fullmatch(name):
                continue
            original = app.read_inode(inode)
            built = strings(original, name)
            count = struct.unpack_from('<I', built, 12)[0]//0x1001
            data = (16+count*2+3)&~3
            first = (FIRST_LABEL & 0xffff) - (struct.unpack_from('<H', built, 10)[0]<<13)
            index = 16+first*2
            old_count = struct.unpack_from('<I', original, 12)[0]//0x1001
            old_base = (16+old_count*2+3)&~3
            restored = bytearray(built[:old_base]+built[data:data+len(original)-old_base])
            restored[12:16] = original[12:16]
            for resource, label in text_records(name):
                at = 16+2*((resource & 0xffff)-(struct.unpack_from('<H', built, 10)[0]<<13))
                offset = data+struct.unpack_from('<H', built, at)[0]*4
                assert offset >= len(original)
                tag = struct.unpack_from('<I', built, offset)[0]
                assert tag == 0x1e000000+(resource & 0xffff)
                assert built[offset+4:].split(b'\0', 1)[0].decode('utf-8') == label
                if resource < 0x0200abde:
                    restored[at:at+2] = b'\xff\xff'
            assert restored == original
            total += 1
    finally:
        app.mm.close()
        app.f.close()
    assert total == 68


@pytest.mark.parametrize('name', IMAGE_SHA)
def test_new_aspect_icons_decode_and_preserve_creative_look_images(name):
    folder = Path(os.environ.get('A7R5_ASPECT_NATIVE24_IMAGES',
        ROOT/'a7r5-qemu/runs/a7r5-lens-af-2qHo9T/default'))
    path = folder/name
    if not path.is_file():
        pytest.skip('需要已核对的 native24 图标')
    before = path.read_bytes()
    after = icons(before)
    decoder = types.ModuleType('aspect_reference_lz77')
    source = (HERE.parents[1] / 'firmware-runtime/dependencies/native12-combined/upstream'
              / 'firmware/r5/src/lib/fwtool/lz77/__init__.py')
    exec(compile(source.read_bytes(), str(source), 'exec'), decoder.__dict__)
    count = struct.unpack_from('<I', after, 12)[0]&0x1fff
    first = FIRST_SMALL_ICON & 0x1fff

    def record(raw, i):
        own_count = struct.unpack_from('<I', raw, 12)[0]&0x1fff
        if i >= own_count:
            return None
        base = (16+2*own_count+3)&~3
        index = struct.unpack_from('<H', raw, 16+2*i)[0]
        if index == 0xffff:
            return None
        at = base+4*index
        key, flags, shape = struct.unpack_from('<III', raw, at)
        field = 32 if flags&0x08000000 else 12
        size, relative = struct.unpack_from('<II', raw, at+field)
        start = at+4+relative
        return key, flags, shape, raw[start:start+size]

    for i in range(count):
        new = record(after, i)
        playback = i - (FIRST_PLAYBACK_ICON & 0x1fff)
        pixel = i - (FIRST_PIXEL_ICON & 0x1fff)
        if first <= i < first+3*len(LABELS) or 0 <= playback < 6 or 0 <= pixel < 18:
            assert record(before, i) is None
            key, flags, shape, payload = new
            slot = i-first
            if 0 <= playback < 6:
                label, variant, width, height = LABELS[playback], 0, 47, 32
                sizes = [3072]
            elif 0 <= pixel < 18:
                label, variant, width, height = PIXEL_LABELS[pixel], 0, 47, 32
                sizes = [3072]
            elif slot < len(LABELS):
                label, variant, width, height = slot, 0, 76, 40
                sizes = [4096, 2304]
            else:
                label, variant = divmod(slot-len(LABELS), 2)
                width, height = 70, 60
                sizes = [4096, 4096, 1408]
            if isinstance(label, int):
                label = LABELS[label]
            assert (key, flags, shape) == (0x1a000000+i, 0xc0000000, (height<<16)|width)
            stream = io.BytesIO(payload)
            blocks = [decoder.inflateLz77(stream) for _ in sizes]
            assert stream.tell() == len(payload) and list(map(len, blocks)) == sizes
            assert b''.join(blocks) == pixels(label, variant, width, height)
        else:
            assert new == record(before, i)
