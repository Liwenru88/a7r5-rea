"""构建保留 LIRO 布局的 A7R5 JPEG／HEIF 尺寸研究组件。"""

import argparse
import io
import json
from pathlib import Path
import struct
import subprocess

from elftools.elf.elffile import ELFFile

from build_ap import HERE, PatchSet, arm64_b, digest


SOURCE = '640740f3bbd7e20cf49be3288f496415b1d045020c5b9a46ea77fb187699ab04'
WINDOW = 0x1f4dbc


def compile_avcam(work):
    elf = work / 'aspect-avcam.elf'
    subprocess.run(['/opt/homebrew/opt/llvm/bin/clang', '--target=aarch64-none-elf',
        '-nostdlib', '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld',
        '-Wl,--build-id=none', '-Wl,-T,'+str(HERE/'avcam.ld'),
        str(HERE/'avcam_jpeg.S'), str(HERE/'avcam_heif.S'), '-o', str(elf)], check=True)
    return elf.read_bytes()


def apply_avcam(raw, elf):
    if digest(raw) != SOURCE:
        raise ValueError('AVCAM 完整前像不符')
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
    result, proof = patches.finish()
    proof.update(installable=False, encoder_executed=False)
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
