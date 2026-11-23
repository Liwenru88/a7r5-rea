#!/usr/bin/env python3
"""为指定 cnflasha1 前像生成信任候选与扇区计划（离线，不访问设备）。

两种模式（默认 skip-key）：
  skip-key     只 patch 四个 verifyKey，保留官方 PEM（verifyKey-only，推荐）
  replace-key  替换 /etc/VerificationKey.pem 并 patch 四个 verifyKey（本仓库原始方案）

候选与计划都从“当轮读到的镜像”生成，因此不要求镜像等于某个硬编码摘要；
--source-sha 必须显式等于输入镜像的摘要，用于把本次构建绑定到这台机身。
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import pathlib
import sys

REPO = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / 'a7r5-updater-trust/src'))

import sector_plan  # noqa: E402
import trust_recipe  # noqa: E402

PUBLIC_KEY = REPO / 'a7r5-updater-trust/public-key.pem'
PARTITION_BYTES = 25100288


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--image', type=pathlib.Path, required=True)
    parser.add_argument('--mode', choices=('replace-key', 'skip-key'), default='skip-key')
    parser.add_argument('--source-sha', required=True,
                        help='必须等于输入镜像的 SHA-256，用于显式绑定本次构建')
    parser.add_argument('--public-key', type=pathlib.Path, default=PUBLIC_KEY)
    parser.add_argument('--output', type=pathlib.Path, required=True)
    args = parser.parse_args()

    raw = args.image.read_bytes()
    if len(raw) != PARTITION_BYTES:
        parser.error(f'镜像长度应为 {PARTITION_BYTES}')
    actual = sha(raw)
    if actual != args.source_sha:
        parser.error(f'--source-sha 与镜像不符：{actual}')

    replace = args.mode == 'replace-key'
    public = args.public_key.read_bytes() if replace else None
    result, patched, new_sums, record = trust_recipe.construct(
        raw, None, public, source_sha=actual, replace_key=replace)
    plan = sector_plan.make_plan(raw, result, source_sha=actual, target_sha=sha(result))

    out = args.output.resolve()
    if out.exists():
        parser.error('输出目录已存在，拒绝覆盖')
    out.mkdir(parents=True)
    (out / 'candidate.bin').write_bytes(result)
    (out / 'plan.json').write_text(json.dumps(plan, ensure_ascii=False, indent=2) + '\n')
    sectors = {
        'source_sha256': actual,
        'target_sha256': sha(result),
        'bytes': len(raw),
        'rows': [{'offset': row['offset'],
                  'before': base64.b64encode(raw[row['offset']:row['offset'] + 512]).decode(),
                  'after': base64.b64encode(result[row['offset']:row['offset'] + 512]).decode()}
                 for row in plan['rows']],
    }
    (out / 'trust-sectors.json').write_text(json.dumps(sectors, ensure_ascii=False, indent=2) + '\n')
    summary = {
        'mode': args.mode,
        'source_sha256': actual,
        'candidate_sha256': sha(result),
        'sectors': len(plan['rows']),
        'changed_bytes': plan['changed_bytes'],
        'key_replaced': record['key_replaced'],
        'changed_squashfs_files': record['changed_squashfs_files'],
        'p1chksum': new_sums.decode().strip().splitlines(),
    }
    (out / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
