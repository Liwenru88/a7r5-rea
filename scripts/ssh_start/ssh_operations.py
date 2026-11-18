"""单会话 SSH 加载、触发与监听验证操作器（同时支持 libjit 与 kit）。"""
import hashlib
import json
from pathlib import Path
import re
import struct
import sys
import time

PROJECT = Path(__file__).resolve().parents[2]
TRUST_DIR = PROJECT / 'scripts/trust_update'
DESKTOP_ENGINE = PROJECT / 'a7r5-desktop/engine'
for _p in (str(TRUST_DIR), str(DESKTOP_ENGINE)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import policy
from usb_session import Channel, FileResultError, HEADER, READ, wire

DEBUG = struct.pack('<HH', 0x1001, 5) + b'\0\0\0'


class JoinedSSHOperation:
    """在单次 USB 0e0a→0336 会话内完成 SSH 程序上传、触发、监听/心跳核验，通过后才允许 STOP。"""

    packet_limit = 512
    usb_read_size = 8192
    strict_usb_reads = True

    def __init__(self, package_dir, channel_factory=Channel, clock=time.monotonic, sleep=time.sleep):
        self.package = Path(package_dir)
        self.config = json.loads((self.package / 'config.json').read_text())
        self.materials = self.package / 'materials'
        self.build = json.loads((self.materials / 'build.json').read_text())
        self.engine = self.config['engine']
        self.run_id = self.build['run_id']
        self.prefix = self.build['prefix']
        self.ram = self.build['ram_directory']
        self.ttl_seconds = self.build['ttl_seconds']
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
        self.allow_debug = False

        self.uploads = {path: (self.materials / name).read_bytes() for path, name in self.build['uploads'].items()}
        self.reads = {
            '/version.txt': 4096,
            '/usr/lib/libJiritsu.so': self.config['loader_bytes'],
            '/etc/ld.so.preload': 4096,
            '/tmp/jbusy': 64,
            self.prefix + '.claim': 128,
            self.prefix + '.trigger-state': 512,
            self.prefix + '.trigger-new': 512,
            self.ram + '/ready': 1024,
            self.ram + '/heartbeat': 512,
            self.ram + '/host-public-key': 512,
            self.ram + '/hostkey-check': 256,
            self.ram + '/banner': 256,
            self.ram + '/started': 1024,
            self.ram + '/result': 1024,
        }
        self.reads.update({path: len(data) for path, data in self.uploads.items()})
        self.writes = dict(self.uploads)

        if self.engine == 'libjit':
            self.ticket_path = self.prefix + '.ticket'
            self.ticket_bytes = (self.materials / 'ticket.bin').read_bytes()
            self.libjit_bytes = (self.materials / 'libJit.so').read_bytes()
            self.reads['/tmp/jiritsu/libJit.so'] = 65536
            self.reads[self.ticket_path] = 128
            self.writes[self.ticket_path] = self.ticket_bytes
            self.writes['/tmp/jiritsu/libJit.so'] = self.libjit_bytes
        else:
            self.kit_so_path = f'/tmp/jiritsu/a7r5-{self.run_id}.so'
            self.arm_bytes = (self.kit_so_path + '\n').encode('ascii')
            self.reads[self.kit_so_path] = 1048576
            self.kit_payloads = {
                name: (self.materials / f'kit-{name}.so').read_bytes()
                for name, _ in self.config['preload_baselines']
            }

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
        if self.engine == 'kit' and body == DEBUG:
            if not self.allow_debug:
                raise PermissionError('未开放 DEBUG 或禁止重复触发')
            return
        selects = {struct.pack('<HH', 0x1001, 15) + b'\0' + wire(p) + b'\0' for p in self.reads}
        puts = {struct.pack('<HH', 0x1001, 16) + b'\0\xff\0' + d for d in self.writes.values()}
        if body not in selects | puts | {READ}:
            raise PermissionError('报文体不在 SSH 白名单内')

    def __call__(self, driver, output, log, report):
        self.output = Path(output)
        channel = self.channel_factory(driver, self, log)
        written = set()
        report.update(
            engine=self.engine,
            fixed_writes_attempted=0,
            trigger_attempts=0,
            preload_written=False,
            debug_commands_sent=False,
            protocol_gate_passed=False,
            service_ready=False,
        )

        def read(label, path):
            raw = channel.read(path, self.reads[path])
            (self.output / f'{label}.bin').write_bytes(raw)
            return raw

        def absent(label, path):
            try:
                read(label, path)
            except FileResultError as exc:
                if exc.result != 0x10000006:
                    raise
                log('candidate_unreadable', path=path)
                return
            raise ValueError(f'路径已有残留内容，停止：{path}')

        def put(path, data):
            if path in written:
                raise PermissionError(f'禁止重复写入：{path}')
            written.add(path)
            report['fixed_writes_attempted'] += 1
            channel.put(path, data)

        def same(label, path, expected):
            if read(label, path) != expected:
                raise ValueError(f'读回内容不符：{label}')

        if hashlib.sha256(read('version', '/version.txt')).hexdigest() != self.config['version_sha256']:
            raise ValueError('相机固件版本 (/version.txt) 不符')
        if hashlib.sha256(read('loader', '/usr/lib/libJiritsu.so')).hexdigest() != self.config['loader_sha256']:
            raise ValueError('机内加载库 (/usr/lib/libJiritsu.so) 摘要不符')

        baseline = read('preload-before', '/etc/ld.so.preload')
        baseline_name = next(
            (name for name, hex_str in self.config['preload_baselines'] if baseline == bytes.fromhex(hex_str)),
            None,
        )
        if baseline_name is None:
            raise ValueError('机内 /etc/ld.so.preload 类型未适配')
        report['preload_baseline'] = baseline_name

        # 阶段 1：上传 service / session / sftp 并逐一核对
        for idx, path in enumerate(self.uploads):
            absent(f'load-candidate-{idx}', path)
        for idx, (path, data) in enumerate(self.uploads.items()):
            put(path, data)
            same(f'load-verify-{idx}', path, data)

        # 阶段 2：触发启动并核对监听、公钥与心跳
        extra_candidates = ['/tmp/jbusy', self.prefix + '.trigger-state', self.prefix + '.trigger-new',
                            self.ram + '/ready', self.ram + '/result']
        if self.engine == 'libjit':
            extra_candidates += ['/tmp/jiritsu/libJit.so', self.ticket_path, self.prefix + '.claim']
        else:
            extra_candidates += [self.kit_so_path]
        for idx, path in enumerate(extra_candidates):
            absent(f'start-candidate-{idx}', path)
        same('preload-before-trigger', '/etc/ld.so.preload', baseline)

        if self.engine == 'libjit':
            put(self.ticket_path, self.ticket_bytes)
            same('ticket-readback', self.ticket_path, self.ticket_bytes)
            report['trigger_attempts'] = 1
            put('/tmp/jiritsu/libJit.so', self.libjit_bytes)
        else:
            kit_payload = self.kit_payloads[baseline_name]
            self.writes[self.kit_so_path] = kit_payload
            self.writes['/etc/ld.so.preload'] = self.arm_bytes
            put(self.kit_so_path, kit_payload)
            same('kit-payload-readback', self.kit_so_path, kit_payload)
            same('preload-before-arm', '/etc/ld.so.preload', baseline)
            report['preload_written'] = True
            put('/etc/ld.so.preload', self.arm_bytes)
            same('preload-armed', '/etc/ld.so.preload', self.arm_bytes)
            self.allow_debug = True
            report.update(trigger_attempts=1, debug_commands_sent=True)
            try:
                channel.exchange(DEBUG, 4, action='debug', path='/etc/ld.so.preload')
            finally:
                self.allow_debug = False

        deadline = self.clock() + 40
        ready_raw = None
        for idx in range(80):
            try:
                raw = read(f'ready-poll-{idx:02d}', self.ram + '/ready')
            except FileResultError as exc:
                if exc.result != 0x10000006:
                    raise
            else:
                policy.ready(raw, self.run_id, self.ttl_seconds)
                ready_raw = raw
                break
            if self.clock() >= deadline:
                raise TimeoutError('等待 SSH 服务 READY 超时')
            self.sleep(0.5)
        if ready_raw is None:
            raise TimeoutError('SSH 服务未返回 READY')

        identity = policy.ready(ready_raw, self.run_id, self.ttl_seconds)
        public = read('host-public-key', self.ram + '/host-public-key')
        policy.public_key(public, identity['public_sha'])
        if self.engine == 'libjit':
            same('claim', self.prefix + '.claim', self.ticket_bytes)
        same('hostkey-check', self.ram + '/hostkey-check', b'A7R5_RAM_GENERATED_HOSTKEY verified=1 mode=600 tmpfs=1 private_key_logged=0\n')

        banner = read('banner', self.ram + '/banner')
        if not re.fullmatch(rb'SSH-2\.0-[ -~]+\r?\n', banner):
            raise ValueError('SSH Banner 格式不符')
        started = read('started', self.ram + '/started')
        match = re.fullmatch(
            rb'A7R5_WILDCARD_STARTED '
            + self.run_id.encode()
            + rb' pid=(\d+) bind=0\.0\.0\.0:2222 listener_observed=1 banner_sha=([0-9a-f]{64})\n',
            started,
        )
        if (
            not match
            or int(match[1]) <= 1
            or int(match[1]) in (identity['parent'], identity['child'])
            or match[2].decode() != hashlib.sha256(banner).hexdigest()
        ):
            raise ValueError('SSH 监听回执与进程身份不符')

        first = policy.heartbeat(read('heartbeat-first', self.ram + '/heartbeat'), self.run_id, identity, self.ttl_seconds)
        self.sleep(2)
        last = policy.heartbeat(read('heartbeat-last', self.ram + '/heartbeat'), self.run_id, identity, self.ttl_seconds)
        if last <= first:
            raise ValueError('SSH 守护心跳未前进')
        same('ready-repeat', self.ram + '/ready', ready_raw)
        same('preload-after', '/etc/ld.so.preload', baseline)

        (self.output.parent / 'host-public-key').write_bytes(public)
        self.safe_to_stop = True
        report.update(
            protocol_gate_passed=True,
            preload_unchanged=True,
            service_ready=True,
            host_public_key=public.decode('ascii').strip(),
        )
