"""构建原厂纵横比菜单及 0x402d 序列化的离线研究组件。"""

import argparse
import io
import json
from pathlib import Path
import struct
import subprocess

from elftools.elf.elffile import ELFFile

from build_cp import HERE, PatchSet, digest
from patches import arm64_b


SOURCE = '7ab2120c14cf1635b920c6583c65e1406f6f3f5a831e570509bdf39c2968ea5d'
AP_LAYOUTS = {
    SOURCE: (0x4239, 0x2b60, 0x8e98ab4, 0x8f010fc, 0x8f01120),
    'eaf0b742745696f651dbe5ee75a813bb168ac41db81706743712ab8f6d0491bf':
        (0x3aba, 0x2b50, 0x8e989a4, 0x8f0107c, 0x8f010a0),
}
RX = 0x8f04400
SELECTION = 0x8f12b60
STOCK_ROWS = 0x3f46600
DESCRIPTOR = 0x586b990
LABELS = ('17:6', '65:24', '5:4', '7:6', '1.91:1', '2.35:1')
FIRST_ROW = 0x1600
FIRST_LABEL = 0x0200ab60
FIRST_ICON = 0x02001e90
FIRST_SMALL_ICON = FIRST_ICON-len(LABELS)
HOOKS = (
    (0x3565f78, '810a40b9', 'ap_prepare', True),
    (0x3566a44, '7ac7ff97', 'ap_send', True),
    (0x16f6610, None, 'register', True),
    (0x16f671c, '32701694', 'parent_register', True),
    (0x16fbf84, 'c65e1694', 'alias_register', True),
    (0x1bd5414, 'fd7bbea9', 'available', False),
    (0x1bc36f8, 'ffc320d1', 'list', False),
    (0x1bcfd18, '00f80151', 'size_class', False),
    (0x1bc7720, 'fd7bbea9', 'apply', False),
    (0x21e1cd4, 'cfdde797', 'list_commit', True),
    (0x1bd18e8, None, 'icon', False),
    (0x1bd19e8, None, 'icon_alt', False),
    (0x1d9ba18, '00013fd6', 'guide_create_call', True),
    (0x1e179e0, '00013fd6', 'guide_create_call', True),
    (0x1d1574c, '00013fd6', 'guide_create_call', True),
    (0x1d15664, '00013fd6', 'guide_create_call', True),
    (0x1d9bb74, 'dbc71994', 'guide_produce', True),
    (0x1e17b1c, 'f1d71794', 'guide_produce', True),
    (0x240de2c, '20e7ff35', 'guide_visibility_gate', False),
    (0x2146224, '003c4191', 'guide_cap_a', False),
    (0x2156e70, '001c4191', 'guide_cap_b', False),
    (0x182e138, 'fd7bbea9', 'guide_draw', False),
    (0x182e1ac, 'fd7bbea9', 'guide_destroy', False),
)


def rows(raw):
    stock = raw[STOCK_ROWS:STOCK_ROWS+4*128]
    result = bytearray(stock)
    for i, _ in enumerate(LABELS):
        row = bytearray(stock[:128])
        struct.pack_into('<IIII', row, 0, FIRST_ROW+i, FIRST_ROW+i, FIRST_LABEL+i, FIRST_SMALL_ICON+i)
        struct.pack_into('<II', row, 0x20, FIRST_ICON+2*i, FIRST_ICON+2*i+1)
        struct.pack_into('<I', row, 0x34, 4+i)
        # 3:2 的专用拦截回调会提前结束确认，新增项走父菜单的 +0x88。
        struct.pack_into('<H', row, 0x74, 0x1086)
        result.extend(row)
    return result


def compile_ap(work, raw):
    _, _, previous_register, previous_icon, previous_icon_alt = AP_LAYOUTS[digest(raw)]
    elf = work / 'aspect-ap.elf'
    row_file = work / 'aspect-ap-rows.bin'
    row_file.write_bytes(rows(raw))
    assembly = work / 'aspect-ap-rows.S'
    assembly.write_text('.section .rodata.rows,"a"\n.balign 8\n'
                        '.global r5_aspect_rows\nr5_aspect_rows:\n'
                        f'.incbin {json.dumps(str(row_file.resolve()))}\n')
    subprocess.run(['/opt/homebrew/opt/llvm/bin/clang', '--target=aarch64-none-elf', '-Oz',
        '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-mno-outline-atomics',
        '-Wall', '-Wextra', '-Werror',
        '-nostdlib', '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld', '-Wl,--build-id=none',
        '-Wl,-T,'+str(HERE/'ap.ld'), '-Wl,--defsym=prior_register='+hex(previous_register),
        '-Wl,--defsym=prior_icon='+hex(previous_icon), '-Wl,--defsym=prior_icon_alt='+hex(previous_icon_alt),
        *(str(HERE/name) for name in ('ap_transport.S', 'ap_menu.S', 'ap_menu.c',
                                      'ap_guide.S', 'ap_guide.c', 'geometry.c')),
        str(assembly), '-o', str(elf)], check=True)
    return elf.read_bytes()


def apply_ap(raw, elf):
    if digest(raw) not in AP_LAYOUTS:
        raise ValueError('AP 完整前像不符')
    old_rx, old_bss, previous_register, previous_icon, previous_icon_alt = AP_LAYOUTS[digest(raw)]
    prior_hooks = {'register': previous_register, 'icon': previous_icon, 'icon_alt': previous_icon_alt}
    source = ELFFile(io.BytesIO(raw))
    segments = list(source.iter_segments())
    rx, rw = segments[8:10]
    if (rx['p_vaddr'], rx['p_filesz'], rx['p_memsz'], rx['p_flags'],
        rw['p_vaddr'], rw['p_filesz'], rw['p_memsz'], rw['p_flags']) != (
            0x8f00000, old_rx, old_rx, 5, 0x8f10000, 0, old_bss, 6):
        raise ValueError('AP 统一入口段布局不符')
    module = ELFFile(io.BytesIO(elf))
    code = module.get_section_by_name('.text')
    if code['sh_addr'] != RX or not 0 < code['sh_size'] <= 0x2000:
        raise ValueError('AP 比例代码超出既有 RX 页')
    if any(s['sh_flags'] & 2 and s['sh_size'] and s.name != '.text' for s in module.iter_sections()):
        raise ValueError('AP 比例模块存在未覆盖的加载节')
    symbols = {s.name: s['st_value'] for s in module.get_section_by_name('.symtab').iter_symbols()
               if s.name.startswith('r5_aspect_')}
    end = RX - rx['p_vaddr'] + code['sh_size']
    patches = PatchSet(raw)
    patches.put(rx['p_offset']+RX-rx['p_vaddr'], bytes(code['sh_size']), code.data(), 'aspect-transport')
    phoff = source['e_phoff']
    phsize = source['e_phentsize']
    for field in (32, 40):
        patches.put(phoff+8*phsize+field, struct.pack('<Q', old_rx), struct.pack('<Q', end), 'aspect-rx-extent')
    patches.put(phoff+9*phsize+40, struct.pack('<Q', old_bss), struct.pack('<Q', 0x2ce8), 'aspect-state')
    for at, before, name, link in HOOKS:
        def branch(target):
            opcode = struct.unpack('<I', arm64_b(at, target))[0]
            return struct.pack('<I', opcode | (0x80000000 if link else 0))
        original = bytes.fromhex(before) if before is not None else branch(prior_hooks[name])
        patches.put(at, original, branch(symbols['r5_aspect_'+name]), name)

    def file_at(va):
        for segment in segments:
            if segment['p_type'] == 'PT_LOAD' and segment['p_vaddr'] <= va < segment['p_vaddr']+segment['p_filesz']:
                return segment['p_offset']+va-segment['p_vaddr']
        raise ValueError('AP 比例描述符不在加载段')

    replacements = {DESCRIPTOR+offset: (before, symbols['r5_aspect_'+name])
                    for offset, before, name in ((0x58, STOCK_ROWS, 'rows'), (0x78, 0x1c448dc, 'get'),
                                                  (0x80, 0x1c61d14, 'set'), (0x88, 0x1c93d88, 'commit'))}
    rela = source.get_section_by_name('.rela.dyn')
    for i, (at, info, addend) in enumerate(struct.iter_unpack('<QQq', rela.data())):
        if at in replacements:
            before, after = replacements.pop(at)
            if info != 1027 or before != addend:
                raise ValueError('AP 比例描述符 RELATIVE 前像不符')
            patches.put(rela['sh_offset']+24*i+16, struct.pack('<Q', before), struct.pack('<Q', after), 'aspect-rela')
            patches.put(file_at(at), struct.pack('<Q', before), struct.pack('<Q', after), 'aspect-descriptor')
    if replacements:
        raise ValueError('AP 比例描述符缺少 RELATIVE')
    patches.put(file_at(DESCRIPTOR+0x54), struct.pack('<I', 4), struct.pack('<I', 4+len(LABELS)), 'aspect-count')
    result, proof = patches.finish()
    proof.update(symbols=symbols, selection=SELECTION, installable=False, menu_wired=True,
                 photo_guide_wired=True,
                 label_resources=list(range(FIRST_LABEL, FIRST_LABEL+len(LABELS))),
                 icon_resources=list(range(FIRST_SMALL_ICON, FIRST_ICON+2*len(LABELS))))
    return result, proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ap', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.ap.read_bytes()
    if digest(raw) not in AP_LAYOUTS:
        parser.error('AP 完整前像不符')
    args.output.mkdir(mode=0o700)
    candidate, proof = apply_ap(raw, compile_ap(args.output, raw))
    (args.output/'appFw.aspect.NONINSTALLABLE.so').write_bytes(candidate)
    (args.output/'build.json').write_text(json.dumps(proof, indent=2)+'\n')
    print(proof['target_sha256'])
