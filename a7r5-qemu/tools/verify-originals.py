#!/usr/bin/env python3
"""显式运行时复核同一研究根目录下的原件；导入模块不读取镜像。"""
import hashlib
import json
from pathlib import Path

def image_root(project):
    return Path(project).parent / 'a7r5-firmware-images'


def main():
    lab = Path(__file__).resolve().parent.parent
    root = image_root(lab)
    manifest = json.loads((root / '物理分类清单.json').read_text())
    rows = []
    for record in manifest['images']:
        relative = Path(record['path'])
        path = root / relative
        if relative.is_absolute() or '..' in relative.parts or any(
                p.is_symlink() for p in (path, *path.parents) if p == root or root in p.parents):
            raise ValueError('原件路径越界或含符号链接: ' + str(path))
        sha, md5 = hashlib.sha256(), hashlib.md5()
        size = 0
        if not path.is_file():
            raise ValueError('原件类型变化: ' + str(path))
        with path.open('rb') as source:
            while chunk := source.read(8 * 1024 * 1024):
                size += len(chunk)
                sha.update(chunk)
                md5.update(chunk)
        okay = size == record['bytes'] and sha.hexdigest() == record['sha256'] and md5.hexdigest() == record['md5']
        rows.append({'path': str(path), 'bytes': size, 'sha256': sha.hexdigest(), 'md5': md5.hexdigest(), 'matches': okay})
    result = {'status': 'unchanged' if all(r['matches'] for r in rows) else 'mismatch', 'count': len(rows), 'images': rows}
    (lab / 'logs/original-images-final-verification.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'status': result['status'], 'count': len(rows)}, ensure_ascii=False))
    return 0 if result['status'] == 'unchanged' else 1


if __name__ == '__main__':
    raise SystemExit(main())
