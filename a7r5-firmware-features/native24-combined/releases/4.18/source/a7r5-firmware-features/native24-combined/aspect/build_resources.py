"""从只读 A7R5 资源中派生纵横比文字和图标。"""

import argparse
import hashlib
import json
from pathlib import Path
import re
import struct
import sys

from build_ap import FIRST_LABEL, FIRST_SMALL_ICON, LABELS, HERE
from unified_icons import GLYPHS, HEADER, payload_fields

sys.path.insert(0, str(HERE.parent))
sys.path.insert(0, str(HERE.parents[2] / 'a7r5-dat-tool'))
from icon_codec import native_lz77_stream
from a7r5dat.ext2read import Ext2


USR_SHA = '197fc934db37ed9b88701ae7fd2e866126f63e098f6d45e3fd767618af638fa5'
IMAGE_SHA = {
    'image_00_23_IPSX.uxc': '6e8c09e8e8a302aa05e7d8dd56f68bdb3675c486ca54a88ba81375b5c02a3bb7',
    'image_00_32_IPSX.uxc': '7e598d75a997c37cea6204e8e35773e9b9ee5e4ce67b0c0ab569011563af3356',
}
LANGUAGE_FILE = re.compile(r'string_([a-z]+)_(horizontal|vertical)\.uxc')


def strings(raw):
    count, remainder = divmod(struct.unpack_from('<I', raw, 12)[0], 0x1001)
    first = struct.unpack_from('<H', raw, 10)[0] << 13
    base = (16+count*2+3)&~3
    index = (FIRST_LABEL & 0xffff)-first
    if raw[:4] != b'uxc\x07' or remainder or not 0 <= index <= count-len(LABELS) or len(raw) % 4:
        raise ValueError('纵横比文字银行布局不符')
    output = bytearray(raw)
    for i, label in enumerate(LABELS):
        at = 16+2*(index+i)
        pointer = (len(output)-base)//4
        if raw[at:at+2] != b'\xff\xff' or not 0 <= pointer < 0xffff:
            raise ValueError('纵横比文字索引已占用或越界')
        struct.pack_into('<H', output, at, pointer)
        output.extend(struct.pack('<I', 0x1e000000 | ((FIRST_LABEL & 0xffff)+i)))
        output.extend(label.encode('ascii')+b'\0')
        output.extend(bytes((-len(output)) % 4))
    return bytes(output)


def pixels(label, selected, width=70, height=60):
    stride = 80
    data = bytearray(stride*height*2)
    glyphs = {**GLYPHS,
              ':': ('00000', '00100', '00100', '00000', '00100', '00100', '00000'),
              '.': ('00000', '00000', '00000', '00000', '00000', '00100', '00100')}

    def paint(x, y):
        struct.pack_into('<H', data, (y*stride+x)*2, 0xffff if not selected else 0xfa0f)

    top = (height-26)//2
    for x in range(3, width-3):
        paint(x, top)
        paint(x, top+25)
    for y in range(top+1, top+25):
        paint(3, y)
        paint(width-4, y)
    start = (width-(12*len(label)-2))//2
    for position, character in enumerate(label):
        for y, row in enumerate(glyphs[character]):
            for x, pixel in enumerate(row):
                if pixel == '1':
                    for dy in range(2):
                        for dx in range(2):
                            paint(start+position*12+x*2+dx, top+6+y*2+dy)
    return bytes(data)


def icons(raw):
    packed = struct.unpack_from('<I', raw, 12)[0]
    count = packed & 0x1fff
    first = FIRST_SMALL_ICON & 0x1fff
    layouts = ([(label, 0, 76, 40) for label in LABELS] +
               [(label, variant, 70, 60) for label in LABELS for variant in range(2)])
    base = (16+count*2+3)&~3
    if raw[:12] != HEADER or count != 0x1ed4 or packed != (count | count<<12):
        raise ValueError('纵横比图标银行布局不符')
    records = []
    for i in range(count):
        pointer = struct.unpack_from('<H', raw, 16+i*2)[0]
        if first <= i < first+len(layouts) and pointer != 0xffff:
            raise ValueError('纵横比图标索引已占用')
        if pointer != 0xffff:
            at = base+4*pointer
            key, flags = struct.unpack_from('<II', raw, at)
            field, size, offset = payload_fields(raw, at, flags)
            if key != 0x1a000000+i or not 0 < size <= len(raw)-(at+4+offset):
                raise ValueError('纵横比图标银行含非法原厂记录')
            records.append((at, field, offset))
    boundary = min(at+4+offset for at, _, offset in records)
    extra = 20*len(layouts)
    if any(at+field+8 > boundary for at, field, _ in records) or (boundary-base) % 4:
        raise ValueError('原厂图标记录与载荷交叠')
    output = bytearray(raw[:boundary]+bytes(extra)+raw[boundary:])
    for at, field, offset in records:
        struct.pack_into('<I', output, at+field+4, offset+extra)
    for slot, (label, variant, width, height) in enumerate(layouts):
        at = boundary+20*slot
        pointer = (at-base)//4
        if not 0 <= pointer < 0xffff:
            raise ValueError('纵横比图标描述符索引越界')
        stream = native_lz77_stream(pixels(label, variant, width, height))
        struct.pack_into('<H', output, 16+2*(first+slot), pointer)
        struct.pack_into('<IIHHII', output, at, 0x1a000000+first+slot, 0xc0000000,
                         width, height, len(stream), len(output)-at-4)
        output.extend(stream)
        output.extend(bytes((-len(output))%4))
    return bytes(output)


def build_resources(usr, native24, output):
    with usr.open('rb') as f:
        if hashlib.file_digest(f, 'sha256').hexdigest() != USR_SHA:
            raise ValueError('A7R5 原厂 USR 身份不符')
    app = Ext2(usr)
    try:
        files = {name: strings(app.read_inode(i)) for i, name, _ in app.dir_entries(app.walk('/share/app'))
                 if LANGUAGE_FILE.fullmatch(name)}
    finally:
        app.mm.close()
        app.f.close()
    pairs = {(m[1], m[2]) for name in files if (m := LANGUAGE_FILE.fullmatch(name))}
    if len(pairs) != 68 or any((language, other) not in pairs for language, _ in pairs
                                for other in ('horizontal', 'vertical')):
        raise ValueError('纵横比文字银行缺少语言或方向')
    for name, expected in IMAGE_SHA.items():
        raw = (native24/name).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError('A7R5 native24 图标银行身份不符')
        files[name] = icons(raw)

    output.mkdir(mode=0o700)
    receipt = {}
    for name, data in sorted(files.items()):
        (output/name).write_bytes(data)
        receipt[name] = hashlib.sha256(data).hexdigest()
    (output/'build.json').write_text(json.dumps(receipt, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('usr', 'native24', 'output'):
        parser.add_argument('--'+name, type=Path, required=True)
    args = parser.parse_args()
    build_resources(args.usr, args.native24, args.output)
