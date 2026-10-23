#!/usr/bin/env python3
"""从本地固定 Debian 包提取单个 SFTP 文件；不下载、不运行包内代码。"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile


def extract(package, package_sha, binary_sha):
    if hashlib.sha256(package).hexdigest() != package_sha:
        raise ValueError('Debian 包摘要不符')
    if not package.startswith(b'!<arch>\n'):
        raise ValueError('不是 ar 格式')
    offset = 8
    archives = []
    while offset < len(package):
        header = package[offset:offset+60]
        if len(header) != 60 or header[58:] != b'`\n':
            raise ValueError('ar 头损坏')
        size = int(header[48:58].strip())
        if size < 0 or offset+60+size > len(package):
            raise ValueError('ar 长度越界')
        name = header[:16].decode('ascii').strip().removesuffix('/')
        if name.startswith('data.tar.'):
            archives.append(package[offset+60:offset+60+size])
        offset += 60+size+(size % 2)
    if len(archives) != 1:
        raise ValueError('data 归档不唯一')
    with tarfile.open(fileobj=io.BytesIO(archives[0]), mode='r:*') as stream:
        members = [m for m in stream.getmembers() if m.name.removeprefix('./') == 'usr/lib/openssh/sftp-server']
        if len(members) != 1 or not members[0].isfile() or members[0].size > 10*1024*1024:
            raise ValueError('SFTP 文件类型或长度不符')
        raw = stream.extractfile(members[0]).read()
    if hashlib.sha256(raw).hexdigest() != binary_sha:
        raise ValueError('SFTP 二进制摘要不符')
    return raw


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('package', type=Path)
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    root = args.root.resolve()
    vendor = root/'a7r5-ssh/ssh-service/original-view/vendor'
    provenance = json.loads((vendor/'sftp-provenance.json').read_text())
    if args.package.is_symlink() or not args.package.is_file() or args.package.stat().st_size > 10*1024*1024:
        raise ValueError('只接受本地普通依赖包')
    raw = extract(args.package.read_bytes(), provenance['package_sha256'], provenance['binary_sha256'])
    destination = vendor/'sftp-server.arm64'
    if any(p.is_symlink() for p in (destination, *destination.parents)):
        raise ValueError('拒绝链接输出路径')
    with destination.open('xb') as stream:
        stream.write(raw)
    print('SFTP 依赖已按固定摘要提取；未运行或上传')


if __name__ == '__main__':
    main()
