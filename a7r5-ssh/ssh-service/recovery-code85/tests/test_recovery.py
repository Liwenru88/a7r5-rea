"""仅用内存设备和保存的文件；不访问相机或主机USB元数据。"""
from pathlib import Path
import contextlib
import copy
import io
import json
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import host_state
import policy
import recover

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / 'reference'
if not REF.exists():
    REF = ROOT / 'packages/code85-recovery-20261021-01/reference'

BASELINE = dict(location_id=0x00100000, model='ILCE-7RM5', pid=0x0e0a,
                media=[[False, 67108352], [False, 8589934592], [False, 118286712832],
                       [True, 67108864], [True, 126877696000]],
                drivers=['IOUSBMassStorageDriver', 'IOUSBMassStorageDriverNub', 'IOUSBMassStorageInterfaceNub'])


def ordinary_tree():
    value = tree(0x0e0a, 'ILCE-7RM5')
    value[0]['IORegistryEntryChildren'] = [dict(IOObjectClass=name) for name in BASELINE['drivers']]
    value[0]['IORegistryEntryChildren'] += [dict(IOObjectClass='IOMedia', Size=size, Whole=whole,
                                               **{'BSD Name': f'disk90s{n}'})
                                             for n, (whole, size) in enumerate(BASELINE['media'])]
    return value


def child(code=124, attempted=0, listener=0, account=1, banner=0, error=2):
    return (f'PRIVATE_RESULT code={code} errno={error} sshd_attempted={attempted} '
            f'listener_observed={listener} children_reaped=1 private_account_changed={account} '
            f'local_banner_verified={banner}\n').encode()


def files():
    data = {'/version.txt': (REF / 'version.bin').read_bytes(),
            policy.PREFIX + '.state': policy.STATE, policy.PREFIX + '.output': policy.FINAL,
            policy.RAM + '/result': policy.FINAL, '/etc/ld.so.preload': policy.NEUTRAL,
            policy.RAM + '/child-result': child(), policy.RAM + '/diagnostic': b'',
            '/etc/passwd': (REF / 'passwd.bin').read_bytes(),
            '/etc/nsswitch.conf': (REF / 'nsswitch.bin').read_bytes(),
            '/etc/ssh/sshd_config': (REF / 'sshd-config.bin').read_bytes(),
            '/proc/net/tcp': b'  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode\n',
            policy.RAM + '/heartbeat': b'A7R5_PRIVATE_ENDED\n'}
    return data


class Driver:
    def __init__(self, data=None, fault=None, diagnostic_error=0, errors=None):
        self.files = files() if data is None else data
        self.fault, self.diagnostic_error = fault, diagnostic_error
        self.errors = errors or {}
        self.commands, self.paths, self.labels = [], [], []
        self.reply, self.selected, self.parent_count, self.preload_count = b'', '', 0, 0

    def write(self, packet):
        size, fun, seq, *meta = recover.HEADER.unpack_from(packet)
        body = packet[recover.HEADER.size:]
        assert size == len(body) and fun == 0x40 and not any(meta)
        group, cmd = struct.unpack_from('<HH', body)
        assert group == 0x1001 and cmd in (15, 17), '禁止写、认证、START和DEBUG'
        self.commands.append(cmd)
        payload, result = b'', 0
        if cmd == 15:
            self.selected = body[5:-1].decode().replace('/tmp/jiritsu/../..', '', 1)
            self.paths.append(self.selected)
            assert body[4:5] == b'\0' and body[-1:] == b'\0'
        else:
            assert body == recover.READ
            payload = self.files[self.selected]
            if self.selected in self.errors:
                payload, result = b'', self.errors[self.selected]
            if self.selected == policy.RAM + '/diagnostic' and self.diagnostic_error:
                payload, result = b'', self.diagnostic_error
            if self.selected == policy.RAM + '/result':
                self.parent_count += 1
                if self.fault == 'parent_after' and self.parent_count == 2:
                    payload += b'changed'
            if self.selected == '/etc/ld.so.preload':
                self.preload_count += 1
                if self.fault == 'preload_after' and self.preload_count == 2:
                    payload = b''
        response = struct.pack('<I', result) + payload
        header = recover.HEADER.pack(len(response), fun, seq + (self.fault == 'sequence'), 3, 1, 2, 0)
        if self.fault in ('function', 'status', 'oversize', 'undersize'):
            values = list(recover.HEADER.unpack(header))
            values[{'function': 1, 'status': 6, 'oversize': 0, 'undersize': 0}[self.fault]] = {
                'function': 0x41, 'status': 1, 'oversize': 100000, 'undersize': 3}[self.fault]
            header = recover.HEADER.pack(*values)
        if self.fault == 'header_short':
            header = header[:-1]
        self.reply = header + response
        if self.fault == 'transport':
            raise OSError('离线传输错误')
        return len(packet) - (self.fault == 'short_write')

    def read(self, size):
        if self.fault == 'header_short':
            return self.reply[:recover.HEADER.size - 1]
        if self.fault == 'body_empty' and size != recover.HEADER.size:
            return b''
        result, self.reply = self.reply[:size], self.reply[size:]
        return result


class Interface(list):
    bInterfaceNumber = 0
    bAlternateSetting = 0
    bInterfaceClass = 255
    bInterfaceSubClass = 255
    bInterfaceProtocol = 255


def interface():
    return Interface([SimpleNamespace(bEndpointAddress=n, bmAttributes=2, wMaxPacketSize=512, bInterval=0)
                      for n in (0x81, 2, 0x83, 4)])


class Configuration:
    bConfigurationValue = 1
    def __init__(self, raw=None):
        self.raw = interface() if raw is None else raw
    def __getitem__(self, key):
        assert key == (0, 0)
        return self.raw


class Device:
    bus = 0
    port_numbers = (1,)
    idProduct = 0x0336
    def __init__(self, driver, raw=None, kernel=False, stop_error=False):
        self.driver, self.raw, self.kernel = driver, raw, kernel
        self.stop_error, self.controls, self.endpoints_used = stop_error, [], []
    def get_active_configuration(self):
        return Configuration(self.raw)
    def is_kernel_driver_active(self, number):
        assert number == 0
        if self.kernel == 'unsupported':
            raise NotImplementedError('Darwin未实现')
        return self.kernel
    def write(self, ep, data, timeout):
        assert 0 < timeout <= 5000
        self.endpoints_used.append(ep)
        return self.driver.write(data)
    def read(self, ep, n, timeout):
        assert 0 < timeout <= 5000
        self.endpoints_used.append(ep)
        return self.driver.read(n)
    def ctrl_transfer(self, *args, timeout):
        self.controls.append(args)
        assert args == recover.STOP and timeout <= 5000
        if self.stop_error:
            raise OSError('离线Pipe error')
        return 0


def tree(pid=0x0336, product='USB Bus-powered Device', location=0x00100000):
    return [dict(IOObjectClass='IOUSBHostDevice', idVendor=0x054c,
                 idProduct=pid, locationID=location, **{'USB Product Name': product})]


class HostRegression(unittest.TestCase):
    def test_service_product_string_is_not_ordinary_model_gate(self):
        self.assertEqual(host_state.parse(tree())['kind'], 'service')

    def test_unknown_or_changed_identity_stops(self):
        for raw in (tree(location=0x01100000), tree(pid=1), tree() * 2,
                    tree(0x0e0a, 'USB Bus-powered Device')):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                host_state.parse(raw)
        self.assertEqual(host_state.parse([])['kind'], 'absent')
        self.assertEqual(host_state.parse(tree(0x096f))['kind'], 'transition')

    def test_raw_tree_saved_before_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            raw = plistlib.dumps(tree(location=1))
            with patch.object(host_state.subprocess, 'run', return_value=SimpleNamespace(stdout=raw)), self.assertRaises(ValueError):
                host_state.snapshot(out, 'rejected')
            self.assertEqual((out / 'rejected.plist').read_bytes(), raw)

    def test_recovery_requires_two_complete_matches_and_rejects_extra_media(self):
        ordinary = host_state.parse(ordinary_tree())
        history = iter([host_state.parse(tree()), host_state.parse(tree(0x096f)), ordinary, ordinary])
        with patch.object(host_state.time, 'sleep'):
            result = host_state.observe(BASELINE, lambda *a, **k: next(history), seconds=1, interval=.01)
        self.assertTrue(result['recovered'])
        self.assertEqual(len(result['observations']), 4)
        changed = copy.deepcopy(ordinary)
        changed['media'].append([True, 1])
        with patch.object(host_state.time, 'sleep'):
            result = host_state.observe(BASELINE, lambda *a, **k: changed, seconds=1, interval=.01)
        self.assertFalse(result['recovered'])
        self.assertEqual(len(result['observations']), 1)

    def test_partial_media_never_counts_as_recovered(self):
        partial = host_state.parse(tree(0x0e0a, 'ILCE-7RM5'))
        with patch.object(host_state.time, 'sleep'):
            proof = host_state.observe(BASELINE, lambda *a, **k: partial, seconds=1, interval=.01)
        self.assertFalse(proof['recovered'])
        self.assertLessEqual(len(proof['observations']), 32)


class ReadGates(unittest.TestCase):
    def test_real_codec_accepts_early_child_failure_and_unreadable_diagnostic(self):
        driver = Driver(diagnostic_error=0x10000006)
        with tempfile.TemporaryDirectory() as tmp:
            result = recover.fixed_reads(driver, Path(tmp), lambda *a, **k: None)
        self.assertTrue(result['gate_passed'])
        self.assertTrue(result['diagnostic_unreadable'])
        self.assertEqual(driver.paths, [row[1] for row in policy.READS])
        self.assertEqual(driver.commands, [15, 17] * 14)

    def test_mandatory_content_mismatches_stop_at_the_first_failure(self):
        cases = {
            '/version.txt': b'wrong version',
            policy.PREFIX + '.state': policy.STATE.replace(policy.RUN.encode(), b'0' * 32),
            policy.PREFIX + '.output': policy.FINAL.replace(b'code=85', b'code=0'),
            policy.RAM + '/result': policy.FINAL.replace(b'parent_unchanged=1', b'parent_unchanged=0'),
            '/etc/ld.so.preload': b'unknown.so\n',
            policy.RAM + '/child-result': child().replace(b'children_reaped=1', b'children_reaped=0'),
            '/etc/passwd': b'changed account', '/etc/nsswitch.conf': b'changed NSS',
            '/etc/ssh/sshd_config': b'changed config',
            '/proc/net/tcp': files()['/proc/net/tcp'] + b'0: 00000000:08AE 00000000:0000 0A 0 0 0 0 0 0\n',
            policy.RAM + '/heartbeat': b'A7R5_PRIVATE_ALIVE\n',
        }
        for path, bad in cases.items():
            with self.subTest(path=path), tempfile.TemporaryDirectory() as tmp:
                data = files()
                data[path] = bad
                driver = Driver(data)
                with self.assertRaises(ValueError):
                    recover.fixed_reads(driver, Path(tmp), lambda *a, **k: None)
                self.assertEqual(driver.paths[-1], path)

    def test_late_change_and_transport_failure_never_continue(self):
        for fault in ('parent_after', 'preload_after', 'sequence', 'header_short', 'transport', 'short_write',
                      'body_empty', 'function', 'status', 'oversize', 'undersize'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                driver = Driver(fault=fault)
                with self.assertRaises((ValueError, OSError)):
                    recover.fixed_reads(driver, Path(tmp), lambda *a, **k: None)
                self.assertLessEqual(len(driver.commands), 28)

    def test_diagnostic_exception_is_not_a_general_file_error_bypass(self):
        for code, attempted, result in [(116, 1, 0x10000006), (124, 0, 1), (110, 0, 0x10000006)]:
            with self.subTest(code=code), tempfile.TemporaryDirectory() as tmp:
                data = files()
                data[policy.RAM + '/child-result'] = child(code, attempted)
                with self.assertRaises(recover.FileResultError):
                    recover.fixed_reads(Driver(data, diagnostic_error=result), Path(tmp), lambda *a, **k: None)
        data = files()
        data[policy.RAM + '/child-result'] = child(116, 1)
        data[policy.RAM + '/diagnostic'] = b'known sshd diagnostic\n'
        with tempfile.TemporaryDirectory() as tmp:
            self.assertTrue(recover.fixed_reads(Driver(data), Path(tmp), lambda *a, **k: None)['gate_passed'])

    def test_unknown_or_inconsistent_child_and_malformed_tcp_are_rejected(self):
        for raw in (child(119), child(118), child(999), child(124, 1), child(101, account=1),
                    child(116, 0), child(124, listener=1), child(0, 1, 1, 1, 1, error=2),
                    child(115, 1, 1), child(108, 1, 1), child(112, 1)):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                policy.child_result(raw)
        for raw in (b'', b'bad\n', files()['/proc/net/tcp'][:-1], files()['/proc/net/tcp'] + b'0: invalid\n'):
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                policy.no_listener(raw)

    def test_nonzero_service_result_for_mandatory_files_is_not_polled_or_ignored(self):
        for path in {row[1] for row in policy.READS if row[0] != 'diagnostic'}:
            with self.subTest(path=path), tempfile.TemporaryDirectory() as tmp:
                driver = Driver(errors={path: 0x10000006})
                with self.assertRaises(recover.FileResultError):
                    recover.fixed_reads(driver, Path(tmp), lambda *a, **k: None)
                self.assertEqual(driver.paths[-1], path)
                self.assertEqual(driver.paths.count(path), 1)

    def test_no_arbitrary_command_path_or_repeated_read(self):
        channel = recover.ReadChannel(Driver(), lambda *a, **k: None)
        for body in (b'DEBUG', recover.READ, struct.pack('<HH', 0x1001, 0x10) + b'\0\xff\0x'):
            with self.assertRaises(PermissionError):
                channel.exchange(body, 100)
        with self.assertRaises(PermissionError):
            channel.read_next('anything', '/etc/shadow', 4096)
        channel.read_next(*policy.READS[0])
        with self.assertRaises(PermissionError):
            channel.read_next(*policy.READS[0])


class ServiceContract(unittest.TestCase):
    def attempt(self, device, *, claim_error=False):
        claims, releases = [], []
        def claim(dev, number):
            claims.append(number)
            if claim_error:
                raise OSError('离线claim失败')
        runtime = (SimpleNamespace(find=lambda **kwargs: [device]),
                   SimpleNamespace(claim_interface=claim,
                                   release_interface=lambda *args: releases.append(True),
                                   dispose_resources=lambda *args: None), object())
        with tempfile.TemporaryDirectory() as tmp, patch.object(recover, 'usb_runtime', return_value=runtime):
            report = dict(gate_passed=False, stop_attempts=0)
            failure = None
            try:
                recover.service_attempt({}, Path(tmp), lambda *a, **k: None, report)
            except Exception as exc:
                failure = exc
            return report, failure, claims, releases

    def test_one_stop_after_gate_and_no_fallback_on_pipe_error(self):
        for stop_error in (False, True):
            for kernel in (False, 'unsupported'):
                with self.subTest(stop_error=stop_error, kernel=kernel):
                    dev = Device(Driver(diagnostic_error=0x10000006), stop_error=stop_error, kernel=kernel)
                    report, failure, claims, releases = self.attempt(dev)
                    self.assertIsNone(failure)
                    self.assertEqual(dev.controls, [recover.STOP])
                    self.assertEqual(report['stop_attempts'], 1)
                    self.assertEqual(claims, [0])
                    self.assertEqual(releases, [True])
                    self.assertEqual(set(dev.endpoints_used), {0x81, 2})

    def test_gate_or_transport_failure_never_sends_stop(self):
        for fault in ('parent_after', 'preload_after', 'sequence', 'transport', 'short_write'):
            with self.subTest(fault=fault):
                dev = Device(Driver(fault=fault))
                report, failure, claims, releases = self.attempt(dev)
                self.assertIsNotNone(failure)
                self.assertEqual(dev.controls, [])
                self.assertEqual(report['stop_attempts'], 0)
                self.assertTrue(set(dev.endpoints_used) <= {0x81, 2})

    def test_identity_endpoint_and_claim_failures_precede_file_requests(self):
        bad_alt = interface()
        bad_alt.bAlternateSetting = 1
        duplicate = interface()
        duplicate.append(duplicate[0])
        for raw, kernel, claim_error in ((bad_alt, False, False), (duplicate, False, False),
                                         (Interface(interface()[:1]), False, False),
                                         (None, True, False), (None, False, True)):
            dev = Device(Driver(), raw, kernel=kernel)
            report, failure, claims, releases = self.attempt(dev, claim_error=claim_error)
            self.assertIsNotNone(failure)
            self.assertEqual(dev.driver.commands, [])
            self.assertEqual(dev.controls, [])
            self.assertLessEqual(len(claims), 1)
        dev = Device(Driver())
        dev.bus = 1
        self.assertIsNotNone(self.attempt(dev)[1])
        self.assertEqual(dev.driver.commands, [])

    def test_expired_window_never_sends_stop(self):
        dev = Device(Driver())
        with patch.object(recover.time, 'monotonic', side_effect=[0, 61]):
            report, failure, claims, releases = self.attempt(dev)
        self.assertIsInstance(failure, TimeoutError)
        self.assertEqual(dev.controls, [])


class ExecutionContract(unittest.TestCase):
    def test_host_only_branches_do_not_open_usb_and_do_not_claim_guest_cleanup(self):
        for kind in ('ordinary', 'transition'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(recover, 'HERE', Path(tmp)))
                stack.enter_context(patch.object(recover, 'check', return_value={'host_baseline': BASELINE}))
                stack.enter_context(patch.object(recover.sys, 'platform', 'darwin'))
                stack.enter_context(patch.object(recover.os, 'geteuid', return_value=0))
                stack.enter_context(patch.object(recover.os, 'chown'))
                stack.enter_context(patch.object(host_state, 'snapshot', return_value={'kind': kind}))
                stack.enter_context(patch.object(host_state, 'observe', return_value={'recovered': True}))
                backend = stack.enter_context(patch.object(recover, 'usb_runtime', side_effect=AssertionError('不许打开USB')))
                with contextlib.redirect_stdout(io.StringIO()):
                    result = recover.execute(True)
                self.assertTrue(result['host_recovery_verified'])
                self.assertFalse(result['guest_cleanup_verified'])
                self.assertEqual(result['stop_attempts'], 0)
                backend.assert_not_called()

    def test_no_approval_or_device_switch_precedes_all_hardware(self):
        with patch.object(recover, 'usb_runtime', side_effect=AssertionError('设备禁用')), \
                patch.object(host_state, 'snapshot', side_effect=AssertionError('主机观察禁用')):
            with self.assertRaises(PermissionError):
                recover.execute(False)
            with patch.object(recover, 'check', side_effect=PermissionError('未批准')):
                with self.assertRaises(PermissionError):
                    recover.execute(True)

    def test_service_stop_error_observes_host_once_without_repeating_service(self):
        for failure in (False, True):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(recover, 'HERE', Path(tmp)))
                stack.enter_context(patch.object(recover, 'check', return_value={'host_baseline': BASELINE}))
                stack.enter_context(patch.object(recover.sys, 'platform', 'darwin'))
                stack.enter_context(patch.object(recover.os, 'geteuid', return_value=0))
                stack.enter_context(patch.object(recover.os, 'chown'))
                stack.enter_context(patch.object(host_state, 'snapshot', return_value={'kind': 'service'}))
                observer = stack.enter_context(patch.object(host_state, 'observe', return_value={'recovered': True}))
                def service(manifest, out, log, report):
                    if failure:
                        raise OSError('读取失败')
                    report.update(gate_passed=True, stop_attempts=1, stop_result='transfer_error')
                attempt = stack.enter_context(patch.object(recover, 'service_attempt', side_effect=service))
                with contextlib.redirect_stdout(io.StringIO()):
                    result = recover.execute(True)
                self.assertEqual(attempt.call_count, 1)
                self.assertEqual(observer.call_count, 0 if failure else 1)
                self.assertEqual(result['stop_attempts'], 0 if failure else 1)
                self.assertEqual(result['execution_succeeded'], not failure)


class PackageGates(unittest.TestCase):
    def package(self, directory):
        path = Path(directory).resolve()
        for name in ('recover.py', 'policy.py', 'host_state.py'):
            shutil.copyfile(ROOT / name, path / name)
        manifest = dict(policy=recover.metadata(), directory=str(path), dependencies={},
                        files={name: dict(bytes=(path / name).stat().st_size,
                                          sha256=policy.digest((path / name).read_bytes()))
                               for name in ('recover.py', 'policy.py', 'host_state.py')})
        recover.save(path / 'recovery.json', manifest)
        return path

    def approve(self, path):
        recover.save(path / 'approval.json', dict(accepted=True, risk=policy.RISK,
                     recovery_sha256=policy.digest((path / 'recovery.json').read_bytes())))

    def test_missing_changed_or_false_approval_and_used_lock_rejected_offline(self):
        for fault in ('missing', 'false', 'hash', 'risk', 'lock', 'result', 'tamper', 'symlink'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                path = self.package(tmp)
                if fault != 'missing':
                    self.approve(path)
                if fault in ('false', 'hash', 'risk'):
                    approval = json.loads((path / 'approval.json').read_text())
                    approval[{'false': 'accepted', 'hash': 'recovery_sha256', 'risk': 'risk'}[fault]] = False
                    recover.save(path / 'approval.json', approval)
                if fault in ('lock', 'result'):
                    (path / ('ATTEMPT_LOCK' if fault == 'lock' else 'result')).mkdir()
                if fault == 'tamper':
                    (path / 'host_state.py').write_text('changed')
                if fault == 'symlink':
                    (path / 'policy.py').rename(path / 'policy-original.py')
                    (path / 'policy.py').symlink_to('policy-original.py')
                with patch.object(recover, 'HERE', path), patch.object(host_state, 'snapshot', side_effect=AssertionError('设备禁用')):
                    with self.assertRaises((PermissionError, FileNotFoundError, FileExistsError, ValueError)):
                        recover.execute(True)
                if fault != 'result':
                    self.assertFalse((path / 'result').exists())

    def test_bound_approval_passes_but_does_not_itself_touch_hardware(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = self.package(tmp)
            self.approve(path)
            with patch.object(recover, 'HERE', path):
                self.assertEqual(recover.check(True)['policy'], recover.metadata())
            self.assertFalse((path / 'ATTEMPT_LOCK').exists())

    @unittest.skipUnless((ROOT / 'run-recovery.command').exists(), '仅在最终封包运行Terminal脚本契约')
    def test_actual_terminal_launcher_refuses_before_sudo_without_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'sudo-was-called'
            sudo = Path(tmp) / 'sudo'
            sudo.write_text('#!/bin/sh\nprintf invoked > "' + str(marker) + '"\nexit 99\n')
            sudo.chmod(0o700)
            environment = dict(os.environ, PATH=tmp + os.pathsep + os.environ.get('PATH', ''))
            result = subprocess.run(['/bin/bash', str(ROOT / 'run-recovery.command')],
                                    capture_output=True, text=True, env=environment, timeout=30)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn('approval.json', result.stderr)
            self.assertFalse(marker.exists())
            self.assertFalse((ROOT / 'ATTEMPT_LOCK').exists())
            self.assertFalse((ROOT / 'result').exists())


if __name__ == '__main__':
    unittest.main()
