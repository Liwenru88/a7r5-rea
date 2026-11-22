"""clean_jiritsu 离线回归测试：白名单校验、ELF 构建、kit 通道门控、闭环恢复与 sudo 路径保留。"""
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest
from unittest import mock

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
TRUST_DIR = PROJECT / 'scripts/trust_update'
for _p in (str(HERE), str(TRUST_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import clean_builder
import clean_jiritsu
from clean_operation import CleanJiritsuOperation, parse_clean_output
from usb_session import HEADER


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


class CleanStubDriver:
    """模拟 0336 Senser 文件与 DEBUG 响应，验证 /tmp_wbshd 零残留清理操作。"""

    def __init__(self, run_id, cfg, preload_bytes, *, fail_mode=None):
        self.run_id = run_id
        self.cfg = cfg
        self.preload_bytes = preload_bytes
        self.fail_mode = fail_mode
        self.files = {'/etc/ld.so.preload': preload_bytes}
        self.selected = None
        self._reads = []
        self.debug_count = 0

    def _wire_to_path(self, raw_wire):
        path = raw_wire.decode('ascii')
        if path.startswith('/tmp/jiritsu/../../'):
            return path[len('/tmp/jiritsu/../..') :]
        return path

    def _queue_chunks(self, seq, result_code, payload):
        body = struct.pack('<I', result_code) + payload
        header = HEADER.pack(len(body), 0x40, seq, 0, 0, 0, 0)
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
                self._reads.append(b'')
            offset += len(block)

    def _trigger(self):
        ctrl = self.cfg['control_prefix']
        if self.fail_mode == 'task_failed':
            self.files[ctrl + '.state'] = f'A7R5-JIT-1 {self.run_id} FAILED 41 uid=0 euid=0 bytes=0 disarmed=1 children=0\n'.encode()
            return
        if self.fail_mode != 'preload_not_restored':
            self.files['/etc/ld.so.preload'] = self.preload_bytes

        mode = self.cfg['mode']
        act = 'deleted' if mode == 'apply' else 'would_delete'
        deleted_n = 2 if mode == 'apply' else 0
        after_e = 2 if mode == 'apply' else 4
        after_r = 1 if mode == 'apply' else 3
        after_s = 2 if mode == 'apply' else 13
        out_text = (
            self.cfg['expected_output_begin']
            + 'ENTRY type=dir action=keep size=16384 est_slots=2 err=0 name=ramdsk\n'
            + 'ENTRY type=reg action=keep size=32 est_slots=1 err=0 name=ver.txt\n'
            + f'ENTRY type=reg action={act} size=65536 est_slots=2 err=0 name=libJit.so\n'
            + f'ENTRY type=reg action={act} size=30720 est_slots=8 err=0 name=a7r5-ljssh-{"0" * 32}.service\n'
            + f'CLEAN_SUMMARY mode={mode} target=/tmp/jiritsu fs_type=19780 overflow=0 '
            + f'before_entries=4 before_reg=3 before_est_slots=13 before_avail_bytes=25755648 '
            + f'matched=2 deleted={deleted_n} delete_failed=0 kept=2 '
            + f'after_entries={after_e} after_reg={after_r} after_est_slots={after_s} after_avail_bytes=25853952\n'
            + self.cfg['expected_output_end']
        ).encode('utf-8')
        self.files[ctrl + '.output'] = out_text
        self.files[ctrl + '.state'] = (
            f'A7R5-JIT-1 {self.run_id} DONE 0 uid=0 euid=0 bytes={len(out_text)} disarmed=1 children=0\n'
        ).encode('ascii')

    def write(self, packet):
        size, func, seq, *meta = HEADER.unpack_from(packet)
        body = packet[HEADER.size :]
        assert size == len(body) and func == 0x40
        group, cmd = struct.unpack_from('<HH', body)
        assert group == 0x1001

        if cmd == 15:
            self.selected = self._wire_to_path(body[5:-1])
            self._queue_chunks(seq, 0, b'')
        elif cmd == 16:
            self.files[self.selected] = body[7:]
            self._queue_chunks(seq, 0, b'')
        elif cmd == 17:
            if self.selected not in self.files:
                self._queue_chunks(seq, 0x10000006, b'')
            else:
                self._queue_chunks(seq, 0, self.files[self.selected])
        elif cmd == 5:
            self.debug_count += 1
            self._queue_chunks(seq, 0, b'')
            self._trigger()
        else:
            raise AssertionError(f'未知命令 {cmd}')
        return len(packet)

    def read(self, length):
        chunk = self._reads.pop(0)
        if len(chunk) > length:
            self._reads.insert(0, chunk[length:])
            return chunk[:length]
        return chunk


class TestCleanJiritsu(unittest.TestCase):
    def test_extra_name_validation_and_compile(self):
        for bad in ('', '.', '..', 'a/b', '../ver.txt', 'a\\b', 'bad space'):
            with self.assertRaises(ValueError):
                clean_builder.validate_extra_names([bad])
        self.assertEqual(clean_builder.validate_extra_names(['passwd.orig', 'old.bin', 'passwd.orig']), ['passwd.orig', 'old.bin'])

        run_id = '0123456789abcdef0123456789abcdef'
        baseline = {'location_id': 0x02100000, 'bus': 2, 'ports': [1], 'pid': 0x0e0a, 'model': 'ILCE-7RM5', 'media': [], 'drivers': ['IOUSBMassStorageDriver']}
        with tempfile.TemporaryDirectory(prefix='a7r5-clean-build-') as tmp:
            pkg = Path(tmp) / 'apply'
            cfg = clean_builder.build_clean_package(
                pkg,
                run_id,
                baseline,
                apply=True,
                extra_names=['passwd.orig'],
            )
            self.assertTrue(cfg['kit_so_path'].startswith('/tmp_wbshd/'))
            self.assertTrue(cfg['control_prefix'].startswith('/tmp_wbshd/'))
            for name in ('blank-512', 'installed-boot-hook'):
                raw = (pkg / f'materials/kit-{name}.so').read_bytes()
                self.assertIn(b'A7R5_CLEAN_JIRITSU_KIT_V1', raw)
                self.assertIn(b'passwd.orig', raw)

            pkg_scan = Path(tmp) / 'scan'
            cfg_scan = clean_builder.build_clean_package(pkg_scan, run_id, baseline, apply=False)
            self.assertEqual(cfg_scan['mode'], 'scan')
            self.assertTrue((pkg_scan / 'materials/kit-blank-512.so').is_file())

    def _run_sim(self, *, apply=True, preload_idx=0, fail_mode=None):
        run_id = 'abcdef0123456789abcdef0123456789'
        baseline = {'location_id': 0x02100000, 'bus': 2, 'ports': [1], 'pid': 0x0e0a, 'model': 'ILCE-7RM5', 'media': [], 'drivers': ['IOUSBMassStorageDriver']}
        with tempfile.TemporaryDirectory(prefix='a7r5-clean-op-') as tmp:
            tmp_path = Path(tmp)
            pkg = tmp_path / 'pkg'
            cfg = clean_builder.build_clean_package(pkg, run_id, baseline, apply=apply)
            preload_bytes = bytes.fromhex(cfg['preload_baselines'][preload_idx][1])
            fake_ver = b'VER_400\n'
            fake_ldr = b'LOADER'
            import hashlib
            cfg['version_sha256'] = hashlib.sha256(fake_ver).hexdigest()
            cfg['loader_sha256'] = hashlib.sha256(fake_ldr).hexdigest()
            cfg['loader_bytes'] = len(fake_ldr)
            (pkg / 'config.json').write_text(json.dumps(cfg))

            op = CleanJiritsuOperation(pkg, sleep=lambda _: None)
            op.interface_checked(FakeDevice(0x0e0a, 2, [1]), FakeInterface([129, 2], interface_class=8, subclass=6, protocol=80))
            op.interface_checked(FakeDevice(0x0336, 2, [1]), FakeInterface([129, 2, 131, 4], interface_class=255, subclass=0, protocol=0))

            driver = CleanStubDriver(run_id, cfg, preload_bytes, fail_mode=fail_mode)
            driver.files['/version.txt'] = fake_ver
            driver.files['/usr/lib/libJiritsu.so'] = fake_ldr

            out = tmp_path / 'session'
            out.mkdir()
            report = {}
            op(driver, out, lambda *a, **kw: None, report)
            return op, report, driver

    def test_scan_and_apply_zero_jiritsu_writes(self):
        for apply, idx in ((False, 0), (True, 1)):
            op, report, driver = self._run_sim(apply=apply, preload_idx=idx)
            self.assertTrue(op.safe_to_stop)
            self.assertTrue(report['protocol_gate_passed'])
            self.assertTrue(report['preload_unchanged'])
            self.assertEqual(driver.debug_count, 1)
            self.assertFalse(any(p.startswith('/tmp/jiritsu/') for p in op.writes))
            self.assertEqual(report['clean_summary']['deleted'], 2 if apply else 0)

    def test_failure_gates_block_stop(self):
        with self.assertRaises(RuntimeError):
            self._run_sim(apply=True, fail_mode='task_failed')
        with self.assertRaises(ValueError):
            self._run_sim(apply=True, fail_mode='preload_not_restored')

    def test_closed_loop_and_sudo_preserves_venv_symlink(self):
        loc = 0x02100000
        baseline_host = {
            'kind': 'ordinary',
            'present': True,
            'location_id': loc,
            'bus': 2,
            'ports': [1],
            'pid': 0x0e0a,
            'model': 'ILCE-7RM5',
            'media': [[True, 67108864]],
            'drivers': ['IOUSBMassStorageDriver'],
        }

        class FakeHost:
            def ensure_ordinary_mode(self, out_dir=None, log_fn=None):
                return baseline_host, {'initial': {'kind': 'service', 'location_id': loc}, 'stop_attempts': 1, 'stop_result': 'returned'}

            def snapshot(self, out_dir=None, label=None, timeout=5, location=None):
                return baseline_host

            def observe_ordinary(self, location_id, take=None, baseline=None, seconds=45, interval=2):
                take('host-00')
                return {'recovered': True}

        def fake_session(output, operation, timeout_seconds=120):
            out = Path(output)
            out.mkdir(parents=True, exist_ok=True)
            (out.parent / 'entries.json').write_text(
                json.dumps([{'type': 'reg', 'action': 'deleted', 'name': 'libJit.so'}])
            )
            return {
                'protocol_gate_passed': True,
                'preload_unchanged': True,
                'trigger_attempts': 1,
                'service_stop_attempts': 1,
                'service_stop_result': 'stalled',
                'service_stop_backend_error_code': -9,
                'clean_summary': {'mode': 'apply', 'deleted': 1},
            }

        with tempfile.TemporaryDirectory(prefix='a7r5-clean-loop-') as tmp:
            res = clean_jiritsu.run_clean(
                apply=True,
                host_mod=FakeHost(),
                builder_mod=clean_builder,
                session_fn=fake_session,
                out_dir=Path(tmp) / 'run1',
            )
            self.assertTrue(res['succeeded'])
            self.assertTrue(res['ordinary_usb_restored'])
            self.assertEqual(res['deleted_names'], ['libJit.so'])

        captured = {}

        def fake_execv(path, argv):
            captured['path'] = path
            captured['argv'] = argv
            raise SystemExit(0)

        with (
            mock.patch.object(clean_jiritsu.os, 'geteuid', return_value=1000),
            mock.patch.object(clean_jiritsu.os, 'execv', side_effect=fake_execv),
        ):
            with self.assertRaises(SystemExit):
                clean_jiritsu.main(['--scan-only'])
        self.assertEqual(captured['path'], '/usr/bin/sudo')
        self.assertEqual(captured['argv'][1], clean_jiritsu.os.path.abspath(clean_jiritsu.sys.executable))


if __name__ == '__main__':
    unittest.main(verbosity=2)
