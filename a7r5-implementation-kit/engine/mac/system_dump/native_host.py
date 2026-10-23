"""预先编译的 IOUSBHost 适配；导入不会枚举或接管 USB。"""

import ctypes
from pathlib import Path

from .core import NORMAL_PID, VID


def load_library():
    library = ctypes.CDLL(str(Path(__file__).with_name("native_usb.dylib")))
    library.a7_usb_error.restype = ctypes.c_char_p
    library.a7_usb_open.argtypes = [ctypes.c_uint32, ctypes.c_uint16, ctypes.c_uint16,
                                   ctypes.c_uint8, ctypes.c_uint8]
    library.a7_usb_open.restype = ctypes.c_void_p
    library.a7_usb_close.argtypes = [ctypes.c_void_p]
    library.a7_usb_close.restype = None
    library.a7_usb_surrender.argtypes = [ctypes.c_void_p]
    library.a7_usb_surrender.restype = None
    for name in ("a7_usb_write", "a7_usb_read"):
        function = getattr(library, name)
        function.argtypes = [ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32]
        function.restype = ctypes.c_int
    library.a7_usb_control.argtypes = [ctypes.c_void_p, ctypes.c_uint16, ctypes.c_uint16, ctypes.c_uint32]
    library.a7_usb_control.restype = ctypes.c_int
    return library


class NativeDevice:
    is_native_host = True

    def __init__(self, device, endpoints):
        self.idVendor, self.idProduct = device.idVendor, device.idProduct
        self.bus, self.port_numbers = device.bus, tuple(device.port_numbers or ())
        if self.idVendor != VID or self.idProduct not in (NORMAL_PID, 0x0336):
            raise ValueError("原生后端拒绝未知目标")
        if not 1 <= len(self.port_numbers) <= 5 or any(not 1 <= p <= 15 for p in self.port_numbers):
            raise ValueError("原生后端端口不可识别")
        self.endpoints = endpoints
        incoming = [e.bEndpointAddress for e in endpoints if e.bmAttributes & 3 == 2 and e.bEndpointAddress & 0x80]
        outgoing = [e.bEndpointAddress for e in endpoints if e.bmAttributes & 3 == 2 and not e.bEndpointAddress & 0x80]
        if not incoming or not outgoing: raise ValueError("原生后端缺少 bulk 端点")
        self.ep_in, self.ep_out = incoming[0], outgoing[0]
        self.library = load_library()
        location = (self.bus << 24) | sum(p << (20 - 4 * i) for i, p in enumerate(self.port_numbers))
        self.handle = self.library.a7_usb_open(location, self.idVendor, self.idProduct, self.ep_in, self.ep_out)
        if not self.handle: self.check(-1)

    def check(self, result):
        if result < 0:
            from usb.core import USBError
            message = self.library.a7_usb_error().decode("utf-8", errors="replace")
            raise USBError(message, error_code=result)
        return result

    def get_active_configuration(self):
        return {(0, 0): self.endpoints}

    def close(self, surrender=False):
        if self.handle:
            close = self.library.a7_usb_surrender if surrender else self.library.a7_usb_close
            close(self.handle)
            self.handle = None

    def write(self, endpoint, data, timeout):
        if endpoint != self.ep_out or not self.handle: raise PermissionError("原生写端点/状态被拒绝")
        buffer = ctypes.create_string_buffer(bytes(data))
        return self.check(self.library.a7_usb_write(self.handle, buffer, len(data), timeout))

    def read(self, endpoint, size, timeout):
        if endpoint != self.ep_in or not self.handle or not 1 <= size <= 4100:
            raise PermissionError("原生读端点/长度/状态被拒绝")
        buffer = ctypes.create_string_buffer(size)
        count = self.check(self.library.a7_usb_read(self.handle, buffer, size, timeout))
        if count > size: raise ValueError("原生响应越界")
        return buffer.raw[:count]

    def ctrl_transfer(self, request_type, request, value, index, data, timeout):
        if request_type != 0x43 or request != 1 or data or (value, index) not in ((0x37FF, 0xD7AA), (0xC800, 0x2855)):
            raise PermissionError("原生后端拒绝其他控制请求")
        return self.check(self.library.a7_usb_control(self.handle, value, index, timeout))
