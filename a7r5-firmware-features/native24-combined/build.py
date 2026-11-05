"""二十四槽独立离线构建；不签名、不封DAT、不接设备。"""
import argparse
import io
import inspect
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys

from elftools.elf.elffile import ELFFile
from derive import FEATURE, FORMAT, HERE, derive, load, unified_source
from stability import replace_exact
from icon_codec import native_lz77_stream

ROOT = HERE.parents[1]


def restore_icons(raw, module):
    """从已归档十二槽资源精确逆还原，随后必须核对原资源完整摘要。"""
    count, new_base, _, records, bitmap = module.layout(raw)
    if count != module.COUNT + 24:
        raise ValueError('旧十二槽图标前像不符')
    base = new_base - 48
    boundary = min(target for index, target, _ in bitmap if index < module.COUNT) - 480
    appended = sum(records[index][3] for index in range(module.COUNT, count))
    old_length = len(raw) - 48 - 480 - appended
    result = bytearray(raw[:base] + raw[new_base:boundary] + raw[boundary + 480:old_length + 528])
    struct.pack_into('<I', result, 12, module.COUNT | module.COUNT << 12)
    for index, (at, flags, *_) in records.items():
        if index >= module.COUNT:
            continue
        field, _, offset = module.payload_fields(raw, at, flags)
        struct.pack_into('<I', result, at - 48 + field + 4, offset - 480)
    return bytes(result)


def build(output, baseline, inputs_directory=None):
    checker = load(FEATURE / 'build.py', 'native24_build_checker')
    def owned_inputs():
        return {str(p.relative_to(HERE)): checker.sha(p) for p in sorted(HERE.rglob('*'))
                if p.is_file() and (p.parent == HERE or p.parent == HERE/'runtime')
                and p.suffix in ('.py','.c','.h','.json') and p.name != 'current-candidate.json'}
    owned_before = owned_inputs()
    helpers = [FEATURE/name for name in ('build.py','patches.py','unified_look.py','unified_icons.py',
                                        'selection.S','integration.S','integration.ld','menu-font.c')]
    helpers += [FORMAT/'prepare.py', FEATURE/'upstream/UPSTREAM_SNAPSHOT.json']
    external_before = {str(p.relative_to(ROOT)): checker.sha(p) for p in helpers}
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    work = output / 'work'
    changes = derive(work)
    inputs = work / 'inputs'
    inputs.mkdir()
    for name, expected in [('ap_baseline.so', 'a8d5cd444bf08a03a70aedc3cc32bdd857b89b468ac10bf8365d640e8d390d75'),
                           ('cp_baseline.bin', '8e9e26bf2e4b93fa5142e961dcf21cb0f43f8871283814be2dcfb0a694cb5a32')]:
        source = (inputs_directory or baseline / 'work/inputs') / name
        if checker.sha(source) != expected:
            raise ValueError('原厂派生基底身份不符：' + name)
        shutil.copyfile(source, inputs / name)
    record = {'schema': 'native24-runtime-build/1', 'commands': [], 'derived_files': changes,
              'stability_revision': 1, 'interaction_revision': 1, 'parameter_revision': 1, 'tabs_revision': 1,
              'DAT_generated': False, 'camera_io': False, 'installable': False}
    contract = json.loads((HERE / 'layout.json').read_text())
    record['contract'] = contract
    record['toolchain'] = {}
    for name, command in [('clang', ['clang', '--version']), ('llvm', ['/opt/homebrew/opt/llvm/bin/clang', '--version']),
                          ('lld', ['/opt/homebrew/opt/lld/bin/ld.lld', '--version']), ('python', [sys.executable, '--version'])]:
        result = subprocess.run(command, capture_output=True, text=True, check=True)
        record['toolchain'][name] = {'argv': command, 'version': result.stdout.strip()}

    def run(script, *args):
        command = [sys.executable, str(script), *map(str, args)]
        result = subprocess.run(command, capture_output=True, text=True)
        record['commands'].append({'argv': command, 'exit_code': result.returncode,
                                   'stdout': result.stdout, 'stderr': result.stderr})
        (output / 'build-progress.json').write_text(json.dumps(record, indent=2) + '\n')
        if result.returncode:
            raise RuntimeError(result.stderr + result.stdout)

    run(work / 'import/build_ap_image.py', '--output', output / 'upstream-ap')
    run(work / 'gamma/getter_gates.py')
    run(work / 'cp/build_cp.py')
    audit_path = work / 'import/module_audit.json'
    audit = json.loads(audit_path.read_text())
    cp_report = json.loads((work / 'cp/build.json').read_text())
    # 本地补丁仍逐点校验原厂指令和数据。完整前像绑定本次严格构建产物。
    patches = load(FEATURE / 'patches.py', 'native24_local_patches')
    raw_ap = (output / 'upstream-ap/appFw.so').read_bytes()
    raw_cp = (work / 'cp/cp423.NONINSTALLABLE.bin').read_bytes()
    if patches.digest(raw_ap) != json.loads((output / 'upstream-ap/ap_build.json').read_text())['AP_sha256']:
        raise ValueError('AP构建收据身份不符')
    if patches.digest(raw_cp) != cp_report['candidate_sha256']:
        raise ValueError('CP构建收据身份不符')
    patches.AP_SHA, patches.CP_SHA = patches.digest(raw_ap), patches.digest(raw_cp)
    final_ap, ap_local = patches.ap_patch(raw_ap)
    cp_folder = output / 'local-cp'
    cp_folder.mkdir()
    final_cp, cp_local = patches.cp_patch(raw_cp, cp_folder)
    (output / 'cpapp-b.bin').write_bytes(final_cp)
    (output / 'local-ap.json').write_text(json.dumps(ap_local, indent=2) + '\n')
    (output / 'local-cp.json').write_text(json.dumps(cp_local, indent=2) + '\n')
    tools = output / 'unified-tools'
    tools.mkdir()
    source = (FEATURE / 'unified_look.py').read_text()
    source = replace_exact(source, "SOURCE_SHA = '65e33ba2075bb59f65a97e6cec550bd8b1d54bac040fe28427cd3922924ffde0'",
                            "SOURCE_SHA = '" + patches.digest(final_ap) + "'")
    source = replace_exact(source, "AUDIT_SHA = '91fc50f73bef7fcb6862a16e890fde765f8055d146d7756b05f072825a1ae569'",
                            "AUDIT_SHA = '" + checker.sha(audit_path) + "'")
    source = replace_exact(source, "(0x8e983a4,'text')", f"({hex(audit['symbols']['r5_filter_menu_text'])},'text')")
    source = replace_exact(source, '0x8eb9df0', hex(audit['symbols']['r5_filter_menu_descriptor']))
    source = replace_exact(source, "struct.pack('<I',31)", "struct.pack('<I',43)")
    source = replace_exact(source, 'custom_count=12', 'custom_count=24')
    source = replace_exact(source, "'r5_filter_full_name'))", "'r5_filter_full_name','r5_filter_bank_crc','r5_filter_recovery_required','r5_filter_factory_reset_needed','r5_filter_factory_reset_done','r5_filter_recovering','r5_tune_seed','r5_tune_value','r5_tune_default','r5_tune_edit','r5_tune_reset','r5_tune_changed','r5_tune_pending_changed','r5_tune_status','r5_tune_overlay','r5_tune_observe425','r5_tune_sent425','r5_osal_msg_size'))")
    source = replace_exact(source, "(0x1a6d8cc,'dispatch'),", "(0x1a6d8cc,'dispatch'), (0x1a6df54,'parameter_dispatch'), (0x263d558,'reset'), (0x220b89c,'parameter_layout'), (0x220c830,'parameter_labels'),")
    # 原vtable的visible先经过上游包装器；附加MID会绕过原visible入口。
    source = replace_exact(source, "('r5_filter_row_available_direct','n12_available')]",
                            "('r5_filter_row_available_direct','n12_available'),('r5_filter_row_available','n12_visible')]")
    extra_calls = [(0x220c8a0,'n12_title_name',0x1bd5508), (0x220c87c,'n12_base_label',0x1bd54d8),
                   (0x220c8dc,'n12_base_icon',0x220b838)]
    extra_calls += [(0x2208e68,'n12_group_title',0x1bd54d8),
                    (0x2208f7c,'n12_list_projection',0x1bc36f8),(0x220847c,'n12_list_projection',0x1bc36f8),
                    (0x22074b4,'n12_tabs_nextrow',0x1bd7234)]
    extra_calls += [(at,'n12_tune_send',0x355882c) for at in (0x355a4a4,0x3561498,0x35613dc,0x3561364,
                    0x35612ec,0x3561274,0x35611fc,0x3561184,0x356110c)]
    extra_calls += [(0x35589d8,'n12_tune_transport_send',0x16dafc0)]
    source = replace_exact(source, "(0x2208e8c,'n12_title_name',0x1bd5508)]",
                            "(0x2208e8c,'n12_title_name',0x1bd5508),"+','.join(repr(row) for row in extra_calls)+']')
    (tools / 'unified_look.py').write_text(source)
    (tools / 'unified-look.c').write_text(unified_source())
    unified = load(tools / 'unified_look.py', 'native24_unified_builder')
    ap_path, unified_receipt = unified.build(final_ap, output / 'unified', audit_path)
    shutil.copyfile(ap_path, output / 'appFw.so')
    icons12 = load(FEATURE / 'unified_icons.py', 'native24_old_icons')
    icon_source = replace_exact((FEATURE / 'unified_icons.py').read_text(), 'ADDED=24', 'ADDED=48')
    icon_source = replace_exact(icon_source, 'range(1,13)', 'range(1,25)')
    icon_source = replace_exact(icon_source, inspect.getsource(icons12.literal_stream),
                                inspect.getsource(native_lz77_stream).replace('native_lz77_stream', 'literal_stream'))
    # 与原厂资源一致，载荷起点四字节对齐；填充不计入压缩流长度。
    icon_source = replace_exact(icon_source, '        candidate.extend(stream)\n',
                                '        candidate.extend(stream)\n        candidate.extend(bytes((-len(candidate))%4))\n')
    icon_source = replace_exact(icon_source, "'selected':selected,'pixel_sha256'",
                                "'selected':selected,'encoding':'sony-lz77-f0','pixel_sha256'")
    (tools / 'unified_icons.py').write_text(icon_source)
    icons24 = load(tools / 'unified_icons.py', 'native24_new_icons')
    icon_reports = {}
    for name, expected in icons12.SOURCES.items():
        old = FEATURE / 'verification/2026-11-03-unified-rapid/components' / Path(name).name
        original = restore_icons(old.read_bytes(), icons12)
        if patches.digest(original) != expected:
            raise ValueError('图形资源逆还原身份不符：' + name)
        candidate, proof = icons24.append_icons(original)
        (output / Path(name).name).write_bytes(candidate)
        icon_reports[name] = proof
    (output / 'unified-icons.json').write_text(json.dumps(icon_reports, indent=2) + '\n')
    stack_usage = {}
    for path in (work / 'import/objects').glob('*.su'):
        stack_usage[path.name] = path.read_text()
    (output / 'stack-usage.json').write_text(json.dumps(stack_usage, indent=2) + '\n')
    frames = {}
    for data in stack_usage.values():
        for line in data.splitlines():
            function, size, _ = line.split('\t')
            frames[function.rsplit(':', 1)[-1]] = int(size)
    chain = ['r5_stage411_child', 'r5_stage421_parameters_ready', 'r5_filter_service', 'storage',
             'r5_lut_directory_acquire', 'read_complete', 'r5_stable_publish425', 'r5_stable_read425']
    if not {'r5_stage411_child','r5_filter_service','r5_stable_publish425','r5_stable_read425'} <= frames.keys():
        raise ValueError('关键栈帧证据缺失')
    known = sum(frames.get(name, 0) for name in chain)
    if max(frames.values()) >= 16384 or known >= contract['AP_known_chain_budget']:
        raise ValueError('已知AP栈预算超出')
    if known + contract['AP_external_stack_reserve'] >= contract['AP_thread_stack']:
        raise ValueError('AP线程栈预留不足')
    if cp_report['heap_bytes'] != contract['CP_heap_bytes'] or cp_report['code_bytes'] > contract['CP_code_capacity']:
        raise ValueError('CP布局合同不符')
    if audit['bss_bytes'] > contract['AP_BSS_capacity']:
        raise ValueError('AP BSS合同不符')
    upstream_receipt = json.loads((output/'upstream-ap/ap_build.json').read_text())
    if upstream_receipt['rx_bytes'] > contract['AP_RX_capacity'] or audit['rw']+audit['bss_bytes']>0x8f00000:
        raise ValueError('AP新增代码／BSS与统一入口冲突')
    record['stack_budget'] = {'known_frames': {name: frames.get(name, 0) for name in chain},
                              'conservative_sum': known, 'external_reserve': contract['AP_external_stack_reserve'],
                              'physical_high_water_measured': False}
    elf = ELFFile(io.BytesIO(ap_path.read_bytes()))
    loads = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
    if any(max(x['p_vaddr'], y['p_vaddr']) < min(x['p_vaddr'] + x['p_memsz'], y['p_vaddr'] + y['p_memsz'])
           for i, x in enumerate(loads) for y in loads[:i]):
        raise ValueError('最终AP段重叠')
    record.update(AP_sha256=patches.digest(ap_path.read_bytes()), CP_sha256=patches.digest(final_cp),
                  AP_bss_bytes=audit['bss_bytes'], CP_code_bytes=cp_report['code_bytes'],
                  CP_heap_bytes=cp_report['heap_bytes'], module_audit_sha256=checker.sha(audit_path),
                  unified=unified_receipt, local_AP=ap_local, local_CP=cp_local,
                  AP_segments=[dict(va=s['p_vaddr'], bytes=s['p_memsz'], flags=s['p_flags']) for s in loads])
    if owned_inputs() != owned_before or any(checker.sha(ROOT/name)!=value for name,value in external_before.items()):
        raise ValueError('构建期间源文件变化，拒绝生成最终收据')
    record['owned_sources'] = owned_before
    record['external_sources'] = external_before
    record['components'] = {name: {'bytes': (output/name).stat().st_size, 'sha256': checker.sha(output/name)}
                            for name in ['appFw.so','cpapp-b.bin', *[Path(x).name for x in icons12.SOURCES]]}
    (output / 'build.json').write_text(json.dumps(record, indent=2) + '\n')
    print(json.dumps({key: record[key] for key in ('AP_sha256', 'CP_sha256', 'AP_bss_bytes', 'CP_code_bytes', 'CP_heap_bytes', 'installable')}))
    return record


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--baseline', type=Path, default=ROOT / '.local/native12-combined-baseline-01')
    parser.add_argument('--inputs', type=Path, help='直接指定含两个已锁定基底文件的目录，优先于--baseline')
    args = parser.parse_args()
    build(args.output.resolve(), args.baseline.resolve(), args.inputs.resolve() if args.inputs else None)
