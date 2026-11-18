"""三种固定保留布局的双段模块和408B原尾链接；不执行目标、不导出固件。"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import io
import json
import shutil
import struct
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = next(p for p in HERE.parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
NATIVE = ROOT/'a7r5-firmware-features/custom-filters/native'
sys.path.insert(0, str(ROOT/'a7r5-desktop/prepared/engine/site'))
from elftools.elf.elffile import ELFFile
_capture_spec = importlib.util.spec_from_file_location('af_capture_layout', HERE/'capture_layout.py')
CAPTURE = importlib.util.module_from_spec(_capture_spec)
_capture_spec.loader.exec_module(CAPTURE)

RX = 0x2afc000
RW = 0x2aff000
TAIL = 0xbef9e8
FACTOR = 0xbef718
FACTOR_BYTES = 288
THUMB_COPY_SITES = (0x898568, 0x4baab6, 0x4bba78, 0x4bc002, 0x884766, 0x719600, 0x9071f6, 0x313c70, 0xaa6978, 0xadf128)
ARM_COPY_SITES = (0x5c36e0, 0x5c3860, 0x5c3888)
NATIVE_ENTRIES = {0x71e41e: 'permanent_matrix', 0x71e670: 'permanent_primary',
                  0x41363c: 'permanent_gamma', 0x230f0c: 'permanent_grid'}
NATIVE_CALLS = {0x845700: 'permanent_gamma_source', 0xaaca82: 'permanent_gamma_reset'}
NATIVE_HOOK_COUNT = len(THUMB_COPY_SITES)+len(ARM_COPY_SITES)+len(NATIVE_ENTRIES)+len(NATIVE_CALLS)+len(CAPTURE.CALLS)
CAPTURE_BYTES = 582
# 原Hook保留自然4字节对齐；只有前582B对应实际段，后2B必须显式为零。
CAPTURE_STORAGE_BYTES = 584
NATIVE_CONTRACT_BYTES = FACTOR_BYTES+CAPTURE_STORAGE_BYTES+NATIVE_HOOK_COUNT*8
NATIVE_SOURCES = ('af_cp_native406.c', 'af_cp_native_bank406.c', 'af_cp_jobs406.c',
                  'af_cp_jobs406.S', 'af_cp_components406.c', 'af_cp_components406.S', 'af_color406.c',
                  'af_cp_capture406.c', 'af_cp_capture_fields406.c', 'af_cp_capture_target406.c',
                  'af_cp_capture_color406.c')
NATIVE_TARGETS = {'native_matrix_target': 'af_cp_components406_matrix_target',
                  'native_primary_target': 'af_cp_components406_cc1_target',
                  'native_gamma_target': 'af_cp_components406_gamma_target',
                  'native_grid_target': 'af_cp_components406_grid_gate',
                  'native_gamma_source_target': 'af_cp_components406_gamma_source_target',
                  'native_gamma_reset_target': 'af_cp_components406_gamma_reset_target'}
SOURCES = ('af_slots.c', 'af_apply_wire.c', 'af_handshake.c', 'af_hs_cp406.c', 'af_hs_cp406.S',
           'af_cp406_state.c', 'af_cp406_state.S', 'af_cp_override406.c', 'af_cp_override406.S',
           'af_cp_recipe406.c', 'af_recipe_transport.c', 'af_joint_asset.c', 'af_joint.c', 'af_sha256.c')
EXPORTS = ('af_cp_hs_gate', 'af_cp_runtime_gate', 'af_cp_hs_configure',
           'af_cp_hs_last_prepare',
           'af_cp_recipe406_bind', 'af_cp_recipe406_owner_bytes', 'af_cp_recipe406_unbind',
           'af_cp_recipe406_pending', 'af_cp_recipe406_finish', 'af_cp_recipe406_release')


def capacity_layout(native_capacity=False, native_integration=False):
    if type(native_capacity) is not bool or type(native_integration) is not bool:
        raise ValueError('容量布局只接受已固定的四页、二十页或Capture颜色二十二页分支')
    rx, rw, cold, rx_pages, rw_pages = (
        (0x2aea000, 0x2af4000, 0x11c8000, 10, 12) if native_integration else
        (0x2aec000, 0x2af4000, 0x11ca000, 8, 12) if native_capacity else
        (RX, RW, 0x11cf000, 3, 1))
    return dict(rx=rx, rw=rw, cold=cold, rx_pages=rx_pages, rw_pages=rw_pages,
                rx_capacity=rx_pages*4096, rw_capacity=rw_pages*4096,
                solid_size=rx-0x128000, pte_bias=((rx & 0xfffff) >> 10)-1)


def layout_header(layout):
    return ''.join(f'#define AF_CARVE_{name.upper()} 0x{layout[name]:x}\n'
                   for name in ('rx', 'rw', 'cold', 'rx_pages', 'rw_pages', 'pte_bias'))


def native_hotpatches(snapshot, factor_symbols, capture_symbols=None):
    spec = importlib.util.spec_from_file_location('native406_branch_encoder', HERE/'memory_plan.py')
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    answer = ([(a, api.thumb_branch(a, snapshot, link=True)) for a in THUMB_COPY_SITES]
            + [(a, api.arm_blx(a, snapshot)) for a in ARM_COPY_SITES]
            + [(a, api.thumb_branch(a, factor_symbols[name])) for a, name in NATIVE_ENTRIES.items()]
            + [(a, api.thumb_branch(a, factor_symbols[name], link=True)) for a, name in NATIVE_CALLS.items()])
    if capture_symbols is not None:
        answer += [(a,api.thumb_branch(a,capture_symbols['permanent_capture_'+name],link=a not in CAPTURE.TAIL_CALLS)) for a,name in CAPTURE.CALLS.items()]
    return answer


def contract_source(factor, hooks, capture=None):
    if len(factor) != FACTOR_BYTES or len(hooks) != NATIVE_HOOK_COUNT or any(len(code) != 4 for _, code in hooks):
        raise ValueError('原生合同挂点数或4字节分支长度错误')
    if capture is None:capture=bytes(CAPTURE_BYTES)
    if len(capture)!=CAPTURE_BYTES:raise ValueError('Capture合同长度错误')
    capture += bytes(CAPTURE_STORAGE_BYTES-CAPTURE_BYTES)
    array = ','.join(hex(b) for b in factor)
    entries = ',\n'.join('{'+hex(address)+', {'+','.join(hex(b) for b in code)+'}}'
                          for address, code in hooks)
    return ('/* 同次实际链接生成的只读启动合同，不是相机验收。 */\n#include "af_cp_native406.h"\n'
            '#define CONTRACT __attribute__((section(".rodata.native406_contract"),used,aligned(4)))\n'
            'CONTRACT const volatile uint8_t af_cp_native406_factor_expected[288]={' + array + '};\n'
            f'CONTRACT const volatile uint8_t af_cp_native406_capture_expected[{CAPTURE_STORAGE_BYTES}]={{' + ','.join(hex(b) for b in capture) + '};\n'
            f'CONTRACT const volatile AfCpNative406Hook af_cp_native406_hooks[{NATIVE_HOOK_COUNT}]={{' + entries + '};\n'
            f'_Static_assert(sizeof(af_cp_native406_factor_expected)+sizeof(af_cp_native406_capture_expected)+sizeof(af_cp_native406_hooks)=={NATIVE_CONTRACT_BYTES},"native contract size");\n')


def text_symbols(elf):
    index = next(n for n, s in enumerate(elf.iter_sections()) if s.name == '.text')
    return sorted((s.name, int(s['st_value']), int(s['st_size']))
                  for s in elf.get_section_by_name('.symtab').iter_symbols() if s['st_shndx'] == index)


def module_bytes(elf, address, count):
    for segment in elf.iter_segments():
        if (segment['p_type'] == 'PT_LOAD' and segment['p_vaddr'] <= address
                and address+count <= segment['p_vaddr']+segment['p_filesz']):
            offset = address-segment['p_vaddr']
            return segment.data()[offset:offset+count]
    raise ValueError('实际ELF不含完整的只读合同范围')


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def crc(raw):
    value = 0
    for byte in raw:
        value ^= byte << 24
        for _ in range(8):
            value = ((value << 1) ^ (0x04c11db7 if value & 0x80000000 else 0)) & 0xffffffff
    return value


def inspect(raw):
    elf = ELFFile(io.BytesIO(raw))
    if elf['e_machine'] != 'EM_ARM' or not elf.little_endian:
        raise ValueError('目标ABI错误')
    symbols = list(elf.get_section_by_name('.symtab').iter_symbols())
    if any(s.name and s['st_shndx'] == 'SHN_UNDEF' for s in symbols):
        raise ValueError('仍有未解析符号')
    if any(s['sh_type'] in ('SHT_REL', 'SHT_RELA') and s['sh_size'] for s in elf.iter_sections()):
        raise ValueError('仍有运行期重定位')
    return elf, {s.name: int(s['st_value']) for s in symbols}


def build(output, capture_input=False, capture_copies=False, native_capacity=False, native_integration=False):
    if type(native_integration) is not bool:
        raise ValueError('原生接线分支必须为布尔值')
    capacity_layout(native_capacity)
    native_capacity = native_capacity or native_integration
    capture_copies = bool(capture_copies or native_integration)
    layout = capacity_layout(native_capacity, native_integration)
    layout_version, cold_before = (
        ('capture-color-22-v1', '02b1c2234680617802901a77eae606ad02e4ddb4282ccbc60061eac5b2d90bba') if native_integration else
        ('native-capacity-20-v1', 'c35020473aed1b4642cd726cad727b63fff2824ad68cedd7ffb73c7cbd890479') if native_capacity else
        ('legacy-4-v1', 'f3cc103136423a57975750907ebc1d367e2985ac6338976d4d5a439f50323f4a'))
    capture_input = bool(capture_input or capture_copies)
    output = Path(output).resolve()
    if output.exists() or output.is_symlink():
        raise ValueError('必须使用全新输出目录')
    output.mkdir(parents=True)
    extra = ((('af_cp_input406.c',) if capture_input else ())
             + (('af_cp_copy406.c', 'af_cp_copy406.S') if capture_copies else ())
             + (NATIVE_SOURCES if native_integration else ()))
    source = [NATIVE/n for n in SOURCES+extra] + [NATIVE.parent/'tests/native_memory.c']
    watched = (source + sorted(NATIVE.glob('*.h')) + list((HERE/'bootstrap').glob('*'))
               + [Path(__file__), HERE/'memory_plan.py', HERE/'capture_layout.py'])
    before = {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in watched}
    commands = []

    def run(argv):
        args = list(map(str, argv))
        result = subprocess.run(args, capture_output=True, text=True, cwd=ROOT)
        commands.append(dict(argv=args, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr))
        (output/'commands.json').write_text(json.dumps(commands, indent=2)+'\n')
        if result.returncode:
            raise RuntimeError(result.stderr)

    flags = ['clang', '--target=armv7a-none-eabi', '-mthumb', '-march=armv7-a', '-mfpu=none',
             '-mfloat-abi=soft', '-Oz', '-ffreestanding', '-fno-builtin', '-fno-stack-protector',
             '-fno-vectorize', '-fno-slp-vectorize', '-ffunction-sections', '-fdata-sections',
             '-fno-unwind-tables', '-fno-asynchronous-unwind-tables', '-Wall', '-Wextra', '-Werror']
    linker = '/opt/homebrew/bin/ld.lld'
    capture_flags = ((['-DAF_CP_CAPTURE_INPUT406=1'] if capture_input else [])
                     + (['-DAF_CP_CAPTURE_COPIES406=1'] if capture_copies else [])
                     + (['-DAF_CP_NATIVE_CAPACITY406=1'] if native_capacity
                        else ['-DAF_JOINT_ASSET_LEGACY_ONLY406=1'])
                     + (['-DAF_CP_NATIVE406=1', '-DAF_CP_NATIVE_JOBS406=1', '-DAF_CP_COMPONENTS406_TARGET=1', '-DAF_CP_CAPTURE406=1']
                        if native_integration else []))
    snapshot_symbol = 'af_cp_copy406_gate' if capture_copies else 'af_cp_override406_snapshot_copy_gate' if capture_input else 'af_cp_override406_snapshot_gate'
    snapshot_patchsite = 0x898568 if capture_input else 0x89856c
    exports = ((*EXPORTS, snapshot_symbol) + (('af_cp_override406_read_input',) if capture_input else ())
               + (tuple(NATIVE_TARGETS.values())+tuple(CAPTURE.TARGETS.values()) if native_integration else ()))
    capture_cp=CAPTURE.source() if native_integration else b''

    def bootstrap(directory, rx_bytes, rx_crc, rw_bytes, targets):
        directory.mkdir()
        (directory/'image_constants.h').write_text(
            f'#define AF_RX_BYTES {rx_bytes}u\n#define AF_RW_BYTES {rw_bytes}u\n'
            f'#define AF_RX_CRC 0x{rx_crc:08x}u\n')
        (directory/'layout_constants.h').write_text(layout_header(layout))
        objects = []
        (directory/'guard.inc').write_bytes((HERE/'bootstrap/guard.inc').read_bytes())
        for name in ('gates.S',):
            local = directory/name
            local.write_bytes((HERE/'bootstrap'/name).read_bytes())
            obj = directory/(name+'.o')
            run([*flags, *capture_flags, '-I'+str(directory), '-c', local, '-o', obj])
            objects.append(obj)
        ld = f'''ENTRY(af_carve_prepare)
SECTIONS {{ . = 0x{TAIL:x}; .text : {{ *(.text.gates) *(.text*) *(.rodata*) }}
 /DISCARD/ : {{ *(.ARM.exidx*) *(.ARM.extab*) *(.comment*) }} }}
ASSERT(SIZEOF(.text) <= 408, "original 408B RX tail exceeded");
'''
        for name, value in dict(stock_copy=0x5f51bc, stock_zero=0x5f58b0, stock_dcache=0x5f3524,
                                stock_icache=0x5f2cf0, stock_lock_fn=0x5b8d6c,
                                stock_start_return=0x495fdd,
                                stock_snapshot_return=0x89856d if capture_input else 0x898571, **targets).items():
            ld += f'{name} = 0x{value:x};\n'
        script = directory/'bootstrap.ld'
        script.write_text(ld)
        target = directory/'bootstrap.elf'
        run([linker, '--no-undefined', '--build-id=none', '-T', script, *objects, '-o', target])
        elf, symbols = inspect(target.read_bytes())
        text = elf.get_section_by_name('.text')
        if text['sh_addr'] != TAIL or not 0 < text['sh_size'] <= 408:
            raise ValueError('原尾容量不符')
        payload = text.data()
        (directory/'bootstrap-rx.bin').write_bytes(payload)
        return symbols, payload

    def factor(directory, module_symbols, boot_symbols):
        directory.mkdir()
        probe = directory/'probe'
        probe.mkdir()
        (probe/'native_factor_constants.h').write_text('#define AF_FACTOR_PHASE_LDR 0x4900\n')
        source_path = HERE/'bootstrap/legacy_factor.S'
        run([*flags, '-I'+str(probe), '-c', source_path, '-o', probe/'factor.o'])
        layout_elf = ELFFile(io.BytesIO((probe/'factor.o').read_bytes()))
        offsets = {s.name: int(s['st_value']) for s in layout_elf.get_section_by_name('.symtab').iter_symbols()}
        if layout_elf.get_section_by_name('.text.factor')['sh_size'] != FACTOR_BYTES:
            raise ValueError('永久factor布局不再恰为288字节')
        site = FACTOR+(offsets['permanent_phase'] & ~1)
        delta = boot_symbols['phase']-((site+4) & ~3)
        if delta < 0 or delta > 1020 or delta & 3:
            raise ValueError('phase literal无法由原16位LDR准确触达')
        opcode = 0x4900 | (delta >> 2)
        (directory/'native_factor_constants.h').write_text(f'#define AF_FACTOR_PHASE_LDR 0x{opcode:04x}\n')
        local = directory/'legacy_factor.S'
        local.write_bytes(source_path.read_bytes())
        run([*flags, '-I'+str(directory), '-c', local, '-o', directory/'factor.o'])
        script = directory/'factor.ld'
        bindings = dict(original_matrix=0xbef701, original_primary=0xbef709, original_secondary=0xbef711)
        bindings.update({name: module_symbols[symbol] for name, symbol in NATIVE_TARGETS.items()})
        script.write_text(f'ENTRY(factor_matrix)\nSECTIONS {{ . = 0x{FACTOR:x}; .text : {{ *(.text.factor) }} '
                          '/DISCARD/ : { *(.ARM.exidx*) *(.ARM.attributes*) *(.comment*) } }\n'
                          f'ASSERT(SIZEOF(.text) == {FACTOR_BYTES}, "factor must remain original 288B");\n'
                          + ''.join(f'{name} = 0x{value:x};\n' for name, value in bindings.items()))
        elf_path = directory/'factor.elf'
        run([linker, '--no-undefined', '--build-id=none', '-T', script, directory/'factor.o', '-o', elf_path])
        elf, sy = inspect(elf_path.read_bytes())
        section = elf.get_section_by_name('.text')
        raw = section.data()
        if section['sh_addr'] != FACTOR or len(raw) != FACTOR_BYTES or (sy['permanent_phase'] & ~1) != site:
            raise ValueError('永久factor地址或phase定位不符')
        (directory/'factor-rx.bin').write_bytes(raw)
        return sy, raw, opcode

    # gates位于C函数之前，真实快照symbol不依赖后方CRC常量和模块大小。
    probe = output/'layout-probe'
    probe.mkdir()
    (probe/'layout_constants.h').write_text(layout_header(layout))
    run([*flags, *capture_flags, '-DAF_CARVE_LAYOUT_PROBE=1', '-I'+str(probe),
         '-c', HERE/'bootstrap/gates.S', '-o', probe/'gates.o'])
    probe_elf = ELFFile(io.BytesIO((probe/'gates.o').read_bytes()))
    probe_symbols = {s.name: int(s['st_value']) for s in probe_elf.get_section_by_name('.symtab').iter_symbols()}
    snapshot = TAIL+probe_symbols['af_carve_snapshot']
    if not snapshot & 1 or not TAIL <= snapshot < TAIL+408:
        raise ValueError('快照入口不在原拥有的Thumb尾部')
    objects = []
    core_flags = [*flags, '-DAF_RUNTIME406=1', '-DAF_CP_PRESET406=1', '-DAF_FACTORY_RESTORE406=1',
                  '-DAF_SNAPSHOT_OVERLAY406=1', '-DAF_RECIPE_BRIDGE406=1', '-DAF_CP_CARVE_BRANCH406=1',
                  *capture_flags, '-DAF_CP_SNAPSHOT_ENTRY406='+hex(snapshot)+'u', '-I'+str(NATIVE)]
    for path in source:
        obj = output/(path.name+'.o')
        # 完整LTO在固定八页RX内合并重复守卫；内存ABI保持可见，供后端新增libcall。
        lto = ['-flto=full'] if native_integration and path.suffix == '.c' and path.name != 'native_memory.c' else []
        run([*core_flags, *lto, '-c', path, '-o', obj])
        objects.append(obj)
    contract = output/'native-contract.c'
    contract_object = output/'native-contract.o'
    if native_integration:
        contract.write_text(contract_source(bytes(FACTOR_BYTES), [(0, bytes(4))]*NATIVE_HOOK_COUNT))
        run([*core_flags, '-c', contract, '-o', contract_object])
        objects.append(contract_object)
    module_ld = output/'module.ld'
    module_ld.write_text('''ENTRY(af_cp_hs_gate)
MEMORY { carved_rx (rx) : ORIGIN = RX_ORIGIN, LENGTH = RX_CAPACITY
         carved_rw (rw) : ORIGIN = RW_ORIGIN, LENGTH = RW_CAPACITY }
PHDRS { text PT_LOAD FLAGS(5); data PT_LOAD FLAGS(6); }
SECTIONS {
 .text : { *(.text*) *(.rodata*) } > carved_rx :text
 .ARM.exidx : { *(.ARM.exidx*) } > carved_rx :text
 .data : { *(.data*) } > carved_rw :data
 .bss (NOLOAD) : { *(.bss*) *(COMMON) __af_carve_rw_statics_end = .; RW_RESERVATION } > carved_rw :data
 /DISCARD/ : { *(.comment) *(.ARM.attributes*) *(.eh_frame*) } }
'''.replace('RX_ORIGIN', hex(layout['rx'])).replace('RX_CAPACITY', str(layout['rx_capacity']))
       .replace('RW_ORIGIN', hex(layout['rw'])).replace('RW_CAPACITY', str(layout['rw_capacity']))
       .replace('RW_RESERVATION', '. = ORIGIN(carved_rw) + LENGTH(carved_rw);' if native_capacity else ''))
    module = output/'cp-carve-OFFLINE-ONLY.elf'
    iterations = []
    factor_symbols = {}
    factor_raw = b''
    factor_opcode = None
    capture_symbols = {}
    capture_regions = []
    hooks = []
    last_text = None
    for iteration in range(3 if native_integration else 1):
        run([linker, '--no-undefined', '--gc-sections', '--build-id=none',
             *['--undefined='+s for s in exports], '-T', module_ld, *objects, '-o', module])
        elf, module_symbols = inspect(module.read_bytes())
        if not native_integration:
            break
        pair = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
        if len(pair) != 2:
            raise ValueError('原生模块段数错误')
        for s, address, cap, permission in zip(pair, (layout['rx'], layout['rw']),
                                               (layout['rx_capacity'], layout['rw_capacity']), (5, 6)):
            if s['p_vaddr'] != address or s['p_flags'] != permission or not 0 < s['p_memsz'] <= cap:
                raise ValueError('原生模块超出已固定RX/RW容量或权限')
        intermediate_rx = pair[0].data()+bytes(pair[0]['p_memsz']-pair[0]['p_filesz'])
        targets = dict(compact_start=module_symbols['af_cp_runtime_gate'], compact_hs=module_symbols['af_cp_hs_gate'],
                       compact_snapshot=module_symbols[snapshot_symbol], compact_copy=module_symbols[snapshot_symbol])
        boot_dir = output/f'bootstrap-pass{iteration}'
        boot_symbols, boot = bootstrap(boot_dir, len(intermediate_rx), crc(intermediate_rx), pair[1]['p_memsz'], targets)
        factor_dir = output/f'factor-pass{iteration}'
        factor_symbols, factor_raw, factor_opcode = factor(factor_dir, module_symbols, boot_symbols)
        capture_dir=output/f'capture-pass{iteration}'
        capture_symbols,capture_regions=CAPTURE.build(capture_dir,flags,run,inspect,module_symbols,factor_symbols,capture_cp)
        hooks = native_hotpatches(snapshot, factor_symbols,capture_symbols)
        capture_blob=CAPTURE.blob(capture_regions)
        wanted = contract_source(factor_raw, hooks,capture_blob)
        positions = text_symbols(elf)
        iterations.append(dict(iteration=iteration, RX_bytes=len(intermediate_rx), RW_bytes=pair[1]['p_memsz'],
                               text_positions_sha256=sha(json.dumps(positions).encode()),
                               text_positions_changed=last_text is not None and last_text != positions,
                               contract_source_sha256=sha(contract.read_bytes()), factor_sha256=sha(factor_raw)))
        if contract.read_text() == wanted and last_text == positions:
            expected = factor_raw+capture_blob+bytes(CAPTURE_STORAGE_BYTES-CAPTURE_BYTES)+b''.join(struct.pack('<I', a)+code for a, code in hooks)
            address = module_symbols['af_cp_native406_factor_expected']
            if module_symbols['af_cp_native406_hooks'] != address+FACTOR_BYTES+CAPTURE_STORAGE_BYTES or module_bytes(elf, address, NATIVE_CONTRACT_BYTES) != expected:
                raise ValueError('最终实际ELF合同未绑定所需factor及全部原生挂点')
            shutil.copytree(boot_dir, output/'bootstrap')
            shutil.copytree(factor_dir, output/'factor')
            shutil.copytree(capture_dir, output/'capture')
            break
        last_text = positions
        contract.write_text(wanted)
        run([*core_flags, '-c', contract, '-o', contract_object])
    else:
        raise ValueError('原生合同实际重链在三轮内未达到地址/字节固定点')
    loads = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
    if len(loads) != 2:
        raise ValueError('模块必须有两个段')
    payloads = []
    for seg, address, capacity, perm in zip(loads, (layout['rx'], layout['rw']),
                                           (layout['rx_capacity'], layout['rw_capacity']), (5, 6)):
        if seg['p_vaddr'] != address or seg['p_flags'] != perm or not 0 < seg['p_filesz'] <= seg['p_memsz'] <= capacity:
            raise ValueError('段地址、权限或容量错误')
        raw = seg.data()+bytes(seg['p_memsz']-seg['p_filesz'])
        name = 'module-rx.bin' if perm == 5 else 'module-rw-initialized.bin'
        (output/name).write_bytes(raw)
        payloads.append(dict(path=str(output/name), address=address, bytes=len(raw), flags=perm, sha256=sha(raw)))
    rx, rw = [(output/n).read_bytes() for n in ('module-rx.bin', 'module-rw-initialized.bin')]
    if rw != b'\xfe\xff\xff\xff'+bytes(len(rw)-4):
        raise ValueError('guard不支持此RW初始化布局')
    targets = dict(compact_start=module_symbols['af_cp_runtime_gate'], compact_hs=module_symbols['af_cp_hs_gate'],
                   compact_snapshot=module_symbols[snapshot_symbol])
    if capture_copies:
        targets['compact_copy'] = module_symbols[snapshot_symbol]
    if not native_integration:
        boot_symbols, boot = bootstrap(output/'bootstrap', len(rx), crc(rx), len(rw), targets)
    if boot_symbols['af_carve_snapshot'] != snapshot:
        raise ValueError('bootstrap最终symbol与模块配对不符')
    if before != {str(p.relative_to(ROOT)): sha(p.read_bytes()) for p in watched}:
        raise ValueError('构建期间源发生变化')
    result = dict(status='CARVE_LINK_PASS_OFFLINE_ONLY', source_sha256=before,
                  artifact=dict(path=str(module), bytes=module.stat().st_size, sha256=sha(module.read_bytes())),
                  payloads=payloads, module_symbols={k: v for k, v in module_symbols.items() if k.startswith('af_cp_')},
                  bootstrap_symbols={k: v for k, v in boot_symbols.items() if k.startswith('af_carve_')},
                  bootstrap_bytes=len(boot), bootstrap_sha256=sha(boot), snapshot_entry=snapshot,
                  capture_input=bool(capture_input), snapshot_patchsite=snapshot_patchsite,
                  capture_copies=bool(capture_copies),
                  native_capacity=native_capacity, capacity_layout=layout,
                  capacity_layout_version=layout_version,
                  reserved_bytes=(layout['rx_pages']+layout['rw_pages'])*4096,
                  cold_source_bytes=layout['rx_capacity'], cold_source_before_sha256=cold_before,
                  native_integration=native_integration,
                  capture_lifecycle=native_integration,
                  capture_symbols={k:v for k,v in capture_symbols.items() if k and not k.startswith('$')},
                  capture_regions=capture_regions,
                  factor_symbols={k: v for k, v in factor_symbols.items() if k and not k.startswith('$')},
                  factor_sha256=sha(factor_raw) if native_integration else None,
                  factor_phase_opcode=factor_opcode,
                  factor_phase_literal=boot_symbols['phase'] if native_integration else None,
                  native_contract_bytes=NATIVE_CONTRACT_BYTES if native_integration else 0,
                  native_hooks=[dict(address=a, code=code.hex()) for a, code in hooks],
                  native_contract_iterations=iterations,
                  native_asset_schema=3 if native_capacity else 1,
                  rw_statics_bytes=module_symbols['__af_carve_rw_statics_end']-layout['rw'],
                  rw_resident_bytes=len(rw),
                  copy_sites=(list(THUMB_COPY_SITES+ARM_COPY_SITES) if native_integration else
                              [0x898568, 0x4baab6, 0x4bba78, 0x4bc002] if capture_copies else []),
                  compact_copy='af_cp_copy406_gate' if capture_copies else None,
                  read_input_exported=bool(capture_input), native_input_consumers_bound=native_integration,
                  snapshot_core_symbol=snapshot_symbol,
                  RX_crc=crc(rx), phase_address=0x1a3ac60, cold_source=layout['cold'],
                  bridge_compiled=True, native_consumer_bound=native_integration,
                  native_consumers_source_bound=native_integration, full_recipe_negotiable=False,
                  guard_implementation='THUMB_ASSEMBLY_WITH_C_HOST_CONTROL_REFERENCE',
                  generated_sha256={str(p): sha(p.read_bytes()) for p in output.rglob('*')
                                    if p.is_file() and p.suffix in ('.h', '.c', '.S', '.inc', '.ld')},
                  commands=commands, target_executed=False, hardware_simulation=False, camera_io=False,
                  CP_written=False, DAT_written=False, installed=False, installable_firmware=False)
    (output/'verification.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--capture-input', action='store_true', help='只在本分支接原锁内DBC memcpy前后版本伴随')
    parser.add_argument('--capture-copies', action='store_true', help='隐含capture-input，四处原copy以BL共用永久安全gate')
    parser.add_argument('--native-capacity', action='store_true', help='固定8RX+12RW二十页，保留四页默认布局')
    parser.add_argument('--native-integration', action='store_true', help='固定22页Capture颜色接入，含13copy、四组件与Capture生命周期入口')
    args = parser.parse_args()
    result = build(args.output, args.capture_input, args.capture_copies, args.native_capacity, args.native_integration)
    print(json.dumps({k: result[k] for k in ('status', 'payloads', 'bootstrap_bytes', 'snapshot_entry')}, indent=2))
