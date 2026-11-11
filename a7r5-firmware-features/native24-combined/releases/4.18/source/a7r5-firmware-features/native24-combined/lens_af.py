"""A7R5 自动兼容模式的五处能力过滤适配。"""

import io
from pathlib import Path
import struct
import subprocess

from elftools.elf.elffile import ELFFile


SOURCE_SHA256 = '35eb911d27be4a8aab8a0a5fe9a8f028c16453d5ab79605fe36dbd199b833300'
HELPER = 0xbef780
HELPER_LIMIT = 0xbef7c0
CALLS = (
    (0x3f4db0, '76f297f7', 'info7'),
    (0x3f3fec, '77f279f6', 'info8'),
    (0x3f47b6, '77f294f2', 'info3D'),
    (0xa64db4, '06f095ff', 'capability-publication-first'),
    (0xa64f48, '06f0cbfe', 'capability-publication-second'),
)


def apply_lens_af(raw, patches, work):
    if patches.digest(raw) != SOURCE_SHA256:
        raise ValueError('AF 补丁要求已核对的 A7R5 整合 CP 前像')
    source = Path(__file__).with_suffix('.S')
    obj = work / 'lens-af.o'
    subprocess.run(['/opt/homebrew/opt/llvm/bin/clang', '--target=armv7a-none-eabi',
                    '-mthumb', '-c', str(source), '-o', str(obj)], check=True, capture_output=True)
    elf = ELFFile(io.BytesIO(obj.read_bytes()))
    code = elf.get_section_by_name('.text').data()
    if not code or HELPER + len(code) > HELPER_LIMIT or elf.get_section_by_name('.rel.text'):
        raise ValueError('AF helper 超出已核对空间或包含待解析重定位')
    result = patches.PatchSet(raw)
    result.put(HELPER - patches.BASE, bytes(len(code)), code, 'lens-af-auto-compat-getter')
    for address, before, consumer in CALLS:
        first, second = struct.unpack('<HH', patches.thumb_b(address, HELPER))
        call = struct.pack('<HH', first, second | 0x4000)
        result.put(address - patches.BASE, bytes.fromhex(before), call, consumer)
    return result.finish()
