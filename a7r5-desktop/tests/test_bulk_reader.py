"""复现原生超时带部分字节被隐藏的契约；不加载或调用真实USB库。"""
from array import array
import ctypes
from types import SimpleNamespace

import pytest

from system_dump.bulk_reader import StrictReadBackend,file_read_limit


@pytest.mark.parametrize('status,count',[(0,32768),(0,24576),(-7,24576),(-7,0),(-9,0)])
def test_native_status_and_partial_count_are_preserved(monkeypatch,status,count):
    import usb.backend.libusb1 as libusb
    import usb.core
    # 使用随包PyUSB的真实方法对照；底层函数仅填充本机array。
    monkeypatch.setattr(libusb,'_strerror',lambda code:'native-fixture')
    calls=[];data=bytes(range(256))*(32768//256)
    def transfer(handle,endpoint,buffer,length,transferred,timeout):
        calls.append((handle,endpoint,length,timeout))
        ctypes.memmove(buffer,data,count)
        ctypes.cast(transferred,ctypes.POINTER(ctypes.c_int))[0]=count
        return status
    class MemoryBackend(libusb._LibUSB):
        def __init__(self):self.lib=SimpleNamespace(libusb_bulk_transfer=transfer)
    raw=MemoryBackend()
    handle=SimpleNamespace(handle=123)
    if status in (0,-7) and count:
        old=array('B',[0])*32768
        assert raw.bulk_read(handle,129,0,old,8000)==count
    reader=StrictReadBackend(raw);buffer=array('B',[0])*32768
    if status:
        with pytest.raises(usb.core.USBError) as caught:reader.bulk_read(handle,129,0,buffer,8000)
        assert caught.value.backend_error_code==status
        assert caught.value.usb_partial_data==data[:count]
        assert caught.value.usb_transferred_bytes==count and caught.value.usb_requested_bytes==32768
    else:
        assert reader.bulk_read(handle,129,0,buffer,8000)==count and bytes(buffer[:count])==data[:count]
    assert all(call==(123,129,32768,8000) for call in calls)
    assert len(calls)==(2 if status in (0,-7) and count else 1)


def test_backend_delegation_and_read_size_reject_invalid_policy():
    token=object();raw=SimpleNamespace(enumerate_devices=lambda:token)
    assert StrictReadBackend(raw).enumerate_devices() is token
    assert file_read_limit(SimpleNamespace())==32768
    assert file_read_limit(SimpleNamespace(usb_read_size=8192))==8192
    with pytest.raises(ValueError):file_read_limit(SimpleNamespace(usb_read_size=513))
