"""构建自包含 Qt 应用；客体只复制一份，开发输入保持不变。"""
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
from runtime_manifest import verified_inputs


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def call(arguments, **kwargs):
    return subprocess.run(arguments, check=True, text=True, **kwargs)


def dependencies(path):
    output = subprocess.check_output(['/usr/bin/otool', '-L', str(path)], text=True)
    return [row.strip().split(' (')[0] for row in output.splitlines()[1:]]


def bundle_qemu(resources, source):
    binary = resources / 'bin/qemu-system-aarch64'
    binary.parent.mkdir()
    shutil.copy2(source, binary)
    lib = resources / 'lib'
    lib.mkdir()
    pending = [source]
    copied = {}
    while pending:
        current = pending.pop()
        for name in dependencies(current):
            if name.startswith(('/usr/lib/', '/System/Library/')):
                continue
            path = Path(name)
            if not path.is_absolute() or not path.is_file():
                raise ValueError('无法封装的依赖：' + name)
            if path.name in copied:
                if copied[path.name].resolve() != path.resolve():
                    raise ValueError('依赖同名冲突')
                continue
            copied[path.name] = path
            shutil.copy2(path.resolve(), lib / path.name)
            pending.append(path)
    artifacts = [binary, *(lib / name for name in copied)]
    for artifact in artifacts:
        changes = []
        for name in dependencies(artifact):
            if name.startswith(('/usr/lib/', '/System/Library/')):
                continue
            target = ('@loader_path/../lib/' if artifact == binary else '@loader_path/') + Path(name).name
            changes.extend(['-change', name, target])
        if artifact != binary:
            changes.extend(['-id', '@loader_path/' + artifact.name])
        if changes:
            call(['/usr/bin/install_name_tool', *changes, str(artifact)])
        call(['/usr/bin/codesign', '--force', '--sign', '-', str(artifact)])
    for artifact in artifacts:
        if any(name.startswith(('/opt/', '/Users/')) for name in dependencies(artifact)):
            raise ValueError('动态库仍依赖开发路径')
    return binary, {name: {'bytes': (lib / name).stat().st_size, 'sha256': digest(lib / name)} for name in copied}


def main():
    if sys.platform != 'darwin':
        raise RuntimeError('本构建配方仅验收 macOS arm64')
    inputs = verified_inputs(ROOT)
    original_manifest = (ROOT / 'runtime/manifest.json').read_bytes()
    source_paths = [p for folder in ('client', 'tools') for p in (ROOT / folder).glob('*.py')]
    source_hashes = {str(p.relative_to(ROOT)): digest(p) for p in source_paths}
    # uv 虚拟环境不复制 libpython；Nuitka 的链接路径需要此本地构建链接。
    python_lib = 'libpython' + str(sys.version_info.major) + '.' + str(sys.version_info.minor) + '.dylib'
    link = Path(sys.prefix) / 'lib' / python_lib
    base = Path(sys.base_prefix) / 'lib' / python_lib
    if not link.exists():
        if not base.is_file():
            raise ValueError('缺少可封装的 Python 动态库')
        link.symlink_to(base)
    output = ROOT / 'build' / ('desktop-package-' + time.strftime('%Y%m%d-%H%M%S'))
    output.mkdir()
    env = os.environ.copy()
    env['PYTHONPATH'] = os.pathsep.join((str(ROOT / 'tools'), str(ROOT)))
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    args = [sys.executable, '-m', 'nuitka', '--standalone', '--macos-create-app-bundle',
            '--enable-plugin=pyside6', '--include-module=probe_app', '--include-package=client',
            '--macos-app-name=A7R5 Emulator', '--macos-app-version=0.1.0',
            '--output-filename=A7R5Emulator', '--output-dir=' + str(output),
            '--disable-cache=ccache', '--macos-app-icon=none',
            '--assume-yes-for-downloads', '--jobs=8', str(ROOT / 'client/main.py')]
    call(args, env=env, cwd=ROOT)
    if (ROOT / 'runtime/manifest.json').read_bytes() != original_manifest or any(
            digest(ROOT / name) != value for name, value in source_hashes.items()):
        raise RuntimeError('构建期间源码或运行清单变化，候选不予验收')
    bundles = list(output.glob('*.app'))
    if len(bundles) != 1:
        raise ValueError('构建没有产生唯一应用包')
    bundle = bundles[0]
    resources = bundle / 'Contents/Resources/a7r5'
    resources.mkdir(parents=True)
    shutil.copytree(ROOT / 'config', resources / 'config')
    manifest = json.loads(original_manifest)
    for key in ('kernel', 'initrd', 'dtb', 'gpe'):
        target = resources / manifest['files'][key]['path']
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(inputs[key], target)
    binary, libraries = bundle_qemu(resources, inputs['binary'])
    manifest['files']['binary'].update(bytes=binary.stat().st_size, sha256=digest(binary))
    manifest['libraries'] = libraries
    (resources / 'runtime/manifest.json').write_text(json.dumps(manifest, indent=2) + '\n')
    licenses = resources / 'licenses'
    shutil.copytree(ROOT / 'source/qemu/licenses', licenses / 'qemu')
    (licenses / 'NOTICE.txt').write_text('PySide6/Qt 使用 LGPL/GPL/商业许可，详情见包内 Qt 许可和安装依赖元数据。\nQEMU 与依赖库源材料见独立项目 source/qemu；本包仅供本机研究。固件归各权利人所有。\n')
    info_path = bundle / 'Contents/Info.plist'
    info = plistlib.loads(info_path.read_bytes())
    info.update(CFBundleIdentifier='local.research.a7r5qemu', LSMinimumSystemVersion='14.0')
    info_path.write_bytes(plistlib.dumps(info))
    call(['/usr/bin/codesign', '--force', '--deep', '--sign', '-', str(bundle)])
    verified_inputs(resources)
    if len(list(bundle.rglob('*.cpio'))) != 1:
        raise ValueError('固件归档数量不为一')
    receipt = {'status': 'built-not-yet-accepted', 'bundle': str(bundle), 'command': args,
               'resources': str(resources), 'manifest': manifest, 'source_sha256': source_hashes,
               'development_binary_unchanged': digest(inputs['binary']) == json.loads((ROOT / 'runtime/manifest.json').read_text())['files']['binary']['sha256']}
    (ROOT / 'logs/desktop-implementation/package-build.json').write_text(json.dumps(receipt, indent=2) + '\n')
    print(json.dumps(receipt, indent=2), flush=True)


if __name__ == '__main__':
    main()
