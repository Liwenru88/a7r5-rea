#!/usr/bin/env python3
"""通过 0336 服务会话执行 stock-absence 258 信任写入（真实设备，需 sudo）。

用法：
  sudo .venv/bin/python -B scripts/trust_write_258.py --bundle <bundle> --output <新目录>
  .venv/bin/python -B scripts/trust_write_258.py --bundle <bundle> --validate-only
"""
import argparse
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'scripts'))
sys.path.insert(0, str(ROOT / 'a7r5-desktop/engine'))

from stock_trust_operation import Operation  # noqa: E402


def execute(operation, output, session_module):
    """设置输出目录并执行会话；只有完整回读与协议门都通过才算成功。"""
    operation.output = output
    report = session_module.run_session(output, 'libusb', _operation=operation)
    if not (report.get('complete_partition_readback_verified') is True
            and report.get('protocol_gate_passed') is True):
        raise SystemExit('会话未完成信任写入：保留现场，不重试；见 ' + str(output))
    return report


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--bundle', type=pathlib.Path, required=True)
    ap.add_argument('--output', type=pathlib.Path)
    ap.add_argument('--validate-only', action='store_true')
    args = ap.parse_args()
    operation = Operation(args.bundle)
    payload = (args.bundle / 'materials/libJit.so').read_bytes()
    if b'/dev/cnflasha1' not in payload or operation.run.encode() not in payload:
        raise SystemExit('载荷不是真实设备写入版或未绑定本次 run')
    if b'/tmp/a7r5-host/target.bin' in payload:
        raise SystemExit('载荷仍是演练版（target.bin）')
    print('bundle ok:', args.bundle)
    print('run:', operation.run, 'source:', operation.source_sha[:16],
          'candidate:', operation.candidate_sha[:16], 'sectors:', len(operation.plan['rows']))
    if args.validate_only:
        return 0
    if args.output is None:
        raise SystemExit('缺少 --output')
    output = args.output.absolute()
    from system_dump import session
    report = execute(operation, output, session)
    print('trust complete:', report.get('logical_partition_sha256'))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
