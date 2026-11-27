"""libjit 与 kit 双引擎信任环境更新、cnflasha1 只读转存与本次 RAM 副本清理通道操作器。

三条通道共用同一套报文守卫、阶段化写入白名单与机内终态校验：
- 信任更新：计划扇区写入 + 机内/主机双重整分区摘要校验（9 块计划扇区回读）；
- cnflasha1 转存：1532 块 16 KiB 只读分块，机内两次整分区读取摘要一致才成功；
- RAM 副本清理：仅删除本次转存模板绑定的分块目录，回执与本机镜像摘要绑定。
"""
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import struct
import time

from usb_session import Channel, FileResultError, HEADER, READ, wire

DEBUG = struct.pack('<HH', 0x1001, 5) + b'\0\0\0'
PARTITION_BYTES = 25100288
CAPTURE_PART_BYTES = 16384
CAPTURE_PART_COUNT = PARTITION_BYTES // CAPTURE_PART_BYTES

CAPTURE_FAILURES = {
    40: '无法切换到 root 身份',
    41: '机内挂载命名空间与 PID 1 不一致',
    42: '/etc/ld.so.preload 不属于已适配基线',
    43: 'cnflasha1 设备号或容量身份不符',
    44: '/tmp_wbshd 容量、可用内存或文件大小预算不足',
    45: '无法创建本次 RAM 转存目录',
    46: '可用内存低于 64 MiB，未开始读取分区',
    48: '两次整分区读取摘要不一致',
    49: '转存期间 /etc/ld.so.preload 发生变化',
    50: '无法写入机内转存回执',
    61: '无法以只读方式打开 cnflasha1',
    62: 'cnflasha1 设备身份不符（需 252:129 / 25100288 字节）',
    63: '机内整分区读取失败',
    64: '机内 RAM 分块写入失败',
    65: '无法关闭 cnflasha1 只读句柄',
    66: '无法创建 RAM 分块文件',
    67: 'RAM 分块 fsync 失败',
    68: 'RAM 分块关闭失败',
    80: '无法切换工作进程身份',
    81: '无法建立新的挂载命名空间',
    82: '无法读取内核能力或 action 参数',
    83: '文件描述符上限异常',
    84: '无法重定向标准输入输出',
    85: '无法切换工作目录',
    86: '无法创建机内状态输出文件',
    87: '无法发布 RUNNING 状态',
    94: '工作进程仍有子进程残留',
    95: '输出长度或 fsync 异常',
    96: '无法发布终态',
    97: '无法确认 root 身份',
    98: '无法解除 /tmp/jiritsu/libJit.so 加载文件',
    99: '无法创建 claim 文件',
    100: 'claim、票据写入或票据删除失败',
    101: '无法派生机内工作进程',
    102: '无法创建 kit claim 文件',
    103: 'kit claim 写入或 fsync 失败',
}

CAPTURE_CLEANUP_FAILURES = {
    60: '清理前身份或挂载命名空间不符',
    61: '/etc/ld.so.preload 不属于已适配基线',
    62: '/tmp_wbshd 不是受控 tmpfs',
    63: '无法定位本次转存目录或控制目录',
    64: '转存回执、摘要或终态与本机记录不符',
    65: '本次转存目录存在非预期文件',
    66: 'RAM 分块缺失、类型或长度不符',
    67: '读取 RAM 分块失败',
    68: 'RAM 分块摘要与机内回执不符',
    69: '清理期间 /etc/ld.so.preload 发生变化',
    70: '删除前 RAM 分块身份变化',
    71: '无法删除 RAM 分块',
    72: '删除后 RAM 分块仍存在',
    73: '转存目录身份变化',
    74: '无法删除本次转存目录',
    75: '无法关闭目录句柄',
    76: '无法写入清理回执',
}
CAPTURE_CLEANUP_FAILURES.update({code: text for code, text in CAPTURE_FAILURES.items() if code >= 80})

CAPTURE_STATE_LINE = re.compile(
    rb'A7R5-JIT-1 (?P<run>[0-9a-f]{32}) '
    rb'(?P<phase>RUNNING|DONE|FAILED|TIMEOUT) (?P<code>-?\d+) '
    rb'uid=(?P<uid>-?\d+) euid=(?P<euid>-?\d+) bytes=(?P<bytes>-?\d+) '
    rb'disarmed=(?P<disarmed>\d+) children=(?P<children>-?\d+)\n'
)


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
    total = len(plan['rows'])
    expected += [
        ('FULL_LOGICAL_READBACK_MATCH', total, -1, 0),
        ('REOPENED_FULL_CAPTURE_MATCH', total, -1, 0),
        ('COMPLETED', total, -1, 0),
    ]
    if actual != expected:
        raise ValueError('机内日志阶段、扇区计数或偏移不符')
    return True


class _BaseOperation:
    """共享的通道守卫、环境基线校验、阶段化写入白名单与证据落盘。"""

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
        self.allow_debug = False
        self.safe_to_stop = False
        self.may_have_written = False
        self.trigger_attempts = 0
        self.stage = None
        self.stage_written = set()
        self.writes = {}
        self._write_guards = frozenset()
        self._select_guards = None
        self.reads = {
            '/version.txt': 4096,
            '/usr/lib/libJiritsu.so': self.config['loader_bytes'],
            '/etc/ld.so.preload': 4096,
            '/tmp/jbusy': 64,
            self.ticket_path: 128,
            self.control_prefix + '.claim': 128,
            self.control_prefix + '.state': 512,
            self.control_prefix + '.state.new': 512,
            self.control_prefix + '.output': 32768,
        }

    def _select_guard_set(self):
        if self._select_guards is None:
            self._select_guards = frozenset(
                struct.pack('<HH', 0x1001, 15) + b'\0' + wire(path) + b'\0' for path in self.reads
            )
        return self._select_guards

    def set_writes(self, writes):
        """切换写入阶段：同一路径在每个阶段最多写一次，报文白名单同步重建。"""
        self.writes = dict(writes)
        self.stage_written = set()
        self._write_guards = frozenset(
            struct.pack('<HH', 0x1001, 16) + b'\0\xff\0' + data for data in self.writes.values()
        )

    def guard_packet(self, packet):
        if packet != self.permitted_packet or len(packet) < HEADER.size + 7:
            raise PermissionError('未经授权的报文')
        size, function, sequence, *meta = HEADER.unpack_from(packet)
        body = packet[HEADER.size :]
        if size != len(body) or function != 0x40 or not 1 <= sequence <= self.packet_limit or any(meta):
            raise PermissionError('非法报文头字段')
        if body == DEBUG:
            # kit 触发报文仅在明确开放的那一次且内容完全一致时放行。
            if not self.allow_debug or size != len(DEBUG):
                raise PermissionError('未开放 DEBUG 或禁止重复触发')
            return
        if body != READ and body not in self._select_guard_set() and body not in self._write_guards:
            raise PermissionError('报文体不在本轮白名单内')

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

    def _read(self, channel, label, path, *, record=True):
        raw = channel.read(path, self.reads[path])
        if record and self.output is not None:
            (self.output / f'{label}.bin').write_bytes(raw)
        return raw

    def _put(self, channel, path, data, report, stage):
        if self.writes.get(path) != data:
            raise PermissionError(f'未列入本阶段写入白名单：{path}')
        if path in self.stage_written:
            raise PermissionError(f'{stage} 阶段禁止重复写入：{path}')
        self.stage_written.add(path)
        self.stage = stage
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
            raise ValueError('相机固件版本 (/version.txt) 与当前材料不符')
        loader = self._read(channel, 'loader', '/usr/lib/libJiritsu.so')
        if hashlib.sha256(loader).hexdigest() != self.config['loader_sha256']:
            raise ValueError('机内加载库 (/usr/lib/libJiritsu.so) 摘要不符')
        baseline = self._read(channel, 'preload-before', '/etc/ld.so.preload')
        for name, hex_str in self.config['preload_baselines']:
            if baseline == bytes.fromhex(hex_str):
                return name, baseline
        raise ValueError('机内 /etc/ld.so.preload 内容未适配，拒绝覆盖')


class _BaseTrustOperation(_BaseOperation):
    """信任更新共享骨架：机内整区摘要与计划前像/候选绑定、9 块计划扇区回读校验。"""

    def __init__(self, package_dir, channel_factory=Channel, clock=time.monotonic, sleep=time.sleep):
        super().__init__(package_dir, channel_factory, clock, sleep)
        self.memory_required_kib = 32768
        self.plan = json.loads((self.package / 'materials/write-plan.json').read_text())
        self.sectors = json.loads((self.package / 'materials/trust-sectors.json').read_text())
        self.patch = self.sectors['rows']
        if not self.patch or [r['offset'] for r in self.patch] != [r['offset'] for r in self.plan['rows']]:
            raise ValueError('写入计划与扇区材料不匹配')
        self.expected_source_sha256 = self.plan['source_sha256']
        self.expected_target_sha256 = self.plan.get('candidate_sha256') or self.sectors['target_sha256']
        if self.expected_source_sha256 != self.sectors['source_sha256']:
            raise ValueError('写入计划前像摘要与扇区材料不一致')
        if self.expected_target_sha256 != self.sectors['target_sha256']:
            raise ValueError('写入计划候选摘要与扇区材料不一致')
        self.patch_count = len(self.patch)
        self.logical_write_bytes = self.patch_count * 512
        self.readback_chunks = (self.logical_write_bytes + 16383) // 16384

        self.readback_parts = [
            (self.config['readback_path'] + f'.sectors-{i}', min(16384, self.logical_write_bytes - i * 16384))
            for i in range(self.readback_chunks)
        ]
        self.reads.update(self.readback_parts)
        self.reads[self.config['journal_path']] = 131072

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
            + f'sectors={self.patch_count} bytes={self.logical_write_bytes} reopened=1 '
              f'chunks={self.readback_chunks} chunk_bytes=16384 readback=planned-sectors-v2\n'.encode('ascii')
            + re.escape(self.config['expected_output_end'].encode())
        )
        match = re.fullmatch(pattern, data)
        if not match or len(data) != size:
            raise ValueError('机内原生输出标记或格式不符')
        candidate_sha = match[1].decode()
        source_sha = match[2].decode()
        # FORCE 模式按机内实际前像计算覆盖后的摘要，因此「写入后整分区摘要 == 计划候选」
        # 才是结果正确的充分条件：满足即表示落盘分区与计划目标逐字节一致。
        if candidate_sha != self.expected_target_sha256:
            raise ValueError(
                '机内写入后整分区摘要与计划候选不符，落盘分区不是计划目标'
                f'（机内 {candidate_sha}，计划 {self.expected_target_sha256}）'
            )
        report['actual_source_sha256'] = source_sha
        report['native_logical_partition_sha256'] = candidate_sha
        if source_sha != self.expected_source_sha256:
            # 前像与转存镜像不一致但结果仍与目标一致：差异只落在被整体覆盖的计划扇区内，
            # 落盘结果依然是目标信任态；记录漂移证据，不误判为失败。
            report['preimage_drift'] = {
                'device_source_sha256': source_sha,
                'plan_source_sha256': self.expected_source_sha256,
                'resolved_by_target_match': True,
            }
            log('preimage_drift_resolved_by_target_match', device_source_sha256=source_sha)

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
        if len(raw_sectors) != self.logical_write_bytes or bytes(raw_sectors) != expected_sectors:
            raise ValueError(f'{self.patch_count} 扇区完整回读不符')

        if self._read(channel, 'preload-after', '/etc/ld.so.preload') != baseline_bytes:
            raise ValueError('/etc/ld.so.preload 未保持或未准确还原')
        if self._read(channel, 'state-repeat', self.control_prefix + '.state') != terminal:
            raise ValueError('终态复核不一致')

        report.update(
            protocol_gate_passed=True,
            planned_sector_readback_verified=True,
            preload_unchanged=True,
            patch_sectors=self.patch_count,
            logical_write_bytes=self.logical_write_bytes,
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
        self.set_writes({self.ticket_path: self.ticket, '/tmp/jiritsu/libJit.so': self.payload})

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
        self.reads[self.kit_so_path] = 1048576
        self.payloads_by_baseline = {
            name: (self.package / f'materials/kit-{name}.so').read_bytes()
            for name, _ in self.config['preload_baselines']
        }

    def _trigger_and_verify(self, channel, baseline_name, baseline_bytes, log, report):
        payload = self.payloads_by_baseline[baseline_name]
        candidates = [
            '/tmp/jbusy',
            self.kit_so_path,
            *[self.control_prefix + s for s in ('.claim', '.state', '.state.new', '.output')],
        ]
        self._check_candidates_absent(channel, log, candidates)
        self.set_writes({self.kit_so_path: payload, '/etc/ld.so.preload': self.arm_bytes})

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


class _BaseCaptureOperation(_BaseOperation):
    """cnflasha1 只读分块转存 + 本次 RAM 副本清理（libjit / kit 共用同一套终态与摘要门控）。"""

    packet_limit = 4096
    capture_marker = b''
    cleanup_marker = b''

    def __init__(self, package_dir, channel_factory=Channel, clock=time.monotonic, sleep=time.sleep):
        super().__init__(package_dir, channel_factory, clock, sleep)
        config = self.config
        if config.get('capture_control_layout') != 'ram-v2':
            raise ValueError('转存控制目录布局不符，请重新构建客户端')
        if config.get('capture_format') != 'ram-16k-v1':
            raise ValueError('未知转存分块布局')
        if config.get('capture_cleanup_policy') != 'verified-current-ram-v2':
            raise ValueError('转存缺少本次 RAM 副本清理模板，请重新构建客户端')
        self.chunk_bytes = int(config['capture_chunk_bytes'])
        self.chunk_count = int(config['capture_chunk_count'])
        self.partition_bytes = int(config['partition_bytes'])
        if (
            self.chunk_bytes != CAPTURE_PART_BYTES
            or self.chunk_count != CAPTURE_PART_COUNT
            or self.partition_bytes != PARTITION_BYTES
        ):
            raise ValueError('转存分块布局与编译模板不符')
        self.cleanup_prefix = config['cleanup_control_dir'] + '/task'
        self.cleanup_ticket = config['cleanup_ticket_path']
        self.capture_path = config['capture_path']
        self.parts = [
            (self.capture_path + f'.part-{index}', min(self.chunk_bytes, self.partition_bytes - index * self.chunk_bytes))
            for index in range(self.chunk_count)
        ]
        self.reads.update(self.parts)
        self.reads[self.cleanup_ticket] = 128
        self.reads[self.cleanup_prefix + '.state'] = 512
        self.reads[self.cleanup_prefix + '.output'] = 32768
        self.capture_sha256 = None

    def _check_markers(self):
        raise NotImplementedError

    def _payload_paths(self, baseline_name):
        raise NotImplementedError

    def _upload_trigger(self, channel, baseline_name, baseline_bytes, log, report, *, stage):
        raise NotImplementedError

    def _capture_output_pattern(self):
        begin = re.escape(self.config['expected_output_begin'].encode())
        end = re.escape(self.config['expected_output_end'].encode())
        summary = (
            f' bytes={self.partition_bytes} twice=1 chunks={self.chunk_count} '
            f'chunk_bytes={self.chunk_bytes}\n'
        ).encode('ascii')
        return re.compile(begin + rb'A7R5_CAPTURE_COMPLETE ([0-9a-f]{64})' + re.escape(summary) + end)

    def _fsync_output(self):
        """逐块文件已各自 fsync；再固化目录项，确保持久化证据先于机内 RAM 副本清理。"""
        fd = os.open(self.output, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)

    def _write_chunk(self, index, part):
        chunk_file = self.output / f'partition-chunk-{index:03d}.bin'
        fd = os.open(chunk_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        try:
            view = memoryview(part)
            while view:
                written = os.write(fd, view)
                if written <= 0:
                    raise OSError(f'转存分块 {index} 写入失败')
                view = view[written:]
            os.fsync(fd)
        finally:
            os.close(fd)

    def _wait_terminal(self, channel, prefix, name, report, failures):
        """轮询转存/清理控制状态；失败时保留现场并附机内回执原文。"""
        label = f'{name}-state'
        deadline = self.clock() + self.config['observe_seconds']
        terminal = None
        size = 0
        for index in range(120):
            if self.clock() >= deadline:
                break
            try:
                raw = self._read(channel, f'{label}-{index:03d}', prefix + '.state')
            except FileResultError as error:
                if error.result != 0x10000006:
                    raise
                self.sleep(0.5)
                continue
            match = CAPTURE_STATE_LINE.fullmatch(raw)
            if not match or match['run'].decode() != self.run_id or (match['uid'], match['euid']) != (b'0', b'0'):
                raise ValueError(f'{label} 状态会话或 root 身份不符')
            if match['phase'] == b'FAILED':
                code = int(match['code'])
                report[f'{name}_native_exit_code'] = code
                self._record_failure_output(channel, prefix, name, report)
                raise RuntimeError(f'{name} 机内任务失败 (code={code})：{failures.get(code, "未适配的失败码")}')
            if match['phase'] == b'TIMEOUT':
                raise RuntimeError(f'{name} 机内任务超时：' + raw.decode().strip())
            if match['phase'] == b'DONE':
                if match['code'] != b'0' or (match['disarmed'], match['children']) != (b'1', b'0'):
                    raise ValueError(f'{name} 成功终态退出码或子进程状态门槛不符')
                size = int(match['bytes'])
                if not 0 < size < 32768:
                    raise ValueError(f'{name} 输出长度无效')
                terminal = raw
                break
            self.sleep(0.5)
        if terminal is None:
            raise TimeoutError(f'等待 {name} 机内终态超时，不自动 STOP')
        report[f'{name}_terminal_sha256'] = hashlib.sha256(terminal).hexdigest()
        return terminal, size

    def _record_failure_output(self, channel, prefix, name, report):
        """失败现场只读取机内回执原文，便于在 result.json 中定位失败码。"""
        try:
            raw = self._read(channel, f'{name}-failure-output', prefix + '.output')
        except (FileResultError, ValueError, PermissionError):
            return
        report[f'{name}_failure_output'] = raw.decode('ascii', 'replace')

    def _capture(self, channel, baseline_name, baseline_bytes, log, report):
        candidates = [
            '/tmp/jbusy',
            self.ticket_path,
            *self._payload_paths(baseline_name),
            *[self.control_prefix + s for s in ('.claim', '.state', '.state.new', '.output')],
        ]
        self._check_candidates_absent(channel, log, candidates)
        if self._read(channel, 'preload-before-dump', '/etc/ld.so.preload') != baseline_bytes:
            raise ValueError('转存前 /etc/ld.so.preload 发生变化')

        self._upload_trigger(channel, baseline_name, baseline_bytes, log, report, stage='capture')
        terminal, size = self._wait_terminal(channel, self.control_prefix, 'capture', report, CAPTURE_FAILURES)
        data = self._read(channel, 'capture-output', self.control_prefix + '.output')
        match = self._capture_output_pattern().fullmatch(data)
        if not match or len(data) != size:
            raise ValueError('机内转存输出标记或格式不符')
        digest = match[1].decode()
        report.update(
            native_capture_complete=True,
            native_capture_sha256=digest,
            native_capture_bytes=self.partition_bytes,
            native_capture_chunks=self.chunk_count,
            capture_chunk_bytes=self.chunk_bytes,
            capture_expected_chunks=self.chunk_count,
            capture_download_chunks=0,
        )

        total = 0
        download_hash = hashlib.sha256()
        for index, (path, expected) in enumerate(self.parts):
            part = self._read(channel, f'partition-chunk-{index:03d}', path, record=False)
            if len(part) != expected:
                raise ValueError(f'转存分块 {index} 长度不符')
            self._write_chunk(index, part)
            total += len(part)
            download_hash.update(part)
            report['capture_download_chunks'] = index + 1
            report['capture_download_bytes'] = total
            report['capture_download_sha256'] = download_hash.hexdigest()

        if total != self.partition_bytes or download_hash.hexdigest() != digest:
            raise ValueError('本机下载镜像长度或摘要与机内整分区摘要不符')
        if self._read(channel, 'preload-after-dump', '/etc/ld.so.preload') != baseline_bytes:
            raise ValueError('转存后 /etc/ld.so.preload 发生变化')
        if self._read(channel, 'state-repeat-dump', self.control_prefix + '.state') != terminal:
            raise ValueError('转存终态复核不一致')
        self._fsync_output()

        self.capture_sha256 = digest
        report.update(
            protocol_gate_passed=True,
            preload_unchanged=True,
            capture_verified=True,
            capture_sha256=digest,
            capture_bytes=total,
            partition_writes=0,
            expected_preload_hex=baseline_bytes.hex(),
        )

    def _cleanup(self, channel, baseline_name, baseline_bytes, log, report):
        digest = self.capture_sha256
        if not report.get('capture_verified') or not digest:
            raise PermissionError('本机转存未通过校验，禁止清理机内 RAM 副本')
        if self._read(channel, 'preload-before-cleanup', '/etc/ld.so.preload') != baseline_bytes:
            raise ValueError('清理前 /etc/ld.so.preload 发生变化')

        self._upload_trigger(channel, baseline_name, baseline_bytes, log, report, stage='cleanup')
        terminal, size = self._wait_terminal(
            channel, self.cleanup_prefix, 'cleanup', report, CAPTURE_CLEANUP_FAILURES
        )
        data = self._read(channel, 'cleanup-output', self.cleanup_prefix + '.output')
        expected = (
            f'A7R5_CAPTURE_CLEANUP {self.run_id} sha256={digest} '
            f'deleted={self.chunk_count} bytes={self.partition_bytes} directory_removed=1\n'
        ).encode('ascii')
        if data != expected or len(data) != size:
            raise ValueError('机内 RAM 副本清理回执不符')
        if self._read(channel, 'preload-after-cleanup', '/etc/ld.so.preload') != baseline_bytes:
            raise ValueError('清理后 /etc/ld.so.preload 发生变化')
        if self._read(channel, 'cleanup-state-repeat', self.cleanup_prefix + '.state') != terminal:
            raise ValueError('清理终态复核不一致')

    def __call__(self, driver, output, log, report):
        self.output = Path(output)
        channel = self.channel_factory(driver, self, log)
        report.update(
            engine=self.config['engine'],
            capture_action='cnflasha1_dump',
            trigger_attempts=0,
            fixed_writes_attempted=0,
            debug_commands_sent=False,
            preload_written=False,
            protocol_gate_passed=False,
            partition_writes=0,
            partition_write_may_have_started=False,
            capture_verified=False,
            capture_cleanup_state='not_started',
            capture_cleanup_verified=False,
        )
        baseline_name, baseline_bytes = self._verify_base_files(channel)
        report['preload_baseline'] = baseline_name
        self._capture(channel, baseline_name, baseline_bytes, log, report)

        try:
            self._cleanup(channel, baseline_name, baseline_bytes, log, report)
        except (Exception, KeyboardInterrupt) as error:
            # 本机镜像已完整下载并复核，允许 STOP 恢复普通 MSC；但本次运行不再继续写入信任环境。
            self.safe_to_stop = True
            report.update(
                capture_cleanup_state='failed',
                capture_cleanup_error=f'{type(error).__name__}: {error}',
            )
            raise
        report.update(capture_cleanup_state='complete', capture_cleanup_verified=True)
        self.safe_to_stop = True


class LibjitCaptureOperation(_BaseCaptureOperation):
    """libjit 转存：票据 + /tmp/jiritsu/libJit.so 两次上传（转存载荷、清理载荷）。"""

    capture_marker = b'A7R5_CAPTURE_READONLY_V5_RAM_16K'
    cleanup_marker = b'A7R5_CAPTURE_CLEANUP_V2_RAM_16K'

    def __init__(self, package_dir, channel_factory=Channel, clock=time.monotonic, sleep=time.sleep):
        super().__init__(package_dir, channel_factory, clock, sleep)
        self.payload = (self.package / 'materials/capture.so').read_bytes()
        self.cleanup_payload = (self.package / 'materials/capture-cleanup.so').read_bytes()
        self.ticket = (self.package / 'materials/ticket.bin').read_bytes()
        self.reads['/tmp/jiritsu/libJit.so'] = 1048576
        self.reads[self.ticket_path] = 128
        self._check_markers()

    def _check_markers(self):
        if self.capture_marker not in self.payload:
            raise ValueError('转存载荷编译标记不符')
        if self.cleanup_marker not in self.cleanup_payload:
            raise ValueError('RAM 清理载荷编译标记不符')

    def _payload_paths(self, baseline_name):
        return ('/tmp/jiritsu/libJit.so',)

    def _upload_trigger(self, channel, baseline_name, baseline_bytes, log, report, *, stage):
        target = '/tmp/jiritsu/libJit.so'
        if stage == 'capture':
            ticket_path, payload, label = self.ticket_path, self.payload, 'capture'
        else:
            ticket_path, payload, label = self.cleanup_ticket, self.cleanup_payload, 'cleanup'
        self.set_writes({ticket_path: self.ticket, target: payload})
        self._put(channel, ticket_path, self.ticket, report, f'{label}-ticket')
        if self._read(channel, f'{label}-ticket-readback', ticket_path) != self.ticket:
            raise ValueError(f'{label} 票据读回不一致')

        self.trigger_attempts += 1
        self.may_have_written = True
        report.update(trigger_attempts=self.trigger_attempts, upload_stage=label)
        self._put(channel, target, payload, report, f'{label}-payload')


class KitCaptureOperation(_BaseCaptureOperation):
    """kit 转存：/tmp_wbshd 随机路径 .so + 临时 preload 挂载 + 单次 DEBUG 触发，零写入 /tmp/jiritsu/。"""

    capture_marker = b'A7R5_CAPTURE_KIT_READONLY_V1_RAM_16K'
    cleanup_marker = b'A7R5_CAPTURE_KIT_CLEANUP_V1_RAM_16K'

    def __init__(self, package_dir, channel_factory=Channel, clock=time.monotonic, sleep=time.sleep):
        super().__init__(package_dir, channel_factory, clock, sleep)
        self.capture_so_path = self.config['capture_kit_so_path']
        self.cleanup_so_path = self.config['cleanup_kit_so_path']
        self.arm_capture = (self.capture_so_path + '\n').encode('ascii')
        self.arm_cleanup = (self.cleanup_so_path + '\n').encode('ascii')
        self.reads[self.capture_so_path] = 1048576
        self.reads[self.cleanup_so_path] = 1048576
        self.payloads = {
            name: (self.package / f'materials/capture-{name}.so').read_bytes()
            for name, _ in self.config['preload_baselines']
        }
        self.cleanup_payloads = {
            name: (self.package / f'materials/cleanup-{name}.so').read_bytes()
            for name, _ in self.config['preload_baselines']
        }
        self._check_markers()

    def _check_markers(self):
        for name, payload in self.payloads.items():
            if self.capture_marker not in payload:
                raise ValueError(f'kit 转存载荷编译标记不符：{name}')
        for name, payload in self.cleanup_payloads.items():
            if self.cleanup_marker not in payload:
                raise ValueError(f'kit RAM 清理载荷编译标记不符：{name}')

    def _payload_paths(self, baseline_name):
        return (self.capture_so_path, self.cleanup_so_path)

    def _upload_trigger(self, channel, baseline_name, baseline_bytes, log, report, *, stage):
        if stage == 'capture':
            so_path, payload, arm, label = self.capture_so_path, self.payloads[baseline_name], self.arm_capture, 'capture'
        else:
            so_path, payload, arm, label = self.cleanup_so_path, self.cleanup_payloads[baseline_name], self.arm_cleanup, 'cleanup'
        self.set_writes({so_path: payload, '/etc/ld.so.preload': arm})
        self._put(channel, so_path, payload, report, f'{label}-kit-payload')
        if self._read(channel, f'{label}-payload-readback', so_path) != payload:
            raise ValueError(f'{label} kit 载荷读回不一致')
        if self._read(channel, f'{label}-preload-before-arm', '/etc/ld.so.preload') != baseline_bytes:
            raise ValueError(f'{label} 挂载前 /etc/ld.so.preload 发生变化')

        report['preload_written'] = True
        self._put(channel, '/etc/ld.so.preload', arm, report, f'{label}-preload-arm')
        if self._read(channel, f'{label}-preload-armed', '/etc/ld.so.preload') != arm:
            raise ValueError(f'{label} /etc/ld.so.preload 挂载读回不一致')

        self.allow_debug = True
        self.trigger_attempts += 1
        report.update(trigger_attempts=self.trigger_attempts, debug_commands_sent=True)
        try:
            channel.exchange(DEBUG, 4, action='debug', path='/etc/ld.so.preload')
        finally:
            self.allow_debug = False