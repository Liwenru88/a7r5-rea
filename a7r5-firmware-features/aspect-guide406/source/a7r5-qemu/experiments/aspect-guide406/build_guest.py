"""构建独立菜单模拟库和辅助程序，只向源客体增加明确列出的实验文件。"""
import argparse
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import subprocess
import sys

from environment import LAB, AP_SHA, SOURCE_SHA, digest, fact
sys.path.insert(0, str(LAB/'tools'))
from cpio_inputs import entries
from media_candidate import add_files, extract, patch_property
from native_vm import dtb_properties
from elftools.elf.elffile import ELFFile
from virtual_fat import make_fixture, read_files


def identity_fixture(version):
    if (version['major'], version['minor'], version['model'], version['region']) != (4, 6, 0x11030080, 0):
        raise ValueError('版本提供者输入与已验签包头不一致')
    raw = bytearray(make_fixture())
    expected = {}
    for index, (name, value) in enumerate((('DAT2', version['model']), ('DAT3', version['region']))):
        cluster = 3+index
        for fat_start in (512, 33*512):
            struct.pack_into('<H', raw, fat_start+cluster*2, 0xffff)
        entry = bytearray(32)
        entry[:11] = name.ljust(11).encode()
        entry[11] = 0x20
        struct.pack_into('<HI', entry, 26, cluster, 4)
        base = 65*512+(index+1)*32
        raw[base:base+32] = entry
        contents = struct.pack('<I', value)
        base = (97+cluster-2)*512
        raw[base:base+4] = contents
        expected['/'+name] = contents
    files = read_files(bytes(raw))
    if any(files.get(name) != data for name, data in expected.items()):
        raise ValueError('版本标识 FAT 独立读取不符')
    # 原厂读取两个字节，再将高字节和低字节分别按 BCD 转换。
    bcd = lambda value: (value//10 << 4) | value % 10
    dat4 = bytes((bcd(version['minor']), bcd(version['major'])))
    return bytes(raw), dat4


def simulator_variant(raw):
    if hashlib.sha256(raw).hexdigest() != 'c945594d84c156be6227df631381095ad1fae8495e8dd152bca023a6b5a1a5f0':
        raise ValueError('IMDB 前像不符')
    image = ELFFile(io.BytesIO(raw))
    segments = [s for s in image.iter_segments() if s['p_type'] == 'PT_LOAD']
    relocations = {}
    for section in image.iter_sections():
        if section['sh_type'] == 'SHT_RELA':
            for rel in section.iter_relocations():
                if rel['r_info_type'] == 1027:
                    relocations[rel['r_offset']] = rel['r_addend']

    def offset(address):
        for segment in segments:
            if segment['p_vaddr'] <= address < segment['p_vaddr']+segment['p_filesz']:
                return segment['p_offset']+address-segment['p_vaddr']
        raise ValueError('IMDB 地址越界')

    target = bytearray(raw)
    changed = []
    names = {'libResourceBluetooth.so': 0xffffffbf, 'libInfraBluetooth.so': 0xffffff9f,
             'libInfraBluetoothWoLEBoot.so': 0x20, 'libInfraBluetoothLowEnergy.so': 0x7fffffff,
             'libInfraBluetoothClassic.so': 0x7fffffff,
             'libUsbBusPower.so': 0xffffffbf, 'libInfraUsbCmn.so': 0x7fffffff,
             'libUsbControl.so': 0xffffff9f, 'libBusPower.so': 0xffffff9f,
             # Hotplug_Init 同步调用已排除的 USB 控制服务，不能保留半套硬件链路。
             'libHotplug.so': 0xffffff9f}
    for i in range(232):
        address = 0x1dc40+i*72
        base = offset(address)
        if struct.unpack_from('<I', raw, base)[0] == 40:
            break
        pointer = relocations.get(address+16, struct.unpack_from('<Q', raw, base+16)[0])
        if not pointer:
            continue
        start = offset(pointer)
        name = raw[start:raw.index(b'\0', start)].decode()
        if name not in names:
            continue
        mask = struct.unpack_from('<I', raw, base+8)[0]
        if mask != names[name]:
            raise ValueError('未模拟硬件模块的 qemu 目标位前像不符')
        struct.pack_into('<I', target, base+8, mask & ~2)
        changed.append({'module': name, 'VA': hex(address+8),
                        'before': mask, 'after': mask & ~2, 'file_offset': base+8})
    if {row['module'] for row in changed} != set(names):
        raise ValueError('硬件加载适配的数据库集合不完整')
    allowed = {row['file_offset'] for row in changed}
    if any(a != b and i not in allowed for i, (a, b) in enumerate(zip(raw, target))):
        raise ValueError('qemu 目标位以外的数据库内容变化')
    return bytes(target), changed


def build(source, boot_manifest, output):
    source, output = source.absolute(), output.absolute()
    if not output.is_relative_to(LAB/'build') or digest(source/'source.cpio') != SOURCE_SHA:
        raise ValueError('输出越界或源客体身份不符')
    output.mkdir(parents=True, exist_ok=False)
    record = json.loads((source/'source-manifest.json').read_text())
    native = LAB/'source/guest'
    glibc_names = ['libc-2.25.so', 'libdl-2.25.so', 'libpthread-2.25.so', 'ld-2.25.so']
    glibc = [LAB/'sdk/lib'/name for name in glibc_names]
    for path in glibc:
        if digest(path) != record['files']['lib/'+path.name]['sha256']:
            raise ValueError('SDK 与当前包 glibc 内容不一致：' + path.name)
    wanted = ['usr/lib/libIMDB.so', 'usr/lib/libbackup.so', 'usr/lib/libosal_uipc.so',
              'usr/lib/libosal_utm.so']
    libraries = extract(source/'source.cpio', wanted)
    for name, data in libraries.items():
        with (output/Path(name).name).open('xb') as stream:
            stream.write(data)
    modified_db, db_changes = simulator_variant(libraries['usr/lib/libIMDB.so'])
    with (output/'libIMDB-menu-qemu.so').open('xb') as stream:
        stream.write(modified_db)

    # 复用已有构建配方的局部源码生成；不调用会更新默认清单的 main。
    gui = ('static void aspect406_observe(void);\n'
           'static unsigned int a7r5_native_pending,a7r5_native_seen_menu,a7r5_native_key_down;\n'
           'static void a7r5_native_reentry_poll(void);\n')+(native/'a7r5-gui.inc').read_text()
    substitutions = {
        '    a7r5_privacy_notice_poll();':
        '    a7r5_privacy_notice_poll();\n    aspect406_observe();',
        '    record("A7R5_MENU_INIT_RETURN ","original rep_menu_controller init completed");':
        '    __atomic_store_n(&a7r5_native_seen_menu,1,__ATOMIC_RELEASE);\n    record("A7R5_MENU_INIT_RETURN ","original rep_menu_controller init completed");',
        '    return r;\n}\nstatic void a7r5_open_screen':
        '    a7r5_native_reentry_poll();\n    return r;\n}\nstatic void a7r5_open_screen',
        '    record("A7R5_GUI_PROBES ",':
        '    a7r5_native_install_boot_exit(base);\n    record("A7R5_GUI_PROBES ",',
    }
    for before, after in substitutions.items():
        if gui.count(before) != 1:
            raise ValueError('GUI 构建配方前像不唯一')
        gui = gui.replace(before, after)
    (output/'a7r5-gui.inc').write_text(gui)
    observer = ('static void a7r5_native_install_boot_exit(unsigned long);\n'
                'static int a7r5_native_key_received(unsigned int,void *);\n'
                'static void a7r5_native_reentry_poll(void);\n')+(native/'menu-observe-a7r5-baseline.c').read_text()
    observer = observer.replace('#include "a7r5-gui.inc"',
        '#include "aspect-guide406.inc"\n#include "a7r5-gui.inc"\n#include "native-menu-reentry.inc"')
    anchor = '        if (getenv("A7R5_SKIP_BT_WRAPPER")) patch_a7r5_bluetooth(symbol);'
    if observer.count(anchor) != 1:
        raise ValueError('AP 初始化窗口前像不唯一')
    observer = observer.replace(anchor,
        '        if (getenv("A7R5_ASPECT_GUIDE406_UNLOCK")) aspect406_install(symbol);\n'+anchor)
    (output/'aspect-guide406.inc').write_bytes((Path(__file__).parent/'aspect-guide406.inc').read_bytes())
    needle = '    int result = real_rcv_msg_tmo(id, message, timeout);'
    if observer.count(needle) != 1:
        raise ValueError('原厂按键接收窗口前像不唯一')
    observer = observer.replace(needle, '''    int result;
    for (;;) {
        result=real_rcv_msg_tmo(id,message,timeout);
        if (result || !message || !*message || !a7r5_native_key_received(id,*message))break;
        real_free_msg(id,*message);*message=0;
    }''')
    (output/'menu-observe-native.c').write_text(observer)
    compiler = '/opt/homebrew/opt/llvm/bin/clang'
    linker = '/opt/homebrew/opt/lld/bin/ld.lld'
    common = [compiler, '--target=aarch64-linux-gnu', '--ld-path='+linker, '-nostdlib',
              '-O2', '-mno-outline-atomics', '-fno-stack-protector', '-Wl,--no-undefined',
              '-I', str(output), '-I', str(native)]
    commands = []
    compiled_sources = ['capid-service.c', 'sa-address-service.c', 'hdmi-format-service.c',
                        'dmm-service.c', 'gpe-raster.c', 'gpe-sprite.c', 'sony-lz77.c',
                        'headless-osd-a7r5.c', 'a7r5-services.c']
    so = output/'menu-observe-a7r5-baseline.so'
    commands.append(common+['-shared', '-fPIC', '-Wl,-soname,'+so.name,
        str(output/'menu-observe-native.c')]+[str(native/name) for name in compiled_sources]+
        [str(path) for path in glibc]+['-o', str(so)])
    additions = {'simulation/'+so.name: so}
    helper_links = {'seed-power-on': ['libbackup.so', 'libosal_uipc.so', 'libosal_utm.so'],
                    'seed-date-clock': ['libosal_uipc.so', 'libosal_utm.so'],
                    'seed-indicator-config': ['libbackup.so', 'libosal_uipc.so', 'libosal_utm.so'],
                    'inject-key': ['libosal_uipc.so', 'libosal_utm.so'],
                    'inspect-date-clock': ['libosal_uipc.so', 'libosal_utm.so'],
                    'seed-date-clock406': ['libosal_uipc.so', 'libosal_utm.so'],
                    'headless-osd-export': []}
    for name, dependencies in helper_links.items():
        path = output/name
        helper_source = (Path(__file__).parent/(name+'.c') if name in ('inspect-date-clock', 'seed-date-clock406')
                         else native/(name+'.c'))
        commands.append(common+['-no-pie', '-Wl,-e,_start',
            '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1', str(helper_source), '-Wl,--no-as-needed']+
            [str(output/lib) for lib in dependencies]+['-Wl,--allow-shlib-undefined']+
            [str(p) for p in glibc]+['-o', str(path)])
        additions['simulation/'+name] = path
    for index, command in enumerate(commands):
        result = subprocess.run(command, capture_output=True, timeout=60)
        (output/f'compiler-{index:02d}.log').write_bytes(result.stdout+result.stderr)
        if result.returncode:
            raise RuntimeError('交叉编译失败，见 '+str(output/f'compiler-{index:02d}.log'))
    additions['simulation/libIMDB-menu-qemu.so'] = output/'libIMDB-menu-qemu.so'
    version = json.loads((source/'version-source.json').read_text())
    if version['dat_sha256'] != record['dat_sha256']:
        raise ValueError('版本标识来自另一个 DAT')
    identity, dat4 = identity_fixture(version)
    for name, contents in (('firmware-identity.fat', identity), ('firmware-version.dat4', dat4)):
        path = output/name
        with path.open('xb') as stream:
            stream.write(contents)
        additions['simulation/'+name] = path
    candidate = output/'menu.cpio'
    add_files(source/'source.cpio', candidate, {name: path.read_bytes() for name, path in additions.items()})
    before, after = entries(source/'source.cpio'), entries(candidate)
    if set(after)-set(before) != set(additions) or any(after.get(k) != v for k, v in before.items()):
        raise ValueError('原归档条目内容或元数据改变')
    manifest = json.loads(boot_manifest.read_text())
    raw = (LAB/manifest['files']['dtb']['path']).read_bytes()
    props = dtb_properties(raw)
    import re
    bootargs = re.sub(rb'ramdisk_size=\d+', b'ramdisk_size='+str((candidate.stat().st_size+1023)//1024).encode(), props[('/chosen', 'bootargs')])
    raw = patch_property(raw, '/chosen', 'bootargs', bootargs)
    raw = patch_property(raw, '/chosen', 'linux,initrd-end', (0x440000000+candidate.stat().st_size).to_bytes(8, 'big'))
    (output/'virt.dtb').write_bytes(raw)
    manifest['files'].update(initrd=fact(candidate), dtb=fact(output/'virt.dtb'))
    manifest['guest_comparison'] = {'original_entries': len(before),
        'all_original_entries_identical': True, 'added': sorted(additions)}
    manifest['simulation_adaptations'] = {'IMDB_qemu_target_masks': db_changes,
        'bluetooth_AP_wrapper': 'existing RAM-only 0x35051bc RET shim; shared init retained',
        'native_menu': 'existing software GPE/CP service and MENU reentry adapters',
        'firmware_identity': {'source': version, 'dat4_hex': dat4.hex(),
            'FAT_files': ['/SEED.TXT', '/DAT2', '/DAT3'], 'real_camera_partition': False},
        'aspect_unlock_applied': False}
    (output/'manifest.json').write_text(json.dumps(manifest, indent=2)+'\n')
    experiment_helpers = ('inspect-date-clock', 'seed-date-clock406')
    source_names = set(compiled_sources) | {name+'.c' for name in helper_links if name not in experiment_helpers} | {
        'menu-observe-a7r5-baseline.c', 'a7r5-gui.inc', 'native-menu-reentry.inc',
        'a7r5-model-trace.inc', 'a7r5-input-trace.inc', 'native-privacy-notice.inc'}
    receipt = {'commands': commands, 'source_hashes': {name: digest(native/name) for name in sorted(source_names)},
               'experiment_source_hashes': {name+'.c': digest(Path(__file__).parent/(name+'.c')) for name in experiment_helpers},
               'outputs': {name: fact(path) for name, path in additions.items()},
               'guest_comparison': manifest['guest_comparison'],
               'AP_sha256': AP_SHA, 'default_manifest_modified': False,
               'menu_verified': False, 'camera_io': False}
    receipt['experiment_source_hashes']['aspect-guide406.inc'] = digest(output/'aspect-guide406.inc')
    (output/'build-receipt.json').write_text(json.dumps(receipt, indent=2)+'\n')
    return output/'manifest.json'


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--boot-manifest', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(build(args.source, args.boot_manifest, args.output))
