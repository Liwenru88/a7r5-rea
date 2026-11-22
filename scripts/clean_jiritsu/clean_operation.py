"""kit 方式扫描/清理 /tmp/jiritsu 的 USB 通道操作器（零写入 /tmp/jiritsu）。"""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import time

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
TRUST_DIR = PROJECT / 'scripts/trust_update'
if str(TRUST_DIR) not in sys.path:
    sys.path.insert(0, str(TRUST_DIR))

from usb_session import Channel, FileResultError, HEADER, READ, wire

DEBUG = struct.pack('<HH', 0x1001, 5) + b'\0\0\0'
ENTRY_RE = re.compile(
    r'^ENTRY type=(reg|dir|other) action=(keep|would_delete|deleted|delete_failed) '
    r'size=(-?\d+) est_slots=(\d+) err=(\d+) name=(.+)$'
)
SUMMARY_RE = re.compile(
    r'^CLEAN_SUMMARY mode=(scan|apply) target=(\S+) fs_type=(\d+) overflow=(\d+) '
    r'before_entries=(\d+) before_reg=(\d+) before_est_slots=(\d+) before_avail_bytes=(-?\d+) '
    r'matched=(\d+) deleted=(\d+) delete_failed=(\d+) kept=(\d+) '
    r'after_entries=(\d+) after_reg=(\d+) after_est_slots=(\d+) after_avail_bytes=(-?\d+)$'
)


def parse_clean_output(raw, begin_marker, end_marker, expected_mode):
    """解析并校验机内输出：返回 (entries, summary, truncated_omitted)。"""
    text = raw.decode('utf-8', errors='replace')
    if not text.startswith(begin_marker) or not text.endswith(end_marker):
        raise ValueError('机内清理输出头尾标记不符')
    body = text[len(begin_marker) : len(text) - len(end_marker)]
    entries = []
    summary = None
    truncated = 0

    for line in body.splitlines():
        if not line:
            continue
        m_entry = ENTRY_RE.fullmatch(line)
        if m_entry:
            entries.append(
                {
                    'type': m_entry[1],
                    'action': m_entry[2],
                    'size': int(m_entry[3]),
                    'est_slots': int(m_entry[4]),
                    'errno': int(m_entry[5]),
                    'name': m_entry[6],
                }
            )
            continue
        if line.startswith('ENTRIES_TRUNCATED omitted='):
            truncated = int(line.split('=', 1)[1])
            continue
        m_sum = SUMMARY_RE.fullmatch(line)
        if m_sum:
            summary = {
                'mode': m_sum[1],
                'target': m_sum[2],
                'fs_type': int(m_sum[3]),
                'overflow': bool(int(m_sum[4])),
                'before_entries': int(m_sum[5]),
                'before_reg': int(m_sum[6]),
                'before_est_slots': int(m_sum[7]),
                'before_avail_bytes': int(m_sum[8]),
                'matched': int(m_sum[9]),
                'deleted': int(m_sum[10]),
                'delete_failed': int(m_sum[11]),
                'kept': int(m_sum[12]),
                'after_entries': int(m_sum[13]),
                'after_reg': int(m_sum[14]),
                'after_est_slots': int(m_sum[15]),
                'after_avail_bytes': int(m_sum[16]),
            }
            continue
        raise ValueError(f'机内清理输出存在未预期行：{line}')

    if summary is None or summary['mode'] != expected_mode:
        raise ValueError('缺少清理汇总行或执行模式不符')
    return entries, summary, truncated


class CleanJiritsuOperation:
    """仅上传载荷到 /tmp_wbshd/ 并借临时 preload + DEBUG 触发清理，通过后开放 STOP。"""

    packet_limit = 512
    usb_read_size = 8192
    strict_usb_reads = True

    def __init__(self, package_dir, channel_factory=Channel, clock=time.monotonic, sleep=time.sleep):
        self.package = Path(package_dir)
        self.config = json.loads((self.package / 'config.json').read_text())
        self.run_id = self.config['run_id']
        self.control_prefix = self.config['control_prefix']
        self.kit_so_path = self.config['kit_so_path']
        self.arm_bytes = (self.kit_so_path + '\n').encode('ascii')
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
        self.written = set()

        self.reads = {
            '/version.txt': 4096,
            '/usr/lib/libJiritsu.so': self.config['loader_bytes'],
            '/etc/ld.so.preload': 4096,
            '/tmp/jbusy': 64,
            self.kit_so_path: 1048576,
            self.control_prefix + '.state': 512,
            self.control_prefix + '.state.new': 512,
            self.control_prefix + '.output': 65536,
        }
        self.payloads_by_baseline = {
            name: (self.package / f'materials/kit-{name}.so').read_bytes()
            for name, _ in self.config['preload_baselines']
        }
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
        if raw != self.config['interfaces'].get(f'interface-{self.interfaces_seen}.json'):
            raise ValueError(f'接口 {self.interfaces_seen} 指纹或物理端口不符')

    def guard_packet(self, packet):
        if packet != self.permitted_packet or len(packet) < HEADER.size + 7:
            raise PermissionError('未经授权的报文')
        size, function, sequence, *meta = HEADER.unpack_from(packet)
        body = packet[HEADER.size :]
        if size != len(body) or function != 0x40 or not 1 <= sequence <= self.packet_limit or any(meta):
            raise PermissionError('非法报文头字段')
        if body == DEBUG:
            if not self.allow_debug:
                raise PermissionError('未开放 DEBUG 或禁止重复触发')
            return
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

    def __call__(self, driver, output, log, report):
        self.output = Path(output)
        channel = self.channel_factory(driver, self, log)
        report.update(
            engine='kit',
            mode=self.config['mode'],
            fixed_writes_attempted=0,
            trigger_attempts=0,
            preload_written=False,
            debug_commands_sent=False,
            protocol_gate_passed=False,
        )

        ver = self._read(channel, 'version', '/version.txt')
        if hashlib.sha256(ver).hexdigest() != self.config['version_sha256']:
            raise ValueError('相机固件版本 (/version.txt) 不符')
        loader = self._read(channel, 'loader', '/usr/lib/libJiritsu.so')
        if hashlib.sha256(loader).hexdigest() != self.config['loader_sha256']:
            raise ValueError('机内加载库 (/usr/lib/libJiritsu.so) 摘要不符')
        baseline = self._read(channel, 'preload-before', '/etc/ld.so.preload')
        baseline_name = next(
            (name for name, hex_str in self.config['preload_baselines'] if baseline == bytes.fromhex(hex_str)),
            None,
        )
        if baseline_name is None:
            raise ValueError('机内 /etc/ld.so.preload 内容未适配，拒绝覆盖')
        report['preload_baseline'] = baseline_name

        payload = self.payloads_by_baseline[baseline_name]
        self.writes = {
            self.kit_so_path: payload,
            '/etc/ld.so.preload': self.arm_bytes,
        }

        for idx, path in enumerate(
            ['/tmp/jbusy', self.kit_so_path, self.control_prefix + '.state', self.control_prefix + '.state.new', self.control_prefix + '.output']
        ):
            try:
                self._read(channel, f'candidate-{idx}', path)
            except FileResultError as error:
                if error.result != 0x10000006:
                    raise
                log('stat_failed_candidate', path=path)
                continue
            raise ValueError(f'工作路径已有残留内容，停止：{path}')

        self._put(channel, self.kit_so_path, payload, report, 'kit-payload')
        if self._read(channel, 'payload-readback', self.kit_so_path) != payload:
            raise ValueError('清理载荷读回不一致')
        if self._read(channel, 'preload-before-arm', '/etc/ld.so.preload') != baseline:
            raise ValueError('挂载前 /etc/ld.so.preload 发生变化')

        report['preload_written'] = True
        self._put(channel, '/etc/ld.so.preload', self.arm_bytes, report, 'preload-arm')
        if self._read(channel, 'preload-armed', '/etc/ld.so.preload') != self.arm_bytes:
            raise ValueError('/etc/ld.so.preload 挂载读回不一致')

        self.allow_debug = True
        report.update(trigger_attempts=1, debug_commands_sent=True)
        try:
            channel.exchange(DEBUG, 4, action='debug', path='/etc/ld.so.preload')
        finally:
            self.allow_debug = False

        deadline = self.clock() + self.config['observe_seconds']
        terminal = None
        size = 0
        for idx in range(120):
            if self.clock() >= deadline:
                break
            try:
                raw = self._read(channel, f'state-{idx:03d}', self.control_prefix + '.state')
            except FileResultError as error:
                if error.result != 0x10000006:
                    raise
                self.sleep(0.5)
                continue
            match = re.fullmatch(
                rb'A7R5-JIT-1 ' + self.run_id.encode() + rb' (RUNNING|DONE|FAILED) (\d+) uid=(\d+) euid=(\d+) bytes=(-?\d+) disarmed=(\d+) children=(\d+)\n',
                raw,
            )
            if not match or match.group(3, 4) != (b'0', b'0'):
                raise ValueError('清理任务会话或 root 身份不符')
            if match[1] == b'FAILED':
                raise RuntimeError('机内清理任务失败：' + raw.decode().strip())
            if match[1] == b'DONE':
                if match[2] != b'0' or match.group(6, 7) != (b'1', b'0'):
                    raise ValueError('成功终态退出码或子进程状态门槛不符')
                size = int(match[5])
                if not 0 < size < 65536:
                    raise ValueError('清理输出长度无效')
                terminal = raw
                break
            self.sleep(0.5)

        if terminal is None:
            raise TimeoutError('等待机内清理任务完成超时')

        out_raw = self._read(channel, 'clean-output', self.control_prefix + '.output')
        if len(out_raw) != size:
            raise ValueError('清理输出实际长度与终态声明不符')

        entries, summary, truncated = parse_clean_output(
            out_raw,
            self.config['expected_output_begin'],
            self.config['expected_output_end'],
            self.config['mode'],
        )
        if self._read(channel, 'preload-after', '/etc/ld.so.preload') != baseline:
            raise ValueError('/etc/ld.so.preload 未准确还原')
        if self._read(channel, 'state-repeat', self.control_prefix + '.state') != terminal:
            raise ValueError('终态复核不一致')

        (self.output.parent / 'entries.json').write_text(json.dumps(entries, ensure_ascii=False, indent=2) + '\n')
        report.update(
            protocol_gate_passed=True,
            preload_unchanged=True,
            entries_count=len(entries),
            entries_truncated=truncated,
            clean_summary=summary,
        )
        self.safe_to_stop = True
