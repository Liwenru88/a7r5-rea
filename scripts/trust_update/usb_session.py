"""动态端口 USB 会话与 Senser 协议通道（支持 0e0a→0336→认证→操作→单次 STOP）。"""
import ctypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import plistlib
import re
import struct
import subprocess
import sys
import time
import traceback

import host_usb

HEADER = struct.Struct('<IHHBBBB')
READ = struct.pack('<HH', 0x1001, 17) + b'\0\xff\0'
START = (1, 0x37FF, 0xD7AA)
STOP = (1, 0xC800, 0x2855)


class StrictReadBackend:
    """限制单次 USB 读取并保留底层部分接收数据，遇错立即停止。"""

    def __init__(self, backend):
        self.backend = backend

    def __getattr__(self, name):
        return getattr(self.backend, name)

    def bulk_read(self, handle, endpoint, interface, buffer, timeout):
        address, length = buffer.buffer_info()
        length *= buffer.itemsize
        transferred = ctypes.c_int()
        status = self.backend.lib.libusb_bulk_transfer(
            handle.handle,
            endpoint,
            ctypes.cast(address, ctypes.POINTER(ctypes.c_ubyte)),
            length,
            ctypes.byref(transferred),
            timeout,
        )
        status = getattr(status, 'value', status)
        count = transferred.value
        if not 0 <= count <= length:
            raise OSError('libusb 返回接收长度越界')
        if status:
            from usb.backend.libusb1 import _check

            try:
                _check(status)
            except Exception as error:
                error.usb_partial_data = bytes(memoryview(buffer).cast('B')[:count])
                error.usb_requested_bytes = length
                error.usb_transferred_bytes = count
                raise
            raise OSError('libusb 返回未知状态')
        return count


class FileResultError(ValueError):
    """相机文件服务返回非零状态码。"""

    def __init__(self, result, *, action=None, path=None):
        self.result = result
        self.action = action
        self.path = path
        meanings = {
            ('read', 0x10000006): '元数据查询失败（不证明文件不存在）',
            ('read', 0x10000008): '读取请求被拒绝',
            ('read', 0x1000000a): '读取长度不符',
            ('write', 0x10000008): '打开目标文件失败',
            ('write', 0x10000009): '写入长度不符',
            ('write', 0x1000000f): '工作区容量检查未通过',
        }
        label = {'select': '选择文件', 'read': '读取文件', 'write': '上传文件'}.get(action, '文件请求')
        detail = meanings.get((action, result), '未知文件错误')
        super().__init__(f'{label}失败：{detail}（0x{result:08x}）' + (f'；路径：{path}' if path else ''))


def wire(path):
    return (path if path.startswith('/tmp/jiritsu/') else '/tmp/jiritsu/../..' + path).encode()


class Channel:
    """固定 Senser 文件/控制通道；报文逐条校验并严格递增序号。"""

    def __init__(self, driver, operation, log):
        self.driver = driver
        self.operation = operation
        self.log = log
        self.sequence = 1
        self.usable = True
        self.packet_limit = getattr(operation, 'packet_limit', 512)
        if type(self.packet_limit) is not int or self.packet_limit not in (512, 4096):
            raise ValueError('未知报文预算')

    def exchange(self, body, limit, *, action=None, path=None):
        if not self.usable or self.sequence > self.packet_limit:
            raise PermissionError('通道失步或报文数超限，停止发送')
        self.log(
            'file_request',
            action=action,
            path=path,
            sequence=self.sequence,
            request_bytes=len(body),
            response_limit=limit,
        )
        self.usable = False
        packet = HEADER.pack(len(body), 0x40, self.sequence, 0, 0, 0, 0) + body
        self.operation.permitted_packet = packet
        try:
            self.operation.guard_packet(packet)
            if self.driver.write(packet) != len(packet):
                raise OSError('USB 短写，不重传')
        finally:
            self.operation.permitted_packet = None

        raw = self.driver.read(HEADER.size)
        self.log('response_header', raw_hex=raw.hex(), sequence=self.sequence, limit=limit)
        if len(raw) != HEADER.size:
            raise ValueError('响应头长度异常')
        size, function, sequence, version, micon, offset, status = HEADER.unpack(raw)
        if function != 0x40 or sequence != self.sequence or not 4 <= size <= limit or status:
            raise ValueError('响应头字段异常')

        data = bytearray()
        try:
            frame_end = min(0x100000, size)
            while len(data) < size:
                block_start = len(data)
                block_end = min(block_start + 0x8000, frame_end)
                while len(data) < block_end:
                    requested = block_end - len(data)
                    try:
                        chunk = self.driver.read(requested)
                    except Exception as exc:
                        partial = getattr(exc, 'usb_partial_data', b'')
                        if partial and len(partial) <= requested:
                            data.extend(partial)
                            self.log(
                                'response_native_error_partial',
                                sequence=self.sequence,
                                received=len(partial),
                                requested=getattr(exc, 'usb_requested_bytes', requested),
                                backend_error_code=getattr(exc, 'backend_error_code', None),
                            )
                        raise
                    self.log(
                        'response_body_fragment',
                        sequence=self.sequence,
                        offset=len(data),
                        requested=requested,
                        received=len(chunk),
                        block_end=block_end,
                    )
                    if not chunk or len(chunk) > requested:
                        raise ValueError('响应体边界异常')
                    data.extend(chunk)
                block_size = block_end - block_start
                if block_size % 512 == 0:
                    boundary = self.driver.read(512)
                    self.log('response_block_boundary', sequence=self.sequence, offset=len(data), received=len(boundary))
                    if boundary != b'':
                        raise ValueError('缺少分块空边界包')
                if len(data) == frame_end and len(data) < size:
                    raw = self.driver.read(HEADER.size)
                    self.log(
                        'response_continuation_header',
                        raw_hex=raw.hex(),
                        sequence=self.sequence,
                        received=len(data),
                        remaining=size - len(data),
                    )
                    if len(raw) != HEADER.size:
                        raise ValueError('后续响应头长度异常')
                    remaining, part_function, part_sequence, *part_meta = HEADER.unpack(raw)
                    if (
                        remaining != size - len(data)
                        or part_function != 0x40
                        or part_sequence != self.sequence
                        or part_meta[-1]
                    ):
                        raise ValueError('后续响应头字段异常')
                    frame_end = len(data) + min(0x100000, remaining)
        except BaseException as exc:
            self.log(
                'response_body_failed',
                sequence=self.sequence,
                received=len(data),
                expected=size,
                partial_sha256=hashlib.sha256(data).hexdigest(),
                error=f'{type(exc).__name__}: {exc}',
            )
            output = getattr(self.operation, 'output', None)
            if output is not None:
                (output / f'response-{self.sequence:03}-partial.bin').write_bytes(data)
            raise

        self.sequence += 1
        self.usable = True
        result, = struct.unpack_from('<I', data)
        self.log(
            'file_result',
            result=hex(result),
            bytes=size - 4,
            version=version,
            micon=micon,
            offset=offset,
            action=action,
            path=path,
            sequence=self.sequence - 1,
        )
        if result:
            raise FileResultError(result, action=action, path=path)
        return bytes(data[4:])

    def select(self, path):
        self.exchange(struct.pack('<HH', 0x1001, 15) + b'\0' + wire(path) + b'\0', 4, action='select', path=path)

    def read(self, path, limit):
        if self.operation.reads.get(path) != limit:
            raise PermissionError(f'不在固定读取清单中：{path}')
        self.select(path)
        return self.exchange(READ, limit + 4, action='read', path=path)

    def put(self, path, data):
        if self.operation.writes.get(path) != data:
            raise PermissionError(f'不在固定写入清单中：{path}')
        self.select(path)
        if self.exchange(struct.pack('<HH', 0x1001, 16) + b'\0\xff\0' + data, 4, action='write', path=path):
            raise ValueError('写入返回非零负载')


def same_port(device, port):
    observed = (device.bus, tuple(device.port_numbers or ()))
    if not port[1] or observed != port:
        raise ValueError(f'设备物理端口改变：期望 {port}，实际 {observed}')
    return True


def claim_interface(device, usb_util, log, *, allow_settle=False):
    """接管 USB 接口 0；若原厂大容量存储驱动已挂载，先卸载并分离内核驱动。"""
    detached = False
    port = (device.bus, tuple(device.port_numbers or ()))
    try:
        active = device.is_kernel_driver_active(0)
        log('kernel_driver_state', active=active)
        if active:
            device.detach_kernel_driver(0)
            detached = True
            log('kernel_driver_detached')
    except NotImplementedError:
        pass

    try:
        for attempt in range(1, 4):
            same_port(device, port)
            log('interface_claim_requested', attempt=attempt)
            try:
                usb_util.claim_interface(device, 0)
                break
            except Exception as exc:
                log(
                    'interface_claim_failed',
                    attempt=attempt,
                    error_type=type(exc).__name__,
                    message=str(exc),
                    backend_error_code=getattr(exc, 'backend_error_code', None),
                )
                if (
                    not allow_settle
                    or sys.platform != 'darwin'
                    or not detached
                    or getattr(exc, 'backend_error_code', None) != -99
                    or attempt == 3
                ):
                    raise
                time.sleep(0.25)
        log('interface_claimed')
    except BaseException:
        if detached:
            try:
                same_port(device, port)
                device.attach_kernel_driver(0)
            except Exception as cleanup_error:
                log('kernel_driver_reattach_failed', message=str(cleanup_error))
        raise
    return detached


def _plist_cmd(args):
    return plistlib.loads(subprocess.run(args, check=True, capture_output=True, timeout=15).stdout)


def unmount_camera(device, log):
    """动态识别当前端口下的相机磁盘节点并全部卸载。"""
    ports = tuple(device.port_numbers or ())
    if not 1 <= len(ports) <= 5 or any(not 1 <= p <= 15 for p in ports):
        raise ValueError('无法把 libusb 端口映射到 macOS locationID')
    location = (device.bus << 24) | sum(p << (20 - 4 * i) for i, p in enumerate(ports))
    tree = _plist_cmd(['/usr/sbin/ioreg', '-a', '-l', '-r', '-c', 'IOUSBHostDevice'])

    targets = []

    def visit(node):
        if (
            node.get('IOObjectClass') == 'IOUSBHostDevice'
            and (node.get('idVendor'), node.get('idProduct'), node.get('locationID'))
            == (host_usb.VID, host_usb.PID_ORDINARY, location)
        ):
            if node.get('USB Product Name') != host_usb.MODEL:
                raise ValueError('IORegistry 产品名与 A7R5 不符')
            targets.append(node)
        for child in node.get('IORegistryEntryChildren', []):
            visit(child)

    for root in tree:
        visit(root)
    if len(targets) != 1:
        raise ValueError('无法唯一定位相机 USB 子树')

    media = []

    def collect(node):
        if 'BSD Name' in node:
            name = node['BSD Name']
            if not re.fullmatch(r'disk[0-9]+(?:s[0-9]+)?', name):
                raise ValueError(f'异常磁盘设备名：{name}')
            media.append({'device': name, 'whole': node.get('Whole', False), 'bytes': node.get('Size')})
        for child in node.get('IORegistryEntryChildren', []):
            collect(child)

    collect(targets[0])
    if not any(m['whole'] for m in media):
        log('camera_no_media_to_unmount', location_id=hex(location))
        return

    for entry in media:
        info = _plist_cmd(['/usr/sbin/diskutil', 'info', '-plist', entry['device']])
        entry['mount_point'] = info.get('MountPoint', '')
    log('camera_media_identified', location_id=hex(location), media=media)

    for entry in media:
        if entry['whole']:
            result = subprocess.run(
                ['/usr/sbin/diskutil', 'unmountDisk', entry['device']],
                check=True,
                capture_output=True,
                text=True,
                timeout=20,
            )
            log('camera_disk_unmounted', device=entry['device'], message=result.stdout.strip())

    for entry in media:
        info = _plist_cmd(['/usr/sbin/diskutil', 'info', '-plist', entry['device']])
        if info.get('MountPoint'):
            raise RuntimeError(f'相机卷 {entry["device"]} 仍挂载，中止进入服务通道')


def run_session(output, operation, *, timeout_seconds=120):
    """执行一次完整的 0e0a → 0336 服务通道 → 写入校验 → 单次 STOP 闭环。"""
    host_usb.ensure_usb_paths()
    import usb.core
    import usb.util
    import usb.backend.libusb1
    from pmca.usb.sony import SonySenserAuthDevice

    output = Path(output).absolute()
    output.mkdir(parents=True, exist_ok=True, mode=0o700)
    report = {
        'model': host_usb.MODEL,
        'first_authentication_passed': False,
        'second_authentication_passed': False,
        'service_start_requested': False,
        'camera_protocol_requests': 0,
        'phase': 'device_discovery',
        'service_stop_attempts': 0,
        'service_stop_result': 'not_attempted',
        'evidence_dir': str(output),
    }

    def log(event, **fields):
        record = {'time': datetime.now(timezone.utc).isoformat(), 'event': event, **fields}
        with (output / 'events.jsonl').open('a') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')

    libusb_path = host_usb.find_libusb()
    backend = usb.backend.libusb1.get_backend(find_library=lambda _: str(libusb_path))
    if backend is None:
        raise RuntimeError('libusb 后端不可用')
    read_limit = getattr(operation, 'usb_read_size', 8192)
    report['file_usb_read_limit'] = read_limit
    if getattr(operation, 'strict_usb_reads', True):
        backend = StrictReadBackend(backend)

    current = None
    claimed = False
    detached = False
    started = False
    port = None
    deadline = time.monotonic() + timeout_seconds

    def io_timeout():
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError('会话超过时间上限')
        return max(1, min(8000, int(remaining * 1000)))

    def find(pid=None):
        devices = list(usb.core.find(find_all=True, idVendor=host_usb.VID, backend=backend))
        matches = [
            d
            for d in devices
            if (pid is None or d.idProduct == pid)
            and (port is None or (d.bus, tuple(d.port_numbers or ())) == port)
        ]
        if len(matches) > 1:
            raise ValueError('检测到多个 Sony 设备匹配，拒绝选择')
        return matches[0] if matches else None

    def wait_for(pid, seconds):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            device = find(pid)
            if device is not None:
                return device
            time.sleep(0.25)
        return None

    class Driver:
        def __init__(self, device):
            self.device = device
            self.phase = 'auth'
            interface = device.get_active_configuration()[(0, 0)]
            operation.interface_checked(device, interface)
            incoming = [e for e in interface if e.bmAttributes & 3 == 2 and e.bEndpointAddress & 0x80]
            outgoing = [e for e in interface if e.bmAttributes & 3 == 2 and not e.bEndpointAddress & 0x80]
            if not incoming or not outgoing:
                raise ValueError('USB 接口缺少 bulk 端点')
            self.ep_in, self.ep_out = incoming[0].bEndpointAddress, outgoing[0].bEndpointAddress

        def reset(self):
            pass

        def getId(self):
            return self.device.idVendor, self.device.idProduct

        def write(self, data, ep=0):
            if ep:
                raise PermissionError('拒绝额外端点')
            if self.phase == 'auth':
                if len(data) != 516:
                    raise PermissionError('认证报文长度异常')
                command, salt = struct.unpack_from('>HH', data)
                if salt or (~command & 0xFFFF) not in (1, 3, 5):
                    raise PermissionError('拒绝非认证命令')
            else:
                operation.guard_packet(data)
            report['camera_protocol_requests'] += 1
            count = self.device.write(self.ep_out, data, timeout=io_timeout())
            if count != len(data):
                raise IOError('USB 短写，不重传')
            return count

        def read(self, length, ep=0, timeout=None):
            limit = 32768 if self.phase == 'operation' else 4100
            if ep or not 1 <= length <= limit:
                raise PermissionError('读取长度或端点越界')
            requested = min(length, read_limit) if self.phase == 'operation' else length
            return bytes(self.device.read(self.ep_in, requested, timeout=io_timeout()))

        def vendorRequestOut(self, request, value, index, data=b''):
            if (request, value, index) not in (START, STOP) or data:
                raise PermissionError('拒绝其他 USB 控制请求')
            try:
                report['camera_protocol_requests'] += 1
                self.device.ctrl_transfer(0x43, request, value, index, data, timeout=io_timeout())
                log('service_control_returned', operation='start' if value == START[1] else 'stop')
            except usb.core.USBError as exc:
                log('service_control_usb_error', operation='start' if value == START[1] else 'stop', message=str(exc))
                if getattr(exc, 'backend_error_code', None) != -9:
                    raise

    class Auth(SonySenserAuthDevice):
        def _sendAuthPacket(self, command, data=b''):
            result, reply = super()._sendAuthPacket(command, data)
            log(
                'authentication_reply',
                pid=f'{self.driver.getId()[1]:04x}',
                command=command,
                result=result,
            )
            return result, reply

    def release():
        nonlocal claimed, detached
        if current is None:
            return
        if claimed:
            try:
                usb.util.release_interface(current, 0)
            except Exception as exc:
                log('release_interface_error', message=str(exc))
        if detached:
            try:
                current.attach_kernel_driver(0)
            except Exception as exc:
                log('reattach_driver_error', message=str(exc))
        usb.util.dispose_resources(current)
        claimed = False
        detached = False

    def open_driver():
        nonlocal claimed, detached
        report['phase'] = 'interface_claim'
        same_port(current, port)
        driver = Driver(current)
        detached = claim_interface(current, usb.util, log, allow_settle=not started)
        claimed = True
        return driver

    try:
        current = find()
        if current is None:
            raise RuntimeError('未连接 Sony 相机')
        model = usb.util.get_string(current, current.iProduct)
        if (current.idVendor, current.idProduct, model) != (host_usb.VID, host_usb.PID_ORDINARY, host_usb.MODEL):
            raise ValueError(f'期望 054c:0e0a ({host_usb.MODEL})，实际为 {current.idVendor:04x}:{current.idProduct:04x} ({model})')
        port = (current.bus, tuple(current.port_numbers or ()))
        expected_port = getattr(operation, 'expected_port', None)
        if expected_port is not None:
            same_port(current, expected_port)
        log('target_confirmed', product=model, pid=f'{current.idProduct:04x}', physical_port=port)

        report['phase'] = 'host_unmount'
        unmount_camera(current, log)

        driver = open_driver()
        auth = Auth(driver)
        started = True
        report['service_start_requested'] = True
        report['phase'] = 'service_start_1'
        auth.start()
        report['phase'] = 'authentication_1'
        auth.authenticate()
        report['first_authentication_passed'] = True
        log('normal_authentication_passed')

        detached = False
        release()
        current = wait_for(host_usb.PID_SERVICE, 20)
        if current is None:
            raise RuntimeError('服务通道 054c:0336 未在同一物理端口出现')
        log('service_identity_seen', pid='0336', physical_port=port)

        driver = open_driver()
        auth = Auth(driver)
        report['phase'] = 'service_start_2'
        auth.start()
        report['phase'] = 'authentication_2'
        auth.authenticate()
        report['second_authentication_passed'] = True
        log('service_authentication_passed')

        driver.phase = 'operation'
        report['phase'] = 'operation'
        operation(driver, output, log, report)
    except (Exception, KeyboardInterrupt) as exc:
        report['failure'] = f'{type(exc).__name__}: {exc}'
        report['backend_error_code'] = getattr(exc, 'backend_error_code', None)
        report['failure_phase'] = report['phase']
        report['failure_traceback'] = traceback.format_exc()
        log('error', message=report['failure'], phase=report['failure_phase'])
    finally:
        safe_exit = getattr(operation, 'safe_to_stop', False)
        if started and not safe_exit:
            report['recovery_required'] = True
            log('automatic_stop_withheld', reason='机内校验未全部通过，保留现场不自动退出服务')
            detached = False
        if started and safe_exit:
            try:
                if current is None:
                    current = find(host_usb.PID_SERVICE)
                if current is None:
                    raise RuntimeError('未找到可请求退出的 0336 设备')
                same_port(current, port)
                report['service_stop_attempts'] += 1
                report['service_stop_result'] = 'attempting'
                log('stop_senser_attempted', attempt=report['service_stop_attempts'])
                report['camera_protocol_requests'] += 1
                current.ctrl_transfer(0x43, *STOP, b'', timeout=5000)
                report['service_stop_result'] = 'returned'
                log('stop_senser_control_returned')
            except Exception as exc:
                code = getattr(exc, 'backend_error_code', None)
                report['service_stop_backend_error_code'] = code
                report['service_stop_result'] = (
                    ('stalled' if code == -9 else 'error') if report['service_stop_attempts'] else 'withheld'
                )
                report['service_stop_error'] = f'{type(exc).__name__}: {exc}'
                log('stop_senser_exception', message=str(exc), backend_error_code=code)
        try:
            release()
        except Exception as exc:
            log('dispose_error', message=str(exc))
        report['completed_at'] = datetime.now(timezone.utc).isoformat()
        (output / 'summary.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    return report
