"""真实受限协议编码+内存设备；所有设备/网络执行均由替身阻断。"""
import base64
import hashlib
import importlib
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

BASE=Path(__file__).resolve().parents[1]
MODULES=BASE/'runtime' if (BASE/'runtime').is_dir() else BASE
sys.path[:0]=[str(MODULES),str(BASE.parent)]
import service_dispatch as d
import native_validation as n
import lab
lab.engine()
from system_dump.usb_adapter import HEADER

RUN=d.RUN
fields=[b'ecdsa-sha2-nistp256',b'nistp256',b'\x04'+b'\x01'*64]
PUBLIC=b'ecdsa-sha2-nistp256 '+base64.b64encode(b''.join(struct.pack('>I',len(v))+v for v in fields))+b'\n'
BANNER=b'SSH-2.0-OpenSSH_7.9p1\r\n'
VERSION=(lab.ROOT/'reference/version.bin').read_bytes()


class Protocol(unittest.TestCase):
    def fixture(self,root,fault):
        p=d.paths(RUN);materials=root/'materials';materials.mkdir();mapping={}
        prefix='/tmp/jiritsu/a7r5-'+RUN
        for name,suffix in (('ssh-service.arm64','.service-helper'),('boot-hook.so','.boot-hook.so'),('control.sh','.control.sh'),('stage.sh','.stage.sh'),('root.arm64.so','.so')):
            (materials/name).write_bytes(name.encode());mapping[name]=prefix+suffix
        (materials/'manifest.json').write_text(json.dumps(dict(upload_map=mapping)))
        output=root/'evidence';output.mkdir()
        text=('A7R5_PRIVATE_LAUNCH '+RUN+' READY\nA7R5_SERVICE_STAGED_AUTOSTART_DISABLED\n').encode()
        ready=(f'A7R5_PRIVATE_READY {RUN} parent=101 child=303 uid=0 euid=0 ttl=0 parent_unchanged=1 private_account_changed=1 parent_ns=mnt:[1] child_ns=mnt:[2] host_public_sha={hashlib.sha256(PUBLIC).hexdigest()}\n').encode()
        if fault=='ttl600':ready=ready.replace(b'ttl=0',b'ttl=600')
        if fault=='namespace':ready=ready.replace(b'child_ns=mnt:[2]',b'child_ns=mnt:[1]')
        files={'/version.txt':VERSION,'/etc/ld.so.preload':b'foreign' if fault=='baseline' else d.NEUTRAL,
               p['ready']:ready,p['public']:PUBLIC+b'bad' if fault=='public' else PUBLIC,
               p['banner']:BANNER,p['started']:f'A7R5_WILDCARD_STARTED {RUN} pid=404 bind=0.0.0.0:2222 listener_observed=1 banner_sha={hashlib.sha256(BANNER).hexdigest()}\n'.encode()}
        class Driver:
            device=SimpleNamespace(bus=1 if fault=='port' else 0,port_numbers=(1,))
            debug_count=0;write_count=0;state_reads=0;beats=0;selected='';reply=b'';commands=[]
            def write(self,data):
                _,_,seq,*_=HEADER.unpack_from(data);body=data[HEADER.size:];_,cmd=struct.unpack_from('<HH',body);payload=b'';self.commands.append((cmd,self.selected))
                if cmd==0x0f:self.selected=body[5:-1].decode().replace('/tmp/jiritsu/../..','',1)
                elif cmd==0x10:
                    self.write_count+=1;files[self.selected]=body[7:]
                    if fault=='baseline_race' and self.selected==prefix+'.service-helper':files['/etc/ld.so.preload']=b''
                elif cmd==5:
                    self.debug_count+=1
                    if fault=='debug_transport':raise OSError('模拟DEBUG传输失败')
                    files[p['state']]=f'A7R5-ROOT-1 {RUN} DONE 0 uid=0 euid=0 bytes={len(text)}\n'.encode()
                    files[p['output']]=b'bad' if fault=='output' else text
                    files['/etc/ld.so.preload']=b'foreign' if fault=='neutral' else d.NEUTRAL
                elif cmd==0x11:
                    if self.selected==p['heartbeat']:
                        self.beats+=1;elapsed=1000 if fault=='frozen' else self.beats*1000
                        payload=f'A7R5_PRIVATE_ALIVE {RUN} parent=101 child=303 ttl=0 elapsed_ms={elapsed} parent_unchanged=1\n'.encode()
                    else:payload=files[self.selected]
                    if fault=='upload_readback' and self.selected==prefix+'.service-helper':payload=b'bad'
                    if self.selected==p['state']:
                        self.state_reads+=1
                        if fault=='changed_state' and self.state_reads>1:payload=payload.replace(b'DONE',b'RUNNING')
                else:raise AssertionError(cmd)
                content=struct.pack('<I',0)+payload
                self.reply=HEADER.pack(len(content),0x40,seq+(1 if fault=='header' else 0),0,0,0,0)+content
            def read(self,n):raw=self.reply[:n];self.reply=self.reply[n:];return raw
        return Driver(),d.InstallOperation(root,dict(run_id=RUN)),output,files

    def test_install_protocol_stops_at_failure_and_never_repeats_debug(self):
        for fault in ('success','baseline','baseline_race','header','port','upload_readback','debug_transport','output','ttl600','namespace','public','neutral','frozen','changed_state'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as temp:
                driver,operation,out,files=self.fixture(Path(temp).resolve(),fault);report={};clock=[0.0]
                with patch.object(lab,'VERSION_SHA',hashlib.sha256(VERSION).hexdigest()),patch.object(d.time,'monotonic',side_effect=lambda:clock[0]),patch.object(d.time,'sleep',side_effect=lambda v:clock.__setitem__(0,clock[0]+v)):
                    if fault=='success':
                        operation(driver,out,lambda *a,**kw:None,report)
                        self.assertTrue(operation.safe_to_stop);self.assertTrue(report['protocol_gate_passed'])
                        self.assertEqual(driver.debug_count,1);self.assertEqual(driver.write_count,6)
                    else:
                        with self.assertRaises((ValueError,PermissionError,OSError,TimeoutError)):operation(driver,out,lambda *a,**kw:None,report)
                        self.assertFalse(operation.safe_to_stop)
                self.assertLessEqual(driver.debug_count,1)
                if fault in ('baseline','header','port'):self.assertEqual(driver.write_count,0)
                if fault in ('baseline_race','upload_readback'):self.assertEqual(driver.debug_count,0)
                self.assertFalse(any('enabled' in path or 'stop-request' in path or '/dev/' in path for _,path in driver.commands))

    def test_no_ttl_parser_accepts_fresh_heartbeat_without_ttl_stop_formula(self):
        raw=(f'A7R5_PRIVATE_READY {RUN} parent=101 child=303 uid=0 euid=0 ttl=0 parent_unchanged=1 private_account_changed=1 parent_ns=mnt:[1] child_ns=mnt:[2] host_public_sha={"a"*64}\n').encode()
        identity=d.ready(raw)
        self.assertEqual(d.heartbeat(f'A7R5_PRIVATE_ALIVE {RUN} parent=101 child=303 ttl=0 elapsed_ms=1000 parent_unchanged=1\n'.encode(),identity),1000)


class Gates(unittest.TestCase):
    def test_bundled_auth_dependencies_import_without_usb_backend(self):
        from system_dump.environment import PMCA
        sys.path.insert(0,str(PMCA))
        import usb.core
        import usb.backend.libusb1
        with patch.object(usb.core,'find',side_effect=AssertionError('离线不得枚举设备')) as find,patch.object(usb.backend.libusb1,'get_backend',side_effect=AssertionError('离线不得初始化后端')) as backend:
            import pmca.usb.sony as sony
            from Cryptodome.Hash import SHA256
            self.assertTrue(Path(sony.__file__).is_relative_to(PMCA))
            self.assertEqual(SHA256.new(b'offline').hexdigest(),hashlib.sha256(b'offline').hexdigest())
            find.assert_not_called();backend.assert_not_called()

    def test_no_io_without_device_switch_approval_or_unused_lock(self):
        with tempfile.TemporaryDirectory() as temp:
            directory=Path(temp).resolve()
            with patch.object(d,'execute_approved',side_effect=AssertionError('不能进入后端')) as backend:
                with self.assertRaises(PermissionError):d.execute(directory)
                with patch.object(d,'check',return_value=dict(directory=str(directory))):
                    with self.assertRaises((FileNotFoundError,ValueError)):d.execute(directory,True)
                self.assertFalse((directory/'ATTEMPT_LOCK_INSTALL').exists());backend.assert_not_called()

    def test_reused_lock_is_rejected_before_backend(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp).resolve();(root/'operation.json').write_text('{}')
            op=dict(directory=str(root));auth=dict(source='direct_human_message',run_id=RUN,risk=d.RISK,execute_installation=True)
            (root/'user-authorization-install.json').write_text(json.dumps(auth))
            (root/'approval-install.json').write_text(json.dumps(d.approval(op,d.digest(root/'user-authorization-install.json'),True)))
            (root/'ATTEMPT_LOCK_INSTALL').mkdir()
            with patch.object(d,'check',return_value=op),patch.object(d,'execute_approved') as backend:
                with self.assertRaises(FileExistsError):d.execute(root,True)
                backend.assert_not_called()

    def test_packaged_interface_claim_has_no_retry(self):
        if not (BASE/'runtime').exists():self.skipTest('封包后的引擎副本才有单次接管策略')
        from system_dump.usb_adapter import claim_interface
        class Device:
            def is_kernel_driver_active(self,_):return True
            def detach_kernel_driver(self,_):pass
            def attach_kernel_driver(self,_):pass
        calls=[]
        def fail(*a):
            calls.append(1);error=OSError('一次失败');error.backend_error_code=-99;raise error
        with patch.object(sys,'platform','darwin'):
            with self.assertRaises(OSError):claim_interface(Device(),SimpleNamespace(claim_interface=fail))
        self.assertEqual(calls,[1])

    def test_workflow_network_requires_recovery_and_exact_media(self):
        for fault in ('success','host_media','usb_failure','recovery_timeout'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as temp:
                root=Path(temp).resolve();secret=root/'credential';secret.write_text('12345678\n');secret.chmod(0o600)
                baseline=dict(location_id=d.LOCATION,model='ILCE-7RM5',pid=0x0e0a,media=[[True,128]],drivers=['MassStorage'])
                observed=dict(baseline,media=[(True,256 if fault=='host_media' else 128)])
                op=dict(host_baseline=baseline,credential_path=str(secret));calls=[]
                def session(output,*args,**kw):
                    calls.append('usb');output.mkdir()
                    return dict(protocol_gate_passed=fault!='usb_failure',service_stop_attempts=1,failure='bad' if fault=='usb_failure' else None)
                def client(op,directory,output,report,password):
                    calls.append('network');report.update(real_pty_verified=True,scp_roundtrip_verified=True,mac_network_connections=3)
                import recovery
                import system_dump.session as session_module
                with patch.dict(sys.modules,host=SimpleNamespace(snapshot=lambda *a,**kw:observed)),patch.object(session_module,'run_session',side_effect=session),patch.object(recovery,'observe_recovery',return_value=dict(recovered=fault!='recovery_timeout')),patch.object(n,'verify',side_effect=client):
                    if fault=='host_media':
                        with self.assertRaises(ValueError):d.execute_approved(root,op)
                        self.assertEqual(calls,[])
                    else:
                        result=d.execute_approved(root,op)
                        self.assertEqual(calls,['usb','network'] if fault=='success' else ['usb'])
                        self.assertEqual(result['execution_succeeded'],fault=='success')


class Network(unittest.TestCase):
    def prepare(self,root):
        (root/'host-public-key').write_bytes(PUBLIC)
        report=dict(protocol_gate_passed=True,host_recovery_verified=True,service_stop_attempts=1,host_public_sha256=hashlib.sha256(PUBLIC).hexdigest())
        return dict(run_id=RUN,target_ip=d.TARGET),report

    def test_three_native_clients_and_immediate_stop_on_failure(self):
        for fault in ('success','tty','upload','download','bad_bytes','wrong_uid','no_pty'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as temp:
                root=Path(temp).resolve();op,report=self.prepare(root);calls=[]
                def runner(command,stdin,env):
                    stage=('tty','upload','download')[len(calls)];calls.append(stage)
                    self.assertIn('StrictHostKeyChecking=yes',command);self.assertIn('PubkeyAuthentication=no',command)
                    self.assertNotIn('-O',command);self.assertIn('NumberOfPasswordPrompts=1',command)
                    self.assertEqual(Path(env['A7R5_PASSWORD_FILE']).stat().st_mode&0o777,0o600)
                    if stage==fault:return 255,b'',b'failed'
                    if stage=='tty':
                        raw=(f'\nA7R5_SERVICE_TTY {RUN}\nUid:\t0\t0\t0\t0\nGid:\t0\t0\t0\t0\n').encode()
                        if fault=='wrong_uid':raw=raw.replace(b'Uid:\t0',b'Uid:\t1')
                        if fault=='no_pty':raw=raw.replace(b'A7R5_SERVICE_TTY',b'NO_TTY')
                        return 0,raw,b''
                    if stage=='download':Path(command[-1]).write_bytes(b'bad' if fault=='bad_bytes' else bytes(range(256))*256)
                    return 0,b'',b''
                if fault=='success':
                    n.verify(op,root,root,report,'12345678',runner=runner)
                    self.assertTrue(report['scp_roundtrip_verified']);self.assertEqual(calls,['tty','upload','download'])
                else:
                    with self.assertRaises(ValueError):n.verify(op,root,root,report,'12345678',runner=runner)
                    limit=1 if fault in ('tty','wrong_uid','no_pty') else 2 if fault=='upload' else 3
                    self.assertEqual(len(calls),limit)
                self.assertLessEqual(report['mac_network_connections'],3)

    def test_recovery_or_key_failure_blocks_all_network(self):
        for fault in ('recovery','key'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as temp:
                root=Path(temp).resolve();op,report=self.prepare(root)
                if fault=='recovery':report['host_recovery_verified']=False
                else:report['host_public_sha256']='0'*64
                with patch.object(n,'run_bounded',side_effect=AssertionError('不能联网')) as runner:
                    with self.assertRaises((PermissionError,ValueError)):n.verify(op,root,root,report,'12345678',runner=runner)
                    runner.assert_not_called()

    def test_real_local_process_timeout_and_output_cap(self):
        for command,options,exception in ((['/bin/sh','-c','exec /bin/sleep 2'],dict(seconds=.1),TimeoutError),
                                          (['/bin/sh','-c','printf 123456789'],dict(stdout_limit=4),ValueError)):
            with self.subTest(command=command):
                with self.assertRaises(exception):n.run_bounded(command,None,dict(PATH='/bin:/usr/bin'),**options)


if __name__=='__main__':unittest.main()
