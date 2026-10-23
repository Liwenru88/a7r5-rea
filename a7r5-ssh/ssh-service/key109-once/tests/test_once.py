"""无设备失败路径与完整协议集成；不得枚举真实USB。"""
import contextlib
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import operation
import policy
import runner
from transport import HEADER, READ, DEBUG

PACKAGE = ROOT if (ROOT / 'config.json').exists() else ROOT / 'packages/key109-once-20261021-01'
STOP = (0x43, 1, 0xc800, 0x2855, b'')


def output(mode='100644', uid=0, rc=0, error=0, mask=8):
    return (f'KEY109_BEGIN1 run={policy.TARGET}\n'
            f'KEY109_META1 run={policy.TARGET} label=install rc=0 errno=0 valid=1 mode=40755 uid=0 gid=0 size=4096 private_policy=0 reject_mask=0\n'
            f'KEY109_META1 run={policy.TARGET} label=private rc={rc} errno={error} valid={int(rc == 0)} mode={mode} uid={uid} gid=0 size={0 if rc else 227} private_policy=1 reject_mask={mask}\n'
            f'KEY109_END1 run={policy.TARGET} samples=2 key_content_read=0 key_writes=0 ssh_started=0\n').encode()


class Driver:
    def __init__(self, op, fault='', probe_output=None, pending=0):
        self.op, self.fault, self.pending = op, fault, pending
        self.probe_output = output() if probe_output is None else probe_output
        self.files = {'/version.txt': (PACKAGE / 'proof/device/session/version.bin').read_bytes(),
                      '/etc/ld.so.preload': policy.NEUTRAL,
                      '/tmp/jiritsu/a7r5-' + policy.TARGET + '.state': policy.OLD_STATE}
        self.commands, self.paths, self.writes = [], [], []
        self.reply, self.selected, self.debugs, self.state_reads = b'', '', 0, 0
        if fault == 'version': self.files['/version.txt'] = b'other'
        if fault == 'baseline': self.files['/etc/ld.so.preload'] = b'unknown.so\n'
        if fault == 'old': self.files['/tmp/jiritsu/a7r5-' + policy.TARGET + '.state'] = b'other\n'
        if fault == 'reused': self.files[op.prefix + '.state'] = b'old result'

    def write(self, packet):
        self.op.guard_packet(packet)
        size, fun, seq, *meta = HEADER.unpack_from(packet)
        body = packet[HEADER.size:]
        cmd = struct.unpack_from('<HH', body)[1]
        self.commands.append(cmd)
        payload, code = b'', 0
        if cmd == 15:
            self.selected = body[5:-1].decode().replace('/tmp/jiritsu/../..', '', 1)
            self.paths.append(self.selected)
        elif cmd == 17:
            if self.selected not in self.files:
                code = 0x10000006
            else:
                payload = self.files[self.selected]
            if self.debugs and self.selected == self.op.prefix + '.state':
                self.state_reads += 1
                if self.state_reads <= self.pending:
                    payload, code = b'', 0x10000006
                if self.fault == 'never_done':
                    payload = f'A7R5-ROOT-1 {self.op.run} RUNNING 0 uid=0 euid=0 bytes=0\n'.encode()
                if self.fault == 'changed_state' and self.state_reads == 2:
                    payload += b'changed'
                if self.fault == 'wrong_uid': payload = payload.replace(b'uid=0', b'uid=1', 1)
                if self.fault == 'failed': payload = payload.replace(b'DONE 0', b'DONE 1')
            if self.debugs and self.selected == '/etc/ld.so.preload' and self.fault == 'late_preload':
                payload = self.op.arm
            if self.selected == self.op.prefix + '.probe' and self.fault == 'readback' and self.writes:
                payload = b'changed'
            if self.selected == '/etc/ld.so.preload' and self.fault == 'arm_readback' and self.writes:
                payload = policy.NEUTRAL
        elif cmd == 16:
            self.writes.append((self.selected, body[7:]))
            self.files[self.selected] = body[7:]
            if self.fault == 'upload_transport': raise OSError('离线上传传输失败')
        elif cmd == 5:
            self.debugs += 1
            if self.fault == 'debug_transport': raise OSError('离线DEBUG传输失败')
            self.files['/etc/ld.so.preload'] = policy.NEUTRAL
            self.files[self.op.prefix + '.output'] = self.probe_output
            n = len(self.probe_output) + (self.fault == 'size')
            self.files[self.op.prefix + '.state'] = f'A7R5-ROOT-1 {self.op.run} DONE 0 uid=0 euid=0 bytes={n}\n'.encode()
        else:
            raise AssertionError('不允许的命令')
        response = struct.pack('<I', code) + payload
        header = HEADER.pack(len(response), fun, seq + (self.fault == 'sequence'), 3, 1, 2, 0)
        if self.fault == 'header_short': header = header[:-1]
        if self.fault == 'status': header = HEADER.pack(len(response), fun, seq, 0, 0, 0, 1)
        self.reply = header + response
        return len(packet) - (self.fault == 'short_write')

    def read(self, size):
        if self.fault == 'header_short': return self.reply[:HEADER.size - 1]
        if self.fault == 'body_empty' and size != HEADER.size: return b''
        value, self.reply = self.reply[:size], self.reply[size:]
        return value


class MetadataContract(unittest.TestCase):
    def test_policy_rejection_is_useful_diagnostic_not_failed_execution(self):
        for args, mask in [({}, 8), ({'mode':'100600','mask':0},0),
                           ({'mode':'0','rc':-1,'error':2,'mask':1},1),
                           ({'mode':'120777','uid':123,'mask':14},14)]:
            with self.subTest(args=args):
                self.assertEqual(policy.parse_output(output(**args))['metadata']['private']['reject_mask'], mask)

    def test_no_extra_secret_lines_wrong_target_or_contradictory_metadata(self):
        raw = output()
        for bad in [raw + b'PRIVATE KEY\n', raw.replace(policy.TARGET.encode(), b'0'*32, 1),
                    raw.replace(b'errno=0 valid=1',b'errno=30 valid=1'),
                    raw.replace(b'reject_mask=8',b'reject_mask=0'), raw[:-1],
                    output(rc=-1,error=2,mask=1), raw.replace(b'uid=0 gid=0',b'uid=4294967296 gid=0'),
                    raw.replace(b'key_content_read=0',b'key_content_read=1')]:
            with self.subTest(bad=bad[-80:]), self.assertRaises(ValueError): policy.parse_output(bad)


class Protocol(unittest.TestCase):
    def run_operation(self, fault='', probe_output=None, pending=0):
        with tempfile.TemporaryDirectory() as tmp:
            op = operation.Operation(Path(tmp), PACKAGE)
            driver = Driver(op, fault, probe_output, pending)
            report = {}
            with patch.object(operation.time, 'sleep'):
                try:
                    op(driver, Path(tmp), lambda *a, **kw: None, report)
                except Exception:
                    if not fault and probe_output is None: raise
            assessment = json.loads((Path(tmp) / 'assessment.json').read_text())
            return op, driver, report, assessment

    def test_success_has_only_two_artifacts_one_arm_one_debug_and_no_key_read(self):
        op, driver, report, assessment = self.run_operation(pending=2)
        self.assertTrue(op.safe_to_stop)
        self.assertTrue(assessment['gate_passed'])
        self.assertEqual(assessment['state_observations'], 3)
        self.assertEqual([p for p, raw in driver.writes], [op.prefix+'.probe',op.prefix+'.so','/etc/ld.so.preload'])
        self.assertEqual(driver.debugs, 1)
        self.assertFalse(any('host_ecdsa' in p or '/etc/passwd' in p for p in driver.paths))
        self.assertEqual(driver.files['/etc/ld.so.preload'], policy.NEUTRAL)

    def test_rejections_and_transmission_errors_withhold_stop(self):
        for fault in ('version','baseline','old','reused','sequence','status','header_short','body_empty',
                      'short_write','upload_transport','readback','arm_readback','debug_transport',
                      'never_done','changed_state','wrong_uid','failed','late_preload','size'):
            with self.subTest(fault=fault):
                op, driver, report, assessment = self.run_operation(fault)
                self.assertFalse(op.safe_to_stop)
                self.assertFalse(assessment['gate_passed'])
                self.assertLessEqual(driver.debugs, 1)
                if fault in ('version','baseline','old','reused','sequence','status','header_short','body_empty','short_write'):
                    self.assertEqual(driver.writes, [])
                if fault in ('upload_transport','readback','arm_readback'):
                    self.assertEqual(driver.debugs, 0)
                if fault == 'never_done': self.assertEqual(assessment['state_observations'],16)

    def test_malformed_output_cannot_grant_exit(self):
        for raw in (b'', output()+b'extra\n', output().replace(b'key_writes=0',b'key_writes=1')):
            op, driver, report, assessment = self.run_operation(probe_output=raw)
            self.assertFalse(op.safe_to_stop)

    def test_guard_rejects_unapproved_frame_arbitrary_paths_or_bytes(self):
        with tempfile.TemporaryDirectory() as tmp:
            op = operation.Operation(Path(tmp), PACKAGE)
            for body in [READ, DEBUG, struct.pack('<HH',0x1001,15)+b'\0/tmp/jiritsu/../../etc/passwd\0',
                         struct.pack('<HH',0x1001,16)+b'\0\xff\0unknown']:
                packet = HEADER.pack(len(body),0x40,1,0,0,0,0)+body
                with self.assertRaises(PermissionError): op.guard_packet(packet)
                if body not in (READ,DEBUG):
                    op.permitted_packet = packet
                    with self.assertRaises(PermissionError): op.guard_packet(packet)
                op.permitted_packet = None


class EvidencePersistence(unittest.TestCase):
    def test_failed_local_receipt_save_cannot_authorize_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            op = operation.Operation(Path(tmp), PACKAGE)
            driver = Driver(op)
            with patch.object(operation, 'save', side_effect=OSError('本机回执无法保存')):
                with self.assertRaises(OSError):
                    op(driver, Path(tmp), lambda *a, **kw: None, {})
            self.assertFalse(op.safe_to_stop)


class Interface(list):
    def __init__(self, raw):
        super().__init__(SimpleNamespace(bEndpointAddress=e['address'],bmAttributes=e['attributes'],
                                        wMaxPacketSize=e['max_packet'],bInterval=e['interval']) for e in raw['endpoints'])
        for source, target in [('number','bInterfaceNumber'),('alternate','bAlternateSetting'),
                               ('interface_class','bInterfaceClass'),('subclass','bInterfaceSubClass'),('protocol','bInterfaceProtocol')]:
            setattr(self,target,raw[source])


class Device:
    bus, port_numbers, idVendor, iProduct = 0, (1,), 0x054c, 1
    def __init__(self, pid, state, driver, fingerprint):
        self.idProduct, self.state, self.driver = pid, state, driver
        self.fingerprint, self.auth_commands, self.auth_reply = fingerprint, [], b''
    def get_active_configuration(self):
        raw = Interface(self.fingerprint)
        class Configuration:
            bConfigurationValue=1
            def __getitem__(self,key):
                assert key == (0,0)
                return raw
        return Configuration()
    def is_kernel_driver_active(self,n): return False
    def write(self, ep, raw, timeout):
        assert ep == 2
        if len(raw) == 516:
            command, salt = struct.unpack_from('>HH',raw)
            command = ~command & 0xffff
            self.auth_commands.append(command)
            result = 99 if self.state.get('bad_auth') == self.idProduct else {1:8,3:4,5:6}[command]
            self.auth_reply = struct.pack('>HH512s',~result & 0xffff,0,b'\x01' if result == 6 else b'challenge')
            return len(raw)
        return self.driver.write(raw)
    def read(self, ep,n,timeout):
        assert ep == 129
        if n == 516 and self.auth_reply:
            value,self.auth_reply=self.auth_reply,b''
            return value
        return self.driver.read(n)
    def ctrl_transfer(self,*args,timeout):
        self.state['controls'].append(args)
        if args == STOP:
            self.state['mode']='normal'
            if self.state.get('pipe'): raise OSError('离线Pipe error')
        else:
            assert args == (0x43,1,0x37ff,0xd7aa,b'')
            self.state['mode']='service'
        return 0


class FullSession(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        manifest=json.loads((PACKAGE/'operation.json').read_text())
        with patch.object(runner,'HERE',PACKAGE): cls.run_session=staticmethod(runner.load_engine(manifest))
        from system_dump import session
        cls.session=session
        import usb.core, usb.util, usb.backend.libusb1
        cls.usb=SimpleNamespace(core=usb.core,util=usb.util,backend=usb.backend.libusb1)

    def simulate(self,fault='',bad_auth=0,pipe=False,bad_interface=False):
        with tempfile.TemporaryDirectory() as tmp, contextlib.ExitStack() as stack:
            out=Path(tmp)/'session'
            op=operation.Operation(out,PACKAGE)
            driver=Driver(op,fault)
            state=dict(mode='normal',controls=[],pipe=pipe,bad_auth=bad_auth)
            normal=Device(0x0e0a,state,driver,op.config['interfaces']['interface-1.json'])
            service=Device(0x0336,state,driver,op.config['interfaces']['interface-2.json'])
            if bad_interface:
                service.fingerprint = dict(service.fingerprint, protocol=1)
            stack.enter_context(patch.object(self.usb.core,'find',side_effect=lambda **kw:[normal if state['mode']=='normal' else service]))
            stack.enter_context(patch.object(self.usb.backend,'get_backend',return_value=object()))
            stack.enter_context(patch.object(self.usb.util,'get_string',return_value='ILCE-7RM5'))
            claim=stack.enter_context(patch.object(self.usb.util,'claim_interface'))
            for name in ('release_interface','dispose_resources'):
                stack.enter_context(patch.object(self.usb.util,name))
            stack.enter_context(patch.object(self.session,'unmount_camera'))
            stack.enter_context(patch.object(operation.time,'sleep'))
            with contextlib.redirect_stdout(io.StringIO()): report=self.run_session(out,'libusb',_operation=op)
            events=[json.loads(row) for row in (out/'events.jsonl').read_text().splitlines()]
            return report,state,normal,service,driver,claim.call_count,events

    def test_two_phase_authentication_probe_and_single_stop_including_pipe_error(self):
        for pipe in (False,True):
            with self.subTest(pipe=pipe):
                report,state,normal,service,driver,claims,events=self.simulate(pipe=pipe)
                self.assertTrue(report['metadata_probe_completed'])
                self.assertEqual(normal.auth_commands,[1,3,1,3,1,3,5])
                self.assertEqual(service.auth_commands,normal.auth_commands)
                self.assertEqual(state['controls'].count(STOP),1)
                self.assertEqual(claims,2)
                self.assertEqual(report['fixed_writes_attempted'],3)
                self.assertEqual(report['debug_attempts'],1)
                self.assertEqual(len([e for e in events if e['event']=='response_header']),len(driver.commands))

    def test_authentication_fingerprint_protocol_or_final_gate_failure_never_sends_stop(self):
        for options in (dict(bad_auth=0x0e0a),dict(bad_auth=0x0336),dict(bad_interface=True),
                        dict(fault='baseline'),dict(fault='debug_transport'),dict(fault='late_preload'),dict(fault='never_done')):
            with self.subTest(options=options):
                report,state,*_=self.simulate(**options)
                self.assertIn('failure',report)
                self.assertEqual(state['controls'].count(STOP),0)

    def test_engine_cannot_run_without_fixed_operation(self):
        with patch.object(self.usb.core,'find',side_effect=AssertionError('禁止USB')):
            for backend,op in [('libusb',None),('native-host',object())]:
                with self.assertRaises(PermissionError): self.run_session(Path('/never-created'),backend,_operation=op)


class Authorization(unittest.TestCase):
    def test_pack_check_no_device_or_approval_is_created(self):
        with patch.object(runner,'HERE',PACKAGE), patch.object(runner.host_state,'snapshot',side_effect=AssertionError('禁止主机枚举')):
            runner.check(False)
            with self.assertRaises((OSError,PermissionError,ValueError)): runner.check(True)
            with self.assertRaises(PermissionError): runner.execute(False)
        self.assertFalse((PACKAGE/'ATTEMPT_LOCK').exists())
        self.assertFalse((PACKAGE/'result').exists())

    def test_terminal_rejects_unapproved_before_sudo(self):
        with tempfile.TemporaryDirectory() as tmp:
            fake=Path(tmp)/'sudo'
            fake.write_text('#!/bin/sh\necho SHOULD_NOT_RUN\nexit 99\n')
            fake.chmod(0o700)
            value=subprocess.run(['/bin/bash',str(PACKAGE/'run-key109-once.command')],capture_output=True,text=True,
                                 env=dict(os.environ,PATH=tmp+':/usr/bin:/bin',PYTHONDONTWRITEBYTECODE='1'))
            self.assertEqual(value.returncode,2)
            self.assertNotIn('SHOULD_NOT_RUN',value.stdout)

    def test_wrong_approval_changed_material_and_used_lock_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            target=Path(tmp).resolve()
            (target/'material').write_bytes(b'original')
            manifest=dict(policy=runner.metadata(),directory=str(target),dependencies={},files={
                'material':dict(bytes=8,sha256=policy.digest(b'original'))})
            runner.save(target/'operation.json',manifest)
            approval=dict(accepted=True,operation_sha256=policy.digest((target/'operation.json').read_bytes()),risk=policy.RISK)
            with patch.object(runner,'HERE',target):
                runner.save(target/'approval.json',dict(approval,accepted=False))
                with self.assertRaises(PermissionError): runner.check(True)
                runner.save(target/'approval.json',approval)
                runner.check(True)
                (target/'ATTEMPT_LOCK').mkdir()
                with self.assertRaises(FileExistsError): runner.check(True)
                (target/'material').write_bytes(b'changed!')
                with self.assertRaises(ValueError): runner.check(False)


class HostWrapper(unittest.TestCase):
    def test_host_gate_precedes_engine_and_guest_failure_is_never_hidden_by_recovery(self):
        manifest = json.loads((PACKAGE/'operation.json').read_text())
        ordinary = dict(manifest['host_baseline'], kind='ordinary')
        for initial, session_ok, recovered in [(dict(kind='service'),True,True),
                                                (ordinary,False,True),(ordinary,True,False),(ordinary,True,True)]:
            with self.subTest(initial=initial['kind'],session_ok=session_ok,recovered=recovered), tempfile.TemporaryDirectory() as tmp:
                target=Path(tmp).resolve()
                (target/'config.json').write_bytes((PACKAGE/'config.json').read_bytes())
                report=dict(metadata_probe_completed=session_ok,service_stop_attempts=int(session_ok),
                            fixed_writes_attempted=3,debug_attempts=1,
                            first_authentication_passed=True,second_authentication_passed=True)
                if not session_ok: report['failure']='固定输出门槛失败'
                with patch.object(runner,'HERE',target), patch.object(runner,'check',return_value=manifest), \
                        patch.object(runner.os,'geteuid',return_value=0), \
                        patch.object(runner.host_state,'snapshot',return_value=initial), \
                        patch.object(runner.host_state,'observe',return_value=dict(recovered=recovered)) as observe, \
                        patch.object(runner,'Operation'), \
                        patch.object(runner,'load_engine',return_value=lambda *a,**kw:report) as load:
                    result=runner.execute(True)
                self.assertEqual(result['execution_succeeded'],initial['kind']=='ordinary' and session_ok and recovered)
                if initial['kind']!='ordinary':
                    load.assert_not_called()
                    observe.assert_not_called()
                elif not session_ok:
                    self.assertIn('固定输出门槛失败',result['failure'])
                self.assertTrue(result['screen_confirmation_pending'])


if __name__=='__main__': unittest.main()
