#!/usr/bin/env python3
"""按固定清单恢复源码资源；默认不联网，不覆盖已有不同文件，不接触设备。"""
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import sys
import tempfile
from urllib.parse import urlsplit
from urllib.request import urlopen


def asset_path(root, name):
    path = PurePosixPath(name)
    if (not isinstance(name, str) or not path.parts or path.is_absolute()
            or '..' in path.parts or '\\' in name):
        raise ValueError('资源路径越界或无效')
    result = root.joinpath(*path.parts)
    if any(p.is_symlink() for p in (result, *result.parents)):
        raise ValueError('资源路径经过链接')
    return result


def check_digest(path, row):
    if not path.is_file() or path.stat().st_size != row['bytes']:
        raise ValueError('资源长度或摘要不符：' + row['path'])
    with path.open('rb') as stream:
        value = hashlib.file_digest(stream, 'sha256').hexdigest()
    if value != row['sha256']:
        raise ValueError('资源摘要不符：' + row['path'])


def validate_manifest(root):
    source = asset_path(root, 'scripts/source-assets.json')
    data = json.loads(source.read_text())
    if data['schema'] != 1 or not isinstance(data['assets'], list):
        raise ValueError('资源清单格式不符')
    names = set()
    for row in data['assets']:
        asset_path(root, row['path'])
        if row['path'] in names:
            raise ValueError('资源路径重复')
        names.add(row['path'])
        if type(row['bytes']) is not int or not 0 <= row['bytes'] <= 1 << 30:
            raise ValueError('资源长度不合法')
        if not re.fullmatch('[0-9a-f]{64}', row['sha256']):
            raise ValueError('资源摘要不合法')
        if ('chunks' in row) == ('source' in row):
            raise ValueError('资源必须且只能有一种恢复来源')
        if 'chunks' in row:
            if not row['chunks'] or sum(p['bytes'] for p in row['chunks']) != row['bytes']:
                raise ValueError('分片总长度不符')
            for part in row['chunks']:
                asset_path(root, part['path'])
                if (type(part['bytes']) is not int or not 0 < part['bytes'] <= 8 << 20
                        or not re.fullmatch('[0-9a-f]{64}', part['sha256'])):
                    raise ValueError('分片摘要或长度不合法')
        else:
            url = urlsplit(row['source'])
            if (url.scheme != 'https' or url.netloc != 'raw.githubusercontent.com'
                    or not re.fullmatch(r'/[^/]+/[^/]+/[0-9a-f]{40}/.+', url.path)
                    or url.query or url.fragment):
                raise ValueError('下载地址必须是固定 Git 提交的 HTTPS 原始文件')
    return data['assets']


def restore(root, row, download=False):
    target = asset_path(root, row['path'])
    if target.exists():
        try:
            check_digest(target, row)
        except ValueError as exc:
            raise ValueError('拒绝覆盖已有不同资源：' + row['path']) from exc
        return 'already-verified'
    if 'source' in row and not download:
        raise ValueError('缺少上游资源；须显式传入 --download：' + row['path'])
    if 'chunks' in row:
        for part in row['chunks']:
            check_digest(asset_path(root, part['path']), part)
    target.parent.mkdir(parents=True, exist_ok=True)
    # 发布前再次检查目录，临时文件和目标位于同一卷，完整校验后独占发布。
    asset_path(root, row['path'])
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(prefix='.restore-', dir=target.parent, delete=False) as output:
            temporary = Path(output.name)
            total = 0

            def copy(stream):
                nonlocal total
                while chunk := stream.read(1 << 20):
                    total += len(chunk)
                    if total > row['bytes']:
                        raise ValueError('资源流长度超限')
                    output.write(chunk)

            if 'chunks' in row:
                for part in row['chunks']:
                    with asset_path(root, part['path']).open('rb') as stream:
                        copy(stream)
            else:
                with urlopen(row['source'], timeout=30) as stream:
                    copy(stream)
            output.flush()
            os.fsync(output.fileno())
        check_digest(temporary, row)
        asset_path(root, row['path'])
        os.link(temporary, target)
        return 'restored'
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('action', choices=('check', 'restore'))
    parser.add_argument('--download', action='store_true', help='允许下载清单中固定版本的缺失上游资源')
    args = parser.parse_args()
    root = args.root.resolve()
    try:
        assets = validate_manifest(root)
        result = []
        for row in assets:
            if args.action == 'restore':
                status = restore(root, row, args.download)
            else:
                check_digest(asset_path(root, row['path']), row)
                status = 'verified'
            result.append(dict(path=row['path'], status=status))
        print(json.dumps(dict(status='passed', assets=result, camera_io=False), ensure_ascii=False))
        return 0
    except (ValueError, OSError, KeyError, TypeError) as exc:
        print('资源准备失败：' + str(exc), file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
