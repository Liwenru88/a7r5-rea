"""独立研究客体的固定输入与沙箱启动，不修改默认运行清单。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import sys

LAB = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(LAB/'tools'))
from media_candidate import patch_property
from native_vm import NativeVM, dtb_properties

SOURCE_SHA = 'c01948220e1cced7f4e1d6a6dd28221c587050214d32cc405291cc00d2f1ed80'
KERNEL_SHA = 'bdb129ad6806e3e33f1a1b9c094c0c97c4940bdea7aa9c09cef18f02e4012e66'
AP_SHA = 'd15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9'


def digest(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('只接受普通文件：' + str(path))
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def fact(path):
    return {'path': str(path.relative_to(LAB)), 'bytes': path.stat().st_size,
            'sha256': digest(path)}


def support():
    default = json.loads((LAB/'runtime/manifest.json').read_text())
    if (default['schema'], default['model'], default['feature']) != (
            1, 'ILCE-7RM5', 'A7R5_NATIVE_MENU_REENTRY'):
        raise ValueError('默认模拟器身份未知')
    result = {}
    # 此处只复用两项已固定的支持材料，不宣称默认客体已完整通过校验。
    for key in ('binary', 'gpe'):
        expected = default['files'][key]
        path = LAB/expected['path']
        if fact(path) != expected:
            raise ValueError('支持材料指纹不符：' + key)
        result[key] = path
    return default, result


def prepare(source, dtb_source, output):
    source = source.absolute()
    output = output.absolute()
    if not source.is_relative_to(LAB/'build') or not output.is_relative_to(LAB/'build'):
        raise ValueError('实验目录越界')
    record = json.loads((source/'source-manifest.json').read_text())
    if record['files']['usr/lib/appFw.so']['sha256'] != AP_SHA:
        raise ValueError('AP 身份不符')
    if digest(source/'source.cpio') != SOURCE_SHA or digest(source/'vmlinux.bin') != KERNEL_SHA:
        raise ValueError('独立源归档或内核摘要不符')
    default, files = support()
    wanted = default['files']['dtb']
    if dtb_source.stat().st_size != wanted['bytes'] or digest(dtb_source) != wanted['sha256']:
        raise ValueError('恢复的设备树与固定清单不符')
    raw = dtb_source.read_bytes()
    original = dtb_properties(raw)
    bootargs = original[('/chosen', 'bootargs')].rstrip(b'\0')
    bootargs = re.sub(rb'ramdisk_size=\d+', b'ramdisk_size='+str(
        (source.joinpath('source.cpio').stat().st_size+1023)//1024).encode(), bootargs)
    raw = patch_property(raw, '/chosen', 'bootargs', bootargs+b'\0')
    raw = patch_property(raw, '/chosen', 'linux,initrd-end', (
        0x440000000+source.joinpath('source.cpio').stat().st_size).to_bytes(8, 'big'))
    updated = dtb_properties(raw)
    allowed = {('/chosen', 'bootargs'), ('/chosen', 'linux,initrd-end')}
    if set(updated) != set(original) or any(updated[k] != v for k, v in original.items() if k not in allowed):
        raise ValueError('设备树出现额外属性变化')
    output.mkdir(parents=True, exist_ok=False)
    with (output/'virt.dtb').open('xb') as stream:
        stream.write(raw)
    files.update(kernel=source/'vmlinux.bin', initrd=source/'source.cpio', dtb=output/'virt.dtb')
    result = {'schema': 'a7r5-aspect406-runtime/1', 'model': 'ILCE-7RM5',
              'firmware': 'research-4.06', 'AP_sha256': AP_SHA,
              'files': {key: fact(path) for key, path in files.items()},
              'source_dtb_sha256': wanted['sha256'], 'dtb_changed_properties': sorted(allowed),
              'original_components_modified': False, 'default_manifest_modified': False,
              'menu_verified': False, 'photo_interface_verified': False, 'camera_io': False}
    with (output/'manifest.json').open('x') as stream:
        json.dump(result, stream, indent=2)
        stream.write('\n')
    return output/'manifest.json'


class AspectVM(NativeVM):
    def __init__(self, manifest):
        self.manifest_path = manifest.absolute()
        if not self.manifest_path.is_relative_to(LAB/'build'):
            raise ValueError('实验清单越界')
        self.runtime_inputs()
        super().__init__('aspect406', capid=True, boot_services=True)

    def runtime_inputs(self):
        record = json.loads(self.manifest_path.read_text())
        if (record['schema'], record['model'], record['AP_sha256']) != (
                'a7r5-aspect406-runtime/1', 'ILCE-7RM5', AP_SHA):
            raise ValueError('研究清单身份不符')
        if set(record['files']) != {'binary', 'kernel', 'initrd', 'dtb', 'gpe'}:
            raise ValueError('研究输入不全')
        result = {}
        for name, expected in record['files'].items():
            relative = Path(expected['path'])
            path = LAB/relative
            if relative.is_absolute() or '..' in relative.parts or path.resolve() != path.absolute():
                raise ValueError('研究输入路径越界或包含链接')
            if fact(path) != expected:
                raise ValueError('研究输入摘要不符：' + name)
            result[name] = path
        return result


def kernel_probe(manifest):
    vm = AspectVM(manifest)
    result = {'stage': 'kernel-and-rootfs', 'status': 'failed',
              'manifest': str(manifest), 'complete_menu_verified': False,
              'photo_interface_verified': False, 'camera_io': False}
    try:
        vm.start()
        reply = vm.command('uname -a; test -r /usr/lib/appFw.so && test -r /seed-backup.bin && echo ASPECT406_SOURCE_READY', timeout=30)
        (vm.out/'source-check.log').write_bytes(reply)
        if b'ASPECT406_SOURCE_READY' not in reply:
            raise RuntimeError('内核终端存在，但研究源文件不完整')
        result['status'] = 'passed'
    except Exception as error:
        result['error'] = str(error)
    finally:
        result['close'] = vm.close()
        result['run_directory'] = str(vm.out)
        (vm.out/'aspect406-kernel.json').write_text(json.dumps(result, indent=2)+'\n')
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    build = sub.add_parser('prepare')
    build.add_argument('--source', type=Path, required=True)
    build.add_argument('--dtb-source', type=Path, required=True)
    build.add_argument('--output', type=Path, required=True)
    run = sub.add_parser('kernel')
    run.add_argument('--manifest', type=Path, required=True)
    args = parser.parse_args()
    if args.action == 'prepare':
        print(prepare(args.source, args.dtb_source, args.output))
    else:
        result = kernel_probe(args.manifest)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        if result['status'] != 'passed' or result['close'].get('exit_code') != 0:
            raise SystemExit(1)


if __name__ == '__main__':
    main()
