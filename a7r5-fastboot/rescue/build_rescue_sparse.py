#!/usr/bin/env python3
"""生成救援 sparse：把写入后的候选镜像恢复成写前镜像（逐扇区覆盖差异）。"""
import argparse
import hashlib
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
MODULE = HERE.parent
REPO = MODULE.parent
sys.path.insert(0, str(REPO / 'a7r5-updater-trust/src'))
from partition_sparse import apply_sparse, make_sparse  # noqa: E402


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--before', type=pathlib.Path, required=True, help='写前镜像')
    ap.add_argument('--after', type=pathlib.Path, required=True, help='写入后候选镜像')
    ap.add_argument('--output', type=pathlib.Path,
                    default=MODULE / 'assets/rescue-to-original.sparse')
    args = ap.parse_args()
    before = args.before.read_bytes()
    after = args.after.read_bytes()
    sparse = make_sparse(after, before)
    rebuilt, _ = apply_sparse(after, sparse)
    if rebuilt != before:
        raise SystemExit('sparse 自检失败')
    if len(sparse) > 524288:
        raise SystemExit(f'sparse 超出 512KiB 上限：{len(sparse)}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(sparse)
    print(f'sparse {len(sparse)} bytes sha256 {sha(sparse)}')
    print(f'before {sha(before)}')
    print(f'after  {sha(after)}')


if __name__ == '__main__':
    main()
