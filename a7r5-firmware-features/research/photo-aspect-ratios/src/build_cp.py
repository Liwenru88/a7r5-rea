"""构建并审计 A7R5 纵横比 CP 研究组件。输出用于离线回放。"""

import argparse
import io
import json
from pathlib import Path
import struct
import subprocess
import sys

from elftools.elf.elffile import ELFFile


HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / 'firmware-runtime/dependencies/native12-combined'))
from patches import BASE, PatchSet, digest, thumb_b


SOURCES = {
    '35eb911d27be4a8aab8a0a5fe9a8f028c16453d5ab79605fe36dbd199b833300',
    '530b45341bd17649d561bb5f906a23c505724d78e408ec2edc7dbf465eade3d5',
}
STOCK = '3269bf62426339791fcfbe8529698cd4accbe6c3d2ea61cd7c368a90ab7ee7c8'
BOOT_MAPPERS = {'stock': (0x108768, '240000eb'), 'native24': (0x108f40, '1a0200eb'),
                'color': (0x109000, '4a0200eb'), 'custom-sound': (0x109100, '8a0200eb')}
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


def compile_cp(work, *, stock=False, shared_color=False, custom_sound=False):
    elf = work / 'aspect-cp.elf'
    mapper, _ = BOOT_MAPPERS['stock' if stock else 'custom-sound' if custom_sound else 'color' if shared_color else 'native24']
    args = ['/opt/homebrew/opt/llvm/bin/clang', '--target=armv7a-none-eabi', '-mthumb',
            '-mhwdiv=thumb', '-Oz', '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
            '-nostdlib', '-Wall', '-Wextra', '-Werror', '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld',
            '-Wl,-T,'+str(HERE/'cp.ld'), '-Wl,--build-id=none',
            '-Wl,--defsym=old_mapper='+hex(mapper),
            *(str(HERE/name) for name in ('cp.c', 'cp_hooks.S', 'geometry.c', 'requests.c')),
            '-o', str(elf)]
    subprocess.run(args, check=True)
    return elf.read_bytes()


def apply_cp(raw, elf, *, source_sha=None, shared_color=False, custom_sound=False):
    pin = digest(raw)
    if pin not in (*SOURCES, STOCK, source_sha):
        raise ValueError('CP 完整前像不符')
    image = ELFFile(io.BytesIO(elf))
    sections = [(s['sh_addr'], s.data()) for s in image.iter_sections()
                if s['sh_flags'] & 2 and s['sh_size']]
    if {at for at, _ in sections} != {0x118000, 0xbef7c0}:
        raise ValueError('CP 比例模块段地址不符')
    if any(not code or len(code) > (0x1000 if at == 0x118000 else 0x3c0)
           for at, code in sections):
        raise ValueError('CP 比例模块段越界')
    symbols = {s.name: s['st_value'] for s in image.get_section_by_name('.symtab').iter_symbols()
               if s.name}

    patches = PatchSet(raw)
    for at, code in sections:
        patches.put(at-BASE, bytes(len(code)), code, 'aspect-code')
    # 保持现有矩阵区、页表根位置和栈地址，使用同一页中矩阵末尾的空白。
    bss = struct.unpack_from('<3I', raw, 0x20148)
    data = struct.unpack_from('<3I', raw, 0x2013c)
    stack = struct.unpack_from('<3I', raw, 0x20154)
    end = 0x1a3af80
    size = max(bss[1], end-bss[2])
    expected_data = (0xf57000, 0x116070 if pin == STOCK else 0x118000, 0x107f000)
    expected_bss = (0x8a4000 if custom_sound else 0x8a2448 if pin == STOCK else
                    0x8a3d80 if pin in SOURCES or shared_color else 0x8a2468)
    if (data, bss, stack) != (expected_data, (0x106f000, expected_bss, 0x1197000),
                              (0, 0x4000, 0x1a3c000)):
        raise ValueError('CP 数据／BSS／栈前像不符')
    old_root = (bss[0]+bss[1]+0x4fff) & ~0x3fff
    new_root = (bss[0]+size+0x4fff) & ~0x3fff
    if new_root != old_root or end >= stack[2]:
        raise ValueError('CP 比例状态影响原页表或栈')
    if size != bss[1]:
        patches.put(0x2014c, struct.pack('<I', bss[1]), struct.pack('<I', size), 'aspect-state')
    boot_call = 0x1086d0
    delta = symbols['r5_aspect_boot']-boot_call-8
    if delta & 3 or not -(1 << 25) <= delta < (1 << 25):
        raise ValueError('ARM 启动分支越界')
    mapper, original = BOOT_MAPPERS['stock' if pin == STOCK else 'custom-sound' if custom_sound else 'color' if shared_color else 'native24']
    if symbols['old_mapper'] != mapper:
        raise ValueError('CP 比例启动入口链接到错误的原生 mapper')
    patches.put(boot_call-BASE, bytes.fromhex(original),
                struct.pack('<I', 0xeb000000 | ((delta // 4) & 0xffffff)), 'aspect-boot')
    for at, before, name in HOOKS:
        symbol = ('r5_aspect_' if name.endswith('_hook') else 'r5_cp_')+name
        first, second = struct.unpack('<HH', thumb_b(at, symbols[symbol] & ~1))
        patches.put(at-BASE, bytes.fromhex(before),
                    struct.pack('<HH', first, second | 0x4000), name)
    candidate, proof = patches.finish()
    proof['symbols'] = {k: v for k, v in symbols.items() if k.startswith(('r5_aspect_', 'r5_cp_'))}
    proof['sections'] = [{'address': at, 'bytes': len(code), 'sha256': digest(code)}
                         for at, code in sections]
    proof['previous_mapper'] = mapper
    proof['installable'] = False
    return candidate, proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cp', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.cp.read_bytes()
    pin = digest(raw)
    if pin not in (*SOURCES, STOCK):
        parser.error('CP 完整前像不符')
    args.output.mkdir(mode=0o700)
    candidate, proof = apply_cp(raw, compile_cp(args.output, stock=pin == STOCK))
    (args.output/'cpapp-b.aspect.NONINSTALLABLE.bin').write_bytes(candidate)
    (args.output/'build.json').write_text(json.dumps(proof, indent=2)+'\n')
    print(proof['target_sha256'])
