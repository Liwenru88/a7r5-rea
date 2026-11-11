"""构建保留 LIRO 布局的 A7R5 JPEG／HEIF 尺寸研究组件。"""

import argparse
import io
import json
from pathlib import Path
import struct
import subprocess

from elftools.elf.elffile import ELFFile

from build_ap import HERE, PatchSet, arm64_b, digest
from aspect_sizes import generate
from link_helpers import compile_helpers


SOURCE = '640740f3bbd7e20cf49be3288f496415b1d045020c5b9a46ea77fb187699ab04'
WINDOW = 0x1f4dbc


def compile_avcam(work):
    generate(work)
    elf = work / 'aspect-avcam.elf'
    subprocess.run(['/opt/homebrew/opt/llvm/bin/clang', '--target=aarch64-none-elf',
        '-nostdlib', '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld',
        '-Wl,--build-id=none', '-Wl,-T,'+str(HERE/'avcam.ld'),
        '-I', str(work),
        str(HERE/'avcam_jpeg.S'), str(HERE/'avcam_heif.S'), '-o', str(elf)], check=True)
    externals = dict(aspect_native_prepare=0x206378, aspect_native_headers=0x1f52d4,
        aspect_native_header_size=0x1f30c8, aspect_native_makernote_full_size=0x1f377c,
        aspect_native_encode_body=0x200738, aspect_native_request_body=0x1f9978,
        aspect_native_raw_headers=0x1f5388)
    # 新代码之后另存原生 RAM 快照，恢复时不会覆盖新增代码。
    code, symbols, proof = compile_helpers(work / 'views',
        ['avcam_views.c', 'avcam_views.S', 'crop_core.c', 'geometry.c'], 0xc5b380, externals)
    if 0xc5b380 + len(code) > 0xc5c000:
        raise ValueError('AVCAM 辅助代码超出原有 FAT 簇链的已核对余量')
    return elf.read_bytes(), code, symbols, proof


def apply_avcam(raw, elf):
    if digest(raw) != SOURCE:
        raise ValueError('AVCAM 完整前像不符')
    elf, views, view_symbols, view_proof = elf
    module = ELFFile(io.BytesIO(elf))
    code = module.get_section_by_name('.text')
    heif = module.get_section_by_name('.heif')
    symbols = {s.name: s['st_value'] for s in module.get_section_by_name('.symtab').iter_symbols()}
    if (code['sh_addr'], code['sh_size'], symbols['r5_avcam_jpeg_both'],
            symbols['r5_avcam_jpeg_one']) != (WINDOW, 0x128, WINDOW, 0x1f4dfc):
        raise ValueError('AVCAM 单槽／双槽入口或覆盖窗口变化')
    if heif['sh_addr'] != 0xa80 or not 0 < heif['sh_size'] <= 0x180:
        raise ValueError('AVCAM HEIF 辅助代码超出同一代码页空白')
    patches = PatchSet(raw)
    patches.put(WINDOW, raw[WINDOW:WINDOW+0x128], code.data(), 'jpeg-dimension-setter')
    patches.put(0xa80, bytes(heif['sh_size']), heif.data(), 'heif-geometry')
    for at, before in ((0x1f40ec, '1d000094'), (0x1f4110, '14000094')):
        branch = struct.unpack('<I', arm64_b(at, symbols['r5_avcam_jpeg_format']))[0]
        patches.put(at, bytes.fromhex(before), struct.pack('<I', branch | 0x80000000), 'jpeg-format')
    for at, before, name in ((0x2066b4, 'c08240b9', 'r5_avcam_scn'),
                             (0x20684c, '808240b9', 'r5_avcam_thumbnail')):
        patches.put(at, bytes.fromhex(before), arm64_b(at, symbols[name]), name)
    def branch(at, name, link=False):
        instruction = struct.unpack('<I', arm64_b(at, view_symbols[name]))[0]
        patches.put(at, raw[at:at+4], struct.pack('<I', instruction | (0x80000000 if link else 0)), name)
    branch(0x20746c, 'aspect_avcam_heif_prepare', True)
    for at in (0x207048, 0x2071e8, 0x207264):
        branch(at, 'aspect_avcam_raw_preview_prepare', True)
    branch(0x200734, 'aspect_avcam_heif_entry')
    branch(0x1f9970, 'aspect_avcam_heif_request')
    patches.put(0x1f9974, raw[0x1f9974:0x1f9978], bytes.fromhex('1f2003d5'), 'heif-offset-clear')
    code_end = 0xc5b380 + len(views)
    backup_start = (code_end + 127) & ~127
    ram_bytes = 0xc5b378 - 0xba7fc0
    backup_end = backup_start + ram_bytes
    tail_end = (backup_end + 127) & ~127
    if tail_end + 4 > 0x1000000:
        raise ValueError('AVCAM 新代码与快照超出原厂可执行保留区')
    for at, register in ((0x2db28, 9), (0x2db58, 20), (0x2dc30, 0), (0x2dc50, 0), (0x2e22c, 1)):
        immediate = (((backup_start & ~4095) - (at & ~4095)) // 4096) & 0x1fffff
        adrp = 0x90000000 | ((immediate & 3) << 29) | ((immediate >> 2) << 5) | register
        add = 0x91000000 | ((backup_start & 4095) << 10) | (register << 5) | register
        patches.put(at, raw[at:at+8], struct.pack('<II', adrp, add), 'avcam-snapshot-reference')
    base = 0xffffffc001000000
    for at, value in ((0x32d9b0, backup_start), (0x32d9b8, backup_end), (0x1cc, tail_end)):
        patches.put(at, raw[at:at+8], struct.pack('<Q', base + value), 'avcam-snapshot-layout')
    result, proof = patches.finish()
    result += bytes(0xc5b380 - len(result)) + views
    proof.update(target_sha256=digest(result), source_bytes=len(raw), target_bytes=len(result),
        installable=False, encoder_executed=False, symbols=view_symbols, view_link=view_proof,
        snapshot=dict(code_start=0xc5b380, code_end=code_end, ram_start=0xba7fc0,
            ram_end=0xc5b378, backup_start=backup_start, backup_end=backup_end, tail_end=tail_end))
    return result, proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--avcam', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.avcam.read_bytes()
    if digest(raw) != SOURCE:
        parser.error('AVCAM 完整前像不符')
    args.output.mkdir(mode=0o700)
    result, proof = apply_avcam(raw, compile_avcam(args.output))
    (args.output/'AV-CAM.aspect.NONINSTALLABLE.BIN').write_bytes(result)
    (args.output/'build.json').write_text(json.dumps(proof, indent=2)+'\n')
    print(proof['target_sha256'])
