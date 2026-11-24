"""使用 macOS USB 枚举或离线快照进行 A7R5 4.00 兼容预检。"""

import argparse
import json
from pathlib import Path
import plistlib
import subprocess
import sys
from xml.parsers.expat import ExpatError

import host_usb


BASELINE_VERSION = '4.00'


def read_usb(snapshot_path):
    if snapshot_path is None:
        if sys.platform != 'darwin':
            raise ValueError('实时 USB 预检仅支持 macOS，可使用 --usb-snapshot 离线检查')
        return host_usb.snapshot()

    tree = plistlib.loads(snapshot_path.read_bytes())
    if not isinstance(tree, list):
        raise ValueError('USB 快照的根节点必须是设备列表')
    return host_usb.parse_ioreg(tree)


def preflight(snapshot_path, firmware_version):
    report = {
        'input': 'offline_snapshot' if snapshot_path is not None else 'live_usb',
        'firmware': {
            'baseline': BASELINE_VERSION,
            'reported': firmware_version,
            'source': 'operator' if firmware_version else 'unavailable',
            'verified_on_device': False,
        },
    }
    try:
        usb = read_usb(snapshot_path)
        report['usb'] = usb
        if usb.get('kind') != 'ordinary' or not usb['drivers']:
            raise ValueError(f'需要唯一一台处于普通 MSC 模式的 {host_usb.MODEL}')
    except (AttributeError, ExpatError, OSError, subprocess.SubprocessError, TypeError, ValueError) as error:
        return 1, dict(report, status='usb_unavailable', message=str(error))

    if firmware_version is None:
        return 2, dict(report, status='firmware_unconfirmed', message='请在相机菜单查看机身版本，再用 --firmware-version 提供版本')
    if firmware_version != BASELINE_VERSION:
        return 2, dict(report, status='firmware_mismatch', message=f'当前仅预检 {BASELINE_VERSION} 基线')
    return 0, dict(report, status='baseline_precheck_passed', message='USB 识别和用户提供的版本符合预检条件，机内状态尚未验证')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--usb-snapshot', type=Path, help='读取已有 ioreg plist 快照，不枚举实时 USB')
    parser.add_argument('--firmware-version', help='在相机菜单查看的机身固件版本')
    args = parser.parse_args(argv)
    code, report = preflight(args.usb_snapshot, args.firmware_version)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
