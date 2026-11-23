#!/usr/bin/env python3
"""离线核对 nflasha1 回读：长度、SHA-256、与期望前像 / 救援 sparse 的关系。

不访问设备；只读入本地文件。用于真机只读阶段的判读。
给了 --sparse 时，--expect 指的是“应用 sparse 之后的镜像摘要”，不是输入镜像的摘要。

  .venv/bin/python -B a7r5-fastboot/rescue/verify_nflasha1.py \
      --image <回读文件> --expect 1c97db64e77eb7e2caa90ffa1c78a7fa48c6ac0bb9b10774c115bf0a208e1441

退出码：0 = 校验通过，1 = 不一致，2 = 输入错误。
"""
import argparse
import hashlib
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
MODULE = HERE.parent
REPO = MODULE.parent
sys.path.insert(0, str(REPO / 'a7r5-updater-trust/src'))
from partition_sparse import apply_sparse  # noqa: E402

PARTITION_BYTES = 25100288


def sha(data):
    return hashlib.sha256(data).hexdigest()


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--image', type=pathlib.Path, required=True)
    ap.add_argument('--expect', help='期望的整分区 SHA-256')
    ap.add_argument('--reference', type=pathlib.Path, help='期望的参考镜像（逐字节比较）')
    ap.add_argument('--sparse', type=pathlib.Path, help='救援 sparse；应用后应与写前镜像一致')
    ap.add_argument('--known-partial', action='store_true',
                    help='写入前判定：当前分区是否为写前/写完/任一顺序半写状态')
    ap.add_argument('--source', type=pathlib.Path, help='写前镜像（配合 --known-partial）')
    ap.add_argument('--candidate', type=pathlib.Path, help='候选镜像（配合 --known-partial）')
    ap.add_argument('--plan', type=pathlib.Path, help='write-plan.json（配合 --known-partial）')
    args = ap.parse_args()

    data = args.image.read_bytes()
    report = {'image': str(args.image), 'bytes': len(data), 'sha256': sha(data)}
    ok = True
    expect_applies_to_input = args.sparse is None
    if len(data) != PARTITION_BYTES:
        report['error'] = '长度不是 25,100,288'
        print(report)
        return 2
    if args.expect:
        report['expect'] = args.expect
        report['matches_expect'] = report['sha256'] == args.expect
        if expect_applies_to_input:
            ok = ok and report['matches_expect']
    if args.known_partial:
        if not (args.source and args.candidate and args.plan):
            print({'error': '--known-partial 需要 --source/--candidate/--plan'})
            return 2
        import json
        source = args.source.read_bytes()
        candidate = args.candidate.read_bytes()
        rows = json.loads(args.plan.read_text())['rows']
        if len(source) != PARTITION_BYTES or len(candidate) != PARTITION_BYTES:
            print({'error': 'source/candidate 长度不符'})
            return 2
        state = bytearray(source)
        digests = [sha(state)]
        for row in rows:
            at = row['offset']
            state[at:at + 512] = candidate[at:at + 512]
            digests.append(sha(state))
        report['known_partial'] = True
        report['known_states'] = len(digests)
        report['known_partial_match'] = report['sha256'] in digests
        if report['known_partial_match']:
            report['matched_state'] = digests.index(report['sha256'])
        ok = ok and report['known_partial_match']
    if args.reference:
        ref = args.reference.read_bytes()
        report['reference'] = str(args.reference)
        report['matches_reference'] = data == ref
        ok = ok and report['matches_reference']
    if args.sparse:
        sparse = args.sparse.read_bytes()
        rebuilt, _ = apply_sparse(data, sparse)
        report['sparse'] = str(args.sparse)
        report['after_sparse_sha256'] = sha(rebuilt)
        if args.expect:
            report['after_sparse_matches_expect'] = report['after_sparse_sha256'] == args.expect
            ok = ok and report['after_sparse_matches_expect']
    print(report)
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
