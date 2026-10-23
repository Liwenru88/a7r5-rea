"""固定旧会话补证的协议、退出与批准契约；全部硬件均为内存替身。"""
from pathlib import Path
import contextlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import collect
import evidence_policy as policy
import host_state
import read_only
from helpers import Driver, Configuration, child, files, interface

PACKAGE = ROOT if (ROOT / 'operation.json').exists() else ROOT / 'packages/code85-evidence-20261021-01'
STOP = (0x43, 1, 0xc800, 0x2855, b'')


class Reads(unittest.TestCase):
    def test_minimum_fixed_sequence_and_partial_assessment(self):
        driver = Driver(diagnostic_error=0x10000006)
        with tempfile.TemporaryDirectory() as tmp:
            result = collect.fixed_reads(driver, Path(tmp), lambda *a, **k: None)
            self.assertEqual(result['file_reads_attempted'], 10)
            self.assertTrue(result['gate_passed'])
            self.assertEqual(result['failure_stage'], collect.STAGES[124])
            self.assertFalse(result['code85_exact_cause_resolved'])
            self.assertFalse(result['diagnostic']['absence_proven'])
            self.assertEqual(driver.paths, [row[1] for row in policy.READS])
            self.assertEqual(driver.commands, [15, 17] * 10)
            self.assertEqual(json.loads((Path(tmp) / 'evidence-assessment.json').read_text())['child']['code'], 124)

    def test_missing_ram_unknown_preload_or_wrong_session_stops_without_extra_reads(self):
        cases = [(policy.RAM + '/result', None), ('/etc/ld.so.preload', b'unknown.so\n'),
                 (policy.PREFIX + '.state', policy.STATE.replace(b'DONE 68', b'DONE 0')),
                 (policy.PREFIX + '.output', policy.FINAL.replace(policy.RUN.encode(), b'0' * 32)),
                 (policy.RAM + '/child-result', child(119)),
                 (policy.RAM + '/heartbeat', b'A7R5_PRIVATE_ALIVE\n')]
        for path, raw in cases:
            with self.subTest(path=path), tempfile.TemporaryDirectory() as tmp:
                data = files()
                if raw is not None:
                    data[path] = raw
                driver = Driver(data, errors={path: 0x10000006} if raw is None else {})
                with self.assertRaises(ValueError):
                    collect.fixed_reads(driver, Path(tmp), lambda *a, **k: None)
                assessment = json.loads((Path(tmp) / 'evidence-assessment.json').read_text())
                self.assertFalse(assessment['gate_passed'])
                self.assertEqual(driver.paths[-1], path)
                self.assertEqual(driver.paths.count(path), 1)
                if raw is not None:
                    label = next(row[0] for row in policy.READS if row[1] == path)
                    self.assertEqual((Path(tmp) / (label + '.bin')).read_bytes(), raw)

    def test_late_diagnostic_error_preserves_child_and_cannot_authorize_exit(self):
        data = files()
        data[policy.RAM + '/child-result'] = child(116, attempted=1)
        with tempfile.TemporaryDirectory() as tmp:
            operation = collect.Operation(Path(tmp))
            driver = Driver(data, diagnostic_error=0x10000006)
            with self.assertRaises(read_only.FileResultError):
                operation(driver, Path(tmp), lambda *a, **k: None, {})
            self.assertFalse(operation.safe_to_stop)
            assessment = json.loads((Path(tmp) / 'evidence-assessment.json').read_text())
            self.assertEqual(assessment['child']['code'], 116)
            self.assertEqual(driver.paths[-1], policy.RAM + '/diagnostic')

    def test_response_metadata_allowed_but_protocol_transport_and_final_race_fail(self):
        for fault in ('parent_after', 'preload_after', 'sequence', 'header_short', 'function', 'status',
                      'oversize', 'undersize', 'body_empty', 'transport', 'short_write'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                operation = collect.Operation(Path(tmp))
                driver = Driver(fault=fault)
                with self.assertRaises((ValueError, OSError)):
                    operation(driver, Path(tmp), lambda *a, **k: None, {})
                self.assertFalse(operation.safe_to_stop)
                self.assertLessEqual(len(driver.commands), 20)

    def test_file_write_debug_and_extra_path_blocked_at_wire_guard(self):
        for body in (struct.pack('<HH', 0x1001, 0x10) + b'\0\xff\0write',
                     struct.pack('<HH', 0x1001, 5) + b'\0\0\0',
                     struct.pack('<HH', 0x1001, 15) + b'\0/tmp/jiritsu/../../etc/passwd\0'):
            raw = read_only.HEADER.pack(len(body), 0x40, 1, 0, 0, 0, 0) + body
            with self.assertRaises(PermissionError):
                collect.Operation.guard_packet(raw)
        channel = read_only.ReadChannel(Driver(), lambda *a, **k: None)
        with self.assertRaises(PermissionError):
            channel.read_next('extra', '/etc/passwd', 4096)


class Device:
    bus = 0
    port_numbers = (1,)
    idVendor = 0x054c
    iProduct = 1
    def __init__(self, pid, state, driver, bad_auth=False):
        self.idProduct, self.state, self.driver, self.bad_auth = pid, state, driver, bad_auth
        self.auth_commands, self.auth_reply, self.endpoints = [], b'', []
    def get_active_configuration(self):
        return Configuration()
    def is_kernel_driver_active(self, number):
        return False
    def write(self, ep, raw, timeout):
        self.endpoints.append(ep)
        if len(raw) == 516:
            command, salt = struct.unpack_from('>HH', raw)
            command = ~command & 0xffff
            assert command in (1, 3, 5) and salt == 0
            self.auth_commands.append(command)
            result = 99 if self.bad_auth else {1: 8, 3: 4, 5: 6}[command]
            payload = b'\x01' if result == 6 else b'challenge'
            self.auth_reply = struct.pack('>HH512s', ~result & 0xffff, 0, payload)
            return len(raw)
        return self.driver.write(raw)
    def read(self, ep, n, timeout):
        self.endpoints.append(ep)
        if n == 516 and self.auth_reply:
            raw, self.auth_reply = self.auth_reply, b''
            return raw
        return self.driver.read(n)
    def ctrl_transfer(self, *args, timeout):
        self.state['controls'].append(args)
        if args == STOP:
            self.state['mode'] = 'normal'
            if self.state.get('pipe_error'):
                raise OSError('离线Pipe error')
        else:
            assert args == (0x43, 1, 0x37ff, 0xd7aa, b'')
            self.state['mode'] = 'service'
        return 0


class FullSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest = json.loads((PACKAGE / 'operation.json').read_text())
        with patch.object(collect, 'HERE', PACKAGE):
            cls.run_session = staticmethod(collect.load_engine(manifest))
        from system_dump import session
        cls.session = session
        import usb.core
        import usb.util
        import usb.backend.libusb1
        cls.usb = SimpleNamespace(core=usb.core, util=usb.util, backend=usb.backend.libusb1)

    def simulate(self, driver, *, bad_auth=0, pipe_error=False, expired=False):
        state = dict(mode='normal', controls=[], pipe_error=pipe_error)
        normal = Device(0x0e0a, state, driver, bad_auth == 1)
        service = Device(0x0336, state, driver, bad_auth == 2)
        def find(**kwargs):
            return [normal if state['mode'] == 'normal' else service]
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            output = Path(tmp) / 'session'
            operation = collect.Operation(output)
            stack.enter_context(patch.object(self.usb.core, 'find', side_effect=find))
            stack.enter_context(patch.object(self.usb.backend, 'get_backend', return_value=object()))
            stack.enter_context(patch.object(self.usb.util, 'get_string', return_value='ILCE-7RM5'))
            claim = stack.enter_context(patch.object(self.usb.util, 'claim_interface'))
            stack.enter_context(patch.object(self.usb.util, 'release_interface'))
            stack.enter_context(patch.object(self.usb.util, 'dispose_resources'))
            unmount = stack.enter_context(patch.object(self.session, 'unmount_camera'))
            if expired:
                times = iter([0, 101])
                stack.enter_context(patch.object(self.session.time, 'monotonic', side_effect=lambda: next(times, 101)))
            with contextlib.redirect_stdout(io.StringIO()):
                report = self.run_session(output, 'libusb', _operation=operation)
            return report, state, normal, service, claim.call_count, unmount.call_count

    def test_real_two_phase_authentication_read_and_one_stop(self):
        for pipe_error in (False, True):
            with self.subTest(pipe_error=pipe_error):
                driver = Driver(diagnostic_error=0x10000006)
                report, state, normal, service, claims, unmounts = self.simulate(driver, pipe_error=pipe_error)
                self.assertTrue(report['code85_evidence_collected'])
                self.assertTrue(report['first_authentication_passed'])
                self.assertTrue(report['second_authentication_passed'])
                self.assertEqual(normal.auth_commands, [1, 3, 1, 3, 1, 3, 5])
                self.assertEqual(service.auth_commands, normal.auth_commands)
                self.assertEqual(state['controls'].count(STOP), 1)
                self.assertEqual(len(state['controls']), 3)
                self.assertEqual((claims, unmounts), (2, 1))
                self.assertEqual(set(service.endpoints), {0x81, 2})
                self.assertFalse(report['camera_file_write_commands_sent'])
                self.assertFalse(report['debug_commands_sent'])

    def test_authentication_error_not_retried_or_followed_by_reads_or_stop(self):
        for stage in (1, 2):
            with self.subTest(stage=stage):
                driver = Driver()
                report, state, normal, service, claims, unmounts = self.simulate(driver, bad_auth=stage)
                self.assertIn('failure', report)
                self.assertEqual(state['controls'].count(STOP), 0)
                self.assertEqual(driver.commands, [])
                self.assertEqual((normal if stage == 1 else service).auth_commands, [1])

    def test_failed_content_protocol_and_final_gate_never_send_stop(self):
        for fault in ('parent_after', 'preload_after', 'sequence', 'transport', 'short_write'):
            with self.subTest(fault=fault):
                driver = Driver(fault=fault)
                report, state, normal, service, claims, unmounts = self.simulate(driver)
                self.assertIn('failure', report)
                self.assertEqual(report['service_stop_attempts'], 0)
                self.assertNotIn(STOP, state['controls'])
                self.assertLessEqual(len(driver.commands), 20)

    def test_expired_communication_budget_sends_no_control_or_file_request(self):
        driver = Driver()
        report, state, normal, service, claims, unmounts = self.simulate(driver, expired=True)
        self.assertIn('TimeoutError', report['failure'])
        self.assertEqual(state['controls'], [])
        self.assertEqual(driver.commands, [])

    def test_unrestricted_or_native_engine_entry_is_rejected_before_usb(self):
        with patch.object(self.usb.core, 'find', side_effect=AssertionError('禁止USB')):
            for transport, operation in (('libusb', None), ('native-host', object())):
                with self.assertRaises(PermissionError):
                    self.run_session(Path('/never-created'), transport, _operation=operation)


class AuthorizationAndHost(unittest.TestCase):
    def test_wrong_port_or_invalid_multi_endpoint_fingerprint_precedes_authentication(self):
        for fault in ('port', 'alt', 'duplicate', 'missing_out', 'packet_size'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                raw = interface()
                device = SimpleNamespace(bus=0, port_numbers=(1,), idProduct=0x0336)
                if fault == 'port':
                    device.bus = 1
                elif fault == 'alt':
                    raw.bAlternateSetting = 1
                elif fault == 'duplicate':
                    raw.append(raw[0])
                elif fault == 'missing_out':
                    raw[:] = [raw[0], raw[2]]
                else:
                    raw[0].wMaxPacketSize = 0
                operation = collect.Operation(Path(tmp))
                with self.assertRaises(ValueError):
                    operation.interface_checked(device, raw)
                self.assertFalse(operation.safe_to_stop)

    def test_bound_material_tamper_false_approval_and_used_package_reject_before_io(self):
        for fault in ('missing', 'false', 'hash', 'tamper', 'lock', 'result'):
            with self.subTest(fault=fault), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp).resolve()
                (root / 'payload-evidence.txt').write_text('unchanged')
                raw = (root / 'payload-evidence.txt').read_bytes()
                manifest = dict(policy=collect.metadata(), directory=str(root), dependencies={},
                                files={'payload-evidence.txt': dict(bytes=len(raw), sha256=policy.digest(raw))})
                collect.save(root / 'operation.json', manifest)
                approval = dict(accepted=True, risk=policy.RISK,
                                operation_sha256=policy.digest((root / 'operation.json').read_bytes()))
                if fault == 'false':
                    approval['accepted'] = False
                elif fault == 'hash':
                    approval['operation_sha256'] = '0' * 64
                if fault != 'missing':
                    collect.save(root / 'approval.json', approval)
                if fault == 'tamper':
                    (root / 'payload-evidence.txt').write_text('changed')
                if fault in ('lock', 'result'):
                    (root / ('ATTEMPT_LOCK' if fault == 'lock' else 'result')).mkdir()
                with patch.object(collect, 'HERE', root), \
                        patch.object(host_state, 'snapshot', side_effect=AssertionError('禁止设备')):
                    with self.assertRaises((PermissionError, ValueError, FileNotFoundError, FileExistsError)):
                        collect.execute(True)
                if fault not in ('lock', 'result'):
                    self.assertFalse((root / 'ATTEMPT_LOCK').exists())

    def test_unapproved_or_no_switch_never_initializes_usb(self):
        with patch.object(collect, 'load_engine', side_effect=AssertionError('禁止USB')), \
                patch.object(host_state, 'snapshot', side_effect=AssertionError('禁止主机观察')):
            with self.assertRaises(PermissionError):
                collect.execute(False)
            with patch.object(collect, 'check', side_effect=PermissionError('尚未批准')):
                with self.assertRaises(PermissionError):
                    collect.execute(True)

    def test_nonordinary_start_never_opens_authentication(self):
        for kind in ('service', 'transition', 'absent'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
                stack.enter_context(patch.object(collect, 'HERE', Path(tmp)))
                stack.enter_context(patch.object(collect, 'check', return_value={'host_baseline': {}}))
                stack.enter_context(patch.object(collect.sys, 'platform', 'darwin'))
                stack.enter_context(patch.object(collect.os, 'geteuid', return_value=0))
                stack.enter_context(patch.object(collect.os, 'chown'))
                stack.enter_context(patch.object(host_state, 'snapshot', return_value={'kind': kind}))
                backend = stack.enter_context(patch.object(collect, 'load_engine', side_effect=AssertionError('禁止USB')))
                result = collect.execute(True)
                self.assertFalse(result['execution_succeeded'])
                backend.assert_not_called()

    @unittest.skipUnless((ROOT / 'run-collect.command').exists(), '只在封包运行Terminal批准门槛')
    def test_actual_launcher_without_approval_exits_before_sudo(self):
        with tempfile.TemporaryDirectory() as tmp:
            marker = Path(tmp) / 'called'
            fake = Path(tmp) / 'sudo'
            fake.write_text('#!/bin/sh\nprintf called > "' + str(marker) + '"\nexit 99\n')
            fake.chmod(0o700)
            environment = dict(os.environ, PATH=tmp + os.pathsep + os.environ.get('PATH', ''))
            result = subprocess.run(['/bin/bash', str(ROOT / 'run-collect.command')], capture_output=True,
                                    text=True, env=environment, timeout=30)
            self.assertEqual(result.returncode, 2, result.stdout + result.stderr)
            self.assertIn('approval.json', result.stderr)
            self.assertFalse(marker.exists())
            self.assertFalse((ROOT / 'ATTEMPT_LOCK').exists())
            self.assertFalse((ROOT / 'result').exists())


if __name__ == '__main__':
    unittest.main()
