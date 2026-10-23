#!/usr/bin/env python3
"""检查未入库的本地构建输入；只读取普通文件，不导入 USB 或启动模拟器。"""
import argparse
import hashlib
import json
from pathlib import Path
import stat


def check(root, records):
    results = []
    for record in records:
        path = root/record['path']
        status = 'missing'
        if path.is_symlink() or any(p.is_symlink() for p in path.parents if p != root and root in p.parents):
            status = 'symlink_rejected'
        elif path.is_file():
            status = 'present'
            if 'sha256' in record:
                with path.open('rb') as stream:
                    digest = hashlib.file_digest(stream, 'sha256').hexdigest()
                status = 'verified' if digest == record['sha256'] else 'hash_mismatch'
            if record.get('private') and stat.S_IMODE(path.stat().st_mode) != 0o600:
                status = 'permissions_must_be_0600'
        results.append(dict(path=record['path'], status=status))
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--module', required=True, choices=['desktop', 'exec', 'libjit', 'qemu'])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    registry = json.loads((Path(__file__).with_name('local-inputs.json')).read_text())
    records = registry[args.module]
    if args.module == 'qemu':
        manifest = json.loads((root/'a7r5-qemu/runtime/manifest.json').read_text())
        records = records+[dict(path='a7r5-qemu/'+v['path'], sha256=v['sha256']) for v in manifest['files'].values()]
    results = check(root, records)
    ok = all(row['status'] in ('present', 'verified') for row in results)
    print(json.dumps(dict(status='passed' if ok else 'incomplete', module=args.module,
                          files=results, camera_IO=False), ensure_ascii=False, indent=2))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
