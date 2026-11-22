"""4.29 CP 常驻纵横比补丁：将代码放进 .text 安全区 (0xbef7b0..0xbf0000)，状态放进原生 BSS (0x1a394a0)。
彻底避开会被 A7R5 lateMMU 卸载的 [0, 0x128000) 引导区间，并保持 0x108000..0x128000 早期映射及页表根不变。
"""
import io
from pathlib import Path
import re
import struct
import subprocess
import sys

from elftools.elf.elffile import ELFFile

HERE = Path(__file__).resolve().parent
FEATURES = HERE.parents[1]
ASPECT_SRC = FEATURES / 'photo-aspect-ratios/src'
sys.path.insert(0, str(FEATURES / 'native24-combined/dependencies/native12-combined'))

from patches import BASE, PatchSet, digest, fnv, thumb_b

CODE_VA = 0xbef7b0
CODE_END = 0xbf0000
CODE_CAPACITY = CODE_END - CODE_VA  # 2128 bytes
STATE_VA = 0x1a394a0  # 508 bytes -> 0x1a3969c，位于原生已映射 0x1a39000 BSS 页内
CURVES_DEST_VA = 0x1a39b80  # 1152 bytes -> 0x1a3a000，紧接原有 0x1a3a000 矩阵前

HOOKS = (
    (0x33f322, 'c5f8cc10', 'select_hook'),
    (0xadf128, '16f748e0', 'snapshot_hook'),
    (0xadd846, '7bf555f7', 'capture_copy'),
    (0xaddd5a, '17f730e2', 'clone_copy'),
    (0xae08da, '00f05af8', 'pool_release'),
    (0x4614a4, '00220260', 'pool_reset_hook'),
    (0x473562, '81f12cee', 'jpeg_hook'),
    (0x472a0e, '82f1d6eb', 'jpeg_hook'),
    (0x46e07e, '87f118ec', 'thumbnail_hook'),
    (0xae77d8, 'a4f5fef0', 'primary_hook'),
    (0xae7822, 'a4f5d9f0', 'secondary_hook'),
    (0x48a00a, '54f217f4', 'raw_emb'),
)


def _movw(reg: int, imm16: int) -> bytes:
    """编码 ARMv7 Thumb-2 MOVW Rd, #imm16（小端 4 字节）。"""
    i = (imm16 >> 11) & 1
    imm4 = (imm16 >> 12) & 0xf
    imm3 = (imm16 >> 8) & 0x7
    imm8 = imm16 & 0xff
    hw1 = 0xf240 | (i << 10) | imm4
    hw2 = (imm3 << 12) | (reg << 8) | imm8
    return struct.pack('<HH', hw1, hw2)


def compile_resident_cp(work: Path) -> bytes:
    """编译链接在 0xbef7b0 的常驻 CP 纵横比 ELF。"""
    work.mkdir(parents=True, exist_ok=True)
    hooks_src = (ASPECT_SRC / 'cp_hooks.S').read_text()
    marker = '.thumb\n.text\n'
    if marker not in hooks_src:
        raise ValueError('cp_hooks.S 布局不符')
    hooks_body = '.syntax unified\n.arch armv7-a\n' + hooks_src[hooks_src.index(marker):]
    hooks_body = hooks_body.replace('entry r5_aspect_heif_hook\n    mov r3, r4\n    b r5_cp_heif_copy\n\n', '')
    hooks_body = re.sub(r'^entry (\S+)', r'.section .text.\1,"ax",%progbits\nentry \1', hooks_body, flags=re.M)
    (work / 'cp_hooks_resident.S').write_text(hooks_body)

    ld_path = work / 'cp_resident.ld'
    ld_path.write_text(
        f'''SECTIONS {{
    .aspect {hex(CODE_VA)} : {{ *(.text*) *(.rodata*) }}
    /DISCARD/ : {{ *(.ARM.attributes*) *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) }}
}}
ASSERT(SIZEOF(.aspect) <= {hex(CODE_CAPACITY)}, "resident aspect code exceeds 0xbef7b0..0xbf0000")
'''
    )

    entries = [
        'r5_aspect_select_hook', 'r5_aspect_snapshot_hook', 'r5_cp_capture_copy',
        'r5_cp_clone_copy', 'r5_cp_pool_release', 'r5_aspect_pool_reset_hook',
        'r5_aspect_jpeg_hook', 'r5_aspect_thumbnail_hook',
        'r5_aspect_primary_hook', 'r5_aspect_secondary_hook', 'r5_cp_raw_emb',
    ]
    elf = work / 'aspect-cp-resident.elf'
    cmd = [
        '/opt/homebrew/opt/llvm/bin/clang',
        '--target=armv7a-none-eabi',
        '-mthumb',
        '-mhwdiv=thumb',
        '-Oz',
        '-ffreestanding',
        '-fno-builtin',
        '-fno-stack-protector',
        '-ffunction-sections',
        '-fdata-sections',
        '-Wl,--gc-sections',
        *('-Wl,--undefined=' + s for s in entries),
        '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld',
        '-nostdlib',
        '-Wl,-T,' + str(ld_path),
        '-Wl,--build-id=none',
        str(HERE / 'cp_aspect_compact.c'),
        str(work / 'cp_hooks_resident.S'),
        '-o', str(elf),
    ]
    subprocess.run(cmd, check=True)
    return elf.read_bytes()


def apply_resident_cp(raw: bytes, elf_bytes: bytes, *, source_sha: str) -> tuple[bytes, dict]:
    """在 4.28 CP 上应用常驻纵横比补丁，搬迁 0xbefb80/0xbefdc0 至 0x1a39b80/0x1a39dc0。"""
    if digest(raw) != source_sha:
        raise ValueError('4.29 CP 输入前像不符')

    image = ELFFile(io.BytesIO(elf_bytes))
    sec = image.get_section_by_name('.aspect')
    if sec is None or sec['sh_addr'] != CODE_VA or not (0 < sec['sh_size'] <= CODE_CAPACITY):
        raise ValueError(f'CP 常驻纵横比段越界或地址不符: size={sec["sh_size"] if sec else None}')
    code = sec.data()
    if any(s['sh_flags'] & 2 and s['sh_size'] and s.name != '.aspect' for s in image.iter_sections()):
        raise ValueError('CP 常驻纵横比存在未预期加载段')
    symbols = {s.name: s['st_value'] for s in image.get_section_by_name('.symtab').iter_symbols() if s.name}

    patches = PatchSet(raw)

    # 1. 扩展原生 BSS 清零循环至 0x1a396a0（覆盖 0x1a394a0..0x1a396a0，不触碰 0x1a39b80）
    if raw[0x5e3ee8 - BASE:0x5e3eec - BASE] != bytes.fromhex('683409e3'):
        raise ValueError('CP 原生 BSS 清零指令前像不符')
    patches.put(0x5e3ee8 - BASE, bytes.fromhex('683409e3'), bytes.fromhex('a03609e3'), 'aspect-bss-clear-extend')

    # 2. 搬迁 0xbefb80 (576B) 与 0xbefdc0 (576B) 至 0x1a39b80..0x1a3a000，紧接 0x1a3a000 矩阵之前
    curve_data = raw[0xbefb80 - BASE:0xbf0000 - BASE]
    if len(curve_data) != 1152:
        raise ValueError('曲线长度不符')
    old_payload = raw[0x11d4000 - BASE:0x11d4000 - BASE + 3456]
    new_payload = curve_data + old_payload  # 4608B -> 拷贝至 0x1a39b80..0x1a3ad80
    if any(raw[0x11d2000 - BASE:0x11d2000 - BASE + len(new_payload)]):
        raise ValueError('0x11d2000..0x11d3200 存在非零前像')
    patches.put(0x11d4000 - BASE, old_payload, bytes(3456), 'clear-old-payload-0x11d4000')
    patches.put(0x11d2000 - BASE, bytes(len(new_payload)), new_payload, 'relocate-4608-payload-0x11d2000')

    # 更新 matrix_boot_copy (0x108f8c): 源 0x011d2000, 目标 0x01a39b80, 长度 4608B (1152 words), FNV
    patches.put(0x108f94 - BASE, _movw(6, 3456), _movw(6, 4608), 'matrix-copy-bytes-4608')
    patches.put(0x108fbe - BASE, _movw(2, 864), _movw(2, 1152), 'matrix-copy-words-1152')
    patches.put(0x108fdc - BASE, struct.pack('<I', 0x011d4000), struct.pack('<I', 0x011d2000), 'matrix-copy-src-0x11d2000')
    patches.put(0x108fe0 - BASE, struct.pack('<I', 0x01a3a000), struct.pack('<I', CURVES_DEST_VA), 'matrix-copy-dst-0x1a39b80')
    patches.put(0x108fe4 - BASE, struct.pack('<I', fnv(old_payload)), struct.pack('<I', fnv(new_payload)), 'matrix-copy-fnv')

    # 重定位 Gamma 表中对 0xbefb80 和 0xbefdc0 的引用
    gamma_start, gamma_end = 0x107e968 - BASE, 0x107e968 - BASE + 51 * 28
    for old_va, new_va in ((0xbefb80, CURVES_DEST_VA), (0xbefdc0, CURVES_DEST_VA + 576)):
        needle = struct.pack('<I', old_va)
        refs = [i for i in range(0, len(raw) - 3, 4) if raw[i:i + 4] == needle]
        if not refs or not all(gamma_start <= at < gamma_end for at in refs):
            raise ValueError(f'曲线 {hex(old_va)} 存在未覆盖引用: {refs}')
        for at in refs:
            patches.put(at, needle, struct.pack('<I', new_va), f'relocate-curve-{hex(old_va)}')

    # 3. 将纵横比常驻代码写入 0xbef7b0..0xbf0000
    if any(raw[CODE_VA - BASE:0xbefb80 - BASE]):
        raise ValueError('0xbef7b0..0xbefb80 存在非零前像')
    before_region = raw[CODE_VA - BASE:CODE_VA - BASE + len(code)]
    patches.put(CODE_VA - BASE, before_region, code, 'resident-aspect-code')

    # 4. 挂接 12 处 CP Hook（全部在 .text 常驻段内，不依赖 [0, 0x128000)）
    for at, before, name in HOOKS:
        symbol = ('r5_aspect_' if name.endswith('_hook') else 'r5_cp_') + name
        first, second = struct.unpack('<HH', thumb_b(at, symbols[symbol] & ~1))
        patches.put(at - BASE, bytes.fromhex(before), struct.pack('<HH', first, second | 0x4000), name)

    candidate, proof = patches.finish()
    proof['symbols'] = {k: v for k, v in symbols.items() if k.startswith(('r5_aspect_', 'r5_cp_'))}
    proof['code_va'] = hex(CODE_VA)
    proof['code_bytes'] = len(code)
    proof['code_capacity'] = CODE_CAPACITY
    proof['state_va'] = hex(STATE_VA)
    proof['curves_dest_va'] = hex(CURVES_DEST_VA)
    proof['late_mmu_safe'] = True
    proof['installable'] = False
    return candidate, proof
