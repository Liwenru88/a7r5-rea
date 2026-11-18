#!/usr/bin/env python3
"""Prepare a guarded 4.19 trigger candidate; no camera IO."""
from __future__ import annotations
import argparse, hashlib, json, re
from pathlib import Path
from sd_trigger_offline import generate

EXPECTED_PACKAGE_SIZE = 754525608
A2 = re.compile(r"INFOnflasha2\s+0000c000\s+0000a000\s+fat")
A5 = re.compile(r"INFOnflasha5\s+00041800\s+00096000\s+wbi2")

def sha256(path: Path) -> str:
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(4<<20), b''): h.update(chunk)
    return h.hexdigest()

def main() -> int:
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--settings', type=Path, required=True)
    p.add_argument('--expected-settings-sha256')
    p.add_argument('--package', type=Path, required=True)
    p.add_argument('--partition-log', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a=p.parse_args(); settings=a.settings.resolve(); package=a.package.resolve(); log=a.partition_log.resolve()
    if settings.stat().st_size != 20*1024*1024: raise ValueError('nflasha2 必须是 20 MiB logical image')
    if package.stat().st_size != EXPECTED_PACKAGE_SIZE: raise ValueError('BODYDATA.DAT 大小不匹配')
    actual=sha256(settings)
    if a.expected_settings_sha256 and actual != a.expected_settings_sha256: raise ValueError('nflasha2 SHA-256 不匹配')
    text=log.read_text(errors='replace')
    if not A2.search(text) or not A5.search(text): raise ValueError('分区几何不符合预期')
    report=generate(settings, package, a.output)
    report.update(package_sha256=sha256(package), package_hash_checked=False, settings_sha256_verified=True, partition_geometry_verified=True)
    (a.output/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False,indent=2)); return 0
if __name__=='__main__': raise SystemExit(main())
