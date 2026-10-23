"""只替换模拟快照辅助程序，逐项核对其他客体条目及原厂材料未变。"""
import hashlib
import importlib.util
import json
import re
from pathlib import Path
import struct
import subprocess
import tempfile

from app_paths import open_vm_lock
from cpio_inputs import entries
from native_vm import dtb_properties
from runtime_manifest import LAB, verified_inputs, update_manifest, digest


def main():
    import fcntl
    with open_vm_lock() as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        inputs = verified_inputs()
        before_manifest = (LAB / 'runtime/manifest.json').read_text()
        controls_path = LAB / 'config/controls.json'
        controls = json.loads(controls_path.read_text())
        old_fingerprint = {key: json.loads(before_manifest)['files'][key]['sha256']
                           for key in ('kernel', 'initrd', 'dtb')}
        if controls['input_fingerprint'] != old_fingerprint:
            raise ValueError('原输入指纹不匹配，拒绝重新绑定')
        compiler = '/opt/homebrew/opt/llvm/bin/clang'
        linker = '/opt/homebrew/opt/lld/bin/ld.lld'
        source = LAB / 'source/guest/headless-osd-export.c'
        binary = LAB / 'build/headless-osd-export'
        command = [compiler, '--target=aarch64-linux-gnu', '--ld-path='+linker,
                   '-nostdlib', '-O2', '-fno-stack-protector', '-no-pie',
                   '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1', '-Wl,-e,_start',
                   str(source), str(LAB / 'sdk/lib/libc-2.25.so'), '-o', str(binary)]
        subprocess.run(command, check=True)
        elf = binary.read_bytes()
        if elf[:6] != b'\x7fELF\x02\x01' or struct.unpack_from('<H', elf, 18)[0] != 183:
            raise ValueError('导出程序不是 AArch64 ELF')
        spec = importlib.util.spec_from_file_location('build_guest', LAB / 'tools/build-guest.py')
        builder = importlib.util.module_from_spec(spec); spec.loader.exec_module(builder)
        with tempfile.TemporaryDirectory(prefix='frame-export-', dir=LAB / 'build') as directory:
            output = Path(directory) / 'menu.cpio'
            builder.replace_cpio(inputs['initrd'], output, {'simulation/headless-osd-export': elf})
            old, new = entries(inputs['initrd']), entries(output)
            changed = [name for name in old if old[name] != new.get(name)]
            if old.keys() != new.keys() or changed not in ([], ['simulation/headless-osd-export']):
                raise ValueError('快照辅助程序以外的归档条目变化')
            raw = bytearray(inputs['dtb'].read_bytes())
            properties = dtb_properties(raw)
            oldend = properties[('/chosen', 'linux,initrd-end')]
            newend = (0x440000000 + output.stat().st_size).to_bytes(len(oldend), 'big')
            if raw.count(oldend) != 1:
                raise ValueError('归档结束地址不唯一')
            raw = raw.replace(oldend, newend)
            bootargs = properties[('/chosen', 'bootargs')]
            newargs = re.sub(rb'ramdisk_size=\d+',
                             ('ramdisk_size='+str((output.stat().st_size+1023)//1024)).encode(), bootargs)
            if len(newargs) != len(bootargs) or raw.count(bootargs) != 1:
                raise ValueError('启动参数尺寸不符')
            raw = raw.replace(bootargs, newargs)
            target = LAB / 'runtime' / ('menu-' + digest(output)[:16] + '.cpio')
            dtb = LAB / 'runtime' / ('virt-' + hashlib.sha256(raw).hexdigest()[:16] + '.dtb')
            if target.exists():
                if digest(target) != digest(output): raise ValueError('归档候选冲突')
            else:
                output.replace(target)
            if dtb.exists():
                if dtb.read_bytes() != raw: raise ValueError('设备树候选冲突')
            else:
                dtb.write_bytes(raw)
            update_manifest({'initrd': target, 'dtb': dtb})
            manifest = json.loads((LAB / 'runtime/manifest.json').read_text())
            controls['input_fingerprint'] = {key: manifest['files'][key]['sha256']
                                             for key in ('kernel', 'initrd', 'dtb')}
            temporary = controls_path.with_suffix('.part')
            temporary.write_text(json.dumps(controls, ensure_ascii=False, indent=2)+'\n')
            temporary.replace(controls_path)
        result = {'command': command, 'source_sha256': digest(source), 'elf_sha256': digest(binary),
                  'previous_manifest': json.loads(before_manifest),
                  'manifest': json.loads((LAB / 'runtime/manifest.json').read_text()),
                  'entries': len(old), 'changed': changed, 'all_other_entries_identical': True,
                  'dtb_changes': 'linux,initrd-end and ramdisk_size only', 'original_images_accessed': False}
        (LAB / 'logs/latency-optimization/guest-build.json').write_text(json.dumps(result, indent=2) + '\n')
        print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
