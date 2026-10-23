"""禁止真实USB、磁盘查询或sudo后运行本包测试；普通文件ext2夹具允许/dev/fd继承。"""
import builtins
import io
import os
from pathlib import Path
import subprocess
import sys

BASE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BASE))
from tools.common import ENGINE
import usb.core
import usb.backend.libusb1


def forbidden(*args, **kwargs):
    raise AssertionError('离线验证禁止访问真实USB、原始磁盘或主机设备查询')


usb.core.find = forbidden
usb.backend.libusb1.get_backend = forbidden
usb.backend.libusb1._LibUSB.__init__ = forbidden


def guard_open(original):
    def guarded(path, *a, **k):
        if isinstance(path, (str, bytes, os.PathLike)) and os.fsdecode(path).startswith('/dev/'):
            forbidden()
        return original(path, *a, **k)
    return guarded


os.open = guard_open(os.open)
io.open = guard_open(io.open)
builtins.open = guard_open(builtins.open)
original_popen = subprocess.Popen


def guarded_popen(argv, *a, **k):
    if (not isinstance(argv, (list, tuple)) or k.get('shell')
            or Path(argv[0]).name in ('sudo', 'open', 'diskutil', 'ioreg', 'system_profiler')
            or Path(argv[0]).name.startswith(('newfs', 'fsck', 'mount', 'umount'))):
        forbidden()
    # debugfs只允许默认只读模式，源须为继承的、指向普通文件的描述符。
    if Path(argv[0]).name == 'debugfs':
        import stat
        if '-w' in argv:
            forbidden()
        for fd in k.get('pass_fds', ()):
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                forbidden()
    return original_popen(argv, *a, **k)


subprocess.Popen = guarded_popen
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD'] = '1'
import pytest
raise SystemExit(pytest.main(['-q', '--capture=sys', '-p', 'no:cacheprovider', '-p', 'no:logging',
                             '--tb=short', str(BASE / 'tests'), *sys.argv[1:]]))
