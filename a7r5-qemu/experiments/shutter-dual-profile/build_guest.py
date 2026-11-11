"""从已核验的历史独立客体派生声音候选；不改默认清单或固件源。"""
import argparse
import base64
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import wave

import environment as env
from elftools.elf.elffile import ELFFile
from cpio_inputs import entries
from media_candidate import add_files, patch_property
from native_vm import dtb_properties

HERE = Path(__file__).resolve().parent
SEED = env.LAB/'build/menu417-17-oLYPDW'


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def symbol_address(work, name):
    audit = json.loads((work/'import/module_audit.json').read_text())
    path = work/'import/objects/r5_filter_runtime423.o'
    with path.open('rb') as stream:
        elf = ELFFile(stream)
        sym, = elf.get_section_by_name('.symtab').get_symbol_by_name(name)
        section = elf.get_section(sym['st_shndx']).name
        row, = [r for r in audit['sections'] if Path(r['object']).name == path.name and r['name'] == section]
        assert sym['st_value']+sym['st_size'] <= row['size']
        return int(row['va'], 16)+sym['st_value']


def build(output, candidate, restore=None, *, extra_components=None):
    record = json.loads((SEED/'final/manifest.json').read_text())
    inputs = env.verified(record)
    if inputs['initrd'].stat().st_size != 438499840 or env.digest(inputs['initrd']) != 'f1c1628fc69d0765cbed7e4fb2d729d5bce5988583a22ae4bfffb00720450b90':
        raise ValueError('独立种子完整身份不符')
    source = json.loads((candidate/'build.json').read_text())
    if (source['AP_sha256'], source['CP_sha256']) != (env.AP_SHA, env.CP_SHA):
        raise ValueError('声音组件来源不符')
    for name, expected in [('appFw.so', env.AP_SHA), ('cpapp-b.bin', env.CP_SHA)]:
        if env.digest(candidate/name) != expected:
            raise ValueError('候选组件摘要不符 '+name)
    if output.parent != env.LAB/'build' or output.exists():
        raise ValueError('必须使用新的独立build目录')
    output.mkdir(mode=0o700)
    old_work = env.LAB/'runs/verify-17-NqJEIq/runtime/work'
    old = json.loads((old_work/'import/module_audit.json').read_text())
    new = json.loads((candidate/'work/import/module_audit.json').read_text())
    old_build = json.loads((old_work.parent/'build.json').read_text())
    mapping = {v: new['symbols'][k] for k, v in old['symbols'].items() if k in new['symbols']}
    mapping[old_build['unified']['symbols']['n12_tabs_state']] = source['unified']['symbols']['n12_tabs_state']
    for name in ('refresh_wait', 'refresh_done', 'refresh_object', 'refresh_request'):
        before = symbol_address(old_work, name)
        after = symbol_address(candidate/'work', name)
        mapping[before] = after
        if name == 'refresh_request':
            mapping[before+16] = after+16
    service = (SEED/'final/native12-services.inc').read_text()
    def remap(match):
        address = int(match[1], 16)
        if not 0x8e90000 <= address < 0x8f10000:
            return match[0]
        if address not in mapping:
            raise ValueError('未绑定历史私有地址 '+hex(address))
        return hex(mapping[address])+'UL'
    service = re.sub(r'0x([0-9a-f]+)UL', remap, service)
    service = 'static void sound_observe(volatile unsigned char *);\n'+service
    marker = '    __atomic_store_n((unsigned *)out,0x4d32314eu,__ATOMIC_RELEASE);'
    assert service.count(marker) == 1
    service = service.replace(marker, '    sound_observe(out);\n'+marker)
    original_detours = 'n12_detour(0x3691104UL,n12_open);n12_detour(0x3691138UL,n12_read);n12_detour(0x3691124UL,n12_close);'
    assert service.count(original_detours) == 1
    service = service.replace(original_detours, 'sound_install_services();')
    for before, after in [('))(1,0);', '))(getenv("R5_SOUND_NO_CARD")?0:1,0);'),
                          ("))(0,0,'A');", "))(0,getenv(\"R5_SOUND_NO_CARD\")?1:0,'A');")]:
        assert service.count(before) == 1
        service = service.replace(before, after)
    service = service.replace('#include "dataflow-adapter.inc"', '#include "sound-services.inc"\n#include "dataflow-adapter.inc"')
    (output/'native12-services.inc').write_text(service)
    for name in ('dataflow-adapter.inc', 'e4-services.inc', 'menu-observe-native.c'):
        shutil.copyfile(SEED/'final'/name, output/name)
    raw = (candidate/'appFw.so').read_bytes()
    elf = ELFFile(io.BytesIO(raw))
    def code(va):
        for s in elf.iter_segments():
            if s['p_type'] == 'PT_LOAD' and s['p_vaddr'] <= va and va+16 <= s['p_vaddr']+s['p_filesz']:
                return s.data()[va-s['p_vaddr']:va-s['p_vaddr']+16]
        raise ValueError('接口地址越界')
    macros = {'SILENT_GET': 'r5ss_native_silent_get', 'SIGNALS_GET': 'r5ss_native_signals_get',
              'SOUND_COUNT': 'r5sound_count', 'PROFILE_SELECTED': 'r5sound_profile_selected',
              'PROFILE_VOLUME': 'r5sound_profile_volume', 'SOUND_SELECTED': 'r5sound_selected', 'SOUND_VOLUME': 'r5sound_volume_get'}
    shim = ''.join(f'#define {k} {hex(new["symbols"][v])}UL\n' for k,v in macros.items())
    shim += (HERE/'sound-services.inc').read_text()
    functions = {'r5_native_fsys_open': 'sound_fs_open', 'r5_native_fsys_read': 'sound_fs_read', 'r5_native_fsys_close': 'sound_fs_close',
                 'r5_native_fsys_find_first': 'sound_find_first', 'r5_native_fsys_find_next': 'sound_find_next', 'r5sound_log': 'sound_log',
                 'r5ss_native_first_owner17': 'sound_owner', 'r5ss_bridge_bind_epoch': 'sound_epoch_bind', 'r5ss_bridge_active': 'sound_active',
                 'r5ss_bridge_diagnostics': 'sound_diagnostics', 'r5ss_backend_first_authorize': 'sound_authorize_first',
                 'r5ss_backend_resume': 'sound_resume', 'r5ss_backend_stage': 'sound_stage', 'r5ss_backend_install': 'sound_install',
                 'r5ss_backend_unload': 'sound_unload', 'r5ss_backend_poll': 'sound_poll', 'r5ss_backend_stop': 'sound_stop',
                 'r5ss_backend_authorize': 'sound_authorize', 'r5ss_backend_start': 'sound_start'}
    detours = []
    for i,(name, target) in enumerate(functions.items()):
        at = new['symbols'][name]
        expected = code(at)
        values = ','.join(hex(n) for n in expected)
        detours.append(f'{{const unsigned char expected[16]={{{values}}};if(memcmp((void *)(n12_base+{hex(at)}UL),expected,16))__builtin_trap();n12_detour({hex(at)}UL,{target});}}')
    shim = shim.replace('SOUND_INSTALL_DETOURS', '\n'.join(detours))
    (output/'sound-services.inc').write_text(shim)
    command = json.loads((SEED/'base/build-receipt.json').read_text())['commands'][0]
    command = [str(output/Path(arg).name) if arg in (str(SEED/'base/menu-observe-native.c'), str(SEED/'base/menu-observe-a7r5-baseline.so')) else arg for arg in command]
    command[1:1] = ['-I', str(candidate/'work/import'), '-I', str(output)]
    compiled = subprocess.run(command, capture_output=True, text=True)
    (output/'compiler.log').write_text(compiled.stdout+compiled.stderr)
    if compiled.returncode:
        raise RuntimeError('声音模拟库编译失败：'+compiled.stderr)
    replacements = {'usr/lib/appFw.so': raw, 'cp/cpapp-b.bin': (candidate/'cpapp-b.bin').read_bytes(),
                    'simulation/menu-observe-a7r5-baseline.so': (output/'menu-observe-a7r5-baseline.so').read_bytes(),
                    'simulation/firmware-version.dat4': b'\x00\x04'}
    for name in ('image_00_23_IPSX.uxc', 'image_00_32_IPSX.uxc'):
        replacements['usr/share/app/'+name] = (candidate/name).read_bytes()
    for name, data in (extra_components or {}).items():
        if not (re.fullmatch(r'usr/share/app/string_[a-z]+_(horizontal|vertical)\.uxc', name)
                or name in ('usr/lib/libmpr.so', 'simulation/R5NATIVE.BIN')) or name in replacements:
            raise ValueError('组合客体附加组件范围不符')
        replacements[name] = data
    converter = load('sound_fixture_converter', env.ROOT/'a7r5-firmware-features/photo-electronic-shutter-sound/host/prepare_sound.py')
    additions = {}
    helper = output/'sound-store-export'
    helper_command = ['/opt/homebrew/opt/llvm/bin/clang','--target=aarch64-linux-gnu',
                      '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld','-nostdlib','-O2','-fno-stack-protector',
                      '-no-pie','-Wl,-e,_start','-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',str(HERE/'store-export.c'),
                      *[str(env.LAB/'sdk/lib'/n) for n in ('libc-2.25.so','ld-2.25.so')],'-o',str(helper)]
    subprocess.run(helper_command,check=True)
    additions['simulation/sound-store-export']=helper.read_bytes()
    restored={}
    if restore:
        for name,encoded in json.loads(restore.read_text()).items():
            if not (name in ('R5SOUND.PRO','R5SOUND.IDX') or re.fullmatch(r'R5SN_[0-9a-f]{64}\.R5S',name)):
                raise ValueError('恢复文件名越界')
            data=base64.b64decode(encoded,validate=True)
            if not data or len(data)>500000:raise ValueError('恢复文件长度越界')
            additions['simulation/restore-'+name]=data
            restored[name]=hashlib.sha256(data).hexdigest()
    for index, name in enumerate(('机械咔嗒', '电子轻响')):
        wav, r5s = output/(name+'.WAV'), output/(name+'.R5S')
        with wave.open(str(wav), 'wb') as f:
            f.setparams((1, 2, 24000, 0, 'NONE', 'not compressed'))
            samples = [int(12000*(1-i/1920)*((i//(7+index*3))%2*2-1)) for i in range(1920)]
            f.writeframes(struct.pack('<1920h', *samples))
        converter.convert_file(wav, r5s)
        additions['simulation/'+r5s.name] = r5s.read_bytes()
    builder = load('sound_cpio_builder', env.LAB/'tools/build-guest.py')
    intermediate = output/'replaced.cpio'
    builder.replace_cpio(inputs['initrd'], intermediate, replacements)
    archive = output/'menu.cpio'
    add_files(intermediate, archive, additions)
    before, after = entries(inputs['initrd']), entries(archive)
    assert set(after)-set(before) == set(additions)
    changed = {k for k in before if before[k] != after[k]}
    expected_changes = {name for name, data in replacements.items()
                        if before[name]['sha256'] != hashlib.sha256(data).hexdigest()}
    assert changed == expected_changes
    assert all(after[name]['sha256'] == hashlib.sha256(data).hexdigest() for name,data in replacements.items())
    for name in changed:
        assert before[name]['metadata'] == after[name]['metadata']
    dtb = inputs['dtb'].read_bytes()
    props = dtb_properties(dtb)
    bootargs = re.sub(rb'ramdisk_size=\d+', b'ramdisk_size='+str((archive.stat().st_size+1023)//1024).encode(), props[('/chosen', 'bootargs')])
    dtb = patch_property(dtb, '/chosen', 'bootargs', bootargs)
    dtb = patch_property(dtb, '/chosen', 'linux,initrd-end', (0x440000000+archive.stat().st_size).to_bytes(8,'big'))
    (output/'virt.dtb').write_bytes(dtb)
    shutil.copyfile(candidate/'cpapp-b.bin', output/'cpapp-b.bin')
    shutil.copyfile(candidate/'build.json', output/'candidate-build.json')
    shutil.copyfile(SEED/'final/R5NATIVE.BIN', output/'R5NATIVE.BIN')
    cp = load('shutter_cp_driver', env.LAB/'experiments/native24-preview-idle/cp_service.py')
    receiver = cp.build(output/'cp-receiver')
    cp_source = output/'cp-receiver/cp-receiver.c'
    text = cp_source.read_text()
    assert text.count('0x1195271') == 1
    text = text.replace('0x1195271', hex(int(json.loads((candidate/'work/cp/build.json').read_text())['symbols']['r5_cp_stage413_consume'],16)))
    assert text.count('    boot_copy();') == 1
    text = text.replace('    boot_copy();', '    /* 本侧车直接加载CP原始字节与零初始化RAM，不执行旧版固定地址mapper；不声称完整CP启动。 */')
    cp_source.write_text(text)
    cmd = json.loads((output/'cp-receiver/build.json').read_text())['command']
    subprocess.run(cmd, check=True)
    env.save(output/'cp-receiver/sound-adaptation.json', dict(source=env.fact(cp_source), elf=env.fact(receiver),
             command=cmd, old_mapper_called=False, full_CP_boot=False))
    inputs.update(initrd=archive, dtb=output/'virt.dtb')
    record.update(schema='r5-sound-dual-qemu/1', firmware='4.00-derived-sound-candidate', AP_sha256=env.AP_SHA, CP_sha256=env.CP_SHA,
                  files={k:env.fact(v) for k,v in inputs.items()}, readonly_AP_state_bytes=2400,
                  loading_inputs={k:env.fact(v) for k,v in {'cp':output/'cpapp-b.bin', 'receiver':receiver, 'bin':output/'R5NATIVE.BIN'}.items()},
                  candidate_build=env.fact(output/'candidate-build.json'), package_source={'version':'双组声音候选'},
                  changed_entries=sorted(changed), added_entries=sorted(additions), all_other_entries_identical=True,
                  restore_files=restored,
                  original_components_modified=True,
                  original_components_change_scope='independent guest AP/CP replaced with exact candidate bytes; firmware source files unchanged',
                  sound_backend='test-only virtual audio; no hardware playback proof', audio_detours=functions,
                  default_manifest_modified=False, DAT_generated=False, camera_io=False)
    env.save(output/'manifest.json', record)
    env.save(output/'sound-service-build.json', dict(command=command, helper_command=helper_command, detours=functions, candidate=str(candidate), source_files={str(p):env.digest(p) for p in HERE.iterdir() if p.is_file()}))
    print(output/'manifest.json', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--candidate', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--restore', type=Path)
    args = parser.parse_args()
    build(args.output.resolve(), args.candidate.resolve(),args.restore.resolve() if args.restore else None)
