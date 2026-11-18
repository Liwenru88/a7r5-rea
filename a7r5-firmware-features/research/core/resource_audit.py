"""检查最终解包 USR；文字和图标采用独立、有界的格式读取。"""
import hashlib
import json
from pathlib import Path
import re
import struct

from .plan import FEATURES, require

LANGUAGE = re.compile(r'string_([a-z]+)_(horizontal|vertical)\.uxc')
IMAGES = ('image_00_23_IPSX.uxc', 'image_00_32_IPSX.uxc')


def text_bank(raw):
    require(len(raw) >= 16 and raw[:4] == b'uxc\x07', '文字银行头无效')
    count, remainder = divmod(struct.unpack_from('<I', raw, 12)[0], 0x1001)
    first = struct.unpack_from('<H', raw, 10)[0] << 13
    base = (16 + count * 2 + 3) & ~3
    require(not remainder and 0 < count <= 8192 and first + count <= 65536
            and base <= len(raw), '文字索引越界')
    records = {}
    for index in range(count):
        pointer = struct.unpack_from('<H', raw, 16 + 2 * index)[0]
        if pointer == 0xffff:
            continue
        at = base + 4 * pointer
        require(at + 4 < len(raw), '文字记录越界')
        require(struct.unpack_from('<I', raw, at)[0] == 0x1e000000 | (first + index), '文字记录标识不符')
        end = raw.find(b'\0', at + 4)
        require(end >= 0, '文字缺少终止符')
        try:
            text = raw[at + 4:end].decode('utf-8')
        except UnicodeDecodeError as error:
            raise ValueError('文字不是有效 UTF-8') from error
        require('\ufffd' not in text, '文字含替代字符')
        records[0x02000000 | (first + index)] = text
    return records


def required_text(records, expected):
    for key, value in expected.items():
        require(key in records, f'缺少文字资源 {key:#x}')
        require(records[key] == value, f'文字资源内容不符 {key:#x}')


def language_pairs(names, languages):
    actual = {(m[1], m[2]) for name in names if (m := LANGUAGE.fullmatch(name))}
    wanted = {(language, direction) for language in languages for direction in ('horizontal', 'vertical')}
    require(actual == wanted, '语言银行横竖配对或语言集合不完整')


def check_claims(claims):
    seen = {}
    for domain, first, end, owner in claims:
        require(0 <= first < end <= 0x100000000, '资源声明范围无效')
        for key in range(first, end):
            require((domain, key) not in seen, f'资源编号冲突 {domain}:{key:#x}，{owner} 与 {seen.get((domain, key))}')
            seen[domain, key] = owner


def pages(raw):
    """每块重置字典，拒绝跨页反向引用、短读及超过 4 KiB 的单块。"""
    position = 0
    result = []

    def take(length):
        nonlocal position
        require(position + length <= len(raw), '图标压缩块短读')
        data = raw[position:position + length]
        position += length
        return data

    while position < len(raw):
        kind = take(1)[0]
        if kind == 0x0f:
            require(take(1) == b'\0', '图标原样块保留字节不符')
            length = int.from_bytes(take(2), 'little')
            require(0 < length <= 4096, '图标单块超出 4 KiB')
            take(length)
        else:
            require(kind == 0xf0, '图标压缩类型未知')
            output = bytearray()
            done = False
            while not done:
                flags = take(1)[0]
                for bit in range(8):
                    if flags & (1 << bit):
                        high, low = take(2)
                        distance = ((high & 15) << 8) | low
                        if not distance:
                            done = True
                            break
                        require(distance <= len(output), '图标跨块字典引用')
                        length = (*range(3, 17), 32, 64)[high >> 4]
                        require(len(output) + length <= 4096, '图标单块超出 4 KiB')
                        for _ in range(length):
                            output.append(output[-distance])
                    else:
                        require(len(output) < 4096, '图标单块超出 4 KiB')
                        output.extend(take(1))
            length = len(output)
            require(length > 0, '图标空压缩块')
        if result:
            require(result[-1] == 4096, '图标中间块不足 4 KiB')
        result.append(length)
    require(result, '图标载荷为空')
    return result


def image_bank(raw):
    require(len(raw) >= 16 and raw[:12] == bytes.fromhex('757864070000000008000000'), '图标银行头不符')
    packed = struct.unpack_from('<I', raw, 12)[0]
    count = packed & 0x1fff
    base = (16 + 2 * count + 3) & ~3
    require(count and packed == (count | count << 12) and base < len(raw), '图标索引越界')
    records = {}
    descriptors = []
    for index in range(count):
        pointer = struct.unpack_from('<H', raw, 16 + 2 * index)[0]
        if pointer == 0xffff:
            continue
        at = base + pointer * 4
        require(at + 20 <= len(raw), '图标描述符越界')
        tag, flags, shape = struct.unpack_from('<III', raw, at)
        require(tag == 0x1a000000 | index and flags in (0x40000000, 0xc0000000, 0x48000000, 0xc8000000), '图标标识或类型不符')
        field = 32 if flags & 0x08000000 else 12
        require(at + field + 8 <= len(raw), '图标复杂描述符越界')
        if field == 32:
            require(struct.unpack_from('<I', raw, at + 12)[0] == 0x10002, '图标复杂描述符类型不符')
        size, relative = struct.unpack_from('<II', raw, at + field)
        start = at + 4 + relative
        require(size > 0 and start % 4 == 0 and at + field + 8 <= start <= len(raw) - size, '图标载荷越界或未对齐')
        descriptors.append((at, at + field + 8, start))
        blocks = pages(raw[start:start + size])
        records[0x02000000 | index] = dict(shape=shape, blocks=blocks)
    require(records, '图标银行为空')
    boundary = min(row[2] for row in descriptors)
    require(all(end <= boundary for _, end, _ in descriptors)
            and len({at for at, _, _ in descriptors}) == len(descriptors), '图标描述符重叠或与载荷交叠')
    return records


def requirements(plan, language):
    ids = set(plan.get('requested', ())) | {row['id'] for row in plan.get('modules', ())}
    text, icons, claims = {}, {}, []
    if ids & {'look24', 'look24-core'}:
        icons.update({0x02001ea4 + i: (70, 35, [4096, 1504]) for i in range(48)})
        claims += [('icon', 0x02001ea4, 0x02001ed4, 'look24'),
                   ('menu', 0x1610, 0x1628, 'look24'),
                   ('dynamic-text', 0x02ff4301, 0x02ff4319, 'look24'),
                   ('dynamic-text', 0x02ff4601, 0x02ff4680, 'look24'),
                   ('dynamic-text', 0x02ff4a00, 0x02ff4a06, 'look24')]
    if 'look-factory-six' in ids:
        names = json.loads((FEATURES / 'materials/recipes.json').read_text())['names']
        text.update({0x0200abd8 + i: name for i, name in enumerate(names)})
        claims += [('text', 0x0200abd8, 0x0200abde, 'look-factory-six')]
    if 'photo-aspect-ratios' in ids:
        labels = ('17:6', '65:24', '5:4', '7:6', '1.91:1', '2.35:1')
        statuses = {
            'simplifiedchinese': ('画幅：正在保存', '画幅已生效，保存失败', '画幅：正在恢复', '画幅：读取失败'),
            'traditionalchinese': ('畫幅：正在儲存', '畫幅已生效，儲存失敗', '畫幅：正在還原', '畫幅：讀取失敗'),
        }.get(language, ('Aspect: saving', 'Aspect: active, save failed', 'Aspect: restoring', 'Aspect: restore failed'))
        text.update({0x0200ab60 + i: name for i, name in enumerate(labels)})
        text.update({0x0200abde + i: name for i, name in enumerate(statuses)})
        for first, count, width, height, blocks in (
            (0x02001e8a, 6, 76, 40, [4096, 2304]), (0x02001e90, 12, 70, 60, [4096, 4096, 1408]),
            (0x02001ef0, 6, 47, 32, [3072]), (0x02001f00, 18, 47, 32, [3072])):
            icons.update({first + i: (width, height, blocks) for i in range(count)})
            claims.append(('icon', first, first + count, 'photo-aspect-ratios'))
        claims += [('text', 0x0200ab60, 0x0200ab66, 'photo-aspect-ratios'),
                   ('text', 0x0200abde, 0x0200abe2, 'photo-aspect-ratios'),
                   ('menu', 0x1600, 0x1606, 'photo-aspect-ratios')]
    if plan.get('variants', {}).get('photo-electronic-shutter-sound') == 'custom-dual-full':
        for first, count in ((0x1680, 61), (0x16c0, 10), (0x1700, 61), (0x1740, 10)):
            claims.append(('menu', first, first + count, 'photo-electronic-shutter-sound'))
        claims += [('dynamic-text', 0x02ff5600, 0x02ff5800, 'photo-electronic-shutter-sound')]
    check_claims(claims)
    return text, icons, claims


def audit_usr(path, plan):
    from a7r5dat.ext2read import Ext2
    recipe = json.loads((FEATURES / 'materials/recipes.json').read_text())
    languages = {LANGUAGE.fullmatch(Path(row['path']).name)[1] for row in recipe['resources']}
    app = Ext2(path)
    files = {}
    try:
        names = {name: inode for inode, name, _ in app.dir_entries(app.walk('/share/app'))}
        language_pairs(names, languages)
        for name, inode in names.items():
            if match := LANGUAGE.fullmatch(name):
                raw = app.read_inode(inode)
                records = text_bank(raw)
                expected, _, claims = requirements(plan, match[1])
                required_text(records, expected)
                files[name] = dict(sha256=hashlib.sha256(raw).hexdigest(), records=len(records), required=len(expected))
        for name in IMAGES:
            require(name in names, '缺少最终图标银行 ' + name)
            raw = app.read_inode(names[name])
            records = image_bank(raw)
            _, expected, _ = requirements(plan, '')
            for key, (width, height, blocks) in expected.items():
                require(key in records, f'缺少图标 {name}:{key:#x}')
                require(records[key] == dict(shape=(height << 16) | width, blocks=blocks), f'图标尺寸或分块不符 {name}:{key:#x}')
            files[name] = dict(sha256=hashlib.sha256(raw).hexdigest(), records=len(records), required=len(expected))
    finally:
        app.mm.close()
        app.f.close()
    return dict(schema='r5-final-resource-audit/1', status='PASS', language_banks=2 * len(languages),
                image_banks=len(IMAGES), files=files, claims=claims, camera_io=False,
                glyph_rendering_verified=False, dynamic_claims='declared-ranges-only')
