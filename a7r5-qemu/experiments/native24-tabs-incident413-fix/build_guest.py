"""固定十二槽研究客体派生24槽，严格核对唯一变更集合及模块符号。"""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import base64
import hashlib
import struct
import zlib
from elftools.elf.elffile import ELFFile

import environment as env
from cpio_inputs import entries
from media_candidate import extract, patch_property
from native_vm import dtb_properties


def map_service(text, old, new):
    def address(match):
        value = int(match.group(1), 16)
        if not 0x8e90000 <= value < 0x8f00000:
            return match.group(0)
        sections = [row for row in old['sections'] if int(row['va'], 16) <= value < int(row['va'], 16) + row['size']]
        if len(sections) != 1:
            raise ValueError('旧采样地址无唯一源节：' + hex(value))
        section = sections[0]
        other = [row for row in new['sections'] if Path(row['object']).name == Path(section['object']).name and row['name'] == section['name']]
        if len(other) != 1:
            raise ValueError('新采样地址无唯一源节：' + section['name'])
        delta = value - int(section['va'], 16)
        if delta >= other[0]['size']:
            raise ValueError('采样地址超新节范围')
        return hex(int(other[0]['va'], 16) + delta) + match.group(2)
    return re.sub(r'0x([0-9a-f]+)(UL|ul|u)', address, text)


def build(output, runtime, empty=False):
    if empty:raise ValueError('本诊断只接受实机正式十二款BIN')
    source = env.LAB / 'build/native12-unified-rapid-20261103-01/manifest.json'
    record = json.loads(source.read_text())
    inputs = env.parent.verified(record)
    if (record['AP_sha256'], record['CP_sha256']) != (env.parent.UNIFIED_AP_SHA, env.parent.CP_SHA):
        raise ValueError('父候选不符')
    output = output.absolute()
    if output.parent != env.LAB / 'build' or output.exists():
        raise ValueError('必须使用新的独立build目录')
    build_record = json.loads((runtime / 'build.json').read_text())
    if (build_record['AP_sha256'], build_record['CP_sha256']) != (env.AP_SHA, env.CP_SHA):
        raise ValueError('24槽输入构建身份不符')
    if any(env.digest(runtime/name) != expected for name, expected in env.ICON_SHAS.items()):
        raise ValueError('F0图标固定输入不符')
    output.mkdir(mode=0o700)
    old_audit = json.loads((env.ROOT / '.local/native12-combined-baseline-01/work/import/module_audit.json').read_text())
    new_audit = json.loads((runtime / 'work/import/module_audit.json').read_text())
    # LLVM会重排同一合并BSS中的局部变量，必须使用本次对象的符号偏移。
    obj = runtime / 'work/import/objects/r5_filter_runtime423.o'
    observed = {}
    with obj.open('rb') as stream:
        elf = ELFFile(stream)
        for name, size in [('refresh_wait',4),('refresh_done',4),('refresh_object',8),('refresh_request',32),
                           ('native_refresh_pending',4),('native_refresh_object',8)]:
            symbols = [s for s in elf.get_section_by_name('.symtab').iter_symbols() if s.name==name]
            if len(symbols)!=1 or symbols[0]['st_size']!=size:
                raise ValueError('只读局部符号不唯一或大小变化：'+name)
            symbol = symbols[0]
            section = elf.get_section(symbol['st_shndx'])
            placed = [s for s in new_audit['sections'] if Path(s['object']).name==obj.name and s['name']==section.name]
            if len(placed)!=1 or symbol['st_value']+size>placed[0]['size']:
                raise ValueError('只读局部符号布局不符：'+name)
            observed[name] = {'address':int(placed[0]['va'],16)+symbol['st_value'],
                              'section':section.name,'offset':symbol['st_value'],'bytes':size}
    env.save(output/'observer-layout.json',{'symbols':observed,'object_sha256':env.digest(obj),
                                           'object_base64':base64.b64encode(obj.read_bytes()).decode()})
    for name in ('appFw.so', 'cpapp-b.bin', 'image_00_23_IPSX.uxc', 'image_00_32_IPSX.uxc', 'build.json'):
        shutil.copyfile(runtime / name, output / name)
    shutil.copyfile(runtime / 'work/import/module_audit.json', output / 'module_audit.json')
    bin_source = env.ROOT / 'a7r5-firmware-features/native24-combined/releases/4.13/R5NATIVE.BIN'
    if env.digest(bin_source) != env.BIN_SHA:
        raise ValueError('合成测试BIN身份不符')
    if empty:
        header=bytearray(bin_source.read_bytes()[:128])
        struct.pack_into('<III',header,16,128,0,0)
        struct.pack_into('<I',header,112,0)
        struct.pack_into('<I',header,112,zlib.crc32(header))
        if hashlib.sha256(header).hexdigest()!=env.EMPTY_BIN_SHA:
            raise ValueError('空库固定身份不符')
        (output/'R5NATIVE.BIN').write_bytes(header)
    else:
        shutil.copyfile(bin_source, output / 'R5NATIVE.BIN')
    service = map_service((env.OLD / 'native12-services.inc').read_text(), old_audit, new_audit)
    service = service.replace('n<=12;', 'n<=24;')
    for before, after in [('out+1184', 'out+2240'), ('out+1188', 'out+2244'), ('out+1192', 'out+2248'),
                          ('out+1200', 'out+2256'), ('out+1208', 'out+2264'), ('out+1224', 'out+2280'),
                          ('out[1228+i]', 'out[2284+i]'), ('out+1252', 'out+2308')]:
        service = service.replace(before, after)
    for offset, name, cast, delta in [(2240,'refresh_wait','unsigned',0),(2244,'refresh_done','unsigned',0),
                                     (2248,'refresh_object','unsigned long',0),(2256,'refresh_request','unsigned long',16)]:
        pattern = rf'^    \*\(volatile {cast} \*\)\(out\+{offset}\)=.*;$'
        address = hex(observed[name]['address']+delta)+'UL'
        rhs = 'n12_base+'+address if delta else f'*(volatile {cast} *)(n12_base+{address})'
        replacement = f'    *(volatile {cast} *)(out+{offset})={rhs};'
        service, count = re.subn(pattern,lambda _:replacement,service,flags=re.MULTILINE)
        if count!=1:
            raise ValueError('只读刷新字段前像不符：'+name)
    marker = '    __atomic_store_n((unsigned *)out,0x4d32314eu,__ATOMIC_RELEASE);'
    if service.count(marker)!=1:
        raise ValueError('只读状态发布前像不符')
    extra = f"    *(volatile unsigned *)(out+2320)=((unsigned(*)(void))(n12_base+{hex(new_audit['symbols']['r5_filter_native_inflight'])}UL))();\n"
    extra += f"    *(volatile unsigned *)(out+2324)=((unsigned(*)(void))(n12_base+{hex(new_audit['symbols']['r5_filter_recovery_required'])}UL))();\n"
    extra += '    unsigned focus=*(unsigned *)((void *(*)(void))(n12_base+0x28a87e8UL))();\n'
    extra += '    unsigned slot=focus-0x1610u<24?focus-0x1610u+1:0;\n'
    extra += '    *(volatile unsigned *)(out+2328)=slot;\n'
    extra += f"    *(volatile unsigned *)(out+2332)=((unsigned(*)(void))(n12_base+{hex(new_audit['symbols']['r5_tune_status'])}UL))();\n"
    for field, symbol in [(2336,'r5_tune_value'),(2368,'r5_tune_default')]:
        extra += f"    for(unsigned i=0;i<8;i++){{int value=(int)0x80000000u;((int(*)(unsigned,unsigned,int *))(n12_base+{hex(new_audit['symbols'][symbol])}UL))(slot,i,&value);*(volatile int *)(out+{field}+4*i)=value;}}\n"
    extra += f"    *(volatile unsigned *)(out+2400)=slot?((unsigned(*)(unsigned))(n12_base+{hex(new_audit['symbols']['r5_tune_changed'])}UL))(slot):0;\n"
    tabs = build_record['unified']['symbols']['n12_tabs_state']
    extra += f"    for(unsigned i=0;i<9;i++)*(volatile unsigned *)(out+2404+4*i)=((unsigned(*)(unsigned))(n12_base+{hex(tabs)}UL))(i);\n"
    extra += '    unsigned screen=0xffffffffu;if(captured_manager && *(volatile unsigned long *)captured_manager==n12_base+0x58d2fb8UL)screen=*(volatile unsigned *)(captured_manager+0x3b8);\n'
    extra += '    *(volatile unsigned *)(out+2440)=screen;\n'
    service = service.replace(marker, extra+marker)
    (output / 'native12-services.inc').write_text(service)
    trace = (env.OLD / 'e4-trace.inc').read_text()
    # 私有页对象池已移除；同时移除其未安装的旧观察函数，保留原生E4追踪。
    first = trace.index('static void *n12_ui_original;')
    last = trace.index('static unsigned long n12_trace_enqueue', first)
    trace = trace[:first] + trace[last:]
    start = trace.index('    const unsigned char *entry=')
    end = trace.index('\n}', start)
    trace = trace[:start] + '    /* 原私有页不注册，不装其旧入口跳板。 */' + trace[end:]
    trace = map_service(trace, old_audit, new_audit)
    for name, cast, field in [('native_refresh_pending','unsigned','serial'),('native_refresh_object','unsigned long','exact')]:
        pattern = rf'^    {cast} {field}=.*;$'
        replacement = f"    {cast} {field}=*(volatile {cast} *)(n12_base+{hex(observed[name]['address'])}UL);"
        trace, count = re.subn(pattern,lambda _:replacement,trace,flags=re.MULTILINE)
        if count!=1:
            raise ValueError('原E4只读追踪前像不符：'+field)
    (output / 'e4-trace.inc').write_text(trace)
    for name in ('e4-services.inc',):
        shutil.copyfile(env.OLD / name, output / name)
    # 数据流模型来源不变，重新编译原观察库，仅更换明确的采样／传输绑定。
    parent_dir = source.parent
    for name in ('dataflow-adapter.inc', 'hold-frequency'):
        shutil.copyfile(parent_dir / name, output / name)
    original = (parent_dir / 'menu-observe-native.c').read_text()
    (output / 'menu-observe-native.c').write_text(original)
    receipt = json.loads((parent_dir / 'service-build.json').read_text())
    command = [str(output / 'menu-observe-native.c') if value == str(parent_dir / 'menu-observe-native.c') else
               str(output / 'menu-observe-a7r5-baseline.so') if value == str(parent_dir / 'menu-observe-a7r5-baseline.so') else value
               for value in receipt['command']]
    result = subprocess.run(command, capture_output=True, text=True)
    (output / 'compiler.log').write_text(result.stdout + result.stderr)
    if result.returncode:
        raise RuntimeError(result.stderr)
    from cp_service import build as receiver_build
    receiver = receiver_build(output / 'cp-receiver')
    spec = importlib.util.spec_from_file_location('native24_cpio_rebuild', env.LAB / 'tools/build-guest.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    replacements = {'usr/lib/appFw.so': (output / 'appFw.so').read_bytes(),
                    'cp/cpapp-b.bin': (output / 'cpapp-b.bin').read_bytes(),
                    'simulation/R5NATIVE.BIN': (output / 'R5NATIVE.BIN').read_bytes(),
                    'simulation/menu-observe-a7r5-baseline.so': (output / 'menu-observe-a7r5-baseline.so').read_bytes()}
    for name in ('image_00_23_IPSX.uxc', 'image_00_32_IPSX.uxc'):
        replacements['usr/share/app/' + name] = (output / name).read_bytes()
    candidate = output / 'menu.cpio'
    module.replace_cpio(inputs['initrd'], candidate, replacements)
    before, after = entries(inputs['initrd']), entries(candidate)
    # 父客体已含这份正式十二款BIN，诊断必须保留其逐字节身份。
    unchanged = {'simulation/R5NATIVE.BIN'}
    if before['simulation/R5NATIVE.BIN']['sha256'] != env.BIN_SHA:
        raise ValueError('父客体正式十二款BIN身份不符')
    changed = set(replacements) - unchanged
    if before.keys() != after.keys() or {key for key in before if before[key] != after[key]} != changed:
        raise ValueError('实机十二款诊断客体变更集合不符')
    for key in replacements:
        if before[key]['metadata'] != after[key]['metadata']:
            raise ValueError('客体元数据变化')
        if after[key]['bytes'] != len(replacements[key]) or after[key]['sha256'] != hashlib.sha256(replacements[key]).hexdigest():
            raise ValueError('客体目标内容不符：'+key)
    dtb = inputs['dtb'].read_bytes()
    props = dtb_properties(dtb)
    args = re.sub(rb'ramdisk_size=\d+', b'ramdisk_size=' + str((candidate.stat().st_size + 1023) // 1024).encode(), props[('/chosen', 'bootargs')])
    dtb = patch_property(dtb, '/chosen', 'bootargs', args)
    dtb = patch_property(dtb, '/chosen', 'linux,initrd-end', (0x440000000 + candidate.stat().st_size).to_bytes(8, 'big'))
    (output / 'virt.dtb').write_bytes(dtb)
    inputs.update(initrd=candidate, dtb=output / 'virt.dtb')
    parent_package = record.get('package_source')
    for key in ('font_patch', 'e4_menu_patch', 'unified_look_patch', 'unified_icons',
                'base_AP_sha256', 'resources_identical_to_package'):
        record.pop(key, None)
    record.update(schema='native24-tabs-incident413-fix/1', AP_sha256=env.AP_SHA, CP_sha256=env.CP_SHA, icon_sha256=env.ICON_SHAS,
                  native24_build=env.fact(output / 'build.json'), files={key: env.fact(value) for key, value in inputs.items()},
                  loading_inputs={key: env.fact(value) for key, value in {'cp': output / 'cpapp-b.bin', 'receiver': receiver, 'bin': output / 'R5NATIVE.BIN'}.items()},
                  readonly_AP_state_bytes=2444, synthetic_recipes=False, actual_recipes=True, recipe_set='installed12', parent_manifest=env.fact(source),
                  component_override='exact 4.13 AP/CP; installed twelve production recipes; no firmware changes',
                  package_source={'version': '创意外观Tab研究候选（未封包）', 'DAT_generated': False, 'default_template_parent': parent_package},
                  native_ui_trace=False, service_changes=sorted(changed))
    env.save(output / 'manifest.json', record)
    env.save(output / 'service-build.json', {'command': command, 'exit_code': result.returncode,
        'old_audit': env.digest(env.ROOT / '.local/native12-combined-baseline-01/work/import/module_audit.json'),
        'new_audit': env.digest(runtime / 'work/import/module_audit.json'),
        'all_other_entries_identical': True, 'changed_entries': sorted(changed), 'unchanged_replacements': sorted(unchanged),
        'sources': {name: env.fact(output / name) for name in ('native12-services.inc', 'e4-trace.inc', 'e4-services.inc', 'dataflow-adapter.inc')}})
    return output / 'manifest.json'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--runtime', type=Path, required=True)
    parser.add_argument('--empty',action='store_true',help='仅使用固定摘要的合法空库，不注入运行状态')
    args = parser.parse_args()
    print(build(args.output, args.runtime.resolve(),args.empty))
