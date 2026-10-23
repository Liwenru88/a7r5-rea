"""Private live-control transport and serial commands; no caller-supplied shell."""
import base64
import io
import json
import os
import re
import secrets
import select
import socket
import time

from headless_osd_capture import decode_export, HEADER, METADATA

MAX_MESSAGE = 2 * 1024 * 1024
# Add only independently verified mappings here; HTTP accepts symbolic names only.
KEYS = {'MENU': '0x1ab', 'ENTER': '0x1ac', 'UP': '0x3', 'DOWN': '0x30',
        'LEFT': '0x15', 'RIGHT': '0x1af', 'DELETE': '0x1f8', 'C4': '0x1f8',
        'REAR_LEFT': '0x10000013', 'REAR_RIGHT': '0x10000013',
        'FN': '0x7095', 'PLAYBACK': '0x1f7', 'DISP': '0x3',
        'C1':'0x66','C2':'0x70e7','C3':'0x70ec',
        'FRONT_DIAL_LEFT':'0x1000001c','FRONT_DIAL_RIGHT':'0x1000001c',
        'REAR_DIAL_L_LEFT':'0x10000013','REAR_DIAL_L_RIGHT':'0x10000013',
        'REAR_DIAL_R_LEFT':'0x10000016','REAR_DIAL_R_RIGHT':'0x10000016',
        'CONTROL_WHEEL_LEFT':'0x1000001d','CONTROL_WHEEL_RIGHT':'0x1000001d',
        'MODE_AUTO':'0x7025','MODE_P':'0x7025','MODE_A':'0x7025','MODE_S':'0x7025','MODE_M':'0x7025',
        'JOYSTICK_UP':'0x70f7','JOYSTICK_DOWN':'0x70f7','JOYSTICK_LEFT':'0x70f7','JOYSTICK_RIGHT':'0x70f7','JOYSTICK_CENTER':'0x70f7'}
# 仅供固定研究入口；有正反向表与设置种子证据，尚不加入正式输入注册表。
RESEARCH_KEYS = dict(DISP_LEGACY='0x1f9',
                     CUSTOM='0x66', CUSTOM2='0x70e7', CUSTOM3='0x70ec')
TAP_STATUS = {'JOYSTICK_UP':'0x1','JOYSTICK_DOWN':'0x2','JOYSTICK_LEFT':'0x4',
              'JOYSTICK_RIGHT':'0x8','JOYSTICK_CENTER':'0x10'}
# 原厂转换函数按每格 30 / 1024 / 30 / 24 除出步进；不是按下/释放事件。
SINGLE_STATUS = {'REAR_LEFT': '0xfffffc00', 'REAR_RIGHT': '0x400',
                 'FRONT_DIAL_LEFT':'0xffffffe2', 'FRONT_DIAL_RIGHT':'0x1e',
                 'REAR_DIAL_L_LEFT':'0xfffffc00', 'REAR_DIAL_L_RIGHT':'0x400',
                 'REAR_DIAL_R_LEFT':'0xffffffe2', 'REAR_DIAL_R_RIGHT':'0x1e',
                 'CONTROL_WHEEL_LEFT':'0xffffffe8', 'CONTROL_WHEEL_RIGHT':'0x18',
                 'MODE_AUTO':'0x2', 'MODE_P':'0x3', 'MODE_A':'0x5', 'MODE_S':'0x4', 'MODE_M':'0x6'}


class FirmwareFault(RuntimeError):
    pass


class FirmwareMonitor:
    """Follow the complete console, including faults between two commands."""
    def __init__(self, console):
        self.console = console
        self.offset = 0
        self.tail = b''
        self.failed = False

    def check(self):
        if self.failed:
            raise FirmwareFault('相机固件发生异常，已停止接收按键；详情见 console.log')
        with self.console.open('rb') as reader:
            if os.fstat(reader.fileno()).st_size < self.offset:
                self.offset, self.tail = 0, b''
            reader.seek(self.offset)
            while chunk := reader.read(65536):
                self.offset += len(chunk)
                data = self.tail + chunk.replace(b'\r', b'')
                if re.search(rb'(?:^|\n)MEDIA_(?:(?:AUX|RM)_UNSUPPORTED(?: |\n)|DATAFLOW_FATAL(?: |\n))',data):
                    self.failed=True
                    raise FirmwareFault('研究模型明确拒绝协议或传输失败，停止后续客体请求；详情见 console.log')
                if re.search(rb'(?:^|\n)(?:Entering exception monitor\.|Exception>)', data):
                    self.failed = True
                    raise FirmwareFault('相机固件发生异常，已停止接收按键；详情见 console.log')
                self.tail = data[-128:]


def key_command(key):
    code = (RESEARCH_KEYS if key in RESEARCH_KEYS else KEYS)[key]
    prefix = f'/simulation/inject-key 0x807a0020 0x92840747 {code} 0'
    if key in SINGLE_STATUS:
        return f'{prefix} {SINGLE_STATUS[key]} 0 1'
    # The native UI expects 1/0. A 50 ms guest tap avoids firmware auto-repeat.
    pressed=TAP_STATUS.get(key,'1')
    return (f'{prefix} {pressed} 0 1; pressed=$?; sleep 0.05; '
            f'{prefix} 0 0 1; released=$?; test "$pressed" = 0 && test "$released" = 0')


def send_message(sock, value):
    sock.sendall(json.dumps(value, ensure_ascii=True).encode() + b'\n')


def receive_message(sock, timeout=120, cancelled=lambda: False):
    deadline = time.monotonic() + timeout
    data = bytearray()
    while time.monotonic() < deadline:
        if cancelled():
            raise RuntimeError('操作已取消')
        if not select.select([sock], [], [], min(.2, max(0, deadline - time.monotonic())))[0]:
            continue
        chunk = sock.recv(65536)
        if not chunk:
            raise RuntimeError('VM 控制通道已关闭')
        data.extend(chunk)
        if len(data) > MAX_MESSAGE:
            raise ValueError('控制消息过大')
        if b'\n' in data:
            if not data.endswith(b'\n') or data.count(b'\n') != 1:
                raise ValueError('控制消息边界错误')
            value = json.loads(data)
            if not isinstance(value, dict):
                raise ValueError('控制消息类型错误')
            return value
    raise TimeoutError('等待 VM 命令完成超时')


def clean_console(data):
    return re.sub(rb'\[\s*\d+\.\d+\] (?:UDIF:|\[K\])[^\n]*\n', b'', data.replace(b'\r\n', b'\n'))


def serial_command(proc, console, command, timeout=90, monitor=None):
    """Ignore echoed commands/prompts and require this command's exact RC sentinel."""
    monitor = monitor or FirmwareMonitor(console)
    monitor.check()
    marker = 'MENU_DIAG_COMMAND_DONE_' + secrets.token_hex(12)
    # Live console writers use O_APPEND; discard old exports only between commands.
    if console.stat().st_size > 16 * 1024 * 1024:
        with console.open('r+b') as old:
            old.truncate(0)
    with console.open('rb') as reader:
        reader.seek(0, 2)
        proc.stdin.write((command + "; rc=$?; printf '\\n" + marker + ":%s\\n' \"$rc\"\n").encode())
        proc.stdin.flush()
        data = bytearray()
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            monitor.check()
            # 排空已有输出再等待，避免每 64 KiB 人为停顿一次。
            chunk = reader.read(1024 * 1024)
            data.extend(chunk)
            if len(data) > 8 * 1024 * 1024:
                raise RuntimeError('单次串口输出超过限制')
            clean = clean_console(bytes(data))
            if b'Exception>' in clean:
                raise RuntimeError('固件进入异常监视器')
            match = re.search(rb'\n' + marker.encode() + rb':([0-9]+)\n', clean)
            if match:
                if int(match[1]):
                    raise RuntimeError('guest 命令失败，返回码 ' + match[1].decode())
                return bytes(data)
            if proc.poll() is not None:
                raise RuntimeError('VM 进程提前退出')
            if not chunk:
                time.sleep(.005)
    raise TimeoutError('串口命令缺少完成标记；停止 VM 以避免后续命令交错')


def snapshot_png(raw):
    """只转换已校验容器；与独立逐像素检查保持完全一致。"""
    from PIL import Image
    pixels = raw[HEADER + METADATA:]
    # Pillow 的 4B 解码得到相反通道顺序；用其 C 实现拆分重排，避免 Python 像素循环。
    reverse = Image.frombytes('RGBA', (640, 480), pixels, 'raw', 'RGBA;4B')
    a, b, g, r = reverse.split()
    image = Image.merge('RGBA', (r, g, b, a))
    buffer = io.BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()


def snapshot_message(console):
    raw, info = decode_export(console)
    return {'type': 'snapshot', 'info': info, 'captured_at': time.time(),
            'png': base64.b64encode(snapshot_png(raw)).decode()}


