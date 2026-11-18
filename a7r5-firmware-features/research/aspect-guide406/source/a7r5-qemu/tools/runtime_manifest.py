"""项目内固定输入清单；摘要、长度、路径边界任一不符即停止。"""
import hashlib
import json
from pathlib import Path

from app_paths import paths
LAB = paths().resources
MANIFEST = LAB / 'runtime/manifest.json'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def verified_inputs(root=LAB):
    root = root.resolve()
    manifest = json.loads((root / 'runtime/manifest.json').read_text())
    if (manifest.get('schema'), manifest.get('model'), manifest.get('firmware'), manifest.get('feature')) != (
            1, 'ILCE-7RM5', '4.00', 'A7R5_NATIVE_MENU_REENTRY'):
        raise ValueError('未知客体清单')
    if set(manifest['files']) != {'binary', 'kernel', 'initrd', 'dtb', 'gpe'}:
        raise ValueError('固定输入不完整')
    result = {}
    for name, record in manifest['files'].items():
        relative = Path(record['path'])
        allowed = 'bin' if name == 'binary' else 'sdk' if name == 'gpe' else 'runtime'
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0] != allowed:
            raise ValueError('输入路径越界')
        path = root / relative
        if any(p.is_symlink() for p in (path, *path.parents) if p != root and root in p.parents):
            raise ValueError('输入含符号链接')
        if not path.is_file() or not path.resolve().is_relative_to(root):
            raise ValueError('输入不存在或越界')
        if path.stat().st_size != record['bytes'] or digest(path) != record['sha256']:
            raise ValueError('输入摘要或长度不符: ' + name)
        result[name] = path
    return result


def verified_libraries(root=LAB):
    """包内依赖逐个校验；不接受额外或漏记的动态库。"""
    manifest = json.loads((root / 'runtime/manifest.json').read_text())
    records = manifest.get('libraries', {})
    directory = root / 'lib'
    if not records and not directory.exists():
        return []
    if not records or directory.is_symlink():
        raise ValueError('包内动态库清单缺失')
    if set(records) != {p.name for p in directory.iterdir()}:
        raise ValueError('包内动态库集合不符')
    libraries = []
    for name, record in records.items():
        if Path(name).name != name or not name.endswith('.dylib'):
            raise ValueError('动态库名称越界')
        path = directory / name
        if path.is_symlink() or not path.is_file() or path.stat().st_size != record['bytes'] or digest(path) != record['sha256']:
            raise ValueError('动态库摘要或长度不符')
        libraries.append(path)
    return libraries


def update_manifest(changes):
    """调用方持有 VM 独占锁，并已验证候选；原子更新生效清单。"""
    manifest = json.loads(MANIFEST.read_text())
    for key, path in changes.items():
        manifest['files'][key] = {'path': str(path.relative_to(LAB)),
                                  'bytes': path.stat().st_size, 'sha256': digest(path)}
    temporary = MANIFEST.with_suffix('.part')
    temporary.write_text(json.dumps(manifest, indent=2) + '\n')
    temporary.replace(MANIFEST)
