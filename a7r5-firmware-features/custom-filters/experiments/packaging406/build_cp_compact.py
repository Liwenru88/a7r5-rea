"""相同CP源的紧凑有界试链接；不授予拟议页所有权、不写固件或执行目标。"""
from pathlib import Path
import argparse
import hashlib
import json
import subprocess

ROOT = next(p for p in Path(__file__).resolve().parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
NATIVE = ROOT/'a7r5-firmware-features/custom-filters/native'
LOCAL = ROOT/'.local/fixed-custom-filters'
SOURCES = ('af_slots.c', 'af_apply_wire.c', 'af_handshake.c', 'af_hs_cp406.c', 'af_hs_cp406.S',
           'af_cp406_state.c', 'af_cp406_state.S', 'af_cp_override406.c', 'af_cp_override406.S')
LINKER = '''ENTRY(af_cp_hs_gate)
MEMORY { proposed_rx (rx) : ORIGIN = 0x1a3b000, LENGTH = 4096
         owned_ro (r) : ORIGIN = 0xbef9e8, LENGTH = 408
         pending_rw (rw) : ORIGIN = 0x1a3ab40, LENGTH = 1216 }
PHDRS { text PT_LOAD FLAGS(5); ro PT_LOAD FLAGS(4); data PT_LOAD FLAGS(6); }
SECTIONS {
 .text : { *(.text*) } > proposed_rx :text
 .rodata : { *(.rodata*) } > owned_ro :ro
 .ARM.exidx : { *(.ARM.exidx*) } > owned_ro :ro
 .data : { *(.data*) } > pending_rw :data
 .bss (NOLOAD) : { *(.bss*) *(COMMON) } > pending_rw :data
 /DISCARD/ : { *(.comment) *(.ARM.attributes*) *(.eh_frame*) } }
'''
COMBINED_LINKER = '''ENTRY(af_cp_hs_gate)
MEMORY { proposed_rx (rx) : ORIGIN = 0x1a3b000, LENGTH = 4096
         pending_rw (rw) : ORIGIN = 0x1a3ab40, LENGTH = 1216 }
PHDRS { text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS {
 .text : { *(.text*) } > proposed_rx :text
 .rodata : { *(.rodata*) } > proposed_rx :text
 .ARM.exidx : { *(.ARM.exidx*) } > proposed_rx :text
 .data : { *(.data*) } > pending_rw :data
 .bss (NOLOAD) : { *(.bss*) *(COMMON) } > pending_rw :data
 /DISCARD/ : { *(.comment) *(.ARM.attributes*) *(.eh_frame*) } }
'''
PIC_LINKER = '''ENTRY(af_cp_hs_gate)
PHDRS { text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); dynamic PT_DYNAMIC FLAGS(6); }
SECTIONS {
 . = SIZEOF_HEADERS;
 .text : { *(.text*) } :text
 .rodata : { *(.rodata*) } :text
 .ARM.exidx : { *(.ARM.exidx*) } :text
 .dynsym : { *(.dynsym) } :text
 .gnu.hash : { *(.gnu.hash) } :text
 .hash : { *(.hash) } :text
 .dynstr : { *(.dynstr) } :text
 .rel.dyn : { *(.rel.dyn) } :text
 . = ALIGN(4096);
 .dynamic : { *(.dynamic) } :data :dynamic
 .data : { *(.data*) *(.got*) } :data
 .bss (NOLOAD) : { *(.bss*) *(COMMON) } :data
 /DISCARD/ : { *(.comment) *(.ARM.attributes*) *(.eh_frame*) } }
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build(output, relocatable=False, combined_page=False, snapshot_entry=None):
    if relocatable and combined_page:
        raise ValueError('可重定位与固定单页布局互斥')
    if snapshot_entry is not None and (not combined_page or not snapshot_entry&1 or
                                      not 0xbef9e9 <= snapshot_entry < 0xbefb80):
        raise ValueError('外层快照入口必须在已确认原RX尾，且仅用于固定单页成对构建')
    output = output.resolve()
    if not output.is_relative_to(LOCAL) or output.exists():
        raise ValueError('只允许全新任务输出目录')
    output.mkdir()
    inputs = [NATIVE/n for n in SOURCES]+[ROOT/'a7r5-firmware-features/custom-filters/tests/native_memory.c']
    watched = inputs+list(NATIVE.glob('*.h'))+[Path(__file__)]
    before = {str(p.relative_to(ROOT)): digest(p) for p in watched}
    linker = output/'proposed-only.ld'
    linker.write_text(PIC_LINKER if relocatable else COMBINED_LINKER if combined_page else LINKER)
    commands = []

    def run(argv):
        r = subprocess.run(list(map(str, argv)), cwd=ROOT, capture_output=True, text=True)
        commands.append(dict(argv=list(map(str, argv)), exit_code=r.returncode, stdout=r.stdout, stderr=r.stderr))
        (output/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
        if r.returncode:
            raise RuntimeError(r.stderr)

    objects = []
    for path in inputs:
        obj = output/(path.name+'.o')
        run(['clang', '--target=armv7a-none-eabi', '-mthumb', '-march=armv7-a', '-mfpu=none',
             '-mfloat-abi=soft', '-Oz', '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
             '-fno-vectorize', '-fno-slp-vectorize', '-ffunction-sections', '-fdata-sections',
             '-Wall', '-Wextra', '-Werror', '-DAF_RUNTIME406=1', '-DAF_CP_PRESET406=1',
             '-DAF_FACTORY_RESTORE406=1', '-DAF_SNAPSHOT_OVERLAY406=1',
             *(['-DAF_CP_SNAPSHOT_ENTRY406='+hex(snapshot_entry)+'u'] if snapshot_entry is not None else []),
             *(['-fPIC'] if relocatable else []), '-I'+str(NATIVE),
             '-c', path, '-o', obj])
        objects.append(obj)
    target = output/'cp-compact-PROPOSAL-ONLY.elf'
    exports = output/'exports.map'
    exports.write_text('{ global: af_cp_hs_gate; af_cp_runtime_gate; af_cp_hs_configure; af_cp_override406_snapshot_gate; local: *; };\n')
    run(['/opt/homebrew/opt/lld/bin/ld.lld', '--gc-sections', '--build-id=none',
         *(['-shared', '-Bsymbolic', '--no-undefined', '--hash-style=gnu', '-z', 'max-page-size=4096',
            '--version-script='+str(exports)] if relocatable else []),
         '--undefined=af_cp_hs_configure', '--undefined=af_cp_runtime_gate',
         '--undefined=af_cp_override406_snapshot_gate', '-T', linker, *objects, '-o', target])
    # 只读取ELF，不导入任何目标执行后端。
    import sys
    sys.path.insert(0, str(ROOT/'a7r5-desktop/prepared/engine/site'))
    from elftools.elf.elffile import ELFFile
    with target.open('rb') as stream:
        elf = ELFFile(stream)
        if elf['e_machine'] != 'EM_ARM' or not elf.little_endian:
            raise ValueError('错误的目标架构')
        syms = list(elf.get_section_by_name('.symtab').iter_symbols())
        if any(s.name and s['st_shndx'] == 'SHN_UNDEF' for s in syms):
            raise ValueError('仍有未解析目标符号')
        sections = {s.name: dict(address=int(s['sh_addr']), bytes=int(s['sh_size']))
                    for s in elf.iter_sections() if s['sh_flags'] & 2}
        loads = [dict(address=int(s['p_vaddr']), bytes=int(s['p_memsz']), flags=int(s['p_flags']),
                      file_offset=int(s['p_offset']), file_bytes=int(s['p_filesz']))
                 for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
        symbols = {s.name: int(s['st_value']) for s in syms if s.name.startswith('af_cp_')}
        payloads = []
        if combined_page:
            expected = ((0x1a3b000, 4096, 5), (0x1a3ab40, 1216, 6))
            if len(loads) != len(expected):
                raise ValueError('固定单页布局的段数错误')
            for seg, (address, capacity, flags) in zip(loads, expected):
                if (seg['address'] != address or seg['flags'] != flags or
                        not 0 < seg['file_bytes'] <= seg['bytes'] <= capacity):
                    raise ValueError('固定单页布局越界或权限错误')
                stream.seek(seg['file_offset'])
                initialized = stream.read(seg['file_bytes'])
                if len(initialized) != seg['file_bytes']:
                    raise ValueError('载荷段截断')
                # 状态尾部不在原清零窗口中，复制源必须显式包含零初始化字节。
                initialized += bytes(seg['bytes']-seg['file_bytes'])
                blob = output/('proposed-rx.bin' if flags == 5 else 'proposed-rw-initialized.bin')
                blob.write_bytes(initialized)
                payloads.append(dict(path=str(blob.relative_to(ROOT)), address=address,
                                     bytes=len(initialized), sha256=digest(blob)))
        relocations = []
        if relocatable:
            if elf['e_type'] != 'ET_DYN' or len(loads) != 2:
                raise ValueError('非双段可重定位模块')
            for section in elf.iter_sections():
                if section['sh_type'] == 'SHT_RELA':
                    raise ValueError('不支持ARM RELA')
                if section['sh_type'] != 'SHT_REL':
                    continue
                for r in section.iter_relocations():
                    at = int(r['r_offset'])
                    if r['r_info_type'] != 23 or r['r_info_sym'] or at%4:
                        raise ValueError('仅允许对齐的R_ARM_RELATIVE')
                    seg = next((s for s in loads if s['flags'] == 6 and
                                s['address'] <= at and at+4 <= s['address']+s['file_bytes']), None)
                    if not seg:
                        raise ValueError('重定位不在已初始化RW段')
                    stream.seek(seg['file_offset']+at-seg['address'])
                    add = int.from_bytes(stream.read(4), 'little')
                    if not any(s['address'] <= (add&~1) < s['address']+s['bytes'] for s in loads):
                        raise ValueError('重定位加数超出模块')
                    relocations.append(dict(offset=at, addend=add))
    if before != {str(p.relative_to(ROOT)): digest(p) for p in watched}:
        raise RuntimeError('构建期间源码变化')
    result = dict(status='BOUNDED_LINK_PASS_PROPOSED_LAYOUT_ONLY', source_sha256=before,
                  artifact=dict(path=str(target.relative_to(ROOT)), sha256=digest(target), bytes=target.stat().st_size),
                  sections=sections, loads=loads, symbols=symbols, commands=commands,
                  relocatable=relocatable, combined_page=combined_page, expected_snapshot_entry=snapshot_entry,
                  payloads=payloads, relocations=relocations,
                  actual_page_reserved=False, actual_page_executable=False, actual_loader_implemented=False,
                  RW_reserved=False, installed=False, installable_firmware=False,
                  target_executed=False, hardware_simulation=False, camera_io=False)
    (output/'verification.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps({k: result[k] for k in ('status', 'sections', 'loads', 'artifact', 'installed')}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument('--relocatable', action='store_true', help='仅构建ARM PIC模块，不安装或分配真实执行区')
    modes.add_argument('--combined-page', action='store_true', help='将text和RO放入同一拟议页，输出显式初始化载荷')
    parser.add_argument('--snapshot-entry', type=lambda value: int(value, 0),
                        help='成对原RX尾快照入口；仍须独立核对bootstrap符号和完整窗口')
    args=parser.parse_args()
    build(args.output, args.relocatable, args.combined_page, args.snapshot_entry)
