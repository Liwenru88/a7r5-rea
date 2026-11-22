"""libjit 与 kit 双引擎信任环境更新通道操作器（共享校验与 9 块回读门控）。"""
import base64
import hashlib
import json
from pathlib import Path
import re
import struct
import time

from usb_session import Channel, FileResultError, HEADER, READ, wire

DEBUG = struct.pack('<HH', 0x1001, 5) + b'\0\0\0'


def validate_journal(raw, run_id, plan):
    """逐行核对机内事务日志：前像捕获、258 扇区写入与同步、重开整区哈希匹配、完成终态。"""
    if not raw.endswith(b'\n'):
        raise ValueError('机内日志尾部不完整')
    pattern = re.compile(r'A7R5_TRUST ' + re.escape(run_id) + r' ([A-Z_]+) completed=(\d+) offset=(-?\d+) code=(-?\d+)')
    actual = []
    for line in raw.decode('ascii').splitlines():
        match = pattern.fullmatch(line)
        if match is None:
            raise ValueError(f'机内日志行格式或会话号不符：{line}')
        actual.append((match[1], int(match[2]), int(match[3]), int(match[4])))

    expected = [('FORCE_PREIMAGE_CAPTURED', 0, -1, 0)]
    for index, row in enumerate(plan['rows']):
        expected += [('WRITE_BEGIN', index, row['offset'], 0), ('WRITE_RETURNED', index + 1, row['offset'], 0)]
        if index == len(plan['rows']) - 1 or row['phase'] != plan['rows'][index + 1]['phase']:
            expected.append(('PHASE_SYNC_RETURNED', index + 1, row['offset'], 0))
    expected += [
        ('FULL_LOGICAL_READBACK_MATCH', 258, -1, 0),
        ('REOPENED_FULL_CAPTURE_MATCH', 258, -1, 0),
        ('COMPLETED', 258, -1, 0),
    ]
    if actual != expected:
        raise ValueError('机内日志阶段、扇区计数或偏移不符')
    return True


class _BaseTrustOperation:
    """共享的通道守卫、环境基线校验、状态轮询与 9 块扇区回读校验。"""

    packet_limit = 512
    usb_read_size = 8192
    strict_usb_reads = True

    def __init__(self, package_dir, channel_factory=Channel, clock=time.monotonic, sleep=time.sleep):
        self.package = Path(package_dir)
        self.config = json.loads((self.package / 'config.json').read_text())
        self.run_id = self.config['run_id']
        self.control_prefix = '/tmp_wbshd/a7r5-control-' + self.run_id + '/task'
        self.ticket_path = '/tmp_wbshd/a7r5-control-' + self.run_id + '.ticket'
        self.expected_port = (
            int(self.config['host_baseline']['bus']),
            tuple(int(p) for p in self.config['host_baseline']['ports']),
        )
        self.channel_factory = channel_factory
        self.clock = clock
        self.sleep = sleep
        self.output = None
        self.interfaces_seen = 0
        self.permitted_packet = None
        self.safe_to_stop = False
        self.may_have_written = False
        self.trigger_attempts = 0
        self.written = set()
        self.memory_required_kib = 32768

        self.plan = json.loads((self.package / 'materials/write-plan.json').read_text())
        self.patch = json.loads((self.package / 'materials/trust-sectors.json').read_text())['rows']
        if len(self.patch) != 258 or [r['offset'] for r in self.patch] != [r['offset'] for r in self.plan['rows']]:
            raise ValueError('写入计划与扇区材料不匹配')

        self.readback_parts = [
            (self.config['readback_path'] + f'.sectors-{i}', min(16384, 132096 - i * 16384))
            for i in range(9)
        ]
        self.reads = {
            '/version.txt': 4096,
            '/usr/lib/libJiritsu.so': self.config['loader_bytes'],
            '/etc/ld.so.preload': 4096,
            '/tmp/jbusy': 64,
            self.control_prefix + '.claim': 128,
            self.control_prefix + '.state': 512,
            self.control_prefix + '.state.new': 512,
            self.control_prefix + '.output': 32768,
            self.config['journal_path']: 131072,
        }
        self.reads.update(self.readback_parts)
        self.writes = {}

    def interface_checked(self, device, interface):
        raw = {
            'pid': int(device.idProduct),
            'bus': device.bus,
            'ports': list(device.port_numbers or ()),
            'number': int(interface.bInterfaceNumber),
            'alternate': int(interface.bAlternateSetting),
            'interface_class': int(interface.bInterfaceClass),
            'subclass': int(interface.bInterfaceSubClass),
            'protocol': int(interface.bInterfaceProtocol),
            'endpoints': [
                {
                    'address': int(e.bEndpointAddress),
                    'attributes': int(e.bmAttributes),
                    'max_packet': int(e.wMaxPacketSize),
                    'interval': int(e.bInterval),
                }
                for e in interface
            ],
        }
        self.interfaces_seen += 1
        if self.output is not None:
            (self.output / f'interface-{self.interfaces_seen}.json').write_text(json.dumps(raw, indent=2) + '\n')
        expected = self.config['interfaces'].get(f'interface-{self.interfaces_seen}.json')
        if raw != expected:
            raise ValueError(f'接口 {self.interfaces_seen} 指纹或物理端口不符')

    def guard_packet(self, packet):
        if packet != self.permitted_packet or len(packet) < HEADER.size + 7:
            raise PermissionError('未经授权的报文')
        size, function, sequence, *meta = HEADER.unpack_from(packet)
        body = packet[HEADER.size :]
        if size != len(body) or function != 0x40 or not 1 <= sequence <= self.packet_limit or any(meta):
            raise PermissionError('非法报文头字段')
        selects = {struct.pack('<HH', 0x1001, 15) + b'\0' + wire(p) + b'\0' for p in self.reads}
        puts = {struct.pack('<HH', 0x1001, 16) + b'\0\xff\0' + d for d in self.writes.values()}
        if body not in selects | puts | {READ}:
            raise PermissionError('报文体不在本轮白名单内')

    def _read(self, channel, label, path):
        raw = channel.read(path, self.reads[path])
        if self.output is not None:
            (self.output / f'{label}.bin').write_bytes(raw)
        return raw

    def _put(self, channel, path, data, report, stage):
        if path in self.written:
            raise PermissionError(f'禁止重复写入路径：{path}')
        self.written.add(path)
        report['fixed_writes_attempted'] += 1
        report.update(upload_stage=stage, upload_path=path)
        channel.put(path, data)

    def _check_candidates_absent(self, channel, log, paths):
        for index, path in enumerate(paths):
            try:
                self._read(channel, f'candidate-{index}', path)
            except FileResultError as error:
                if error.result != 0x10000006:
                    raise
                log('stat_failed_candidate', path=path)
                continue
            raise ValueError(f'固定工作路径已有可读内容，停止执行：{path}')

    def _verify_base_files(self, channel):
        ver = self._read(channel, 'version', '/version.txt')
        if hashlib.sha256(ver).hexdigest() != self.config['version_sha256']:
            raise ValueError('相机固件版本 (/version.txt) 与当前信任更新材料不符')
        loader = self._read(channel, 'loader', '/usr/lib/libJiritsu.so')
        if hashlib.sha256(loader).hexdigest() != self.config['loader_sha256']:
            raise ValueError('机内加载库 (/usr/lib/libJiritsu.so) 摘要不符')
        baseline = self._read(channel, 'preload-before', '/etc/ld.so.preload')
        for name, hex_str in self.config['preload_baselines']:
            if baseline == bytes.fromhex(hex_str):
                return name, baseline
        raise ValueError('机内 /etc/ld.so.preload 内容未适配，拒绝覆盖')

    def _poll_and_verify(self, channel, baseline_bytes, log, report):
        deadline = self.clock() + self.config['observe_seconds']
        terminal = None
        size = 0
        for index in range(120):
            if self.clock() >= deadline:
                break
            try:
                raw = self._read(channel, f'state-{index:03d}', self.control_prefix + '.state')
            except FileResultError as error:
                if error.result != 0x10000006:
                    raise
                self.sleep(0.5)
                continue
            match = re.fullmatch(
                rb'A7R5-JIT-1 '
                + self.run_id.encode()
                + rb' (RUNNING|DONE|FAILED|TIMEOUT) (\d+) uid=(\d+) euid=(\d+) bytes=(-?\d+) disarmed=(\d+) children=(\d+)'
                rb'(?: precheck_reason=(\d+) precheck_pid=(-?\d+) precheck_fd=(-?\d+) precheck_error=(-?\d+) precheck_device=(\d+) partition_writes=(0)'
                rb'| resource_reason=(\d+) resource_error=(-?\d+) memory_available_kib=(-?\d+) memory_required_kib=(\d+) ram_available_bytes=(-?\d+) partition_writes=(0))?\n',
                raw,
            )
            if not match or match.group(3, 4) != (b'0', b'0'):
                raise ValueError('状态会话或 root 身份不符')
            if match[1] == b'FAILED':
                code = int(match[2])
                report['trust_native_exit_code'] = code
                if match[14] is not None:
                    diag = dict(
                        zip(
                            ('reason', 'error', 'memory_available_kib', 'memory_required_kib', 'ram_available_bytes'),
                            (int(match[i]) for i in range(14, 19)),
                        )
                    )
                    report['trust_resources'] = diag
                    raise RuntimeError(f'写前资源检查失败 (code={code})：{diag}')
                if match[8] is not None:
                    diag = dict(
                        zip(('reason', 'pid', 'fd', 'error', 'device'), (int(match[i]) for i in range(8, 13)))
                    )
                    report['trust_precheck'] = diag
                    raise RuntimeError(f'写前进程/挂载占用检查失败 (code={code})：{diag}')
                raise RuntimeError('机内原生任务失败：' + raw.decode().strip())
            if match[1] == b'TIMEOUT':
                raise RuntimeError('机内任务超时：' + raw.decode().strip())
            if match[1] == b'DONE':
                if match[2] != b'0' or match.group(6, 7) != (b'1', b'0'):
                    raise ValueError('成功终态退出码或子进程状态门槛不符')
                size = int(match[5])
                if not 0 < size < 32768:
                    raise ValueError('输出长度无效')
                terminal = raw
                break
            self.sleep(0.5)

        if terminal is None:
            raise TimeoutError('等待机内写入终态超时，不自动 STOP')

        data = self._read(channel, 'native-output', self.control_prefix + '.output')
        pattern = (
            re.escape(self.config['expected_output_begin'].encode())
            + rb'A7R5_TRUST_FORCE_COMPLETE ([0-9a-f]{64}) source_sha256=([0-9a-f]{64}) '
            rb'sectors=258 bytes=132096 reopened=1 chunks=9 chunk_bytes=16384 readback=planned-sectors-v2\n'
            + re.escape(self.config['expected_output_end'].encode())
        )
        match = re.fullmatch(pattern, data)
        if not match or len(data) != size:
            raise ValueError('机内原生输出标记或格式不符')
        candidate_sha = match[1].decode()
        report['actual_source_sha256'] = match[2].decode()
        report['native_logical_partition_sha256'] = candidate_sha

        journal = self._read(channel, 'native-journal', self.config['journal_path'])
        validate_journal(journal, self.run_id, self.plan)
        report.update(
            native_write_complete=True,
            native_full_readback_verified=True,
            native_reopened_readback_verified=True,
        )

        expected_sectors = b''.join(base64.b64decode(row['after'], validate=True) for row in self.patch)
        raw_sectors = bytearray()
        for index, (path, expected_len) in enumerate(self.readback_parts):
            part = self._read(channel, f'trust-readback-{index:04d}', path)
            if len(part) != expected_len:
                raise ValueError(f'扇区回读分块 {index} 长度不符')
            if part != expected_sectors[index * 16384 : index * 16384 + expected_len]:
                raise ValueError(f'扇区回读分块 {index} 内容与目标不符')
            raw_sectors.extend(part)
        if len(raw_sectors) != 132096 or bytes(raw_sectors) != expected_sectors:
            raise ValueError('258 扇区完整回读不符')

        if self._read(channel, 'preload-after', '/etc/ld.so.preload') != baseline_bytes:
            raise ValueError('/etc/ld.so.preload 未保持或未准确还原')
        if self._read(channel, 'state-repeat', self.control_prefix + '.state') != terminal:
            raise ValueError('终态复核不一致')

        report.update(
            protocol_gate_passed=True,
            planned_sector_readback_verified=True,
            preload_unchanged=True,
            patch_sectors=258,
            logical_write_bytes=132096,
            planned_sector_readback_sha256=hashlib.sha256(raw_sectors).hexdigest(),
        )
        self.safe_to_stop = True

    def __call__(self, driver, output, log, report):
        self.output = Path(output)
        channel = self.channel_factory(driver, self, log)
        report.update(
            engine=self.config['engine'],
            trigger_attempts=0,
            fixed_writes_attempted=0,
            debug_commands_sent=False,
            preload_written=False,
            protocol_gate_passed=False,
            partition_write_may_have_started=False,
            native_write_complete=False,
            planned_sector_readback_verified=False,
        )
        baseline_name, baseline_bytes = self._verify_base_files(channel)
        report['preload_baseline'] = baseline_name
        self._trigger_and_verify(channel, baseline_name, baseline_bytes, log, report)


class LibjitTrustOperation(_BaseTrustOperation):
    """libjit 方式：写入 RAM 票据后上传 /tmp/jiritsu/libJit.so 触发执行。"""

    def __init__(self, package_dir, channel_factory=Channel, clock=time.monotonic, sleep=time.sleep):
        super().__init__(package_dir, channel_factory, clock, sleep)
        self.payload = (self.package / 'materials/libJit.so').read_bytes()
        self.ticket = (self.package / 'materials/ticket.bin').read_bytes()
        self.reads['/tmp/jiritsu/libJit.so'] = 1048576
        self.reads[self.ticket_path] = 128
        self.writes = {
            self.ticket_path: self.ticket,
            '/tmp/jiritsu/libJit.so': self.payload,
        }

    def _trigger_and_verify(self, channel, baseline_name, baseline_bytes, log, report):
        candidates = [
            '/tmp/jiritsu/libJit.so',
            '/tmp/jbusy',
            self.ticket_path,
            *[self.control_prefix + s for s in ('.claim', '.state', '.state.new', '.output')],
        ]
        self._check_candidates_absent(channel, log, candidates)
        if self._read(channel, 'preload-before-upload', '/etc/ld.so.preload') != baseline_bytes:
            raise ValueError('上传前 /etc/ld.so.preload 发生变化')

        self._put(channel, self.ticket_path, self.ticket, report, 'ticket')
        if self._read(channel, 'ticket-readback', self.ticket_path) != self.ticket:
            raise ValueError('票据读回不一致')

        self.trigger_attempts = 1
        self.may_have_written = True
        report.update(trigger_attempts=1, partition_write_may_have_started=True)
        self._put(channel, '/tmp/jiritsu/libJit.so', self.payload, report, 'loader')
        self._poll_and_verify(channel, baseline_bytes, log, report)


class KitTrustOperation(_BaseTrustOperation):
    """kit 方式：上传随机路径 .so，临时写入 /etc/ld.so.preload 后发送一次 DEBUG 触发并还原 preload。"""

    def __init__(self, package_dir, channel_factory=Channel, clock=time.monotonic, sleep=time.sleep):
        super().__init__(package_dir, channel_factory, clock, sleep)
        self.kit_so_path = f'/tmp_wbshd/a7r5-trust-{self.run_id}.so'
        self.arm_bytes = (self.kit_so_path + '\n').encode('ascii')
        self.allow_debug = False
        self.reads[self.kit_so_path] = 1048576
        self.payloads_by_baseline = {
            name: (self.package / f'materials/kit-{name}.so').read_bytes()
            for name, _ in self.config['preload_baselines']
        }

    def guard_packet(self, packet):
        if packet[HEADER.size :] == DEBUG:
            if not self.allow_debug or packet != self.permitted_packet:
                raise PermissionError('未开放 DEBUG 或禁止重复触发')
            size, function, sequence, *meta = HEADER.unpack_from(packet)
            if size != len(DEBUG) or function != 0x40 or any(meta) or not 1 <= sequence <= self.packet_limit:
                raise PermissionError('DEBUG 报文头不符')
            return
        super().guard_packet(packet)

    def _trigger_and_verify(self, channel, baseline_name, baseline_bytes, log, report):
        payload = self.payloads_by_baseline[baseline_name]
        self.writes = {
            self.kit_so_path: payload,
            '/etc/ld.so.preload': self.arm_bytes,
        }
        candidates = [
            '/tmp/jbusy',
            self.kit_so_path,
            *[self.control_prefix + s for s in ('.claim', '.state', '.state.new', '.output')],
        ]
        self._check_candidates_absent(channel, log, candidates)

        self._put(channel, self.kit_so_path, payload, report, 'kit-payload')
        if self._read(channel, 'payload-readback', self.kit_so_path) != payload:
            raise ValueError('kit 载荷读回不一致')
        if self._read(channel, 'preload-before-arm', '/etc/ld.so.preload') != baseline_bytes:
            raise ValueError('挂载前 /etc/ld.so.preload 发生变化')

        report['preload_written'] = True
        self._put(channel, '/etc/ld.so.preload', self.arm_bytes, report, 'preload-arm')
        if self._read(channel, 'preload-armed', '/etc/ld.so.preload') != self.arm_bytes:
            raise ValueError('/etc/ld.so.preload 挂载读回不一致')

        self.allow_debug = True
        self.trigger_attempts = 1
        self.may_have_written = True
        report.update(trigger_attempts=1, debug_commands_sent=True, partition_write_may_have_started=True)
        try:
            channel.exchange(DEBUG, 4, action='debug', path='/etc/ld.so.preload')
        finally:
            self.allow_debug = False

        self._poll_and_verify(channel, baseline_bytes, log, report)
