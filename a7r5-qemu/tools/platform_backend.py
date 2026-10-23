"""能力探测不导入 POSIX 后端；未验收平台禁止启动。"""
from pathlib import Path
import platform
import sys


def capability(system=None, machine=None):
    system = sys.platform if system is None else system
    machine = platform.machine() if machine is None else machine
    if system != 'darwin' or machine != 'arm64':
        return {'supported': False, 'reason': '当前只验收了 macOS Apple Silicon；此平台不能启动固件'}
    if not Path('/usr/bin/sandbox-exec').is_file():
        return {'supported': False, 'reason': '缺少强制沙箱，拒绝启动'}
    return {'supported': True, 'reason': 'macOS arm64 原生隔离后端'}


def require_backend():
    result = capability()
    if not result['supported']:
        raise RuntimeError(result['reason'])
