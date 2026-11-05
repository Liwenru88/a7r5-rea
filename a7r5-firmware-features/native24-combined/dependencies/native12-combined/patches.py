"""固定4.36前像上的局部整合；未知、重叠、越界均拒绝。"""
import hashlib
import io
import json
from pathlib import Path
import struct
import subprocess
import tempfile

from elftools.elf.elffile import ELFFile

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[3]
AP_SHA = 'bc766baaf1cd617479993afbec526bbc4dd5f6fc62a0f79bf2682abbd1adc222'
CP_SHA = '8523298baa613ff93b6c9ae4f5e801fc81fd117680a81f4ea7ba6e1262350cb6'
BASE = 0x108000
PINS = {
    'a7r5-firmware-features/aspect-guide406/patch-plan.json': 'c063df73ed7370091e05b13438401b117d29357b383afbf91e952d333783fb30',
    'a7r5-firmware-features/materials/matrix-inline.json': 'a0f4896af67cf16c5fa42070b58a96a2777929901ee4805e88c32d2103c50c9e',
    'a7r5-firmware-features/materials/recipes.json': 'f29fcdf0e005cf87cc821a45014ee295310cced806fd92123d68af38ec2c6fac',
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def material(name):
    path = ROOT/name
    raw = path.read_bytes()
    require(digest(raw) == PINS[name], '本地材料发生变化：'+name)
    return json.loads(raw)


class PatchSet:
    def __init__(self, raw):
        self.raw, self.target, self.rows = raw, bytearray(raw), []

    def put(self, offset, before, after, feature):
        require(type(offset) is int and len(before) == len(after) and
                0 <= offset < offset+len(before) <= len(self.raw), '补丁越界或非等长')
        require(self.raw[offset:offset+len(before)] == before, '局部前像不符：'+feature)
        require(all(offset+len(before) <= r['offset'] or
                    r['offset']+len(bytes.fromhex(r['before'])) <= offset for r in self.rows), '补丁重叠')
        require(before != after, '补丁无变化')
        self.target[offset:offset+len(after)] = after
        self.rows.append(dict(offset=offset, before=before.hex(), after=after.hex(), feature=feature))

    def finish(self):
        reverse = bytearray(self.target)
        for row in self.rows:
            at, before = row['offset'], bytes.fromhex(row['before'])
            reverse[at:at+len(before)] = before
        require(reverse == self.raw, '不能精确逆还原')
        return bytes(self.target), dict(source_sha256=digest(self.raw), target_sha256=digest(self.target),
            patches=self.rows, inverse_exact=True, camera_io=False, device_tested=False)


def arm64_b(at, target):
    delta = target-at
    require(delta % 4 == 0 and -(1 << 27) <= delta < (1 << 27), 'AArch64分支越界')
    return struct.pack('<I', 0x14000000 | ((delta//4) & 0x3ffffff))


def thumb_b(at, target):
    delta = target-at-4
    require(delta % 2 == 0 and -(1 << 24) <= delta < (1 << 24), 'Thumb分支越界')
    value = delta & ((1 << 25)-1)
    s, a, b = (value >> 24) & 1, (value >> 23) & 1, (value >> 22) & 1
    return struct.pack('<HH', 0xf000 | s << 10 | ((value >> 12) & 0x3ff),
        0x9000 | (1 ^ a ^ s) << 13 | (1 ^ b ^ s) << 11 | ((value >> 1) & 0x7ff))


def matrix_bytes():
    plan = material('a7r5-firmware-features/materials/matrix-inline.json')
    rows = [r for r in plan['patches'] if r['offset'] == 17612800]
    require(len(rows) == 1, '矩阵材料身份不符')
    table = bytes.fromhex(rows[0]['after'])
    checksum = 2166136261
    for value in table:
        checksum = ((checksum ^ value)*16777619) & 0xffffffff
    require(len(table) == 2304 and checksum == 0xc08d9b7e, '矩阵长度／FNV不符')
    return table


def selection_code():
    with tempfile.TemporaryDirectory(prefix='native12-selection-') as temporary:
        output = Path(temporary)/'selection.elf'
        command = ['/opt/homebrew/opt/llvm/bin/clang', '--target=aarch64-none-elf', '-nostdlib',
            '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld', '-Wl,-Ttext=0x3550354',
            '-Wl,--entry=combined_selection', '-Wl,--defsym=invalid_base=0x35503d8',
            '-Wl,--build-id=none', str(HERE/'selection.S'), '-o', str(output)]
        subprocess.run(command, check=True, capture_output=True)
        elf = ELFFile(io.BytesIO(output.read_bytes()))
        section = elf.get_section_by_name('.text')
        code = section.data()
        require(section['sh_addr'] == 0x3550354 and len(code) <= 132 and len(code)%4 == 0,
                'AP选择函数超过原窗口')
        return code+bytes.fromhex('1f2003d5')*((132-len(code))//4)


def ap_patch(raw):
    require(digest(raw) == AP_SHA, 'AP完整前像不符')
    patches = PatchSet(raw)
    patches.put(0x3550354, raw[0x3550354:0x35503d8], selection_code(), 'FL23-independent-selector')
    for group in range(3):
        for slot, value in ((16, 10), (17, 11)):
            at = 0x4a422f8+(group*18+slot)*8
            key, before = struct.unpack_from('<II', raw, at)
            require(key == 0x163a+group*18+slot and before == 0, 'FL23默认字段前像不符')
            patches.put(at+4, struct.pack('<I', before), struct.pack('<I', value), 'FL23-reset-default')
    recipe = material('a7r5-firmware-features/materials/recipes.json')
    for row in recipe['ntsc_only']['patches']:
        patches.put(row['offset'], bytes.fromhex(row['before']), bytes.fromhex(row['after']), 'NTSC')
    plan = material('a7r5-firmware-features/aspect-guide406/patch-plan.json')
    image = ELFFile(io.BytesIO(raw))
    segments = list(image.iter_segments())
    rx = segments[0]
    original_end, start, end = 0x500fbb7, 0x500fc10, 0x500fc70
    require((rx['p_type'], rx['p_flags'], rx['p_offset'], rx['p_vaddr'], rx['p_filesz'], rx['p_memsz']) ==
            ('PT_LOAD', 5, 0, 0, original_end, original_end), 'AP原代码段布局不符')
    require(original_end//4096 == (end-1)//4096 and raw[original_end:end] == bytes(end-original_end),
            '标记代码空间不符')
    for segment in segments[1:]:
        if segment['p_type'] == 'PT_LOAD':
            require(segment['p_offset'] >= end and segment['p_vaddr'] >= end, '标记与映射段冲突')
    for section in image.iter_sections():
        if section['sh_size'] and section['sh_type'] != 'SHT_NOBITS':
            require(max(start, section['sh_offset']) >= min(end, section['sh_offset']+section['sh_size']),
                    '标记与既有section冲突')
        if section['sh_type'] == 'SHT_RELA':
            for offset, _, addend in struct.iter_unpack('<QQq', section.data()):
                require(not start <= offset < end and not start <= addend < end, '标记空间已有重定位')
    require(len(plan['registrations']) == 3 and len(plan['support_writes']) == 28, '标记清单数量不符')
    block = bytearray(end-start)
    for n, row in enumerate(plan['registrations']):
        entry = start+32*n
        code = struct.pack('<I', 0x10000041)+arm64_b(entry+4, 0x29051dc)
        payload = code+struct.pack('<iii', *row['range'])
        block[n*32:n*32+len(payload)] = payload
        at = row['existing_validator_relocation']['entry_file_offset']
        require(struct.unpack_from('<QQq', raw, at) == (int(row['VA'], 16), 1027, 0x2905250),
                '标记RELA前像不符')
        patches.put(row['file_offset'], struct.pack('<Q', 0x2905250), struct.pack('<Q', entry), 'marker-registration')
        patches.put(at+16, struct.pack('<q', 0x2905250), struct.pack('<q', entry), 'marker-RELA')
    patches.put(start, bytes(end-start), bytes(block), 'marker-range-wrappers')
    for row in plan['support_writes']:
        patches.put(row['file_offset'], bytes.fromhex(row['before_hex']), bytes.fromhex(row['after_hex']), 'marker-support')
    # 远端把PHDR移入新增RX段，必须更新活动PHDR，不能沿用旧0x60/0x68地址。
    for field in (32, 40):
        patches.put(image['e_phoff']+field, struct.pack('<Q', original_end), struct.pack('<Q', end), 'active-PHDR-marker-extent')
    target, report = patches.finish()
    report.update(marker_support_writes=28, marker_registrations=3, active_phoff=image['e_phoff'],
                  photo_overlay_verified=False, upstream_image_resources_unchanged=True)
    return target, report


def fnv(raw):
    value = 2166136261
    for byte in raw:
        value = ((value ^ byte)*16777619) & 0xffffffff
    return value


def cp_payload(raw):
    return matrix_bytes()+b''.join(raw[a-BASE:a-BASE+576] for a in (0xbef700, 0xbef940))


def compile_integration(folder, payload):
    output = folder/'integration.elf'
    command = ['/opt/homebrew/opt/llvm/bin/clang', '--target=armv7a-none-eabi', '-mthumb', '-nostdlib',
        '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld', '-Wl,-T,'+str(HERE/'integration.ld'),
        '-Wl,--build-id=none', '-DPAYLOAD_FNV='+hex(fnv(payload)), str(HERE/'integration.S'), '-o', str(output)]
    subprocess.run(command, check=True, capture_output=True)
    elf = ELFFile(io.BytesIO(output.read_bytes()))
    sections = [(s['sh_addr'], s.data()) for s in elf.iter_sections() if s['sh_flags'] & 2 and s['sh_size']]
    require({address for address, _ in sections} == {0x108f20, 0x108f8c, 0xbef700, 0xbef720}, '编译段集合不符')
    symbols = {s.name: s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name}
    return sections, dict(command=command, symbols=symbols, source_sha256=digest((HERE/'integration.S').read_bytes()),
        linker_sha256=digest((HERE/'integration.ld').read_bytes()), sections=[dict(VA=a, bytes=len(b), sha256=digest(b)) for a,b in sections])


def cp_patch(raw, folder):
    require(digest(raw) == CP_SHA, 'CP完整前像不符')
    patches = PatchSet(raw)
    payload = cp_payload(raw)
    require(len(payload) == 3456, '矩阵与搬迁曲线长度不符')
    sections, compiled = compile_integration(folder, payload)
    retired = bytearray(1152)
    for address, code in sections:
        if address < 0x109000:
            patches.put(address-BASE, bytes(len(code)), code, 'combined-native-code')
        else:
            retired[address-0xbef700:address-0xbef700+len(code)] = code
    patches.put(0xbef700-BASE, raw[0xbef700-BASE:0xbefb80-BASE], bytes(retired), 'relocated-curves-native-code')
    relocations = []
    gamma_start, gamma_end = 0x107e968-BASE, 0x107e968-BASE+51*28
    for old, new in ((0xbef700, 0x1a3a900), (0xbef940, 0x1a3ab40)):
        needle = struct.pack('<I', old)
        references = [i for i in range(0, len(raw)-3, 4) if raw[i:i+4] == needle]
        require(references and all(gamma_start <= at < gamma_end for at in references),
                '曲线存在未覆盖的对齐引用')
        for at in references:
            patches.put(at, needle, struct.pack('<I', new), 'native-Gamma-record-relocation')
        relocations.append(dict(before=old, after=new, pointer_offsets=references,
                                record_sha256=digest(raw[old-BASE:old-BASE+576])))
    # BLX立即数使用ARM的PC+8与H位；目标是Thumb复制器。
    at, target = 0x108524, 0x108f8c
    delta = target-at-8
    call = struct.pack('<I', 0xfa000000 | ((delta & 2) << 23) | ((delta >> 2) & 0xffffff))
    patches.put(at-BASE, bytes.fromhex('480194e5'), call, 'matrix-early-copy-call')
    patches.put(0x11d4000-BASE, bytes(len(payload)), payload, 'embedded-FL23-matrices-and-native-curves')
    data = struct.unpack_from('<3I', raw, 0x2013c)
    bss = struct.unpack_from('<3I', raw, 0x20148)
    stack = struct.unpack_from('<3I', raw, 0x20154)
    require(data == (0xf57000, 0x118000, 0x107f000) and
            bss == (0x106f000, 0x8a2468, 0x1197000) and stack == (0, 0x4000, 0x1a3c000), 'CP布局前像不符')
    new_size = 0x1a3a000+len(payload)-bss[2]
    translation = data[2]-data[0]
    old_root = ((bss[0]+bss[1]+0x4fff) & ~0x3fff)+translation
    new_root = ((bss[0]+new_size+0x4fff) & ~0x3fff)+translation
    require(old_root == new_root and 0x1a3a000+len(payload) <= stack[2], '矩阵将移动页表或碰到栈')
    patches.put(0x2014c, struct.pack('<I', bss[1]), struct.pack('<I', new_size), 'matrix-BSS-map-extent')
    patches.put(0x71e43e-BASE, thumb_b(0x71e43e, 0xbef3b4), thumb_b(0x71e43e, 0xbef720), 'FL23-matrix-source')
    patches.put(0x47f622-BASE, bytes.fromhex('03210028'), thumb_b(0x47f622, 0xbef700), 'type1-sound-selector')
    require(raw[0x377601] == 0x0f, '禁止旧type1声音分派补丁')
    target, report = patches.finish()
    report.update(compiled=compiled, matrix_va=0x1a3a000, matrix_bytes=2304,
        payload_bytes=len(payload), payload_sha256=digest(payload), payload_fnv=fnv(payload),
        curve_relocations=relocations,
        original_mapper_preserved=target[0xf40:0xf8c] == raw[0xf40:0xf8c],
        page_table_root=old_root, page_table_root_unchanged=True, stack_unchanged=True,
        BSS_global_addresses_unchanged=True, upstream_custom_bank_unchanged=True,
        sound_playback_verified=False, full_CP_boot_verified=False)
    return target, report
