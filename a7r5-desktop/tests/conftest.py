"""测试默认阻断硬件和外网；协议测试只能显式替换为内存设备。"""
from pathlib import Path
import sys
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'engine'), str(ROOT/'prepared/engine/site'), str(ROOT/'prepared/engine/vendor/pmca_source')]
import pytest
import common


@pytest.fixture(autouse=True)
def no_camera(monkeypatch):
    import socket
    import subprocess
    import usb.core
    import usb.backend.libusb1
    def forbidden(*a, **k):raise AssertionError('测试禁止实际设备、授权及IP连接')
    monkeypatch.setattr(usb.core, 'find', forbidden)
    monkeypatch.setattr(usb.backend.libusb1, 'get_backend', forbidden)
    monkeypatch.setattr(socket, 'create_connection', forbidden)
    monkeypatch.setattr(socket.socket, 'connect', forbidden)
    original = subprocess.Popen
    def process(argv, *args, **kwargs):
        if not isinstance(argv, (tuple, list)) or kwargs.get('shell') or Path(argv[0]).name in ('sudo','osascript','ioreg','diskutil','ssh','scp','sftp','qemu-aarch64'):
            return forbidden()
        return original(argv, *args, **kwargs)
    monkeypatch.setattr(subprocess, 'Popen', process)
    monkeypatch.setattr(common, 'ROOT', ROOT/'prepared/engine')
    import device
    monkeypatch.setattr(device, 'ROOT', ROOT/'prepared/engine')
    import system_dump.environment
    monkeypatch.setattr(system_dump.environment, 'PMCA', ROOT/'prepared/engine/vendor/pmca_source')


@pytest.fixture
def baseline():
    return dict(kind='ordinary', model='ILCE-7RM5', location_id=0x14100000, media=[[True,100000]], drivers=['IOUSBMassStorageDriver'])
