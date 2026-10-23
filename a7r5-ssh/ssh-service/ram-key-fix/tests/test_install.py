"""无相机、无SSH服务的契约与安装协议失败路径。"""
import base64
import contextlib
import io
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
PACKAGE=ROOT if (ROOT/'config.json').exists() else ROOT/'packages/ram-key-install-20261021-01'
sys.path.insert(0,str(PACKAGE))
import install_operation as install
import policy,runner,native_validation as native
from transport import HEADER
RUN=json.loads((PACKAGE/'config.json').read_text())['run_id']
FIELDS=[b'ecdsa-sha2-nistp256',b'nistp256',b'\x04'+b'\x01'*64]
PUBLIC=b'ecdsa-sha2-nistp256 '+base64.b64encode(b''.join(struct.pack('>I',len(v))+v for v in FIELDS))+b'\n'
BANNER=b'SSH-2.0-OpenSSH_7.9p1\r\n'


def metadata():
    return (f'A7R5_RAM_HOSTKEY1 {RUN} stage=0 errno=0 verified=1 source_mode=100755 source_uid=0 source_gid=0 source_bytes=505 '
            'dest_mode=100600 dest_uid=0 dest_gid=0 dest_bytes=505 dest_tmpfs=1 source_unchanged=1 partial_removed=0 private_key_logged=0\n').encode()


class Driver:
    def __init__(self,op,fault=''):
        self.op,self.fault=op,fault;self.commands=[];self.paths=[];self.writes=[];self.debugs=0;self.beats=0;self.state_reads=0
        self.selected='';self.reply=b''
        self.files={'/version.txt':(PACKAGE/'proof/device/session/version.bin').read_bytes(),'/etc/ld.so.preload':policy.NEUTRAL,
                    '/tmp/jiritsu/a7r5-'+policy.PREDECESSOR+'.state':(PACKAGE/'proof/device/session/state-repeat.bin').read_bytes()}
        if fault=='baseline':self.files['/etc/ld.so.preload']=b'unknown\n'
        if fault=='reused':self.files[op.prefix+'.state']=b'old-state'
    def write(self,packet):
        self.op.guard_packet(packet)
        _,fn,seq,*_=HEADER.unpack_from(packet);body=packet[HEADER.size:];cmd=struct.unpack_from('<HH',body)[1]
        self.commands.append(cmd);data=b'';code=0
        if cmd==15:self.selected=body[5:-1].decode().replace('/tmp/jiritsu/../..','',1);self.paths.append(self.selected)
        elif cmd==16:
            self.writes.append(self.selected);self.files[self.selected]=body[7:]
            if self.fault=='upload_transport':raise OSError('离线上传失败')
        elif cmd==5:
            self.debugs+=1
            if self.fault=='debug_transport':raise OSError('离线DEBUG失败')
            text=(f'A7R5_PRIVATE_LAUNCH {RUN} READY\nA7R5_SERVICE_STAGED_AUTOSTART_DISABLED\n').encode()
            self.files[self.op.prefix+'.output']=text
            self.files[self.op.prefix+'.state']=f'A7R5-ROOT-1 {RUN} DONE 0 uid=0 euid=0 bytes={len(text)}\n'.encode()
            self.files['/etc/ld.so.preload']=policy.NEUTRAL
            self.files[self.op.ram+'/hostkey-copy']=metadata()
            self.files[self.op.ram+'/ready']=(f'A7R5_PRIVATE_READY {RUN} parent=101 child=303 uid=0 euid=0 ttl=0 parent_unchanged=1 private_account_changed=1 parent_ns=mnt:[1] child_ns=mnt:[2] host_public_sha={policy.digest(PUBLIC)}\n').encode()
            self.files[self.op.ram+'/host-public-key']=PUBLIC
            self.files[self.op.ram+'/banner']=BANNER
            self.files[self.op.ram+'/started']=(f'A7R5_WILDCARD_STARTED {RUN} pid=404 bind=0.0.0.0:2222 listener_observed=1 banner_sha={policy.digest(BANNER)}\n').encode()
            if self.fault=='copy_failed':
                self.files[self.op.prefix+'.state']=self.files[self.op.prefix+'.state'].replace(b'DONE 0',b'DONE 68')
                self.files[self.op.ram+'/child-result']=b'PRIVATE_RESULT code=109\n'
            if self.fault=='key_mode':self.files[self.op.ram+'/hostkey-copy']=metadata().replace(b'dest_mode=100600',b'dest_mode=100755')
            if self.fault=='namespace':self.files[self.op.ram+'/ready']=self.files[self.op.ram+'/ready'].replace(b'child_ns=mnt:[2]',b'child_ns=mnt:[1]')
        elif cmd==17:
            if self.selected==self.op.ram+'/heartbeat':
                self.beats+=1
                self.files[self.selected]=(f'A7R5_PRIVATE_ALIVE {RUN} parent=101 child=303 ttl=0 elapsed_ms={1000 if self.fault=="frozen" else self.beats*1000} parent_unchanged=1\n').encode()
            if self.selected not in self.files:code=0x10000006
            else:data=self.files[self.selected]
            if self.selected==self.op.prefix+'.service-helper' and self.fault=='readback' and self.writes:data=b'bad'
            if self.debugs and self.selected=='/etc/ld.so.preload' and self.fault=='neutral':data=self.op.arm
            if self.debugs and self.selected==self.op.prefix+'.state':
                self.state_reads+=1
                if self.fault=='changed_state' and self.state_reads==2:data+=b'changed'
                if self.fault=='running_forever':data=f'A7R5-ROOT-1 {RUN} RUNNING 0 uid=0 euid=0 bytes=0\n'.encode()
        else:raise AssertionError(cmd)
        response=struct.pack('<I',code)+data
        self.reply=HEADER.pack(len(response),fn,seq+(self.fault=='sequence'),3,1,2,0)+response
        return len(packet)-(self.fault=='short_write')
    def read(self,n):
        value,self.reply=self.reply[:n],self.reply[n:];return value


class CopyContract(unittest.TestCase):
    def test_source_755_copy_and_failure_paths_under_sanitizers(self):
        cases=('success','short_write','dir_mode','missing','symlink','fifo','writable','owner','oversize','not_ram',
               'collision','destination_symlink','chmod','chmod_ignored','read','disk_full','race','corrupt')
        with tempfile.TemporaryDirectory() as tmp:
            binary=Path(tmp)/'contract'
            source=PACKAGE/'test-sources/ssh-service/ram-key-fix/tests/test_private_hostkey.c'
            command=['/usr/bin/clang','-std=c11','-D_DARWIN_C_SOURCE','-Wall','-Wextra','-Werror','-Wno-unused-function',
                     '-O1','-g','-fsanitize=address,undefined','-fno-omit-frame-pointer',str(source),'-o',str(binary)]
            compiled=subprocess.run(command,capture_output=True,text=True,timeout=30)
            self.assertEqual(compiled.returncode,0,compiled.stderr)
            for case in cases:
                with self.subTest(case=case),tempfile.TemporaryDirectory() as fixture:
                    value=subprocess.run([str(binary),str(Path(fixture).resolve()),case],capture_output=True,text=True,timeout=5)
                    self.assertEqual(value.returncode,0,value.stdout+value.stderr)
                    self.assertNotIn('SYNTHETIC_PRIVATE_KEY_BYTES_NOT_FOR_LOGS',value.stdout)

    def test_legacy_755_reproduces_109(self):
        with tempfile.TemporaryDirectory() as tmp:
            binary=Path(tmp)/'legacy';source=PACKAGE/'proof/key-copy/tests/reproduce_legacy.c'
            subprocess.run(['/usr/bin/clang','-Wall','-Wextra','-Werror',str(source),'-o',str(binary)],check=True,capture_output=True)
            value=subprocess.run([str(binary)],capture_output=True,text=True)
            self.assertEqual(value.returncode,1);self.assertIn('code=109 permission_rejection=1',value.stdout)

    def test_material_configuration_uses_only_private_ram_hostkey(self):
        text=(PACKAGE/'materials/config.h').read_text()
        configuration=json.loads(re.search(r'^#define SSH_CONFIG (".*")$',text,re.M)[1])
        self.assertEqual([line for line in configuration.splitlines() if line.startswith('HostKey ')],
                         ['HostKey /var/run/a7r5-ssh-'+RUN+'/host_ecdsa'])
        for value in ('PermitTTY yes','Subsystem sftp internal-sftp','ListenAddress 0.0.0.0','AllowTcpForwarding no'):
            self.assertIn(value,configuration.splitlines())
        self.assertNotIn('ForceCommand ',configuration);self.assertIn('#define SSH_SECONDS 0\n',text)
        stage=(PACKAGE/'materials/stage.sh').read_text()
        self.assertNotIn('enable-autostart',stage);self.assertNotIn('/enabled',stage)
        self.assertIn('private_hostkey_copy',(PACKAGE/'materials/sources/launcher.c').read_text())

    def test_metadata_receipt_fails_closed(self):
        self.assertEqual(policy.hostkey_receipt(metadata(),RUN)['destination_mode'],'0o100600')
        for a,b in [(b'dest_mode=100600',b'dest_mode=100755'),(b'dest_tmpfs=1',b'dest_tmpfs=0'),
                    (b'verified=1',b'verified=0'),(b'dest_bytes=505',b'dest_bytes=504'),(b'private_key_logged=0',b'private_key_logged=1')]:
            with self.subTest(field=a),self.assertRaises(ValueError):policy.hostkey_receipt(metadata().replace(a,b),RUN)


class Protocol(unittest.TestCase):
    def test_install_success_and_failure_gates(self):
        for fault in ('','baseline','reused','sequence','short_write','upload_transport','readback','debug_transport',
                      'key_mode','copy_failed','namespace','frozen','neutral','changed_state','running_forever'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                out=Path(tmp);op=install.InstallOperation(out,PACKAGE);driver=Driver(op,fault);report={}
                with patch.object(install.time,'sleep'):
                    if not fault:
                        op(driver,out,lambda *a,**kw:None,report)
                        self.assertTrue(op.safe_to_stop);self.assertTrue(report['ram_hostkey_verified'])
                        self.assertEqual(len(driver.writes),6);self.assertEqual(driver.debugs,1)
                    else:
                        with self.assertRaises((ValueError,OSError,TimeoutError)):op(driver,out,lambda *a,**kw:None,report)
                        self.assertFalse(op.safe_to_stop)
                self.assertLessEqual(driver.debugs,1)
                self.assertFalse(any('host_ecdsa' in path or '/enabled' in path or '/dev/' in path for path in driver.paths))
                if fault in ('baseline','reused','sequence','short_write'):self.assertEqual(driver.writes,[])
                if fault in ('upload_transport','readback'):self.assertEqual(driver.debugs,0)
                if fault=='copy_failed':
                    self.assertTrue((out/'failure-hostkey-copy.bin').exists())
                    self.assertTrue((out/'failure-child-result.bin').exists())
                    self.assertEqual(driver.paths[-1],op.ram+'/diagnostic')

    def test_failed_receipt_persistence_never_permits_stop(self):
        with tempfile.TemporaryDirectory() as tmp:
            op=install.InstallOperation(Path(tmp),PACKAGE);driver=Driver(op)
            original=Path.write_text
            def fail(path,*args,**kw):
                if path.name=='assessment.json':raise OSError('回执无法保存')
                return original(path,*args,**kw)
            with patch.object(Path,'write_text',fail),patch.object(install.time,'sleep'):
                with self.assertRaises(OSError):op(driver,Path(tmp),lambda *a,**kw:None,{})
            self.assertFalse(op.safe_to_stop)


class NativeClient(unittest.TestCase):
    def fixture(self,root):
        (root/'host-public-key').write_bytes(PUBLIC)
        return dict(run_id=RUN,target_ip='10.10.10.177'),dict(protocol_gate_passed=True,host_recovery_verified=True,
                     service_stop_attempts=1,host_public_sha256=policy.digest(PUBLIC))
    def test_terminal_and_scp_contract_without_running_ssh(self):
        for fault in ('','tty','upload','download','bad_bytes','wrong_uid','no_pty'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve();op,report=self.fixture(root);calls=[]
                def client(command,stdin,env):
                    stage=('tty','upload','download')[len(calls)];calls.append(stage)
                    for flag in ('StrictHostKeyChecking=yes','PubkeyAuthentication=no','NumberOfPasswordPrompts=1','ConnectionAttempts=1'):
                        self.assertIn(flag,command)
                    self.assertNotIn('-O',command)
                    self.assertEqual(Path(env['A7R5_PASSWORD_FILE']).stat().st_mode&0o777,0o600)
                    if fault==stage:return 255,b'',b'failed'
                    if stage=='tty':
                        raw=f'\nA7R5_SERVICE_TTY {RUN}\nUid:\t0\t0\t0\t0\nGid:\t0\t0\t0\t0\n'.encode()
                        if fault=='wrong_uid':raw=raw.replace(b'Uid:\t0',b'Uid:\t1')
                        if fault=='no_pty':raw=raw.replace(b'A7R5_SERVICE_TTY',b'NO_TTY')
                        return 0,raw,b''
                    if stage=='download':Path(command[-1]).write_bytes(b'bad' if fault=='bad_bytes' else bytes(range(256))*256)
                    return 0,b'',b''
                if not fault:
                    native.verify(op,root,root,report,'12345678',runner=client)
                    self.assertTrue(report['real_pty_verified']);self.assertTrue(report['scp_roundtrip_verified'])
                else:
                    with self.assertRaises(ValueError):native.verify(op,root,root,report,'12345678',runner=client)
                self.assertLessEqual(len(calls),3)
    def test_recovery_or_trusted_key_failure_blocks_clients(self):
        for fault in ('recovery','key'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp);op,report=self.fixture(root)
                if fault=='recovery':report['host_recovery_verified']=False
                else:report['host_public_sha256']='0'*64
                with patch.object(native,'run_bounded',side_effect=AssertionError('禁止SSH客户端')) as client:
                    with self.assertRaises((ValueError,PermissionError)):native.verify(op,root,root,report,'12345678',runner=client)
                    client.assert_not_called()


class Approval(unittest.TestCase):
    def test_check_and_no_approval_precedes_all_device_io(self):
        with patch.object(runner,'HERE',PACKAGE),patch.object(runner.host_state,'snapshot',side_effect=AssertionError('禁止主机枚举')):
            runner.check(False)
            with self.assertRaises((ValueError,OSError,PermissionError)):runner.check(True)
            with self.assertRaises(PermissionError):runner.execute(False)
        self.assertFalse((PACKAGE/'ATTEMPT_LOCK').exists());self.assertFalse((PACKAGE/'result').exists())
    def test_terminal_refuses_before_sudo(self):
        with tempfile.TemporaryDirectory() as tmp:
            sudo=Path(tmp)/'sudo';sudo.write_text('#!/bin/sh\necho SUDO_MUST_NOT_RUN\nexit 99\n');sudo.chmod(0o700)
            value=subprocess.run(['/bin/bash',str(PACKAGE/'run-install-once.command')],capture_output=True,text=True,
                env=dict(os.environ,PATH=tmp+':/usr/bin:/bin',PYTHONDONTWRITEBYTECODE='1'))
            self.assertEqual(value.returncode,2);self.assertNotIn('SUDO_MUST_NOT_RUN',value.stdout)


class WrapperAndApproval(unittest.TestCase):
    def test_wrong_approval_used_lock_and_material_tamper_fail_before_device(self):
        manifest=json.loads((PACKAGE/'operation.json').read_text())
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();(root/'materials').mkdir()
            (root/'config.json').write_bytes((PACKAGE/'config.json').read_bytes())
            data=(PACKAGE/'materials/config.h').read_bytes();(root/'materials/config.h').write_bytes(data)
            fixed=dict(policy=runner.metadata(),directory=str(root),dependencies={},credential_path=manifest['credential_path'],
                       openssl=manifest['openssl'],files={'materials/config.h':dict(bytes=len(data),sha256=policy.digest(data))})
            runner.save(root/'operation.json',fixed)
            approval=dict(accepted=False,operation_sha256=policy.digest((root/'operation.json').read_bytes()),risk=policy.RISK)
            runner.save(root/'approval.json',approval)
            with patch.object(runner,'HERE',root),patch.object(runner.host_state,'snapshot',side_effect=AssertionError('禁止设备')):
                with self.assertRaises(PermissionError):runner.check(True)
                approval['accepted']=True;runner.save(root/'approval.json',approval);runner.check(True)
                (root/'ATTEMPT_LOCK').mkdir()
                with self.assertRaises(FileExistsError):runner.check(True)
                (root/'materials/config.h').write_bytes(data+b'changed')
                with self.assertRaises(ValueError):runner.check(False)

    def test_host_recovery_and_installation_gates_control_network_and_success(self):
        manifest=json.loads((PACKAGE/'operation.json').read_text())
        ordinary=dict(manifest['host_baseline'],kind='ordinary')
        for initial,session_ok,recovered,network_ok in [(dict(kind='service'),True,True,True),
                (ordinary,False,True,True),(ordinary,True,False,True),(ordinary,True,True,False),(ordinary,True,True,True)]:
            with self.subTest(initial=initial['kind'],session_ok=session_ok,recovered=recovered,network_ok=network_ok),tempfile.TemporaryDirectory() as tmp:
                root=Path(tmp).resolve();(root/'config.json').write_bytes((PACKAGE/'config.json').read_bytes())
                secret=root/'credential';secret.write_text('12345678\n');secret.chmod(0o600)
                op=dict(manifest,credential_path=str(secret));calls=[]
                report=dict(protocol_gate_passed=session_ok,service_stop_attempts=int(session_ok),fixed_writes_attempted=6,debug_attempts=1)
                if not session_ok:report['failure']='安装门槛失败'
                def client(op,directory,output,value,password):
                    calls.append('client')
                    if not network_ok:raise TimeoutError('离线模拟网络失败')
                    value.update(real_pty_verified=True,scp_roundtrip_verified=True,mac_network_connections=3)
                with patch.object(runner,'HERE',root),patch.object(runner,'check',return_value=op),patch.object(runner.os,'geteuid',return_value=0), \
                        patch.object(runner.host_state,'snapshot',return_value=initial), \
                        patch.object(runner.host_state,'observe',return_value=dict(recovered=recovered)), \
                        patch.object(runner,'InstallOperation'),patch.object(runner,'load_engine',return_value=lambda *a,**kw:report) as load, \
                        patch.object(runner.native_validation,'verify',side_effect=client):
                    result=runner.execute(True)
                expected=initial['kind']=='ordinary' and session_ok and recovered
                self.assertEqual(bool(calls),expected)
                self.assertEqual(result['execution_succeeded'],expected and network_ok)
                if initial['kind']!='ordinary':load.assert_not_called()
                if initial['kind']=='ordinary' and not session_ok:self.assertIn('安装门槛失败',result['failure'])
                self.assertTrue(result['screen_confirmation_pending'])


STOP=(0x43,1,0xc800,0x2855,b'')

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
            op=install.InstallOperation(out,PACKAGE)
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
            stack.enter_context(patch.object(install.time,'sleep'))
            with contextlib.redirect_stdout(io.StringIO()): report=self.run_session(out,'libusb',_operation=op)
            events=[json.loads(row) for row in (out/'events.jsonl').read_text().splitlines()]
            return report,state,normal,service,driver,claim.call_count,events

    def test_two_phase_authentication_probe_and_single_stop_including_pipe_error(self):
        for pipe in (False,True):
            with self.subTest(pipe=pipe):
                report,state,normal,service,driver,claims,events=self.simulate(pipe=pipe)
                self.assertTrue(report['protocol_gate_passed'])
                self.assertEqual(normal.auth_commands,[1,3,1,3,1,3,5])
                self.assertEqual(service.auth_commands,normal.auth_commands)
                self.assertEqual(state['controls'].count(STOP),1)
                self.assertEqual(claims,2)
                self.assertEqual(report['fixed_writes_attempted'],6)
                self.assertEqual(report['debug_attempts'],1)
                self.assertEqual(len([e for e in events if e['event']=='response_header']),len(driver.commands))

    def test_authentication_fingerprint_protocol_or_final_gate_failure_never_sends_stop(self):
        for options in (dict(bad_auth=0x0e0a),dict(bad_auth=0x0336),dict(bad_interface=True),
                        dict(fault='baseline'),dict(fault='debug_transport'),dict(fault='neutral'),dict(fault='running_forever')):
            with self.subTest(options=options):
                report,state,*_=self.simulate(**options)
                self.assertIn('failure',report)
                self.assertEqual(state['controls'].count(STOP),0)

    def test_engine_cannot_run_without_fixed_operation(self):
        with patch.object(self.usb.core,'find',side_effect=AssertionError('禁止USB')):
            for backend,op in [('libusb',None),('native-host',object())]:
                with self.assertRaises(PermissionError): self.run_session(Path('/never-created'),backend,_operation=op)


if __name__=='__main__':unittest.main()
