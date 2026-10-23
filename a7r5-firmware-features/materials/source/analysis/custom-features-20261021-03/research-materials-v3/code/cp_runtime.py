"""A7R5 六款外观的本机候选布局与 CP 控制器挂钩；不含设备入口。"""
import hashlib
import struct

from assembler import assemble

BASE = 0x108000
SOURCE_SHA = '8e9e26bf2e4b93fa5142e961dcf21cb0f43f8871283814be2dcfb0a694cb5a32'
GAMMA_FILE, GAMMA_BYTES = 0xae74c0, 576
GAMMA_TABLE = 0xf76968
RELOCATED_GAMMA = 0x108d080
TABLE_FILE = RELOCATED_GAMMA + GAMMA_BYTES
PREFIX_VA, TABLE_VA = BASE + TABLE_FILE, BASE + TABLE_FILE + 32
HELPER = BASE + GAMMA_FILE
CHECKER = HELPER + 0x100
MAIN = 0x230da8
PACKER = 0x231654
UPLOADER = 0x414f44
QUERY = 0x415160
MAGIC, VERSION = 0x364c3741, 0x10006


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def fnv(raw):
    value = 2166136261
    for byte in raw:
        value = ((value ^ byte) * 16777619) & 0xffffffff
    return value


def asm(lines, address):
    return assemble(lines, address)


def prefix(tables):
    if len(tables) != 6 or any(len(t) != 1215 for t in tables):
        raise ValueError('必须提供六张原生网格')
    if any(v < -64 or v > 63 for t in tables for v in struct.unpack('1215b', t)):
        raise ValueError('色表系数越界')
    return struct.pack('<8I', MAGIC, VERSION, *(fnv(t) for t in tables)) + b''.join(tables)


def helper_blob():
    legacy, gate = HELPER + 0x4c, HELPER + 0xc8
    code = bytearray(GAMMA_BYTES)
    occupied = set()

    def add(offset, lines, maximum):
        raw = asm(lines, HELPER + offset)
        if len(raw) > maximum or occupied.intersection(range(offset, offset + len(raw))):
            raise ValueError('CP 辅助函数越界或重叠')
        occupied.update(range(offset, offset + len(raw)))
        code[offset:offset + len(raw)] = raw
        return raw

    add(0, ['push {r0,r1,r2,lr}', 'ldrb.w r3,[sl,#1]', 'cmp r3,#1', f'bne 0x{gate:x}',
        'ldrb.w r3,[sl,#0x2e]', 'sub.w r3,r3,#249', 'cmp r3,#5', f'bhi 0x{legacy:x}',
        'ldr.w r3,[sb,#4]', 'ldrb r3,[r3,#6]', 'cmp r3,#1', f'bhi 0x{legacy:x}',
        'ldrb.w r3,[sl,#0x2e]', 'sub.w r3,r3,#249',
        f'movw r2,#{TABLE_VA & 65535}', f'movt r2,#{TABLE_VA >> 16}',
        'movw r0,#1215', 'mla r2,r3,r0,r2', f'bl 0x{CHECKER:x}', 'cmp r3,#0',
        f'beq 0x{legacy:x}', 'ldr lr,[sp,#12]', 'add sp,#16', 'movs r0,#2', 'movs r1,#1',
        'b store', 'legacy:', 'pop {r0,r1,r2,lr}', 'store:', 'cmp r2,#0', 'it eq', 'moveq r1,r2',
        'str.w r2,[r5,#0x184]', 'strb.w r1,[r5,#0x188]', 'strb.w r0,[r5,#0x189]', 'bx lr'], 0x70)
    if code[0x4c:0x50] != asm(['pop {r0,r1,r2,lr}'], legacy):
        raise ValueError('回退栈帧入口发生变化')
    add(0x7e, [f'cbnz r4,0x{HELPER+0xf6:x}', 'ldrh.w r0,[r5,#0x188]',
        'movw r1,#0x201', 'cmp r0,r1', f'bne 0x{HELPER+0xf6:x}', f'b.w 0x{HELPER+0xe8:x}'], 18)
    add(0x90, ['cmp r4,#0', 'bne build', 'ldrb.w r0,[sl,#0x2e]', 'sub.w r0,r0,#249',
        'cmp r0,#5', 'bhi skip', 'ldr.w r0,[sb,#4]', 'ldrb r0,[r0,#6]', 'cmp r0,#1',
        'beq build', 'bhi skip', 'ldr.w r0,[r8,#0xc]', 'ldr.w r0,[r0,#0x6b0]',
        'cmp r0,#0', 'beq skip', 'build:', 'mov r0,sb', 'b.w 0x230f10',
        'skip:', 'b.w 0x230f3e'], 0x38)
    add(0xc8, ['cmp r3,#0', f'bne 0x{legacy:x}', 'ldr.w r3,[sb,#4]', 'ldrb r3,[r3,#6]',
        'cmp r3,#1', 'beq resume', f'bhi 0x{legacy:x}', 'ldr.w r3,[r8,#0xc]',
        'ldr.w r3,[r3,#0x6b0]', 'cmp r3,#0', f'beq 0x{legacy:x}',
        'resume:', f'b.w 0x{HELPER+10:x}'], 0x20)
    add(0xe8, ['ldr.w r0,[r8,#0xc]', 'ldr.w r0,[r0,#0x6b0]', f'cbz r0,0x{HELPER+0xf6:x}',
        'b.w 0x230f94', 'movw r0,#0xfd14', 'b.w 0x230f66'], 22)
    add(0x100, ['push {r0,r1,r2,r4,r5,r6,r7,lr}',
        f'movw r4,#{PREFIX_VA & 65535}', f'movt r4,#{PREFIX_VA >> 16}',
        'ldr r5,[r4]', 'movw r6,#0x3741', 'movt r6,#0x364c', 'cmp r5,r6', 'bne invalid',
        'ldr r5,[r4,#4]', 'movw r6,#6', 'movt r6,#1', 'cmp r5,r6', 'bne invalid',
        'add.w r4,r4,#8', 'ldr.w r4,[r4,r3,lsl #2]', 'movw r5,#40389', 'movt r5,#33052',
        'movw r6,#403', 'movt r6,#256', 'movw r1,#1215', 'loop:', 'ldrb r0,[r2],#1',
        'eors r5,r0', 'muls r5,r6,r5', 'subs r1,#1', 'bne loop', 'cmp r5,r4', 'ite eq',
        'moveq r3,#1', 'movne r3,#0', 'pop {r0,r1,r2,r4,r5,r6,r7,pc}',
        'invalid:', 'movs r3,#0', 'pop {r0,r1,r2,r4,r5,r6,r7,pc}'], 0x60)
    add(0x160, ['ldr.w r0,[r8]', 'ldrb r2,[r0,#1]', 'cmp r2,#0', 'bne legacy',
        'ldrb.w r2,[r0,#0x2e]', 'sub.w r2,r2,#249', 'cmp r2,#5', 'bhi legacy',
        'ldr r0,[sp,#0x38]', 'ldr r0,[r0,#8]', 'ldrb.w r2,[r0,#0x188]', 'cmp r2,#1',
        'bne legacy', 'ldrb.w r2,[r0,#0x189]', 'cmp r2,#2', 'bne legacy',
        'movs r1,#4', 'mov.w lr,#4', 'b.w 0x2312f4', 'legacy:', 'movs r5,#0',
        'b.w 0x2315c0'], 0x40)
    # R5 的 Gamma 控制器直接读入 color，不存在 A7C II 的路由 helper。
    # 只将输出参数副本中的六个自定义标记归为 ST；源参数及 FL2/FL3 不变。
    add(0x1a0, ['ldr r3,[r5,#0x10]!', 'subw ip,r3,#249', 'cmp ip,#5',
        'it ls', 'movls r3,#0', 'str r3,[r4,#0xc]', 'b.w 0xaa8214'], 0x20)
    # 第二条原生局部更新路径是叶函数；保留 LR，以尾跳返回。
    add(0x1c0, ['ldr r0,[r0,#4]', 'subw ip,r0,#249', 'cmp ip,#5',
        'it ls', 'movls r0,#0', 'movw r2,#0xeefc', 'movt r2,#0x107',
        'b.w 0xaa86b0'], 0x30)
    return bytes(code)


def build(original, tables):
    if len(original) != 17617008 or sha(original) != SOURCE_SHA:
        raise ValueError('CP 完整前像不符')
    data = bytearray(original)
    rows = []

    def put(at, raw, purpose):
        if at < 0 or at + len(raw) > len(data):
            raise ValueError('修改超出文件')
        if any(not (at + len(raw) <= x['offset'] or x['offset'] + x['bytes'] <= at) for x in rows):
            raise ValueError('修改区间重叠')
        rows.append({'offset': at, 'bytes': len(raw), 'before': original[at:at+len(raw)].hex(),
                     'after': bytes(raw).hex(), 'purpose': purpose})
        data[at:at+len(raw)] = raw

    # 原 data 之后、BSS 之前只有 0x1f90 空隙；恰好容纳一条曲线和六张 LUT。
    if struct.unpack_from('<3I', original, 0x2013c) != (0xf57000, 0x116070, 0x107f000):
        raise ValueError('data 描述符不符')
    bss_file = 0x20000 + struct.unpack_from('<I', original, 0x20148)[0]
    bss_va = struct.unpack_from('<I', original, 0x20150)[0]
    payload = original[GAMMA_FILE:GAMMA_FILE+GAMMA_BYTES] + prefix(tables)
    end = (RELOCATED_GAMMA + len(payload) + 3) & ~3
    if end > bss_file or BASE + end > bss_va or any(original[0x108d070:bss_file]):
        raise ValueError('data/BSS 空隙不足、占用或映射越界')
    put(RELOCATED_GAMMA, payload + bytes(end-RELOCATED_GAMMA-len(payload)), '曲线原样迁移及六张 FNV 网格')
    put(0x20140, struct.pack('<I', end - 0xf77000), '仅扩展 data 文件长度，BSS 起点不变')
    old_pointer, new_pointer = BASE + GAMMA_FILE, BASE + RELOCATED_GAMMA
    expected = [GAMMA_TABLE + 47*28 + slot*4 for slot in range(6)]
    actual, start = [], 0
    while True:
        at = original.find(struct.pack('<I', old_pointer), start)
        if at < 0:
            break
        actual.append(at)
        start = at + 1
    if actual != expected:
        raise ValueError('被迁移 Gamma 曲线的全部指针引用不符')
    for at in actual:
        put(at, struct.pack('<I', new_pointer), '更新 FL2 still 0–5 曲线指针')
    put(GAMMA_FILE, helper_blob(), '复用已迁移曲线腾出的 RX 空间')
    # 前像在首次离线勘查中与 A7C II 窗口相同；这里再次按本机字节校验边界。
    at = 0x128ee0
    source = original[at:at+48]
    if source[:18] != bytes.fromhex('002ac5f8842108bf114685f8881185f88901'):
        raise ValueError('LUT 原生存储窗口前像不符')
    target = bytearray(source)
    target[:18] = asm([f'bl 0x{HELPER:x}'] + ['nop']*7, BASE+at)
    target[26:28] = asm([f'cbz r4,0x{BASE+at+44:x}'], BASE+at+26)
    target[42:44] = asm([f'b 0x{BASE+at+44:x}'], BASE+at+42)
    target[44:48] = asm([f'b.w 0x{HELPER+0x90:x}'], BASE+at+44)
    put(at, target, 'CP marker/type/transform 选择及安全回退')
    for off, old, new, purpose in [
        (0x128f62, ['movw r0,#0xfd14'], [f'b.w 0x{HELPER+0x7e:x}'], '有效缓存丢失提交后的再次上传'),
        (0x1292f0, ['movs r5,#0', 'b 0x2315c0'], [f'b.w 0x{HELPER+0x160:x}'], '消费者切换桥')]:
        if original[off:off+4] != asm(old, BASE+off):
            raise ValueError('原生入口前像不符：' + purpose)
        put(off, asm(new, BASE+off), purpose)
    for off, old, new, purpose in [
        (0x9a020e, ['ldr r3,[r5,#0x10]!', 'str r3,[r4,#0xc]'],
            [f'b.w 0x{HELPER+0x1a0:x}', 'nop'], 'Gamma 完整更新仅在输出副本归一化自定义标记'),
        (0x9a0320, ['ldr r0,[r5]'], ['ldr r0,[r4,#0xc]'], 'Gamma 第二消费者读取已归一化副本'),
        (0x9a032e, ['ldr r0,[r5]'], ['ldr r0,[r4,#0xc]'], 'Gamma 第三消费者读取已归一化副本'),
        (0x9a06a6, ['movw r2,#0xeefc', 'ldr r0,[r0,#4]', 'movt r2,#0x107'],
            [f'b.w 0x{HELPER+0x1c0:x}', 'nop','nop','nop'], 'Gamma 局部更新的自定义标记归一化')]:
        old_raw, new_raw = asm(old, BASE+off), asm(new, BASE+off)
        if len(old_raw) != len(new_raw) or original[off:off+len(old_raw)] != old_raw:
            raise ValueError('Gamma 控制器前像或长度不符：' + purpose)
        put(off, new_raw, purpose)
    inverse = bytearray(data)
    for row in rows:
        inverse[row['offset']:row['offset']+row['bytes']] = bytes.fromhex(row['before'])
    if inverse != original:
        raise ValueError('CP 反向重建失败')
    return bytes(data), {'source_sha256': sha(original), 'target_sha256': sha(data),
        'bytes': len(data), 'patches': rows, 'inverse_exact': True,
        'gamma_moved_bytes': GAMMA_BYTES, 'gamma_reference_count': len(actual),
        'gamma_source': GAMMA_FILE, 'gamma_target': RELOCATED_GAMMA,
        'table_file': TABLE_FILE, 'table_va': TABLE_VA,
        'data_end_file': end, 'data_end_va': BASE+end,
        'bss_file': bss_file, 'bss_va': bss_va,
        'bss_descriptor_unchanged': original[0x20148:0x2016c] == data[0x20148:0x2016c],
        'file_size_unchanged': len(data) == len(original), 'no_boot_prefix_reuse': True,
        'gamma_parameter_normalization_complete': True,
        'photo_metadata_or_exif_verified': False,
        'physical_hardware_verified': False}
