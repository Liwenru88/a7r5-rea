"""构建原厂纵横比菜单及 0x402d 序列化的离线研究组件。"""

import argparse
import io
import json
import re
from pathlib import Path
import struct
import subprocess

from elftools.elf.elffile import ELFFile

from build_cp import HERE, PatchSet, digest
from patches import arm64_b
from aspect_sizes import generate


SOURCE = '7ab2120c14cf1635b920c6583c65e1406f6f3f5a831e570509bdf39c2968ea5d'
STOCK = '41bd8f4cda1f44c7038912837737e1ce6a650065f2108061ada30e5c7f9ce7c7'
AP_LAYOUTS = {
    SOURCE: (0x4239, 0x2b60, 0x8e98ab4, 0x8f010fc, 0x8f01120),
    'eaf0b742745696f651dbe5ee75a813bb168ac41db81706743712ab8f6d0491bf':
        (0x3aba, 0x2b50, 0x8e989a4, 0x8f0107c, 0x8f010a0),
}
RX = 0x8f04400
SELECTION = 0x8f13000
STOCK_ROWS = 0x3f46600
DESCRIPTOR = 0x586b990
LABELS = ('17:6', '65:24', '5:4', '7:6', '1.91:1', '2.35:1')
FIRST_ROW = 0x1640
FIRST_LABEL = 0x0200ab60
# 0xab66 已有原厂条目；提示从 C1–C6 的 0xabd8..0xabdd 之后扩展索引。
FIRST_STATUS = 0x0200abde
FIRST_ICON = 0x02001e90
FIRST_SMALL_ICON = FIRST_ICON-len(LABELS)
FIRST_PLAYBACK_ICON = 0x02001ef0
FIRST_PIXEL_ICON = 0x02001f00
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
    (0x1bd54d8, 'fd7bbea9', 'title', False),
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
    (0x2dbf3b0, 'fd7bbfa9', 'playback', False),
    (0x2adfd3c, 'fd7bbfa9', 'capture_value', False),
    (0x2adfd5c, 'fd7bbea9', 'restore_value', False),
    (0x1bd64c8, '09bbff97', 'restore_alias', True),
    (0x1bd64d4, '20003fd6', 'restore_commit', True),
    (0x30c6f1c, '35e2f397', 'zoom_map', True),
    (0x249069c, '020c80b9', 'zoom_policy', False),
    (0x2492230, 'f30b40f9', 'zoom_domain', False),
    (0x23de638, '00008012', 'badge', False),
    (0x23dfa30, '031c8252', 'pixels', False),
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


def layout(raw, source_sha):
    pin = digest(raw)
    if pin == STOCK:
        return None
    if pin in AP_LAYOUTS:
        return AP_LAYOUTS[pin]
    if pin != source_sha:
        raise ValueError('AP 完整前像不符')
    segments = list(ELFFile(io.BytesIO(raw)).iter_segments())
    if len(segments) != 10:
        raise ValueError('AP 统一入口加载段数量不符')
    rx, rw = segments[8:10]
    shift = rx['p_vaddr'] - 0x8f00000
    if shift not in (0, 0x10000) or rw['p_vaddr'] != 0x8f10000 + shift:
        raise ValueError('未知 AP 统一入口布局')
    if not 0 < rx['p_filesz'] <= RX - 0x8f00000 or not 0 < rw['p_memsz'] <= SELECTION - 0x8f10000:
        raise ValueError('AP 统一入口与比例扩展重叠')
    destinations = []
    for at, opcode, segment in ((0x16f6610, 0x94000000, segments[6]),
                                 (0x1bd18e8, 0x14000000, rx), (0x1bd19e8, 0x14000000, rx)):
        word, = struct.unpack_from('<I', raw, at)
        delta = ((word & 0x3ffffff) ^ 0x2000000) - 0x2000000
        target = at + delta * 4
        if word & 0xfc000000 != opcode or not segment['p_vaddr'] <= target < segment['p_vaddr'] + segment['p_filesz']:
            raise ValueError('AP 比例与统一入口的接续分支不符')
        destinations.append(target)
    return rx['p_filesz'], rw['p_memsz'], *destinations, shift


def compile_ap(work, raw, *, source_sha=None):
    generate(work)
    existing = layout(raw, source_sha)
    shift = existing[5] if existing and len(existing) > 5 else 0
    linker = HERE / 'ap.ld'
    if shift:
        linker = work / 'aspect-ap-layout.ld'
        source = (HERE / 'ap.ld').read_text()
        linker.write_text(re.sub(r'0x8f[01][0-9a-f]{4}',
                                lambda m: hex(int(m[0], 16) + shift), source))
    if existing:
        hooks = ['-Wl,--defsym='+key+'='+hex(value) for key, value in
                 zip(('prior_register', 'prior_icon', 'prior_icon_alt'), existing[2:])]
    else:
        hooks = ['-DR5_ASPECT_STOCK', '-Wl,--defsym=prior_register=0x1c91e94',
                 '-Wl,--defsym=prior_icon=r5_aspect_stock_icon',
                 '-Wl,--defsym=prior_icon_alt=r5_aspect_stock_icon_alt']
    elf = work / 'aspect-ap.elf'
    row_file = work / 'aspect-ap-rows.bin'
    row_file.write_bytes(rows(raw))
    assembly = work / 'aspect-ap-rows.S'
    assembly.write_text('.section .rodata.rows,"a"\n.balign 8\n'
                        '.global r5_aspect_rows\nr5_aspect_rows:\n'
                        f'.incbin {json.dumps(str(row_file.resolve()))}\n')
    subprocess.run(['/opt/homebrew/opt/llvm/bin/clang', '--target=aarch64-none-elf', '-Oz',
        '-ffreestanding', '-fno-builtin', '-fno-stack-protector', '-mno-outline-atomics',
        '-Wall', '-Wextra', '-Werror', '-I', str(work),
        '-nostdlib', '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld', '-Wl,--build-id=none',
        '-Wl,-T,'+str(linker), *hooks,
        *(str(HERE/name) for name in ('ap_transport.S', 'ap_menu.S', 'ap_menu.c',
                                      'ap_state.c', 'ap_persist.c', 'ap_guide.S', 'ap_guide.c',
                                      'geometry.c', 'playback.S', 'ap_zoom.S', 'ap_playback_info.S')),
        str(assembly), '-o', str(elf)], check=True)
    return elf.read_bytes()


def apply_ap(raw, elf, *, source_sha=None):
    existing = layout(raw, source_sha)
    shift = existing[5] if existing and len(existing) > 5 else 0
    code_address = RX + shift
    prior_hooks = dict(zip(('register', 'icon', 'icon_alt'), existing[2:])) if existing else {}
    source = ELFFile(io.BytesIO(raw))
    segments = list(source.iter_segments())
    module = ELFFile(io.BytesIO(elf))
    code = module.get_section_by_name('.text')
    if code['sh_addr'] != code_address or not 0 < code['sh_size'] <= 0x6000:
        raise ValueError('AP 比例代码超出既有 RX 页')
    if any(s['sh_flags'] & 2 and s['sh_size'] and s.name != '.text' for s in module.iter_sections()):
        raise ValueError('AP 比例模块存在未覆盖的加载节')
    symbols = {s.name: s['st_value'] for s in module.get_section_by_name('.symtab').iter_symbols()
               if s.name.startswith('r5_aspect_')}
    patches = PatchSet(raw)
    phoff = source['e_phoff']
    phsize = source['e_phentsize']
    rx_base, rw_base, state_size = 0x8f00000 + shift, 0x8f10000 + shift, 0x3300
    end = code_address - rx_base + code['sh_size']
    if existing:
        old_rx, old_bss = existing[:2]
        rx, rw = segments[8:10]
        if (rx['p_type'], rx['p_vaddr'], rx['p_filesz'], rx['p_memsz'], rx['p_flags'],
            rw['p_type'], rw['p_vaddr'], rw['p_filesz'], rw['p_memsz'], rw['p_flags']) != (
                'PT_LOAD', rx_base, old_rx, old_rx, 5, 'PT_LOAD', rw_base, 0, old_bss, 6):
            raise ValueError('AP 统一入口段布局不符')
        patches.put(rx['p_offset']+code_address-rx_base, bytes(code['sh_size']), code.data(), 'aspect-transport')
        for field in (32, 40):
            patches.put(phoff+8*phsize+field, struct.pack('<Q', old_rx), struct.pack('<Q', end), 'aspect-rx-extent')
        patches.put(phoff+9*phsize+40, struct.pack('<Q', old_bss), struct.pack('<Q', state_size), 'aspect-state')
    else:
        appended = (len(raw)+0xffff)&~0xffff
        if phsize != 56 or len(segments) != 6 or any(
                s['p_vaddr']+s['p_memsz'] > rx_base for s in segments if s['p_type'] == 'PT_LOAD'):
            raise ValueError('AP 原厂程序头布局不符')
        headers = raw[phoff:phoff+phsize*len(segments)]
        headers += struct.pack('<II6Q', 1, 5, appended, rx_base, rx_base, end, end, 0x10000)
        headers += struct.pack('<II6Q', 1, 6, appended+0x10000, rw_base, rw_base, 0, state_size, 0x10000)
        patches.put(32, struct.pack('<Q', phoff), struct.pack('<Q', appended), 'aspect-phoff')
        patches.put(56, struct.pack('<H', len(segments)), struct.pack('<H', len(segments)+2), 'aspect-phnum')
    for at, before, name, link in HOOKS:
        def branch(target):
            opcode = struct.unpack('<I', arm64_b(at, target))[0]
            return struct.pack('<I', opcode | (0x80000000 if link else 0))
        if before is not None:
            original = bytes.fromhex(before)
        elif existing:
            original = branch(prior_hooks[name])
        else:
            original = bytes.fromhex('216e1694' if name == 'register' else 'fd7bbba9')
        patches.put(at, original, branch(symbols['r5_aspect_'+name]), name)

    patches.put(0x434eabc, struct.pack('<I', 0x5049), struct.pack('<I', 0x507a), 'custom-playback-zoom-domain')

    def file_at(va):
        for segment in segments:
            if segment['p_type'] == 'PT_LOAD' and segment['p_vaddr'] <= va < segment['p_vaddr']+segment['p_filesz']:
                return segment['p_offset']+va-segment['p_vaddr']
        raise ValueError('AP 比例描述符不在加载段')

    at = file_at(0x53db918)
    if raw[at:at+8] != struct.pack('<II', 0xffd, 0x8cc):
        raise ValueError('AP 回放放大策略描述符前像不符')

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
    if not existing:
        result += bytes(appended-len(result)) + headers
        result += bytes(appended+RX-rx_base-len(result)) + code.data()
        result += bytes(appended+0x10000-len(result))
        proof.update(target_sha256=digest(result), source_bytes=len(raw))
    proof.update(symbols=symbols, selection=SELECTION + shift, layout_shift=shift,
                 installable=False, menu_wired=True,
                 photo_guide_wired=True,
                 label_resources=list(range(FIRST_LABEL, FIRST_LABEL+len(LABELS))),
                 status_resources=list(range(FIRST_STATUS, FIRST_STATUS+4)),
                 icon_resources=list(range(FIRST_SMALL_ICON, FIRST_ICON+2*len(LABELS))))
    return result, proof


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--ap', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    raw = args.ap.read_bytes()
    layout(raw, None)
    args.output.mkdir(mode=0o700)
    candidate, proof = apply_ap(raw, compile_ap(args.output, raw))
    (args.output/'appFw.aspect.NONINSTALLABLE.so').write_bytes(candidate)
    (args.output/'build.json').write_text(json.dumps(proof, indent=2)+'\n')
    print(proof['target_sha256'])
