"""trust_update 离线回归测试：动态 USB 识别、0336 预恢复、自动转存、双引擎交叉编译、报文守卫与闭环状态机。"""
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import builder
import capture as capture_flow
import host_usb
from operations import (
    DEBUG,
    KitCaptureOperation,
    KitTrustOperation,
    LibjitCaptureOperation,
    LibjitTrustOperation,
)
from usb_session import HEADER, READ, wire
import update_trust


CAPTURE_VER = b'A7R5_TEST_VER_400\n'
CAPTURE_LDR = b'A7R5_TEST_LOADER'
PARTITION_BYTES = builder.PARTITION_BYTES
# 25,100,288 字节 = 256 * 98,048，用固定字节环保证每次转存内容完全一致。
CAPTURE_IMAGE = bytes(range(256)) * (PARTITION_BYTES // 256)


def _fake_ioreg_tree(pid, location_id, *, product='ILCE-7RM5', with_media=True):
    children = []
    if pid == host_usb.PID_ORDINARY:
        children.append({'IOObjectClass': 'IOUSBMassStorageInterfaceNub', 'IORegistryEntryChildren': []})
        if with_media:
            children.append(
                {
                    'IOObjectClass': 'IOUSBMassStorageDriver',
                    'IORegistryEntryChildren': [
                        {'BSD Name': 'disk4', 'Whole': True, 'Size': 67108864, 'IORegistryEntryChildren': []},
                    ],
                }
            )
    return [
        {
            'IOObjectClass': 'IOUSBHostDevice',
            'idVendor': host_usb.VID,
            'idProduct': pid,
            'locationID': location_id,
            'USB Product Name': product,
            'IORegistryEntryChildren': children,
        }
    ]


def _make_journal(run_id, plan, source_sha, target_sha):
    lines = [f'A7R5_TRUST {run_id} FORCE_PREIMAGE_CAPTURED completed=0 offset=-1 code=0']
    for index, row in enumerate(plan['rows']):
        lines.append(f'A7R5_TRUST {run_id} WRITE_BEGIN completed={index} offset={row["offset"]} code=0')
        lines.append(f'A7R5_TRUST {run_id} WRITE_RETURNED completed={index + 1} offset={row["offset"]} code=0')
        if index == len(plan['rows']) - 1 or row['phase'] != plan['rows'][index + 1]['phase']:
            lines.append(f'A7R5_TRUST {run_id} PHASE_SYNC_RETURNED completed={index + 1} offset={row["offset"]} code=0')
    lines.append(f'A7R5_TRUST {run_id} FULL_LOGICAL_READBACK_MATCH completed=258 offset=-1 code=0')
    lines.append(f'A7R5_TRUST {run_id} REOPENED_FULL_CAPTURE_MATCH completed=258 offset=-1 code=0')
    lines.append(f'A7R5_TRUST {run_id} COMPLETED completed=258 offset=-1 code=0')
    return ('\n'.join(lines) + '\n').encode('ascii')


class FakeEndpoint:
    def __init__(self, address):
        self.bEndpointAddress = address
        self.bmAttributes = 2
        self.wMaxPacketSize = 512
        self.bInterval = 0


class FakeInterface:
    def __init__(self, endpoints, *, interface_class=255, subclass=0, protocol=0):
        self.bInterfaceNumber = 0
        self.bAlternateSetting = 0
        self.bInterfaceClass = interface_class
        self.bInterfaceSubClass = subclass
        self.bInterfaceProtocol = protocol
        self._endpoints = [FakeEndpoint(addr) for addr in endpoints]

    def __iter__(self):
        return iter(self._endpoints)


class FakeDevice:
    def __init__(self, pid, bus, ports):
        self.idProduct = pid
        self.bus = bus
        self.port_numbers = tuple(ports)


class FakeCameraDriver:
    """模拟 0336 Senser 文件与 DEBUG 协议响应，并在触发时生成合法日志与 9 块回读数据。"""

    def __init__(self, engine, run_id, cfg, materials, preload_bytes, *, fail_mode=None):
        self.engine = engine
        self.run_id = run_id
        self.cfg = cfg
        self.materials = materials
        self.preload_bytes = preload_bytes
        self.fail_mode = fail_mode

        self.control_prefix = '/tmp_wbshd/a7r5-control-' + run_id + '/task'
        self.ticket_path = '/tmp_wbshd/a7r5-control-' + run_id + '.ticket'
        self.kit_so_path = f'/tmp/jiritsu/a7r5-{run_id}.so'
        self.files = {
            '/version.txt': self._dummy_with_sha(cfg['version_sha256']),
            '/usr/lib/libJiritsu.so': self._dummy_with_sha(cfg['loader_sha256'], length=cfg['loader_bytes']),
            '/etc/ld.so.preload': preload_bytes,
        }
        self.selected = None
        self.responses = []
        self.debug_count = 0

    @staticmethod
    def _dummy_with_sha(expected_sha, length=32):
        # 仅在测试替身中通过预存匹配表模拟；实际校验使用 cfg 中真摘要。
        raise NotImplementedError

    def setup_fixed_hashes(self):
        pass


class _ChannelStub:
    """固定 Senser 协议替身：按 0x8000 块与 512 字节边界把响应排队给 Channel。"""

    state_polls = 0

    def _wire_to_path(self, raw_wire):
        path = raw_wire.decode('ascii')
        if path.startswith('/tmp/jiritsu/../../'):
            return path[len('/tmp/jiritsu/../..') :]
        return path

    def _queue_chunks(self, seq, result_code, payload):
        body = struct.pack('<I', result_code) + payload
        header = HEADER.pack(len(body), 0x40, seq, 0, 0, 0, 0)
        self._reads = getattr(self, '_reads', [])
        self._reads.append(header)
        offset = 0
        while offset < len(body):
            block = body[offset : offset + 0x8000]
            pos = 0
            while pos < len(block):
                piece = block[pos : pos + 4096]
                self._reads.append(piece)
                pos += len(piece)
            if len(block) % 512 == 0:
                self._reads.append(b'')  # ZLP 边界
            offset += len(block)

    def read(self, length):
        chunk = self._reads.pop(0)
        if len(chunk) > length:
            self._reads.insert(0, chunk[length:])
            return chunk[:length]
        return chunk


class HashStubDriver(_ChannelStub):
    """与 _BaseTrustOperation 配合的协议驱动替身，校验真实读写与响应分块。"""

    def __init__(self, engine, run_id, cfg, materials, preload_bytes, *, fail_mode=None):
        self.engine = engine
        self.run_id = run_id
        self.cfg = cfg
        self.materials = materials
        self.preload_bytes = preload_bytes
        self.fail_mode = fail_mode
        self.control_prefix = '/tmp_wbshd/a7r5-control-' + run_id + '/task'
        self.ticket_path = '/tmp_wbshd/a7r5-control-' + run_id + '.ticket'
        self.kit_so_path = f'/tmp/jiritsu/a7r5-{run_id}.so'
        self.files = {
            '/etc/ld.so.preload': preload_bytes,
        }
        self.selected = None
        self.outbox = bytearray()
        self.state_polls = 0
        self.debug_count = 0

    def _queue_reply(self, seq, result_code, payload=b''):
        body = struct.pack('<I', result_code) + payload
        header = HEADER.pack(len(body), 0x40, seq, 0, 0, 0, 0)
        self.outbox.extend(header)
        self.outbox.extend(body)
        if len(body) % 512 == 0:
            pass  # 假驱动仅按 0x8000 块边界追加 ZLP
        # 若 size <= 0x8000 且 size % 512 == 0，Channel 会读取 512 字节边界空包（返回 b'' 表示 ZLP）。
        # 这里用特殊队列控制 read() 返回值。

    def _trigger_task(self):
        if self.fail_mode == 'precheck_47':
            self.files[self.control_prefix + '.state'] = (
                f'A7R5-JIT-1 {self.run_id} FAILED 47 uid=0 euid=0 bytes=0 disarmed=1 children=0 '
                f'precheck_reason=5 precheck_pid=100 precheck_fd=-1 precheck_error=0 precheck_device=64641 partition_writes=0\n'
            ).encode()
            return
        if self.fail_mode == 'resource_43':
            self.files[self.control_prefix + '.state'] = (
                f'A7R5-JIT-1 {self.run_id} FAILED 43 uid=0 euid=0 bytes=0 disarmed=1 children=0 '
                f'resource_reason=2 resource_error=0 memory_available_kib=20000 memory_required_kib=32768 ram_available_bytes=-1 partition_writes=0\n'
            ).encode()
            return

        if self.engine == 'kit' and self.fail_mode != 'preload_not_restored':
            self.files['/etc/ld.so.preload'] = self.preload_bytes

        src_sha = self.materials['sectors']['source_sha256']
        tgt_sha = self.materials['sectors']['target_sha256']
        if self.fail_mode == 'changed_preimage':
            # 机内分区在转存后被改动：机内前像摘要与计划前像不一致。
            src_sha = '0' * 64
        output_text = (
            self.cfg['expected_output_begin']
            + f'A7R5_TRUST_FORCE_COMPLETE {tgt_sha} source_sha256={src_sha} '
            + 'sectors=258 bytes=132096 reopened=1 chunks=9 chunk_bytes=16384 readback=planned-sectors-v2\n'
            + self.cfg['expected_output_end']
        ).encode('ascii')
        self.files[self.control_prefix + '.output'] = output_text
        self.files[self.control_prefix + '.state'] = (
            f'A7R5-JIT-1 {self.run_id} DONE 0 uid=0 euid=0 bytes={len(output_text)} disarmed=1 children=0\n'
        ).encode('ascii')
        self.files[self.cfg['journal_path']] = _make_journal(self.run_id, self.materials['plan'], src_sha, tgt_sha)

        after_all = bytearray(self.materials['after_bytes'])
        if self.fail_mode == 'corrupt_sector':
            after_all[0] ^= 0xFF
        for i in range(9):
            chunk = bytes(after_all[i * 16384 : (i + 1) * 16384])
            self.files[self.cfg['readback_path'] + f'.sectors-{i}'] = chunk

    def write(self, packet):
        size, func, seq, *meta = HEADER.unpack_from(packet)
        body = packet[HEADER.size :]
        assert size == len(body) and func == 0x40
        group, cmd = struct.unpack_from('<HH', body)
        assert group == 0x1001

        if cmd == 15:  # select
            self.selected = self._wire_to_path(body[5:-1])
            self._queue_chunks(seq, 0, b'')
        elif cmd == 16:  # put
            data = body[7:]
            self.files[self.selected] = data
            self._queue_chunks(seq, 0, b'')
            if self.engine == 'libjit' and self.selected == '/tmp/jiritsu/libJit.so':
                self.files.pop('/tmp/jiritsu/libJit.so', None)
                self._trigger_task()
        elif cmd == 17:  # read
            if self.selected not in self.files:
                self._queue_chunks(seq, 0x10000006, b'')
            else:
                content = self.files[self.selected]
                if self.selected == self.control_prefix + '.state' and self.state_polls == 0:
                    self.state_polls += 1
                    running = f'A7R5-JIT-1 {self.run_id} RUNNING 0 uid=0 euid=0 bytes=0 disarmed=1 children=0\n'.encode()
                    self._queue_chunks(seq, 0, running)
                else:
                    self._queue_chunks(seq, 0, content)
        elif cmd == 5:  # DEBUG
            self.debug_count += 1
            self._queue_chunks(seq, 0, b'')
            if self.engine == 'kit':
                self._trigger_task()
        else:
            raise AssertionError(f'未知命令 {cmd}')
        return len(packet)


class CaptureStubDriver(_ChannelStub):
    """模拟 cnflasha1 只读转存与 RAM 副本清理：两次触发分别产出分块镜像与清理回执。"""

    def __init__(self, engine, run_id, cfg, preload_bytes, *, fail_mode=None, image=CAPTURE_IMAGE):
        self.engine = engine
        self.run_id = run_id
        self.cfg = cfg
        self.preload_bytes = preload_bytes
        self.fail_mode = fail_mode
        self.image = image
        self.capture_sha256 = hashlib.sha256(image).hexdigest()
        self.control_prefix = cfg['capture_control_dir'] + '/task'
        self.ticket_path = cfg['capture_control_dir'] + '.ticket'
        self.cleanup_prefix = cfg['cleanup_control_dir'] + '/task'
        self.capture_so_path = cfg['capture_kit_so_path']
        self.cleanup_so_path = cfg['cleanup_kit_so_path']
        self.files = {
            '/version.txt': CAPTURE_VER,
            '/usr/lib/libJiritsu.so': CAPTURE_LDR,
            '/etc/ld.so.preload': preload_bytes,
        }
        self.selected = None
        self.stage = 0
        self.stage_polls = {}
        self.debug_count = 0
        self.ticket_bytes = f'A7R5_LIBJIT {run_id}\n'.encode('ascii')

    def _done_state(self, prefix, output):
        return (
            f'A7R5-JIT-1 {self.run_id} DONE 0 uid=0 euid=0 bytes={len(output)} '
            f'disarmed=1 children=0\n'
        ).encode('ascii')

    def _capture_output(self):
        summary = (
            f' bytes={self.cfg["partition_bytes"]} twice=1 chunks={self.cfg["capture_chunk_count"]} '
            f'chunk_bytes={self.cfg["capture_chunk_bytes"]}\n'
        )
        return (
            self.cfg['expected_output_begin']
            + f'A7R5_CAPTURE_COMPLETE {self.capture_sha256}'
            + summary
            + self.cfg['expected_output_end']
        ).encode('ascii')

    def _cleanup_output(self):
        return (
            f'A7R5_CAPTURE_CLEANUP {self.run_id} sha256={self.capture_sha256} '
            f'deleted={self.cfg["capture_chunk_count"]} bytes={self.cfg["partition_bytes"]} '
            f'directory_removed=1\n'
        ).encode('ascii')

    def _trigger(self):
        if self.stage == 0:
            if self.fail_mode == 'capture_44':
                self.files[self.control_prefix + '.output'] = b'\n'
                self.files[self.control_prefix + '.state'] = (
                    f'A7R5-JIT-1 {self.run_id} FAILED 44 uid=0 euid=0 bytes=0 disarmed=1 children=0\n'
                ).encode('ascii')
            else:
                output = self._capture_output()
                self.files[self.control_prefix + '.claim'] = self.ticket_bytes
                self.files[self.control_prefix + '.output'] = output
                self.files[self.control_prefix + '.state'] = self._done_state(self.control_prefix, output)
                chunk_bytes = int(self.cfg['capture_chunk_bytes'])
                for index in range(int(self.cfg['capture_chunk_count'])):
                    self.files[f'{self.cfg["capture_path"]}.part-{index}'] = CAPTURE_IMAGE[
                        index * chunk_bytes : (index + 1) * chunk_bytes
                    ]
        else:
            if self.fail_mode == 'cleanup_68':
                output = f'A7R5_CAPTURE_CLEANUP_FAILED {self.run_id} deleted=0 code=68\n'.encode('ascii')
                self.files[self.cleanup_prefix + '.output'] = output
                self.files[self.cleanup_prefix + '.state'] = (
                    f'A7R5-JIT-1 {self.run_id} FAILED 68 uid=0 euid=0 bytes={len(output)} '
                    f'disarmed=1 children=0\n'
                ).encode('ascii')
            else:
                output = self._cleanup_output()
                self.files[self.cleanup_prefix + '.output'] = output
                self.files[self.cleanup_prefix + '.state'] = self._done_state(self.cleanup_prefix, output)
                for path in [p for p in self.files if p.startswith(self.cfg['capture_path'] + '.part-')]:
                    self.files.pop(path)
        self.stage += 1

    def write(self, packet):
        size, func, seq, *meta = HEADER.unpack_from(packet)
        body = packet[HEADER.size :]
        assert size == len(body) and func == 0x40
        group, cmd = struct.unpack_from('<HH', body)
        assert group == 0x1001

        if cmd == 15:  # select
            self.selected = self._wire_to_path(body[5:-1])
            self._queue_chunks(seq, 0, b'')
        elif cmd == 16:  # put
            data = body[7:]
            self.files[self.selected] = data
            if self.engine == 'libjit' and self.selected == '/tmp/jiritsu/libJit.so':
                self.files.pop('/tmp/jiritsu/libJit.so', None)
                self._trigger()
            self._queue_chunks(seq, 0, b'')
        elif cmd == 17:  # read
            if self.selected not in self.files:
                self._queue_chunks(seq, 0x10000006, b'')
            else:
                content = self.files[self.selected]
                polls = self.stage_polls.get(self.selected, 0)
                if self.selected.endswith('/task.state') and polls == 0:
                    self.stage_polls[self.selected] = 1
                    running = (
                        f'A7R5-JIT-1 {self.run_id} RUNNING 0 uid=0 euid=0 bytes=0 disarmed=1 children=0\n'
                    ).encode('ascii')
                    self._queue_chunks(seq, 0, running)
                else:
                    self.stage_polls[self.selected] = polls + 1
                    self._queue_chunks(seq, 0, content)
        elif cmd == 5:  # DEBUG
            assert self.engine == 'kit'
            self.debug_count += 1
            if self.files['/etc/ld.so.preload'] not in (b'', self.preload_bytes):
                # 载荷 _init 在派发工作进程前还原 /etc/ld.so.preload。
                self.files['/etc/ld.so.preload'] = self.preload_bytes
            self.files.pop(self.capture_so_path if self.stage == 0 else self.cleanup_so_path, None)
            self._trigger()
            self._queue_chunks(seq, 0, b'')
        else:
            raise AssertionError(f'未知命令 {cmd}')
        return len(packet)


def _synthetic_materials(count=258):
    """在无 prepared/engine/ 的干净归档中构造确定性模拟扇区材料。"""
    rows = []
    plan_rows = []
    before_parts = []
    after_parts = []
    for idx in range(count):
        offset = (100 + idx) * 512
        b = bytes([(idx * 7 + j) & 0xFF for j in range(512)])
        a = bytes([(idx * 13 + j + 1) & 0xFF for j in range(512)])
        before_parts.append(b)
        after_parts.append(a)
        phase = 'checksum' if idx == count - 1 else 'initrd'
        plan_rows.append({'offset': offset, 'bytes': 512, 'phase': phase})
        rows.append({
            'offset': offset,
            'before': base64.b64encode(b).decode('ascii'),
            'after': base64.b64encode(a).decode('ascii'),
        })
    src_sha = hashlib.sha256(b''.join(before_parts)).hexdigest()
    tgt_sha = hashlib.sha256(b''.join(after_parts)).hexdigest()
    return builder._pack_trust_materials(
        {'source_sha256': src_sha, 'target_sha256': tgt_sha, 'rows': plan_rows},
        {'source_sha256': src_sha, 'target_sha256': tgt_sha, 'bytes': builder.PARTITION_BYTES, 'rows': rows},
    )


class TestTrustUpdate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.materials = builder.load_trust_materials()
        except FileNotFoundError:
            cls.materials = _synthetic_materials(258)

    def test_preimage_offline_plan_without_prepared_engine(self):
        from unittest import mock

        with tempfile.TemporaryDirectory(prefix='a7r5-noprep-') as tmp:
            missing = Path(tmp) / 'missing-prepared'
            with mock.patch.object(builder, 'PREPARED_ENGINE', missing):
                with self.assertRaisesRegex(FileNotFoundError, '--preimage'):
                    builder.load_trust_materials()

                preimage = builder.PROJECT / 'a7r5-firmware-images/标准固件_19项/明文分区_17项/cnflasha1.img'
                if preimage.is_file():
                    mat_replace = builder.load_trust_materials(preimage, mode='replace-key')
                    mat_skip = builder.load_trust_materials(preimage, mode='skip-key')
                    self.assertEqual(len(mat_replace['plan']['rows']), 258)
                    self.assertGreater(len(mat_skip['plan']['rows']), 0)
                    self.assertLess(len(mat_skip['plan']['rows']), 258)
                    baseline = {'location_id': 0x02140000, 'bus': 2, 'ports': [1, 4], 'pid': 0x0e0a, 'model': 'ILCE-7RM5', 'media': [], 'drivers': ['IOUSBMassStorageDriver']}
                    pkg = Path(tmp) / 'pkg-skip'
                    builder.build_package(pkg, 'libjit', '22334455667788992233445566778899', baseline, mat_skip)
                    op = LibjitTrustOperation(pkg, sleep=lambda _: None)
                    self.assertEqual(op.patch_count, len(mat_skip['plan']['rows']))

    def test_dynamic_usb_port_and_prerecovery(self):
        # 测试任意非历史端口 (bus=2, ports=[1, 4], locationID=0x02140000)
        loc = 0x02140000
        self.assertEqual(host_usb.physical_port(loc), (2, [1, 4]))

        parsed_service = host_usb.parse_ioreg(_fake_ioreg_tree(host_usb.PID_SERVICE, loc))
        self.assertEqual(parsed_service['kind'], 'service')
        self.assertEqual((parsed_service['bus'], parsed_service['ports']), (2, [1, 4]))

        # 模拟：开始为 0336 → 自动发 STOP → 过渡态 096f → 两次稳定 0e0a
        seq = [
            _fake_ioreg_tree(host_usb.PID_SERVICE, loc),
            _fake_ioreg_tree(host_usb.PID_TRANSITION, loc),
            _fake_ioreg_tree(host_usb.PID_ORDINARY, loc),
            _fake_ioreg_tree(host_usb.PID_ORDINARY, loc),
        ]
        stops = []

        def fake_take(label, timeout=5):
            tree = seq.pop(0) if seq else _fake_ioreg_tree(host_usb.PID_ORDINARY, loc)
            return host_usb.parse_ioreg(tree)

        def fake_stop(location_id, report):
            stops.append(location_id)
            report['stop_attempts'] = 1
            report['stop_result'] = 'returned'

        baseline, recovery = host_usb.ensure_ordinary_mode(
            take=fake_take,
            stop_fn=fake_stop,
            sleep=lambda _: None,
        )
        self.assertEqual(stops, [loc])
        self.assertEqual(baseline['location_id'], loc)
        self.assertEqual((baseline['bus'], baseline['ports']), (2, [1, 4]))
        self.assertTrue(recovery['host_recovery']['recovered'])
        self.assertEqual(host_usb.parse_ioreg([]), {'kind': 'absent', 'present': False})

    def test_compile_both_engines_elf(self):
        run_id = '0123456789abcdef0123456789abcdef'
        baseline = {'location_id': 0x02140000, 'bus': 2, 'ports': [1, 4], 'pid': 0x0e0a, 'model': 'ILCE-7RM5', 'media': [], 'drivers': ['IOUSBMassStorageDriver']}
        with tempfile.TemporaryDirectory(prefix='a7r5-test-build-') as tmp:
            pkg_jit = Path(tmp) / 'jit'
            cfg_jit = builder.build_package(pkg_jit, 'libjit', run_id, baseline, self.materials)
            self.assertTrue((pkg_jit / 'materials/libJit.so').is_file())
            self.assertIn(b'A7R5_TRUST_PRODUCTION_V2', (pkg_jit / 'materials/libJit.so').read_bytes())
            self.assertEqual(cfg_jit['interfaces']['interface-1.json']['bus'], 2)
            self.assertEqual(cfg_jit['interfaces']['interface-1.json']['ports'], [1, 4])

            pkg_kit = Path(tmp) / 'kit'
            builder.build_package(pkg_kit, 'kit', run_id, baseline, self.materials)
            for name in ('blank-512', 'installed-boot-hook'):
                so_path = pkg_kit / f'materials/kit-{name}.so'
                self.assertTrue(so_path.is_file())
                self.assertIn(b'A7R5_TRUST_KIT_FORCE_V1', so_path.read_bytes())

    def test_compile_capture_and_cleanup_payloads(self):
        run_id = '89abcdef0123456789abcdef01234567'
        baseline = {'location_id': 0x02140000, 'bus': 2, 'ports': [1, 4], 'pid': 0x0e0a, 'model': 'ILCE-7RM5', 'media': [], 'drivers': ['IOUSBMassStorageDriver']}
        with tempfile.TemporaryDirectory(prefix='a7r5-test-capture-') as tmp:
            pkg_jit = Path(tmp) / 'jit'
            cfg_jit = builder.build_capture_package(pkg_jit, 'libjit', run_id, baseline)
            self.assertIn(b'A7R5_CAPTURE_READONLY_V5_RAM_16K', (pkg_jit / 'materials/capture.so').read_bytes())
            self.assertIn(b'A7R5_CAPTURE_CLEANUP_V2_RAM_16K', (pkg_jit / 'materials/capture-cleanup.so').read_bytes())
            self.assertEqual(cfg_jit['capture_chunk_count'], 1532)
            self.assertEqual(cfg_jit['capture_chunk_bytes'], 16384)
            self.assertEqual(cfg_jit['cleanup_ticket_path'], '/tmp_wbshd/a7r5-cleanup-' + run_id + '.ticket')
            self.assertTrue(LibjitCaptureOperation(pkg_jit).packet_limit == 4096)

            pkg_kit = Path(tmp) / 'kit'
            cfg_kit = builder.build_capture_package(pkg_kit, 'kit', run_id, baseline)
            for name in ('blank-512', 'installed-boot-hook'):
                self.assertIn(
                    b'A7R5_CAPTURE_KIT_READONLY_V1_RAM_16K',
                    (pkg_kit / f'materials/capture-{name}.so').read_bytes(),
                )
                self.assertIn(
                    b'A7R5_CAPTURE_KIT_CLEANUP_V1_RAM_16K',
                    (pkg_kit / f'materials/cleanup-{name}.so').read_bytes(),
                )
            self.assertEqual(cfg_kit['capture_kit_so_path'], '/tmp_wbshd/a7r5-capture-' + run_id + '.so')
            self.assertTrue(KitCaptureOperation(pkg_kit).cleanup_so_path.startswith('/tmp_wbshd/'))
            self.assertFalse(
                any(path.startswith('/tmp/jiritsu/') for path in KitCaptureOperation(pkg_kit).reads)
            )

    def _run_operation_sim(self, engine, preload_index, *, fail_mode=None):
        run_id = 'abcdef0123456789abcdef0123456789'
        baseline = {'location_id': 0x03210000, 'bus': 3, 'ports': [2, 1], 'pid': 0x0e0a, 'model': 'ILCE-7RM5', 'media': [], 'drivers': ['IOUSBMassStorageDriver']}
        preload_bytes = bytes.fromhex(self.materials['profile']['preload_baselines'][preload_index][1])

        with tempfile.TemporaryDirectory(prefix='a7r5-test-op-') as tmp:
            tmp_path = Path(tmp)
            pkg = tmp_path / 'package'
            cfg = builder.build_package(pkg, engine, run_id, baseline, self.materials)
            # 在测试中替换 version_sha256 与 loader_sha256 为确定性测试桩摘要
            fake_ver = b'A7R5_TEST_VER_400\n'
            fake_ldr = b'A7R5_TEST_LOADER'
            cfg['version_sha256'] = hashlib.sha256(fake_ver).hexdigest()
            cfg['loader_sha256'] = hashlib.sha256(fake_ldr).hexdigest()
            cfg['loader_bytes'] = len(fake_ldr)
            (pkg / 'config.json').write_text(json.dumps(cfg))

            op = (LibjitTrustOperation if engine == 'libjit' else KitTrustOperation)(
                pkg,
                sleep=lambda _: None,
            )
            op.interface_checked(FakeDevice(0x0e0a, 3, [2, 1]), FakeInterface([129, 2], interface_class=8, subclass=6, protocol=80))
            op.interface_checked(FakeDevice(0x0336, 3, [2, 1]), FakeInterface([129, 2, 131, 4], interface_class=255, subclass=0, protocol=0))

            driver = HashStubDriver(engine, run_id, cfg, self.materials, preload_bytes, fail_mode=fail_mode)
            driver.files['/version.txt'] = fake_ver
            driver.files['/usr/lib/libJiritsu.so'] = fake_ldr

            out = tmp_path / 'out'
            out.mkdir()
            report = {}
            events = []
            op(driver, out, lambda ev, **kw: events.append((ev, kw)), report)
            return op, report, driver

    def test_libjit_and_kit_operations_success(self):
        for engine in ('libjit', 'kit'):
            for preload_idx in (0, 1):  # blank-512 & installed-boot-hook
                op, report, driver = self._run_operation_sim(engine, preload_idx)
                self.assertTrue(op.safe_to_stop)
                self.assertTrue(report['protocol_gate_passed'])
                self.assertTrue(report['native_write_complete'])
                self.assertTrue(report['planned_sector_readback_verified'])
                self.assertTrue(report['preload_unchanged'])
                self.assertEqual(report['trigger_attempts'], 1)
                if engine == 'kit':
                    self.assertTrue(report['debug_commands_sent'])
                    self.assertEqual(driver.debug_count, 1)
                    self.assertTrue(op.kit_so_path.startswith('/tmp_wbshd/'))
                    self.assertFalse(any(p.startswith('/tmp/jiritsu/') for p in op.writes))

    def test_failure_gates_block_stop(self):
        for mode in ('precheck_47', 'resource_43', 'corrupt_sector'):
            with self.assertRaises((RuntimeError, ValueError)):
                self._run_operation_sim('libjit', 0, fail_mode=mode)

        with self.assertRaises(ValueError):
            self._run_operation_sim('kit', 1, fail_mode='preload_not_restored')

    def test_changed_device_preimage_with_target_match_is_reported_as_drift(self):
        # 前像漂移但落盘结果仍等于计划目标：记录漂移证据，不误判为失败。
        op, report, driver = self._run_operation_sim('kit', 0, fail_mode='changed_preimage')
        self.assertTrue(op.safe_to_stop)
        self.assertTrue(report['preimage_drift']['resolved_by_target_match'])
        self.assertEqual(report['preimage_drift']['device_source_sha256'], '0' * 64)
        self.assertEqual(
            report['preimage_drift']['plan_source_sha256'], self.materials['sectors']['source_sha256']
        )

    def test_wrong_target_partition_is_rejected(self):
        materials = dict(
            self.materials,
            plan=dict(self.materials['plan'], candidate_sha256='f' * 64),
            sectors=dict(self.materials['sectors'], target_sha256='f' * 64),
        )
        run_id = 'aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa'
        baseline = {'location_id': 0x02140000, 'bus': 2, 'ports': [1, 4], 'pid': 0x0e0a, 'model': 'ILCE-7RM5', 'media': [], 'drivers': ['IOUSBMassStorageDriver']}
        preload = bytes.fromhex(self.materials['profile']['preload_baselines'][0][1])
        with tempfile.TemporaryDirectory(prefix='a7r5-wrong-target-') as tmp:
            pkg = Path(tmp) / 'pkg'
            cfg = builder.build_package(pkg, 'libjit', run_id, baseline, materials)
            # 计划候选与扇区材料目标被一起改写，操作器仍会接受材料，但机内回执必须是同一目标。
            cfg['version_sha256'] = hashlib.sha256(CAPTURE_VER).hexdigest()
            cfg['loader_sha256'] = hashlib.sha256(CAPTURE_LDR).hexdigest()
            cfg['loader_bytes'] = len(CAPTURE_LDR)
            (pkg / 'config.json').write_text(json.dumps(cfg))
            op = LibjitTrustOperation(pkg, sleep=lambda _: None)
            driver = HashStubDriver('libjit', run_id, cfg, self.materials, preload)
            driver.files['/version.txt'] = CAPTURE_VER
            driver.files['/usr/lib/libJiritsu.so'] = CAPTURE_LDR
            report = {}
            out = Path(tmp) / 'out'
            out.mkdir()
            with self.assertRaisesRegex(ValueError, '计划候选'):
                op(driver, out, lambda ev, **kw: None, report)
            self.assertFalse(op.safe_to_stop)

    def _run_capture_sim(self, engine, preload_index=0, *, fail_mode=None, tmp=None):
        run_id = 'fedcba9876543210fedcba9876543210'
        baseline = {'location_id': 0x02140000, 'bus': 2, 'ports': [1, 4], 'pid': 0x0e0a, 'model': 'ILCE-7RM5', 'media': [], 'drivers': ['IOUSBMassStorageDriver']}
        preload_bytes = bytes.fromhex(self.materials['profile']['preload_baselines'][preload_index][1])
        pkg = Path(tmp) / f'capture-{engine}'
        cfg = builder.build_capture_package(pkg, engine, run_id, baseline)
        cfg['version_sha256'] = hashlib.sha256(CAPTURE_VER).hexdigest()
        cfg['loader_sha256'] = hashlib.sha256(CAPTURE_LDR).hexdigest()
        cfg['loader_bytes'] = len(CAPTURE_LDR)
        (pkg / 'config.json').write_text(json.dumps(cfg))

        op = (LibjitCaptureOperation if engine == 'libjit' else KitCaptureOperation)(pkg, sleep=lambda _: None)
        op.interface_checked(FakeDevice(0x0e0a, 2, [1, 4]), FakeInterface([129, 2], interface_class=8, subclass=6, protocol=80))
        op.interface_checked(FakeDevice(0x0336, 2, [1, 4]), FakeInterface([129, 2, 131, 4]))

        driver = CaptureStubDriver(engine, run_id, cfg, preload_bytes, fail_mode=fail_mode)
        out = Path(tmp) / f'session-{engine}'
        out.mkdir()
        report = {}
        op(driver, out, lambda ev, **kw: None, report)
        return op, report, driver, out, cfg

    def test_capture_operations_dump_and_cleanup(self):
        for engine in ('libjit', 'kit'):
            with self.subTest(engine=engine), tempfile.TemporaryDirectory(prefix='a7r5-capture-') as tmp:
                op, report, driver, out, cfg = self._run_capture_sim(engine, 0, tmp=tmp)
                self.assertTrue(op.safe_to_stop)
                self.assertTrue(report['capture_verified'])
                self.assertTrue(report['native_capture_complete'])
                self.assertEqual(report['capture_sha256'], hashlib.sha256(CAPTURE_IMAGE).hexdigest())
                self.assertEqual(report['capture_download_chunks'], 1532)
                self.assertEqual(report['partition_writes'], 0)
                self.assertEqual(report['trigger_attempts'], 2)
                self.assertEqual(report['fixed_writes_attempted'], 4)
                self.assertEqual(report['capture_cleanup_state'], 'complete')
                self.assertTrue(report['capture_cleanup_verified'])
                self.assertEqual(driver.stage, 2)
                if engine == 'kit':
                    self.assertEqual(driver.debug_count, 2)
                    self.assertFalse(any(p.startswith('/tmp/jiritsu/') for p in op.writes))

                receipt = capture_flow.persist_image(
                    out,
                    Path(tmp) / 'cnflasha1.img',
                    report=report,
                    run_id=op.run_id,
                    chunk_count=op.chunk_count,
                    chunk_bytes=op.chunk_bytes,
                    partition_bytes=op.partition_bytes,
                )
                image = Path(tmp) / 'cnflasha1.img'
                self.assertEqual(receipt['sha256'], hashlib.sha256(CAPTURE_IMAGE).hexdigest())
                self.assertEqual(receipt['bytes'], PARTITION_BYTES)
                self.assertEqual(image.stat().st_size, PARTITION_BYTES)
                self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(), receipt['sha256'])
                self.assertTrue((Path(tmp) / 'cnflasha1.img.receipt.json').is_file())
                self.assertFalse((out / 'partition-chunk-000.bin').exists())

    def test_capture_failure_withholds_stop(self):
        with tempfile.TemporaryDirectory(prefix='a7r5-capture-fail-') as tmp:
            with self.assertRaisesRegex(RuntimeError, '44'):
                self._run_capture_sim('libjit', 0, fail_mode='capture_44', tmp=tmp)
            out = Path(tmp) / 'session-libjit'
            self.assertFalse(any(out.glob('partition-chunk-*')))

    def test_capture_cleanup_failure_still_allows_stop_but_reports(self):
        # 清理失败时本机镜像已完整下载：允许 STOP 恢复普通 MSC，但状态必须记录为 failed。
        run_id = '00112233445566778899aabbccddeeff'
        baseline = {'location_id': 0x02140000, 'bus': 2, 'ports': [1, 4], 'pid': 0x0e0a, 'model': 'ILCE-7RM5', 'media': [], 'drivers': ['IOUSBMassStorageDriver']}
        preload_bytes = bytes.fromhex(self.materials['profile']['preload_baselines'][0][1])
        with tempfile.TemporaryDirectory(prefix='a7r5-capture-cleanup-fail-') as tmp:
            pkg = Path(tmp) / 'pkg'
            cfg = builder.build_capture_package(pkg, 'libjit', run_id, baseline)
            cfg['version_sha256'] = hashlib.sha256(CAPTURE_VER).hexdigest()
            cfg['loader_sha256'] = hashlib.sha256(CAPTURE_LDR).hexdigest()
            cfg['loader_bytes'] = len(CAPTURE_LDR)
            (pkg / 'config.json').write_text(json.dumps(cfg))
            op = LibjitCaptureOperation(pkg, sleep=lambda _: None)
            driver = CaptureStubDriver('libjit', run_id, cfg, preload_bytes, fail_mode='cleanup_68')
            out = Path(tmp) / 'session'
            out.mkdir()
            report = {}
            with self.assertRaisesRegex(RuntimeError, '68'):
                op(driver, out, lambda ev, **kw: None, report)
            self.assertTrue(op.safe_to_stop)
            self.assertEqual(report['capture_cleanup_state'], 'failed')
            self.assertFalse(report['capture_cleanup_verified'])
            self.assertTrue(report['capture_verified'])
            self.assertEqual(report['cleanup_native_exit_code'], 68)
            self.assertIn('68', report['cleanup_failure_output'])

    def _host_baseline(self):
        return {
            'kind': 'ordinary',
            'present': True,
            'location_id': 0x02140000,
            'bus': 2,
            'ports': [1, 4],
            'pid': 0x0e0a,
            'model': 'ILCE-7RM5',
            'media': [[True, 67108864]],
            'drivers': ['IOUSBMassStorageDriver'],
        }

    def _fake_host_mod(self):
        baseline_host = self._host_baseline()

        class FakeHostMod:
            def __init__(self):
                self.snap_calls = 0
                self.ensure_calls = 0

            def ensure_ordinary_mode(self, out_dir=None, log_fn=None):
                self.ensure_calls += 1
                if out_dir is not None:
                    Path(out_dir).mkdir(parents=True, exist_ok=True)
                return baseline_host, {
                    'initial': {'kind': 'service', 'location_id': baseline_host['location_id']},
                    'stop_attempts': 1,
                    'stop_result': 'returned',
                }

            def snapshot(self, out_dir=None, label=None, timeout=5, location=None):
                self.snap_calls += 1
                return baseline_host

            def observe_ordinary(self, location_id, take=None, baseline=None, seconds=45, interval=2):
                take('host-00')
                take('host-01')
                return {'recovered': True, 'observations': [baseline_host, baseline_host]}

        return FakeHostMod()

    def _fake_builder(self, *, status='stock_ready'):
        materials = self.materials

        class FakeBuilder:
            build_capture_package = staticmethod(builder.build_capture_package)
            build_package = staticmethod(builder.build_package)
            material_paths = []

            @staticmethod
            def load_trust_materials(path=None, *, mode='replace-key'):
                FakeBuilder.material_paths.append(path)
                if path is not None:
                    assert Path(path).is_file(), '自动模式必须使用刚转存的本机镜像'
                return materials

            @staticmethod
            def inspect_trust_image(path, *, mode='replace-key'):
                raw = Path(path).read_bytes()
                return {
                    'status': status,
                    'sha256': hashlib.sha256(raw).hexdigest(),
                    'mode': mode,
                    'key_sha256': '0' * 64,
                    'p1chksum_valid': status != 'unknown',
                    'libraries': {},
                }

        return FakeBuilder()

    def _auto_session(self, *, counters=None, capture_fail_mode=None, preload_index=0):
        """把真实转存操作器接到 CaptureStubDriver；信任写入阶段用固定成功门控回执。"""
        preload = bytes.fromhex(self.materials['profile']['preload_baselines'][preload_index][1])

        def session(output, operation, timeout_seconds=120):
            Path(output).mkdir(parents=True, exist_ok=True)
            if isinstance(operation, (LibjitCaptureOperation, KitCaptureOperation)):
                if counters is not None:
                    counters['capture'] = counters.get('capture', 0) + 1
                operation.config['version_sha256'] = hashlib.sha256(CAPTURE_VER).hexdigest()
                operation.config['loader_sha256'] = hashlib.sha256(CAPTURE_LDR).hexdigest()
                operation.config['loader_bytes'] = len(CAPTURE_LDR)
                driver = CaptureStubDriver(
                    operation.config['engine'],
                    operation.run_id,
                    operation.config,
                    preload,
                    fail_mode=capture_fail_mode,
                )
                report = {}
                try:
                    operation(driver, Path(output), lambda *a, **k: None, report)
                except Exception as exc:
                    report['failure'] = f'{type(exc).__name__}: {exc}'
                if operation.safe_to_stop:
                    report.update(service_stop_attempts=1, service_stop_result='returned')
                else:
                    report['recovery_required'] = True
                return report
            if counters is not None:
                counters['trust'] = counters.get('trust', 0) + 1
            return {
                'protocol_gate_passed': True,
                'native_write_complete': True,
                'planned_sector_readback_verified': True,
                'preload_unchanged': True,
                'trigger_attempts': 1,
                'fixed_writes_attempted': 2,
                'service_stop_attempts': 1,
                'service_stop_result': 'stalled',
                'service_stop_backend_error_code': -9,
            }

        return session

    def test_full_closed_loop_with_0336_prerecovery(self):
        with tempfile.TemporaryDirectory(prefix='a7r5-test-loop-') as tmp:
            res = update_trust.run_update(
                'kit',
                auto_capture=False,
                host_mod=self._fake_host_mod(),
                builder_mod=self._fake_builder(),
                session_fn=self._auto_session(),
                out_dir=Path(tmp) / 'run1',
            )
            self.assertTrue(res['succeeded'], res.get('failure'))
            self.assertEqual(res['capture_mode'], 'prepared')
            self.assertTrue(res['ordinary_usb_restored'])
            self.assertTrue((Path(tmp) / 'run1/result.json').is_file())

    def test_auto_capture_then_update_closed_loop(self):
        for engine in ('libjit', 'kit'):
            with self.subTest(engine=engine), tempfile.TemporaryDirectory(prefix='a7r5-auto-') as tmp:
                counters = {}
                fake_builder = self._fake_builder()
                res = update_trust.run_update(
                    engine,
                    host_mod=self._fake_host_mod(),
                    builder_mod=fake_builder,
                    session_fn=self._auto_session(counters=counters),
                    capture_mod=capture_flow,
                    out_dir=Path(tmp) / 'run',
                )
                self.assertTrue(res['succeeded'], res.get('failure'))
                self.assertEqual(counters, {'capture': 1, 'trust': 1})
                self.assertEqual(res['capture_mode'], 'auto')
                self.assertEqual(res['capture_receipt']['sha256'], hashlib.sha256(CAPTURE_IMAGE).hexdigest())
                self.assertEqual(res['capture_report']['trigger_attempts'], 2)
                image = Path(tmp) / 'run/cnflasha1.img'
                self.assertEqual(image.stat().st_size, PARTITION_BYTES)
                self.assertEqual(hashlib.sha256(image.read_bytes()).hexdigest(), res['capture_receipt']['sha256'])
                self.assertTrue(res['inspection']['p1chksum_valid'])
                self.assertEqual(
                    [str(path) for path in fake_builder.material_paths],
                    [str(Path(tmp) / 'run/cnflasha1.img')],
                )
                self.assertTrue(res['ordinary_usb_restored'])
                self.assertTrue((Path(tmp) / 'run/result.json').is_file())
                self.assertFalse((Path(tmp) / 'run/capture/session/partition-chunk-000.bin').exists())

    def test_auto_flow_uses_real_capture_and_trust_operations(self):
        """自动转存 → 镜像落盘 → 信任写入两条真实操作器串联，仅镜像解析与材料生成用替身。"""
        for engine in ('libjit', 'kit'):
            with self.subTest(engine=engine), tempfile.TemporaryDirectory(prefix='a7r5-e2e-') as tmp:
                preload = bytes.fromhex(self.materials['profile']['preload_baselines'][0][1])
                calls = {'capture': 0, 'trust': 0}

                def session(output, operation, timeout_seconds=120):
                    Path(output).mkdir(parents=True, exist_ok=True)
                    operation.config['version_sha256'] = hashlib.sha256(CAPTURE_VER).hexdigest()
                    operation.config['loader_sha256'] = hashlib.sha256(CAPTURE_LDR).hexdigest()
                    operation.config['loader_bytes'] = len(CAPTURE_LDR)
                    if isinstance(operation, (LibjitCaptureOperation, KitCaptureOperation)):
                        calls['capture'] += 1
                        driver = CaptureStubDriver(engine, operation.run_id, operation.config, preload)
                    else:
                        calls['trust'] += 1
                        driver = HashStubDriver(engine, operation.run_id, operation.config, self.materials, preload)
                        driver.files['/version.txt'] = CAPTURE_VER
                        driver.files['/usr/lib/libJiritsu.so'] = CAPTURE_LDR
                    report = {}
                    try:
                        operation(driver, Path(output), lambda *a, **k: None, report)
                    except Exception as exc:
                        report['failure'] = f'{type(exc).__name__}: {exc}'
                    if operation.safe_to_stop:
                        report.update(service_stop_attempts=1, service_stop_result='returned')
                    else:
                        report['recovery_required'] = True
                    return report

                res = update_trust.run_update(
                    engine,
                    host_mod=self._fake_host_mod(),
                    builder_mod=self._fake_builder(),
                    session_fn=session,
                    capture_mod=capture_flow,
                    out_dir=Path(tmp) / 'run',
                )
                self.assertTrue(res['succeeded'], res.get('failure'))
                self.assertEqual(calls, {'capture': 1, 'trust': 1})
                self.assertEqual(
                    res['session_report']['actual_source_sha256'], self.materials['sectors']['source_sha256']
                )
                self.assertEqual(
                    res['session_report']['native_logical_partition_sha256'],
                    self.materials['sectors']['target_sha256'],
                )
                self.assertTrue(res['session_report']['protocol_gate_passed'])
                self.assertEqual(res['capture_report']['capture_sha256'], hashlib.sha256(CAPTURE_IMAGE).hexdigest())

    def test_auto_capture_skips_when_already_updated(self):
        with tempfile.TemporaryDirectory(prefix='a7r5-auto-skip-') as tmp:
            counters = {}
            res = update_trust.run_update(
                'kit',
                host_mod=self._fake_host_mod(),
                builder_mod=self._fake_builder(status='already_updated'),
                session_fn=self._auto_session(counters=counters),
                capture_mod=capture_flow,
                out_dir=Path(tmp) / 'run',
            )
            self.assertTrue(res['succeeded'], res.get('failure'))
            self.assertEqual(res['skipped'], 'already_updated')
            self.assertEqual(counters, {'capture': 1})
            self.assertTrue((Path(tmp) / 'run/cnflasha1.img').is_file())

    def test_auto_capture_aborts_before_write_when_capture_fails(self):
        with tempfile.TemporaryDirectory(prefix='a7r5-auto-fail-') as tmp:
            counters = {}
            res = update_trust.run_update(
                'libjit',
                host_mod=self._fake_host_mod(),
                builder_mod=self._fake_builder(),
                session_fn=self._auto_session(counters=counters, capture_fail_mode='capture_44'),
                capture_mod=capture_flow,
                out_dir=Path(tmp) / 'run',
            )
            self.assertFalse(res['succeeded'])
            self.assertNotIn('trust', counters)
            self.assertIn('44', res['failure'])
            self.assertTrue(res['capture_report']['recovery_required'])
            self.assertIn('--restore-only', res['recovery_hint'])
            self.assertFalse((Path(tmp) / 'run/package').exists())
            self.assertFalse((Path(tmp) / 'run/cnflasha1.img').exists())

    def test_preimage_mode_skips_capture(self):
        with tempfile.TemporaryDirectory(prefix='a7r5-preimage-') as tmp:
            preimage = Path(tmp) / 'cnflasha1.img'
            preimage.write_bytes(b'A7R5-EXISTING-IMAGE')
            counters = {}
            res = update_trust.run_update(
                'kit',
                preimage_path=preimage,
                host_mod=self._fake_host_mod(),
                builder_mod=self._fake_builder(),
                session_fn=self._auto_session(counters=counters),
                capture_mod=capture_flow,
                out_dir=Path(tmp) / 'run',
            )
            self.assertTrue(res['succeeded'], res.get('failure'))
            self.assertEqual(res['capture_mode'], 'preimage')
            self.assertEqual(counters, {'trust': 1})
            self.assertFalse((Path(tmp) / 'run/capture').exists())

    def test_persist_image_rejects_mismatched_digest(self):
        with tempfile.TemporaryDirectory(prefix='a7r5-persist-fail-') as tmp:
            session = Path(tmp) / 'session'
            session.mkdir()
            (session / 'partition-chunk-000.bin').write_bytes(b'A' * 8)
            (session / 'partition-chunk-001.bin').write_bytes(b'B' * 8)
            with self.assertRaisesRegex(ValueError, '摘要'):
                capture_flow.persist_image(
                    session,
                    Path(tmp) / 'cnflasha1.img',
                    report={'capture_sha256': '0' * 64},
                    run_id='0' * 32,
                    chunk_count=2,
                    chunk_bytes=8,
                    partition_bytes=16,
                )
            self.assertFalse((Path(tmp) / 'cnflasha1.img').exists())

    def test_capture_only_writes_image_without_update(self):
        with tempfile.TemporaryDirectory(prefix='a7r5-capture-only-') as tmp:
            counters = {}
            code = update_trust.run_capture_only(
                'kit',
                capture_mod=capture_flow,
                host_mod=self._fake_host_mod(),
                builder_mod=self._fake_builder(),
                session_fn=self._auto_session(counters=counters),
                out_dir=Path(tmp) / 'capture-run',
            )
            self.assertEqual(code, 0)
            result = json.loads((Path(tmp) / 'capture-run/result.json').read_text())
            self.assertTrue(result['succeeded'])
            self.assertEqual(result['capture_receipt']['sha256'], hashlib.sha256(CAPTURE_IMAGE).hexdigest())
            self.assertEqual(counters, {'capture': 1})
            self.assertTrue(Path(result['captured_image']).is_file())
            self.assertEqual(result['inspection']['status'], 'stock_ready')

    def test_sudo_reexec_preserves_venv_symlink(self):
        from unittest import mock

        captured = {}

        def fake_execv(path, argv):
            captured['path'] = path
            captured['argv'] = argv
            raise SystemExit(0)

        with (
            mock.patch.object(update_trust.os, 'geteuid', return_value=1000),
            mock.patch.object(update_trust.os, 'execv', side_effect=fake_execv),
        ):
            with self.assertRaises(SystemExit):
                update_trust.main(['--engine', 'libjit'])

        self.assertEqual(captured['path'], '/usr/bin/sudo')
        self.assertEqual(captured['argv'][1], update_trust.os.path.abspath(update_trust.sys.executable))


if __name__ == '__main__':
    unittest.main(verbosity=2)
