"""离线测试门禁：拦截USB、主机设备查询、sudo、原始磁盘和网络连接。"""
from pathlib import Path
import builtins
import io
import os
import socket
import subprocess
import sys

HERE=Path(__file__).resolve().parent
libs=HERE/'vendor/engine/libs'
if not libs.exists():libs=HERE.parent/'a7r5-implementation-kit/engine/libs'
sys.path[:0]=[str(HERE),str(libs)]
def forbidden(*a,**k):raise AssertionError('离线验证禁止设备、网络、sudo和原始卡')
import usb.core
import usb.backend.libusb1
usb.core.find=forbidden;usb.backend.libusb1.get_backend=forbidden;usb.backend.libusb1._LibUSB.__init__=forbidden
socket.socket.connect=forbidden;socket.create_connection=forbidden
def opened(original):
    def wrapper(path,*a,**k):
        if isinstance(path,(str,bytes,os.PathLike)) and os.fsdecode(path).startswith('/dev/') and os.fsdecode(path)!='/dev/null':forbidden()
        return original(path,*a,**k)
    return wrapper
os.open=opened(os.open);io.open=opened(io.open);builtins.open=opened(builtins.open)
original=subprocess.Popen
def popen(argv,*a,**k):
    if not isinstance(argv,(list,tuple)) or k.get('shell') or Path(argv[0]).name in ('sudo','open','ioreg','diskutil','ssh','scp','system_profiler'):forbidden()
    return original(argv,*a,**k)
subprocess.Popen=popen
os.environ['PYTEST_DISABLE_PLUGIN_AUTOLOAD']='1'
import pytest
raise SystemExit(pytest.main(['-q','--capture=sys','-p','no:cacheprovider','-p','no:logging','--tb=short',str(HERE/'tests'),*sys.argv[1:]]))
