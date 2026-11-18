#!/usr/bin/env python3
"""Passively log macOS USB-tree presence of Fastboot VID:PID 18d1:4ee0.

This script only runs `ioreg -p IOUSB -l -w 0` and parses its text output. It does
not open USB devices, claim interfaces, send USB transfers, touch serial ports,
or reset/send payloads to a camera.
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import sys
import time
from pathlib import Path

TARGET_VID = 0x18D1
TARGET_PID = 0x4EE0
VID_RE = re.compile(r'"idVendor"\s*=\s*(\d+)')
PID_RE = re.compile(r'"idProduct"\s*=\s*(\d+)')
NAME_RE = re.compile(r'"USB Product Name"\s*=\s*"([^"]*)"')
NODE_RE = re.compile(r'^\s*\+-o\s+(.+?)(?:\s+<|$)')


def parse_ioreg(text):
    """Return target-device observations from ioreg text."""
    observations = []
    current = None
    for line in text.splitlines():
        node = NODE_RE.match(line)
        if node:
            if current and current.get('vid') == TARGET_VID and current.get('pid') == TARGET_PID:
                observations.append(current)
            current = {'node': node.group(1).strip()}
            continue
        if current is None:
            continue
        match = VID_RE.search(line)
        if match:
            current['vid'] = int(match.group(1))
            continue
        match = PID_RE.search(line)
        if match:
            current['pid'] = int(match.group(1))
            continue
        match = NAME_RE.search(line)
        if match:
            current['product_name'] = match.group(1)
    if current and current.get('vid') == TARGET_VID and current.get('pid') == TARGET_PID:
        observations.append(current)
    return observations


def snapshot(input_path=None):
    if input_path:
        text = Path(input_path).read_text(errors='replace')
    else:
        result = subprocess.run(['ioreg', '-p', 'IOUSB', '-l', '-w', '0'],
                                capture_output=True, text=True, check=True)
        text = result.stdout
    devices = parse_ioreg(text)
    return {
        'timestamp': dt.datetime.now(dt.timezone.utc).isoformat(),
        'fastboot_present': bool(devices),
        'devices': devices,
        'vid': f'{TARGET_VID:04x}' if devices else None,
        'pid': f'{TARGET_PID:04x}' if devices else None,
        'usb_operations': [],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument('--once', action='store_true', help='take one passive snapshot')
    mode.add_argument('--watch', action='store_true', help='poll the USB tree until Ctrl+C')
    parser.add_argument('--input', type=Path, help='offline ioreg text fixture; never invokes ioreg')
    parser.add_argument('--output', type=Path, required=True, help='new JSONL output file')
    parser.add_argument('--interval', type=float, default=0.1, help='watch interval in seconds')
    args = parser.parse_args()
    if args.interval <= 0:
        parser.error('--interval must be positive')
    if args.output.exists():
        parser.error('output file already exists; choose a new path')
    if args.watch and args.input:
        parser.error('--input is only valid with --once')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    present = False
    try:
        with args.output.open('x', encoding='utf-8') as out:
            while True:
                report = snapshot(args.input)
                json.dump(report, out, ensure_ascii=False)
                out.write('\n')
                out.flush()
                print(json.dumps(report, ensure_ascii=False), flush=True)
                present = present or report['fastboot_present']
                if args.once:
                    break
                time.sleep(args.interval)
    except KeyboardInterrupt:
        return 0 if present else 1
    return 0 if present else 1


if __name__ == '__main__':
    sys.exit(main())
