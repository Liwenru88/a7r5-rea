"""trust_update 离线回归测试：动态 USB 识别、0336 预恢复、双引擎交叉编译、报文守卫与闭环状态机。"""
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
import host_usb
from operations import DEBUG, KitTrustOperation, LibjitTrustOperation
from usb_session import HEADER, READ, wire
import update_trust


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


class HashStubDriver:
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

    def _wire_to_path(self, raw_wire):
        path = raw_wire.decode('ascii')
        if path.startswith('/tmp/jiritsu/../../'):
            return path[len('/tmp/jiritsu/../..') :]
        return path

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


class TestTrustUpdate(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.materials = builder.load_trust_materials()

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

    def test_failure_gates_block_stop(self):
        for mode in ('precheck_47', 'resource_43', 'corrupt_sector'):
            with self.assertRaises((RuntimeError, ValueError)):
                self._run_operation_sim('libjit', 0, fail_mode=mode)

        with self.assertRaises(ValueError):
            self._run_operation_sim('kit', 1, fail_mode='preload_not_restored')

    def test_full_closed_loop_with_0336_prerecovery(self):
        loc = 0x02140000
        baseline_host = {
            'kind': 'ordinary',
            'present': True,
            'location_id': loc,
            'bus': 2,
            'ports': [1, 4],
            'pid': 0x0e0a,
            'model': 'ILCE-7RM5',
            'media': [[True, 67108864]],
            'drivers': ['IOUSBMassStorageDriver'],
        }

        class FakeHostMod:
            def __init__(self):
                self.snap_calls = 0

            def ensure_ordinary_mode(self, out_dir=None, log_fn=None):
                return baseline_host, {'initial': {'kind': 'service', 'location_id': loc}, 'stop_attempts': 1, 'stop_result': 'returned'}

            def snapshot(self, out_dir=None, label=None, timeout=5, location=None):
                self.snap_calls += 1
                return baseline_host

            def observe_ordinary(self, location_id, take=None, baseline=None, seconds=45, interval=2):
                take('host-00')
                take('host-01')
                return {'recovered': True, 'observations': [baseline_host, baseline_host]}

        def fake_session(output, operation, timeout_seconds=120):
            Path(output).mkdir(parents=True, exist_ok=True)
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

        with tempfile.TemporaryDirectory(prefix='a7r5-test-loop-') as tmp:
            res = update_trust.run_update(
                'kit',
                host_mod=FakeHostMod(),
                builder_mod=builder,
                session_fn=fake_session,
                out_dir=Path(tmp) / 'run1',
            )
            self.assertTrue(res['succeeded'])
            self.assertTrue(res['ordinary_usb_restored'])
            self.assertTrue((Path(tmp) / 'run1/result.json').is_file())


if __name__ == '__main__':
    unittest.main(verbosity=2)
