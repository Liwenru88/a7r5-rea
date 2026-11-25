"""使用 macOS USB 枚举或离线快照进行只读预检。"""

import argparse
import json
from pathlib import Path
import plistlib
import subprocess
import sys
from xml.parsers.expat import ExpatError

import host_usb


BASELINE_VERSION = '4.00'
USB_TARGETS = {'rp2040': (0x2e8a, None), 'fastboot': (0x18d1, 0x4ee0)}


def read_usb(snapshot_path):
    if snapshot_path is None:
        if sys.platform != 'darwin':
            raise ValueError('实时 USB 预检仅支持 macOS，可使用 --usb-snapshot 离线检查')
        raw = host_usb.read_ioreg()
        tree = plistlib.loads(raw) if raw.strip() else []
    else:
        tree = plistlib.loads(snapshot_path.read_bytes())
    if not isinstance(tree, list):
        raise ValueError('USB 快照的根节点必须是设备列表')
    return tree


def match_usb(tree, target):
    if target not in USB_TARGETS:
        return host_usb.parse_ioreg(tree)

    vid, pid = USB_TARGETS[target]
    matches = [
        node for node in host_usb.usb_devices(tree)
        if node.get('idVendor') == vid and (pid is None or node.get('idProduct') == pid)
    ]
    if not matches:
        return {'kind': 'absent', 'present': False}
    if len(matches) != 1:
        raise ValueError(f'发现多个 {target} USB 设备，请只连接一个目标')
    entry = matches[0]
    return {
        'kind': target,
        'present': True,
        'location_id': entry.get('locationID'),
        'pid': entry.get('idProduct'),
        'observed_product': entry.get('USB Product Name'),
    }


def preflight(snapshot_path, firmware_version, target='msc'):
    report = {'input': 'offline_snapshot' if snapshot_path is not None else 'live_usb'}
    if target == 'msc':
        report['firmware'] = {
            'baseline': BASELINE_VERSION,
            'reported': firmware_version,
            'source': 'operator' if firmware_version else 'unavailable',
            'verified_on_device': False,
        }
    try:
        usb = match_usb(read_usb(snapshot_path), target)
        report['usb'] = usb
        if target == 'msc' and (usb.get('kind') != 'ordinary' or not usb['drivers']):
            raise ValueError(f'需要唯一一台处于普通 MSC 模式的 {host_usb.MODEL}')
        if not usb['present']:
            raise ValueError(f'未发现 {target} 对应的 USB 设备')
    except (AttributeError, ExpatError, OSError, subprocess.SubprocessError, TypeError, ValueError) as error:
        return 1, dict(report, status='usb_unavailable', message=str(error))

    if target != 'msc':
        return 0, dict(report, status='usb_observed', message='已识别唯一匹配的 USB 设备，尚未验证设备通信、机内版本或恢复结果')
    if firmware_version is None:
        return 2, dict(report, status='firmware_unconfirmed', message='请在相机菜单查看机身版本，再用 --firmware-version 提供版本')
    if firmware_version != BASELINE_VERSION:
        return 2, dict(report, status='firmware_mismatch', message=f'当前仅预检 {BASELINE_VERSION} 基线')
    return 0, dict(report, status='baseline_precheck_passed', message='USB 识别和用户提供的版本符合预检条件，机内状态尚未验证')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('target', nargs='?', default='msc', choices=('msc', 'recovery', *USB_TARGETS))
    parser.add_argument('--usb-snapshot', type=Path, help='读取已有 ioreg plist 快照，不枚举实时 USB')
    parser.add_argument('--firmware-version', help='在相机菜单查看的机身固件版本')
    args = parser.parse_args(argv)
    if args.target != 'msc' and args.firmware_version is not None:
        parser.error('此入口只报告 USB 枚举状态，无需提供固件版本')
    code, report = preflight(args.usb_snapshot, args.firmware_version, args.target)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return code


if __name__ == '__main__':
    raise SystemExit(main())
