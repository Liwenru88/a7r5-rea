"""单次元数据探针调度；默认不具备退出服务的许可。"""
import json
from pathlib import Path
import re
import struct
import time

import policy
from transport import Channel, DEBUG, HEADER, READ, FileResultError

HERE = Path(__file__).resolve().parent


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')


class Operation:
    def __init__(self, output, bundle=None):
        self.output = Path(output)
        self.bundle = HERE if bundle is None else Path(bundle)
        self.config = json.loads((self.bundle / 'config.json').read_text())
        self.run = self.config['run_id']
        if not re.fullmatch('[0-9a-f]{32}', self.run) or self.run == policy.TARGET:
            raise ValueError('新执行会话标识不符')
        self.prefix = '/tmp/jiritsu/a7r5-' + self.run
        self.arm = (self.prefix + '.so\n').encode()
        self.writes = {self.prefix + '.probe': (self.bundle / 'materials/probe.arm64').read_bytes(),
                       self.prefix + '.so': (self.bundle / 'materials/root.arm64.so').read_bytes(),
                       '/etc/ld.so.preload': self.arm}
        if policy.digest(self.writes[self.prefix + '.probe']) != policy.PROBE_SHA:
            raise ValueError('固定探针摘要不符')
        self.reads = {'/version.txt': 4096, '/etc/ld.so.preload': 4096,
                      '/tmp/jiritsu/a7r5-' + policy.TARGET + '.state': 512,
                      self.prefix + '.state': 512, self.prefix + '.output': 2048,
                      self.prefix + '.probe': len(self.writes[self.prefix + '.probe']),
                      self.prefix + '.so': len(self.writes[self.prefix + '.so'])}
        self.safe_to_stop = False
        self.interfaces_seen = 0
        self.permitted_packet = None

    def interface_checked(self, device, interface):
        raw = dict(pid=int(device.idProduct), bus=device.bus, ports=list(device.port_numbers or ()),
                   number=int(interface.bInterfaceNumber), alternate=int(interface.bAlternateSetting),
                   interface_class=int(interface.bInterfaceClass), subclass=int(interface.bInterfaceSubClass),
                   protocol=int(interface.bInterfaceProtocol),
                   endpoints=[dict(address=int(ep.bEndpointAddress), attributes=int(ep.bmAttributes),
                                   max_packet=int(ep.wMaxPacketSize), interval=int(ep.bInterval)) for ep in interface])
        self.interfaces_seen += 1
        save(self.output / f'interface-{self.interfaces_seen}.json', raw)
        key = f'interface-{self.interfaces_seen}.json'
        if self.interfaces_seen > 2 or raw != self.config['interfaces'].get(key):
            raise ValueError('物理端口、接口指纹或阶段不符，不换端点')
        save(self.output / f'endpoint-selection-{self.interfaces_seen}.json',
             dict(selected_in=129, selected_out=2, descriptors=raw['endpoints'],
                  rule='frozen_first_bulk_each_direction_no_fallback'))

    def guard_packet(self, packet):
        if self.permitted_packet is None or packet != self.permitted_packet or len(packet) < HEADER.size + 7:
            raise PermissionError('报文未经本次操作精确授权')
        size, function, sequence, *meta = HEADER.unpack_from(packet)
        body = packet[HEADER.size:]
        if size != len(body) or function != 0x40 or not 1 <= sequence <= 100 or any(meta):
            raise PermissionError('非法固定报文')
        selects = {struct.pack('<HH', 0x1001, 15) + b'\0' +
                   (p if p.startswith('/tmp/jiritsu/') else '/tmp/jiritsu/../..' + p).encode() + b'\0'
                   for p in self.reads}
        puts = {struct.pack('<HH', 0x1001, 16) + b'\0\xff\0' + value for value in self.writes.values()}
        if body not in selects | puts | {READ, DEBUG}:
            raise PermissionError('超出固定路径或完整写入字节')

    def __call__(self, driver, output, log, report):
        channel = Channel(driver, self, log)
        result = dict(run_id=self.run, target_session=policy.TARGET, gate_passed=False,
                      key_content_read=False, ssh_started=False, state_observations=0)
        def read(label, path):
            log('fixed_read_attempt', label=label, path=path)
            raw = channel.read(path, self.reads[path])
            (output / (label + '.bin')).write_bytes(raw)
            return raw
        def expect(label, path, wanted):
            value = read(label, path)
            if value != wanted:
                raise ValueError('固定内容不符：' + label)
            return value
        try:
            if policy.digest(read('version', '/version.txt')) != policy.VERSION_SHA:
                raise ValueError('固件版本不符')
            expect('preload-before', '/etc/ld.so.preload', policy.NEUTRAL)
            expect('old-state', '/tmp/jiritsu/a7r5-' + policy.TARGET + '.state', policy.OLD_STATE)
            # 新nonce路径须由文件服务明确报告不可读；不是不存在的证明，O_EXCL仍做最终保护。
            for label, suffix in (('fresh-state', '.state'), ('fresh-output', '.output'), ('fresh-probe', '.probe'), ('fresh-library', '.so')):
                try:
                    read(label, self.prefix + suffix)
                except FileResultError as exc:
                    if exc.result != 0x10000006:
                        raise
                    log('new_nonce_unreadable', label=label, absence_proven=False)
                else:
                    raise ValueError('新nonce结果路径已可读，拒绝重用')
            for suffix in ('.probe', '.so'):
                path = self.prefix + suffix
                channel.put(path, self.writes[path])
                expect('readback-' + suffix[1:], path, self.writes[path])
            expect('preload-before-arm', '/etc/ld.so.preload', policy.NEUTRAL)
            channel.put('/etc/ld.so.preload', self.arm)
            expect('preload-armed', '/etc/ld.so.preload', self.arm)
            channel.debug()
            terminal = None
            for index in range(16):
                result['state_observations'] += 1
                try:
                    raw = read(f'state-{index:02}', self.prefix + '.state')
                except FileResultError as exc:
                    if exc.result != 0x10000006:
                        raise
                    raw = None
                if raw is not None:
                    running = f'A7R5-ROOT-1 {self.run} RUNNING 0 uid=0 euid=0 bytes=0\n'.encode()
                    if raw != running:
                        match = re.fullmatch(rb'A7R5-ROOT-1 ' + self.run.encode() + rb' DONE 0 uid=0 euid=0 bytes=(\d{1,4})\n', raw)
                        if not match or not 0 < int(match[1]) <= 2048:
                            raise ValueError('执行器终态、root身份或输出长度不符')
                        terminal, size = raw, int(match[1])
                        break
                if index < 15:
                    time.sleep(1)
            if terminal is None:
                raise TimeoutError('有界状态观察结束，不重发DEBUG')
            raw = read('probe-output', self.prefix + '.output')
            if len(raw) != size:
                raise ValueError('输出长度与终态不符')
            result['probe'] = policy.parse_output(raw)
            expect('state-repeat', self.prefix + '.state', terminal)
            expect('preload-after', '/etc/ld.so.preload', policy.NEUTRAL)
            result['gate_passed'] = True
        except BaseException as exc:
            result['failure'] = type(exc).__name__ + ': ' + str(exc)
            raise
        finally:
            self.permitted_packet = None
            result.update(file_reads_attempted=channel.reads, file_writes_attempted=channel.writes,
                          debug_attempts=channel.debug_attempts, responses_completed=channel.sequence - 1)
            report.update(camera_file_write_commands_sent=channel.writes > 0, debug_commands_sent=channel.debug_attempts > 0,
                          file_request_attempts=channel.reads, fixed_writes_attempted=channel.writes,
                          debug_attempts=channel.debug_attempts)
            save(output / 'assessment.json', result)
        # 先保存完整门槛回执，再允许通信引擎退出服务。
        self.safe_to_stop = True
        report.update(metadata_probe_completed=True, preload_neutral_verified=True)
