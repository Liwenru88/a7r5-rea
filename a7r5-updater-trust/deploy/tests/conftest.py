"""本测试集只使用本机文件和模拟USB；所有真实设备入口默认拒绝。"""
from pathlib import Path
import json
import os
import sys
import subprocess
import pytest

HERE=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(HERE),str(HERE/'runtime'),str(HERE/'vendor/engine/libs'),str(HERE/'vendor/engine/mac')]
import usb.core,usb.backend.libusb1
import host_state


@pytest.fixture(autouse=True)
def no_real_devices(monkeypatch):
    def forbidden(*args,**kwargs):raise AssertionError('离线测试禁止接入真实设备或观察相机')
    monkeypatch.setattr(usb.core,'find',forbidden)
    monkeypatch.setattr(usb.backend.libusb1,'get_backend',forbidden)
    monkeypatch.setattr(host_state,'snapshot',forbidden)
    original=subprocess.run
    def safe_run(argv,*args,**kwargs):
        if isinstance(argv,str):raise AssertionError('测试禁止shell命令')
        if Path(argv[0]).name in ('ioreg','diskutil','sudo','ssh','scp','open'):forbidden()
        return original(argv,*args,**kwargs)
    monkeypatch.setattr(subprocess,'run',safe_run)


@pytest.fixture(scope='session')
def sealed():
    path=Path(os.environ['A7R5_TRUST_TEST_RUN'])
    assert (path/'manifest.json').is_file()
    return path
