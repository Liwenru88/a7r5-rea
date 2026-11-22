"""ssh_start 离线回归测试：口令哈希、双引擎交叉编译、单会话协议门控与闭环登录命令生成。"""
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
TRUST_DIR = PROJECT / 'scripts/trust_update'
for _p in (str(HERE), str(TRUST_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import ssh_builder
from ssh_operations import DEBUG, JoinedSSHOperation
import start_ssh
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


class SSHStubDriver:
    """模拟 0336 Senser 文件与 DEBUG 协议响应，验证单会话上传、触发、监听与心跳。"""

    def __init__(self, engine, run_id, cfg, build_meta, preload_bytes, *, fail_mode=None):
        self.engine = engine
        self.run_id = run_id
        self.cfg = cfg
        self.build_meta = build_meta
        self.preload_bytes = preload_bytes
        self.fail_mode = fail_mode
        self.prefix = build_meta['prefix']
        self.ram = build_meta['ram_directory']
        self.files = {'/etc/ld.so.preload': preload_bytes}
        self.selected = None
        self._reads = []
        self.heartbeat_reads = 0
        self.debug_count = 0

        # 构造符合 policy.public_key 长度(104B)与结构的测试 ECDSA 公钥
        blob = b'\x00\x00\x00\x13ecdsa-sha2-nistp256' + b'A' * (104 - 23)
        self.pub_line = b'ecdsa-sha2-nistp256 ' + base64.b64encode(blob) + b' root@a7r5\n'
        self.pub_sha = hashlib.sha256(self.pub_line).hexdigest()

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

    def _trigger_ssh(self):
        if self.engine == 'kit' and self.fail_mode != 'preload_not_restored':
            self.files['/etc/ld.so.preload'] = self.preload_bytes

        ttl = self.build_meta['ttl_seconds']
        ready = (
            f'A7R5_PRIVATE_READY {self.run_id} parent=123 child=124 uid=0 euid=0 ttl={ttl} '
            f'parent_unchanged=1 private_account_changed=1 parent_ns=mnt:[10] child_ns=mnt:[20] '
            f'host_public_sha={self.pub_sha}\n'
        ).encode('ascii')
        banner = b'SSH-2.0-OpenSSH_8.4\r\n'
        banner_sha = hashlib.sha256(banner).hexdigest()
        started = (
            f'A7R5_WILDCARD_STARTED {self.run_id} pid=125 bind=0.0.0.0:2222 '
            f'listener_observed=1 banner_sha={banner_sha}\n'
        ).encode('ascii')

        self.files[self.ram + '/ready'] = ready
        self.files[self.ram + '/host-public-key'] = self.pub_line
        self.files[self.ram + '/hostkey-check'] = b'A7R5_RAM_GENERATED_HOSTKEY verified=1 mode=600 tmpfs=1 private_key_logged=0\n'
        self.files[self.ram + '/banner'] = banner
        self.files[self.ram + '/started'] = started
        if self.engine == 'libjit':
            self.files[self.prefix + '.claim'] = self.files[self.prefix + '.ticket']

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
            data = body[7:]
            self.files[self.selected] = data
            self._queue_chunks(seq, 0, b'')
            if self.engine == 'libjit' and self.selected == '/tmp/jiritsu/libJit.so':
                self.files.pop('/tmp/jiritsu/libJit.so', None)
                self._trigger_ssh()
        elif cmd == 17:
            if self.selected == self.ram + '/heartbeat':
                self.heartbeat_reads += 1
                elapsed = 1000 if self.fail_mode == 'stale_heartbeat' else self.heartbeat_reads * 1500
                ttl = self.build_meta['ttl_seconds']
                hb = (
                    f'A7R5_PRIVATE_ALIVE {self.run_id} parent=123 child=124 ttl={ttl} '
                    f'elapsed_ms={elapsed} parent_unchanged=1 changes_observed=0\n'
                ).encode('ascii')
                self._queue_chunks(seq, 0, hb)
            elif self.selected not in self.files:
                self._queue_chunks(seq, 0x10000006, b'')
            else:
                self._queue_chunks(seq, 0, self.files[self.selected])
        elif cmd == 5:
            self.debug_count += 1
            self._queue_chunks(seq, 0, b'')
            if self.engine == 'kit':
                self._trigger_ssh()
        else:
            raise AssertionError(f'未知命令 {cmd}')
        return len(packet)

    def read(self, length):
        chunk = self._reads.pop(0)
        if len(chunk) > length:
            self._reads.insert(0, chunk[length:])
            return chunk[:length]
        return chunk


class TestSSHStart(unittest.TestCase):
    def test_password_validation_and_hash(self):
        with self.assertRaises(ValueError):
            ssh_builder.make_password_hash('short')
        with self.assertRaises(ValueError):
            ssh_builder.make_password_hash('bad\npassword')
        h = ssh_builder.make_password_hash('MyTestPass!2026')
        self.assertRegex(h, ssh_builder.HASH_PATTERN)

    def test_compile_both_engines(self):
        run_id = '0123456789abcdef0123456789abcdef'
        pwd_hash = ssh_builder.make_password_hash('CompilePass#99')
        baseline = {'location_id': 0x02140000, 'bus': 2, 'ports': [1, 4], 'pid': 0x0e0a, 'model': 'ILCE-7RM5', 'media': [], 'drivers': ['IOUSBMassStorageDriver']}
        with tempfile.TemporaryDirectory(prefix='a7r5-ssh-build-') as tmp:
            pkg_jit = Path(tmp) / 'jit'
            cfg_jit, meta_jit = ssh_builder.build_ssh_package(pkg_jit, 'libjit', run_id, pwd_hash, baseline, ttl_seconds=0)
            self.assertTrue((pkg_jit / 'materials/service.arm64').is_file())
            self.assertTrue((pkg_jit / 'materials/session.arm64').is_file())
            self.assertTrue((pkg_jit / 'materials/sftp-server.arm64').is_file())
            self.assertTrue((pkg_jit / 'materials/libJit.so').is_file())
            self.assertEqual(meta_jit['ttl_seconds'], 0)
            self.assertEqual(cfg_jit['interfaces']['interface-1.json']['ports'], [1, 4])

            pkg_kit = Path(tmp) / 'kit'
            ssh_builder.build_ssh_package(pkg_kit, 'kit', run_id, pwd_hash, baseline, ttl_seconds=0)
            self.assertIn(b'A7R5_SSH_KIT_TRIGGER_V1', (pkg_kit / 'materials/kit-blank-512.so').read_bytes())
            self.assertIn(b'A7R5_SSH_KIT_TRIGGER_V1', (pkg_kit / 'materials/kit-installed-boot-hook.so').read_bytes())

    def _run_op_sim(self, engine, preload_idx, *, fail_mode=None):
        run_id = 'fedcba9876543210fedcba9876543210'
        pwd_hash = ssh_builder.make_password_hash('SimPass!2026')
        baseline = {'location_id': 0x03210000, 'bus': 3, 'ports': [2, 1], 'pid': 0x0e0a, 'model': 'ILCE-7RM5', 'media': [], 'drivers': ['IOUSBMassStorageDriver']}
        profile = ssh_builder.load_profile()
        preload_bytes = bytes.fromhex(profile['preload_baselines'][preload_idx][1])

        with tempfile.TemporaryDirectory(prefix='a7r5-ssh-op-') as tmp:
            tmp_path = Path(tmp)
            pkg = tmp_path / 'pkg'
            cfg, meta = ssh_builder.build_ssh_package(pkg, engine, run_id, pwd_hash, baseline, ttl_seconds=0)
            fake_ver = b'A7R5_VER_400\n'
            fake_ldr = b'A7R5_LOADER'
            cfg['version_sha256'] = hashlib.sha256(fake_ver).hexdigest()
            cfg['loader_sha256'] = hashlib.sha256(fake_ldr).hexdigest()
            cfg['loader_bytes'] = len(fake_ldr)
            (pkg / 'config.json').write_text(json.dumps(cfg))

            op = JoinedSSHOperation(pkg, sleep=lambda _: None)
            op.interface_checked(FakeDevice(0x0e0a, 3, [2, 1]), FakeInterface([129, 2], interface_class=8, subclass=6, protocol=80))
            op.interface_checked(FakeDevice(0x0336, 3, [2, 1]), FakeInterface([129, 2, 131, 4], interface_class=255, subclass=0, protocol=0))

            driver = SSHStubDriver(engine, run_id, cfg, meta, preload_bytes, fail_mode=fail_mode)
            driver.files['/version.txt'] = fake_ver
            driver.files['/usr/lib/libJiritsu.so'] = fake_ldr

            out = tmp_path / 'session'
            out.mkdir()
            report = {}
            op(driver, out, lambda *a, **kw: None, report)
            return op, report, driver

    def test_joined_ssh_both_engines_and_preloads(self):
        for engine in ('libjit', 'kit'):
            for idx in (0, 1):
                op, report, driver = self._run_op_sim(engine, idx)
                self.assertTrue(op.safe_to_stop)
                self.assertTrue(report['protocol_gate_passed'])
                self.assertTrue(report['service_ready'])
                self.assertTrue(report['preload_unchanged'])
                self.assertEqual(report['trigger_attempts'], 1)
                self.assertTrue(op.prefix.startswith('/tmp_wbshd/'))
                if engine == 'kit':
                    self.assertEqual(driver.debug_count, 1)
                    self.assertTrue(op.kit_so_path.startswith('/tmp_wbshd/'))
                    self.assertFalse(any(p.startswith('/tmp/jiritsu/') for p in op.writes))

    def test_failure_gates_block_stop(self):
        with self.assertRaises(ValueError):
            self._run_op_sim('libjit', 0, fail_mode='stale_heartbeat')
        with self.assertRaises(ValueError):
            self._run_op_sim('kit', 1, fail_mode='preload_not_restored')

    def test_full_closed_loop_and_login_command(self):
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
        pub = 'ecdsa-sha2-nistp256 AAAAE2VjZHNhLXNoYTItbmlzdHAyNTYAAAAIbmlzdHAyNTYAAABBBI= root@a7r5'

        class FakeHost:
            def ensure_ordinary_mode(self, out_dir=None, log_fn=None):
                return baseline_host, {'initial': {'kind': 'service', 'location_id': loc}, 'stop_attempts': 1, 'stop_result': 'returned'}

            def snapshot(self, out_dir=None, label=None, timeout=5, location=None):
                return baseline_host

            def observe_ordinary(self, location_id, take=None, baseline=None, seconds=45, interval=2):
                take('host-00')
                return {'recovered': True}

        def fake_session(output, operation, timeout_seconds=120):
            Path(output).mkdir(parents=True, exist_ok=True)
            return {
                'protocol_gate_passed': True,
                'service_ready': True,
                'preload_unchanged': True,
                'trigger_attempts': 1,
                'service_stop_attempts': 1,
                'service_stop_result': 'stalled',
                'service_stop_backend_error_code': -9,
                'host_public_key': pub,
            }

        pwd_hash = ssh_builder.make_password_hash('LoopPass!2026')
        with tempfile.TemporaryDirectory(prefix='a7r5-ssh-loop-') as tmp:
            res = start_ssh.run_ssh_start(
                'kit',
                pwd_hash,
                ip='192.168.122.1',
                host_mod=FakeHost(),
                builder_mod=ssh_builder,
                session_fn=fake_session,
                out_dir=Path(tmp) / 'run1',
            )
            self.assertTrue(res['succeeded'])
            self.assertTrue(res['ordinary_usb_restored'])
            self.assertIn('root@192.168.122.1', res['login_command'])
            self.assertIn('-p 2222', res['login_command'])
            self.assertTrue((Path(tmp) / 'run1/known_hosts').is_file())

    def test_sudo_reexec_preserves_venv_symlink(self):
        from unittest import mock

        captured = {}

        def fake_execv(path, argv):
            captured['path'] = path
            captured['argv'] = argv
            raise SystemExit(0)

        with tempfile.TemporaryDirectory(prefix='a7r5-ssh-sudo-') as tmp:
            tmp_dir = Path(tmp)
            with (
                mock.patch.object(start_ssh.os, 'geteuid', return_value=1000),
                mock.patch.object(start_ssh.os, 'execv', side_effect=fake_execv),
                mock.patch.object(start_ssh, '_create_run_dir', return_value=tmp_dir),
            ):
                with self.assertRaises(SystemExit):
                    start_ssh.main(['--password', 'SudoPathTest!2026'])
                self.assertTrue((tmp_dir / '.pwd.hash').is_file())

        self.assertEqual(captured['path'], '/usr/bin/sudo')
        self.assertEqual(captured['argv'][1], start_ssh.os.path.abspath(start_ssh.sys.executable))


if __name__ == '__main__':
    unittest.main(verbosity=2)
