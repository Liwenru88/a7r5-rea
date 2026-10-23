"""已知残留响应的受限恢复；默认只离线检查，设备操作必须另行批准。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys
import time

import host_state
from transport import Channel, HEADER, READ, wire

HERE = Path(__file__).resolve().parent
RUN = '76065e3af98e4ede9fdf46d1f4a41372'
STOP = (0x43, 1, 0xc800, 0x2855, b'')
READS = (('version-a', '/version.txt'), ('preload-a', '/etc/ld.so.preload'),
         ('version-b', '/version.txt'), ('preload-b', '/etc/ld.so.preload'))
RISK = ('本包只用于失败会话'+RUN+'；同端口0336先只读IN端点，逐字节匹配已知加载库响应的唯一剩余后缀。'
        '排空会消费USB队列数据，不能保证队列仍保留或可恢复；匹配、边界或传输不确定立即停止，不发新请求。'
        '排空成功后仅版本→预加载→版本→预加载四次固定读取，全部门槛通过才一次STOP。'
        '普通身份或096f仅观察主机，最多45秒；STOP可能Pipe error或停在096f，不能保证恢复。'
        '不认证、不START、不上传、不写相机文件、不写预加载、不DEBUG、不SSH、不操作SD卡；'
        '不换端点、不重试、不自动断电或重启。原失败包和锁保留。')


def digest(data):
    return hashlib.sha256(data).hexdigest()


def regular(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path, *path.parents)) or not path.is_file():
        raise ValueError('材料不是无链接普通文件：'+str(path))
    return path


def save(path, obj):
    with path.open('x', encoding='utf-8') as handle:
        json.dump(obj, handle, ensure_ascii=False, indent=2)
        handle.write('\n'); handle.flush(); os.fsync(handle.fileno())


def check(approved=False):
    manifest = json.loads(regular(HERE/'recovery.json').read_text())
    if (manifest['schema'] != 'a7r5-libjit-stream-recovery-1' or manifest['run_id'] != RUN
            or manifest['risk'] != RISK or manifest['directory'] != str(HERE)):
        raise ValueError('本次包位置、会话或策略变化')
    for name, expected in manifest['files'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts:
            raise ValueError('材料路径越界')
        if digest(regular(HERE/name).read_bytes()) != expected:
            raise ValueError('包材料变化：'+name)
    for name, expected in manifest['dependencies'].items():
        if digest(regular(name).read_bytes()) != expected:
            raise ValueError('本机依赖变化：'+name)
    if approved:
        expected = dict(accepted=True, recovery_sha256=digest((HERE/'recovery.json').read_bytes()), risk=RISK)
        if json.loads(regular(HERE/'approval.json').read_text()) != expected:
            raise PermissionError('没有绑定本包的明确批准')
        if (HERE/'ATTEMPT_LOCK').exists() or (HERE/'result').exists():
            raise FileExistsError('本包已使用，不重试')
    return manifest


def drain_known_response(driver, expected, log, clock=time.monotonic):
    """只消费可唯一定位的后缀；没有数据绝不等同排空成功。"""
    if len(expected) != 233420 or expected[:4] != b'\0'*4:
        raise ValueError('不是本次已知响应')
    candidates = list(range(0, len(expected), 32768))
    consumed = 0
    start = clock()
    calls = 0
    received = bytearray()

    def read(n):
        nonlocal calls
        calls += 1
        if calls > 1024 or clock()-start >= 60:
            raise TimeoutError('排空读取预算耗尽')
        raw = driver.read(n)
        log('drain_fragment', requested=n, received=len(raw), consumed=consumed,
            candidates=candidates[:], read_number=calls)
        return raw

    while True:
        complete = [offset for offset in candidates if offset+consumed == len(expected)]
        if complete:
            if len(candidates) != 1:
                raise ValueError('后缀结束位置存在歧义，不继续读取')
            result = dict(start_offset=complete[0], bytes=consumed, sha256=digest(received),
                          reads=calls, unique_suffix_matched=True)
            log('drain_complete', **result)
            return result
        n = min(4096, 32768-consumed % 32768,
                min(len(expected)-offset-consumed for offset in candidates))
        raw = read(n)
        if not raw or len(raw) > n:
            raise ValueError('残留响应体边界异常')
        candidates = [offset for offset in candidates
                      if expected[offset+consumed:offset+consumed+len(raw)] == raw]
        if not candidates:
            raise ValueError('残留数据不匹配已知后缀')
        received.extend(raw); consumed += len(raw)
        if consumed % 32768 == 0:
            if read(512) != b'':
                raise ValueError('残留逻辑块缺少空边界包')


class FixedOperation:
    """只允许序号5至12的八个精确select/get报文。"""
    def __init__(self, out):
        self.output = out
        self.reads = {'/version.txt': 4096, '/etc/ld.so.preload': 4096}
        self.permitted_packet = None
        self.index = 0
        self.bodies = []
        for _, path in READS:
            self.bodies += [struct.pack('<HH', 0x1001, 15)+b'\0'+wire(path)+b'\0', READ]

    def guard_packet(self, packet):
        if self.index >= 8:
            raise PermissionError('固定读取次数耗尽')
        body = self.bodies[self.index]
        expected = HEADER.pack(len(body), 0x40, self.index+5, 0, 0, 0, 0)+body
        if packet != expected or packet != self.permitted_packet:
            raise PermissionError('禁止固定顺序之外的报文')
        self.index += 1


def recover_stream(driver, out, log, config, expected):
    proof = drain_known_response(driver, expected, log)
    save(out/'drain-proof.json', proof)
    operation = FixedOperation(out)
    def strict_log(event, **details):
        log(event, **details)
        if event == 'response_header':
            raw = bytes.fromhex(details['raw_hex'])
            if len(raw) != 12 or HEADER.unpack(raw)[3:] != (3, 0, 0, 0):
                raise ValueError('响应头接口元数据与本次记录不同')
    channel = Channel(driver, operation, strict_log)
    channel.sequence = 5
    baseline = None
    for label, path in READS:
        raw = channel.read(path, 4096)
        (out/(label+'.bin')).write_bytes(raw)
        log('fixed_content', label=label, bytes=len(raw), sha256=digest(raw))
        if path == '/version.txt':
            if digest(raw) != config['version_sha256']:
                raise ValueError('版本内容与失败会话不同')
        else:
            if raw not in [bytes.fromhex(row[1]) for row in config['preload_baselines']]:
                raise ValueError('未知预加载内容，不覆盖')
            if baseline is not None and raw != baseline:
                raise ValueError('重复预加载内容变化')
            baseline = raw
    if operation.index != 8 or channel.sequence != 13 or not channel.usable:
        raise ValueError('固定读取不完整')
    proof.update(gate_passed=True, protocol_requests=8, preload_unchanged=True)
    save(out/'read-gates.json', proof)
    return proof


def fingerprint(dev, interface):
    return dict(pid=int(dev.idProduct), bus=dev.bus, ports=list(dev.port_numbers or ()),
                number=int(interface.bInterfaceNumber), alternate=int(interface.bAlternateSetting),
                interface_class=int(interface.bInterfaceClass), subclass=int(interface.bInterfaceSubClass),
                protocol=int(interface.bInterfaceProtocol),
                endpoints=[dict(address=int(e.bEndpointAddress), attributes=int(e.bmAttributes),
                                max_packet=int(e.wMaxPacketSize), interval=int(e.bInterval)) for e in interface])


def usb_runtime(manifest):
    sys.path.insert(0, str(HERE/'vendor'))
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
    deadline = time.monotonic()+60
    calls = 0
    def timeout():
        left = deadline-time.monotonic()
        if left <= 0:
            raise TimeoutError('本次通信窗口耗尽')
        return max(1, min(5000, int(left*1000)))
    try:
        devices = list(core.find(find_all=True, idVendor=0x054c, backend=backend))
        if len(devices) != 1 or (devices[0].bus, tuple(devices[0].port_numbers or ()), devices[0].idProduct) != (0, (1,), 0x0336):
            raise ValueError('不是唯一同端口0336，不切换身份')
        dev = devices[0]
        interface = dev.get_active_configuration()[(0, 0)]
        actual = fingerprint(dev, interface)
        save(out/'descriptors.json', actual)
        expected_interface = manifest['config']['interfaces']['interface-2.json']
        if actual != expected_interface:
            raise ValueError('完整接口指纹不同，不换端点')
        save(out/'endpoint-selection.json', dict(incoming=129, outgoing=2, rule='exact_historical_fingerprint'))
        try:
            active = dev.is_kernel_driver_active(0)
        except NotImplementedError:
            active = None
            log('driver_query_unsupported', action='single_claim_without_detach')
        if active:
            raise PermissionError('有活动内核驱动，不分离')
        util.claim_interface(dev, 0); claimed = True
        class Driver:
            def write(self, raw):
                return dev.write(2, raw, timeout=timeout())
            def read(self, n):
                nonlocal calls
                calls += 1
                if calls > 1100:
                    raise TimeoutError('本次总读取次数耗尽')
                raw = bytes(dev.read(129, n, timeout=timeout()))
                # 保存每次IN原始字节，包括空边界；发生异常也保留此前数据。
                (out/f'in-{calls:04}.bin').write_bytes(raw)
                return raw
        expected = b'\0'*4+(HERE/'evidence/libJiritsu.so').read_bytes()
        recover_stream(Driver(), out, log, manifest['config'], expected)
        report['gate_passed'] = True
        timeout()
        report['stop_attempts'] = 1
        log('stop_attempted', attempt=1)
        try:
            dev.ctrl_transfer(*STOP, timeout=timeout())
            report['stop_result'] = 'returned'
        except Exception as exc:
            report['stop_result'] = 'transfer_error'
            report['stop_error'] = type(exc).__name__+': '+str(exc)
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


def dispatch(initial, manifest, out, log, report, attempt, observe):
    if initial['kind'] == 'service':
        attempt(manifest, out, log, report)
        if not report['gate_passed'] or report['stop_attempts'] != 1:
            raise ValueError('服务分支未通过，不进入后续步骤')
    elif initial['kind'] not in ('ordinary', 'transition'):
        raise ValueError('没有已知目标身份')
    else:
        log('host_only_branch', kind=initial['kind'], usb_backend_opened=False)
    proof = observe()
    save(out/'host-recovery.json', proof)
    report['host_recovery_verified'] = bool(proof['recovered'])
    report['execution_succeeded'] = bool(proof['recovered'])
    if not proof['recovered']:
        report['failure'] = '普通USB或完整媒体未恢复，不重试或自动断电'


def execute(device_io=False):
    if not device_io or not (HERE/'approval.json').is_file():
        raise PermissionError('缺少实机开关或本包明确批准，不观察设备')
    manifest = check(True)
    if sys.platform != 'darwin' or os.geteuid() != 0:
        raise PermissionError('仅允许macOS Terminal本机sudo执行')
    (HERE/'ATTEMPT_LOCK').mkdir(mode=0o700)
    out = HERE/'result'; out.mkdir(mode=0o700)
    report = dict(run_id=RUN, gate_passed=False, stop_attempts=0, authentication=0, start=0,
                  debug=0, uploads=0, camera_file_writes=0, preload_writes=0,
                  automatic_retry=False, sd_operations=False, host_recovery_verified=False,
                  execution_succeeded=False, screen_confirmation_pending=True)
    def log(event, **details):
        row = dict(time=time.time(), event=event, **details)
        with (out/'events.jsonl').open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row, ensure_ascii=False)+'\n'); handle.flush()
        print(json.dumps(row, ensure_ascii=False), flush=True)
    def take(label, timeout=5):
        value = host_state.snapshot(out, label, timeout)
        save(out/(label+'.json'), value)
        return value
    try:
        initial = take('initial')
        dispatch(initial, manifest, out, log, report, service_attempt,
                 lambda: host_state.observe(manifest['config']['host_baseline'], take))
    except (Exception, KeyboardInterrupt) as exc:
        report['failure'] = type(exc).__name__+': '+str(exc)
        log('stopped', error=report['failure'])
    finally:
        save(out/'result.json', report)
        owner = HERE.stat()
        for path in [HERE/'ATTEMPT_LOCK', out, *out.rglob('*')]:
            if path.is_symlink():
                raise ValueError('输出出现链接')
            os.chown(path, owner.st_uid, owner.st_gid, follow_symlinks=False)
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'approve', 'execute'))
    parser.add_argument('--device-io', action='store_true')
    parser.add_argument('--accept')
    args = parser.parse_args()
    if args.action == 'execute':
        result = execute(args.device_io)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0 if result['execution_succeeded'] else 3
    manifest = check()
    phrase = 'ACCEPT-'+digest((HERE/'recovery.json').read_bytes())[:16]
    if args.action == 'approve':
        if args.accept != phrase:
            raise PermissionError('必须明确接受本包精确风险短语')
        if (HERE/'ATTEMPT_LOCK').exists() or (HERE/'result').exists():
            raise FileExistsError('已尝试，不批准重跑')
        save(HERE/'approval.json', dict(accepted=True, recovery_sha256=digest((HERE/'recovery.json').read_bytes()), risk=RISK))
    print(json.dumps(dict(offline_only=True, run_id=manifest['run_id'], approved=(HERE/'approval.json').exists(),
                          risk=RISK, consent_phrase=phrase), ensure_ascii=False, indent=2))
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt) as exc:
        print('停止：'+type(exc).__name__+': '+str(exc), file=sys.stderr)
        raise SystemExit(2)
