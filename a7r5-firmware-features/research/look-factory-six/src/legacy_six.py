"""读取与原六款实现逐字节匹配的 A7R5 固定配方。"""

import base64
from hashlib import sha256
import json
from pathlib import Path
import struct


MATERIALS = Path(__file__).resolve().parents[2] / 'materials'
SOURCE_PINS = {
    'six-looks.json': '9b48e4a2fe2b5bfff1280fbcc52c5795f9a3826c32b1f9c6d08559dd2e13e1fb',
    'joint-layout.json': '02f5494969b2d48da90f22db19ffd13924656b046d0cf622200b1afecfcac14d',
}
FILES = (
    '1-Classic-Neg.a7look', '2-Classic-Chrome.a7look', '3-Nostalgic-Neg.a7look',
    '4-Astia.a7look', '5-GR-Positive-Film.a7look', '6-GR-Negative-Film.a7look',
)


def pinned_json(folder, name):
    raw = (folder / name).read_bytes()
    if sha256(raw).hexdigest() != SOURCE_PINS[name]:
        raise ValueError('六款历史材料摘要不符 ' + name)
    return json.loads(raw)


def load_recipes(folder=MATERIALS):
    catalog = pinned_json(folder, 'six-looks.json')
    layout = pinned_json(folder, 'joint-layout.json')
    if len(catalog['slots']) != len(FILES):
        raise ValueError('六款目录数量不符')
    patches = {row['offset']: bytes.fromhex(row['after']) for row in layout['patches']}
    old_payload = patches[layout['payload_source_VA'] - 0x108000]
    old_tables = patches[0x108d2c0]
    recipes = []
    for index, (filename, slot) in enumerate(zip(FILES, catalog['slots'], strict=True)):
        doc = json.loads((folder / 'upstream-default-six' / filename).read_bytes())
        canonical = (json.dumps(doc, sort_keys=True) + '\n').encode()
        if sha256(canonical).hexdigest() != slot['upstream_profile_canonical_sha256']:
            raise ValueError('配方摘要不符 ' + filename)
        grid = base64.b64decode(doc['table_base64'], validate=True)
        basis = doc['native_photo']['runtime_basis']
        if (slot['slot'] != index + 1 or slot['name'] != doc['name'] or
                slot['native_photo_basis'] != basis or doc['base'] != 'ST' or
                len(grid) != 1215 or any(not -64 <= value <= 63 for value in struct.unpack('1215b', grid)) or
                sha256(grid).hexdigest() != slot['table_sha256']):
            raise ValueError('配方与六款目录不符 ' + filename)
        expanded = []
        for a, b, c, d, e, f in basis['matrix_planes']:
            expanded.extend((a + b, -a, -b, -c, c + d, -d, -e, -f, e + f))
        chroma = [value for plane in basis['chroma_planes'] for value in plane]
        basis_bytes = struct.pack('<54h', *basis['tone_q10'], *expanded, *chroma)
        table_at, basis_at = 32 + index * 1215, index * 108
        if (grid != old_tables[table_at:table_at + 1215] or
                basis_bytes != old_payload[basis_at:basis_at + 108]):
            raise ValueError('色表或增量与历史固件实装数据不符 ' + filename)
        recipes.append((doc['name'], grid, basis_bytes))
    return tuple(recipes)
