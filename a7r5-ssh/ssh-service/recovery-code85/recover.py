"""code=85单次受限恢复。默认只离线校验，实机必须另行批准。"""
import argparse
import json
import os
from pathlib import Path
import struct
import sys
import time

import host_state
import policy

HERE = Path(__file__).resolve().parent
HEADER = struct.Struct('<IHHBBBB')
READ = struct.pack('<HH', 0x1001, 0x11) + b'\0\xff\0'
STOP = (0x43, 1, 0xC800, 0x2855, b'')


def save(path, value):
    with path.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())


def regular(path):
    if path.is_symlink() or not path.is_file():
        raise ValueError('不是普通文件：' + str(path))
    return path


def metadata():
    return dict(schema='a7r5-code85-recovery-v1', run_id=policy.RUN, risk=policy.RISK,
                location_id=host_state.LOCATION, bus=0, ports=[1], service_pid=0x0336,
                fixed_reads=[list(row) for row in policy.READS],
                max_stop_attempts=1, file_read_window_seconds=60,
                host_observation_seconds=45, authentication=0, start=0, debug=0,
                camera_file_writes=0, ssh_connections=0, automatic_retry=False)


def check(approved=False):
    manifest = json.loads(regular(HERE / 'recovery.json').read_text())
    if manifest['policy'] != metadata() or manifest['directory'] != str(HERE):
        raise ValueError('本次包目录或固定策略变化')
    for name, value in manifest['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('包清单路径越界')
        path = HERE / relative
        if any(item.is_symlink() for item in [path, *path.parents] if item != HERE.parent):
            raise ValueError('不接受软连接材料')
        data = regular(path).read_bytes()
        if {'bytes': len(data), 'sha256': policy.digest(data)} != value:
            raise ValueError('包材料变化：' + name)
    for name, expected in manifest['dependencies'].items():
        if policy.digest(regular(Path(name)).read_bytes()) != expected:
            raise ValueError('本机依赖变化：' + name)
    if approved:
        value = json.loads(regular(HERE / 'approval.json').read_text())
        expected = dict(recovery_sha256=policy.digest((HERE / 'recovery.json').read_bytes()),
                        accepted=True, risk=policy.RISK)
        if value != expected or value.get('accepted') is not True:
            raise PermissionError('缺少绑定本包的明确恢复批准')
        if (HERE / 'ATTEMPT_LOCK').exists() or (HERE / 'result').exists():
            raise FileExistsError('本次包已使用，不重试')
    return manifest


class FileResultError(ValueError):
    def __init__(self, result):
        self.result = result
        super().__init__(f'固定读取服务结果0x{result:08x}')


class ReadChannel:
    """只有固定顺序的select/get，无put、认证、START或DEBUG接口。"""
    def __init__(self, driver, log):
        self.driver, self.log = driver, log
        self.sequence, self.index, self.usable = 1, 0, True
        self.permitted_body = None

    def exchange(self, body, limit):
        if not self.usable or body != self.permitted_body or self.sequence > 28:
            raise PermissionError('不允许的命令、顺序或已失败通道')
        self.permitted_body = None
        self.usable = False
        packet = HEADER.pack(len(body), 0x40, self.sequence, 0, 0, 0, 0) + body
        if self.driver.write(packet) != len(packet):
            raise OSError('USB短写，不重试')
        raw = self.driver.read(HEADER.size)
        self.log('response_header', sequence=self.sequence, raw_hex=raw.hex(), response_limit=limit)
        if len(raw) != HEADER.size:
            raise ValueError('响应头长度错误')
        size, function, sequence, version, micon, offset, status = HEADER.unpack(raw)
        if function != 0x40 or sequence != self.sequence or not 4 <= size <= limit or status:
            raise ValueError('响应头功能、序号、长度或状态错误')
        content = bytearray()
        while len(content) < size:
            chunk = self.driver.read(min(4096, size - len(content)))
            if not chunk or len(chunk) > size - len(content):
                raise ValueError('响应体边界错误')
            content.extend(chunk)
        if size % 512 == 0 and self.driver.read(512) != b'':
            raise ValueError('响应缺少空边界包')
        self.sequence += 1
        self.usable = True
        result, = struct.unpack_from('<I', content)
        self.log('file_result', result=f'0x{result:08x}', bytes=size - 4,
                 version=version, micon=micon, offset=offset)
        if result:
            raise FileResultError(result)
        return bytes(content[4:])

    def read_next(self, label, path, limit):
        if self.index >= len(policy.READS) or (label, path, limit) != policy.READS[self.index]:
            raise PermissionError('只允许本次固定14次读取，不重发')
        self.index += 1
        wire = (path if path.startswith('/tmp/jiritsu/') else '/tmp/jiritsu/../..' + path).encode('ascii')
        self.permitted_body = struct.pack('<HH', 0x1001, 0x0f) + b'\0' + wire + b'\0'
        self.exchange(self.permitted_body, 4)
        self.permitted_body = READ
        return self.exchange(READ, limit + 4)


def fixed_reads(driver, out, log):
    channel = ReadChannel(driver, log)
    child = None
    report = dict(reads=[], diagnostic_unreadable=False)
    for label, path, limit in policy.READS:
        log('fixed_read', label=label, path=path, limit=limit)
        try:
            raw = channel.read_next(label, path, limit)
        except FileResultError as exc:
            if (label != 'diagnostic' or exc.result != 0x10000006
                    or child is None or not policy.diagnostic_unreadable_allowed(child)):
                raise
            report['diagnostic_unreadable'] = True
            report['reads'].append(dict(label=label, path=path, result='0x10000006', absence_proven=False))
            log('diagnostic_unreadable_early_stage', child_code=child['code'], absence_proven=False)
            continue
        (out / (label + '.bin')).write_bytes(raw)
        report['reads'].append(dict(label=label, path=path, bytes=len(raw), sha256=policy.digest(raw)))
        if path in policy.HASHES and policy.digest(raw) != policy.HASHES[path]:
            raise ValueError('固定原件摘要不符：' + label)
        if label == 'root-state' and raw != policy.STATE:
            raise ValueError('root状态、会话或输出长度不符')
        if label in ('root-output', 'parent-before', 'parent-after') and raw != policy.FINAL:
            raise ValueError('本次精确父终态不符或变化')
        if label.startswith('preload-') and raw != policy.NEUTRAL:
            raise ValueError('预加载不是精确512换行，不覆盖')
        if label == 'child-result':
            child = policy.child_result(raw)
            report['child'] = child
        if label == 'tcp':
            policy.no_listener(raw)
        if label == 'heartbeat' and raw != b'A7R5_PRIVATE_ENDED\n':
            raise ValueError('子进程树尚非ENDED终态')
    report.update(gate_passed=True, file_reads_attempted=channel.index,
                  max_protocol_requests=28, protocol_requests=channel.sequence - 1)
    save(out / 'read-gates.json', report)
    return report


def endpoints(interface):
    if interface.bInterfaceNumber != 0 or interface.bAlternateSetting != 0:
        raise ValueError('不是接口0/alt0，不切换接口')
    rows = [dict(address=int(e.bEndpointAddress), attributes=int(e.bmAttributes),
                 max_packet=int(e.wMaxPacketSize), interval=int(e.bInterval)) for e in interface]
    if len({row['address'] for row in rows}) != len(rows):
        raise ValueError('重复端点地址')
    for row in rows:
        if row['address'] & 0x70 or not row['address'] & 15 or not 0 < row['max_packet'] <= 1024:
            raise ValueError('端点地址或包长异常')
    incoming = [row for row in rows if row['attributes'] & 3 == 2 and row['address'] & 0x80]
    outgoing = [row for row in rows if row['attributes'] & 3 == 2 and not row['address'] & 0x80]
    if not incoming or not outgoing:
        raise ValueError('缺少双向bulk端点')
    return dict(interface=0, alternate=0, interface_class=int(interface.bInterfaceClass),
                subclass=int(interface.bInterfaceSubClass), protocol=int(interface.bInterfaceProtocol),
                descriptors=rows, selected_in=incoming[0]['address'], selected_out=outgoing[0]['address'],
                rule='first_bulk_each_direction_in_descriptor_order', historical_full_fingerprint_available=False)


def usb_runtime(manifest):
    sys.path.insert(0, str(HERE / 'vendor'))
    import usb.core
    import usb.util
    import usb.backend.libusb1
    backend = usb.backend.libusb1.get_backend(find_library=lambda _: manifest['libusb'])
    if backend is None:
        raise RuntimeError('libusb不可用')
    return usb.core, usb.util, backend


def service_attempt(manifest, out, log, report):
    core, util, backend = usb_runtime(manifest)
    dev = None
    claimed = False
    deadline = time.monotonic() + 60
    def timeout():
        left = deadline - time.monotonic()
        if left <= 0:
            raise TimeoutError('固定读取窗口已耗尽')
        return max(1, min(5000, int(left * 1000)))
    try:
        devices = list(core.find(find_all=True, idVendor=0x054c, backend=backend))
        if len(devices) != 1 or (devices[0].bus, tuple(devices[0].port_numbers or ()), devices[0].idProduct) != (0, (1,), 0x0336):
            raise ValueError('不是唯一原端口服务身份，不认证或切换身份')
        dev = devices[0]
        config = dev.get_active_configuration()
        interface = config[(0, 0)]
        raw = dict(configuration=int(config.bConfigurationValue),
                   device=dict(bus=dev.bus, ports=list(dev.port_numbers or ()), pid=dev.idProduct),
                   interface=dict(number=int(interface.bInterfaceNumber), alternate=int(interface.bAlternateSetting),
                                  interface_class=int(interface.bInterfaceClass), subclass=int(interface.bInterfaceSubClass),
                                  protocol=int(interface.bInterfaceProtocol)),
                   endpoints=[dict(address=int(e.bEndpointAddress), attributes=int(e.bmAttributes),
                                   max_packet=int(e.wMaxPacketSize), interval=int(e.bInterval)) for e in interface])
        save(out / 'descriptors.json', raw)
        selection = endpoints(interface)
        save(out / 'endpoint-selection.json', selection)
        # Darwin可能不实现驱动状态查询；仍只claim一次，不detach、不reset。
        try:
            active = dev.is_kernel_driver_active(0)
        except NotImplementedError:
            active = None
            log('kernel_driver_query_unsupported', next_action='single_claim_without_detach')
        if active:
            raise PermissionError('接口有活动内核驱动，不自动分离')
        util.claim_interface(dev, 0)
        claimed = True
        class Driver:
            def write(self, data):
                return dev.write(selection['selected_out'], data, timeout=timeout())
            def read(self, n):
                return bytes(dev.read(selection['selected_in'], n, timeout=timeout()))
        gates = fixed_reads(Driver(), out, log)
        report['gate_passed'] = gates['gate_passed']
        timeout()
        report['stop_attempts'] = 1
        log('stop_attempted', attempt=1, request_type=0x43, request=1, value=0xC800, index=0x2855)
        try:
            dev.ctrl_transfer(*STOP, timeout=5000)
            report['stop_result'] = 'returned'
        except Exception as exc:
            report['stop_result'] = 'transfer_error'
            report['stop_error'] = type(exc).__name__ + ': ' + str(exc)
            log('stop_error', error=report['stop_error'], next_action='host_metadata_only')
    finally:
        if dev is not None:
            if claimed:
                try:
                    util.release_interface(dev, 0)
                except Exception as exc:
                    log('release_error', error=str(exc))
            try:
                util.dispose_resources(dev)
            except Exception as exc:
                log('dispose_error', error=str(exc))


def execute(device_io=False):
    if not device_io:
        raise PermissionError('缺少实机开关')
    manifest = check(True)
    if sys.platform != 'darwin' or os.geteuid() != 0:
        raise PermissionError('只允许本机Terminal管理员执行')
    (HERE / 'ATTEMPT_LOCK').mkdir(mode=0o700)
    out = HERE / 'result'
    out.mkdir(mode=0o700)
    report = dict(run_id=policy.RUN, gate_passed=False, stop_attempts=0,
                  authentication=0, start=0, debug=0, camera_file_writes=0, ssh_connections=0,
                  host_recovery_verified=False, guest_cleanup_verified=False,
                  screen_confirmation_pending=True, execution_succeeded=False)
    def log(event, **details):
        row = dict(time=time.time(), event=event, **details)
        with (out / 'events.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, ensure_ascii=False) + '\n')
            handle.flush()
        print(json.dumps(row, ensure_ascii=False), flush=True)
    def take(label, timeout=5):
        value = host_state.snapshot(out, label, timeout)
        save(out / (label + '.json'), value)
        return value
    try:
        initial = take('initial')
        if initial['kind'] == 'service':
            service_attempt(manifest, out, log, report)
            report['guest_cleanup_verified'] = report['gate_passed']
        elif initial['kind'] not in ('ordinary', 'transition'):
            raise ValueError('没有已知目标身份，停止')
        else:
            report['guest_evidence_not_collected'] = True
            log('host_only_branch', kind=initial['kind'], usb_backend_opened=False)
        if report['stop_attempts'] == 1 or initial['kind'] in ('ordinary', 'transition'):
            proof = host_state.observe(manifest['host_baseline'], take)
            save(out / 'host-recovery.json', proof)
            report['host_recovery_verified'] = proof['recovered']
            report['execution_succeeded'] = proof['recovered']
            if not proof['recovered']:
                report['failure'] = 'USB或媒体未恢复，仅保留观察；不重发STOP或自动断电'
    except (Exception, KeyboardInterrupt) as exc:
        report['failure'] = type(exc).__name__ + ': ' + str(exc)
        log('stopped', error=report['failure'])
    finally:
        save(out / 'result.json', report)
        owner = HERE.stat()
        for path in out.iterdir():
            os.chown(path, owner.st_uid, owner.st_gid, follow_symlinks=False)
        os.chown(out, owner.st_uid, owner.st_gid, follow_symlinks=False)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'check-approval', 'execute'))
    parser.add_argument('--device-io', action='store_true')
    args = parser.parse_args()
    if args.action == 'execute':
        value = execute(args.device_io)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value['execution_succeeded'] else 3
    check(args.action == 'check-approval')
    print('本次离线材料核对通过；未查询USB、未发送相机请求。')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt) as exc:
        print('停止：' + type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        raise SystemExit(2)
