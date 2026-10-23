"""主机状态机失败门槛；全部使用内存USB/SSH替身，不访问设备或网络。"""
import base64
import hashlib
import json
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import operation as op

RUN='face1234'*4
PUBLIC=b'ecdsa-sha2-nistp256 '+base64.b64encode(b'fixture-key')+b'\n'
BANNER=b'SSH-2.0-OpenSSH_7.9p1\r\n'


class Protocol(unittest.TestCase):
    def fixture(self,root,fault,phase):
        op.lab.engine()
        from system_dump.usb_adapter import HEADER
        p=op.paths(RUN)
        (root/'private-sshd.arm64').write_bytes(b'fixed-helper')
        (root/'root.arm64.so').write_bytes(b'fixed-payload')
        output=root/'evidence';output.mkdir()
        text=f'A7R5_PRIVATE_LAUNCH {RUN} READY\n'.encode()
        ready=(f'A7R5_PRIVATE_READY {RUN} parent=101 child=303 uid=0 euid=0 ttl=600 parent_unchanged=1 private_account_changed=1 parent_ns=mnt:[1] child_ns=mnt:[2] host_public_sha={hashlib.sha256(PUBLIC).hexdigest()}\n').encode()
        if fault=='namespace':ready=ready.replace(b'child_ns=mnt:[2]',b'child_ns=mnt:[1]')
        final=f'A7R5_PRIVATE_RESULT {RUN} code=0 parent_unchanged=1 child_tree_reaped=1 child_terminal_seen=1 listener_absent=1\n'.encode()
        if fault=='not_reaped':final=final.replace(b'child_tree_reaped=1',b'child_tree_reaped=0')
        if fault in ('early_clean','mixed'):final=final.replace(b'code=0',b'code=87')
        child=b'PRIVATE_RESULT code=0 errno=0 sshd_attempted=1 listener_observed=1 children_reaped=1 private_account_changed=1 local_banner_verified=1\n'
        if fault=='early_clean':child=child.replace(b'code=0',b'code=116')
        files={'/version.txt':(op.lab.ROOT/'reference/version.bin').read_bytes(),
               '/etc/ld.so.preload':b'foreign' if fault=='baseline' else b'\n'*512,
               p['ready']:ready,p['public']:PUBLIC+b'wrong' if fault=='public' else PUBLIC,
               p['result']:final,p['child']:child,
               p['banner']:BANNER+b'bad' if fault=='banner' else BANNER,
               p['started']:f'A7R5_WILDCARD_STARTED {RUN} pid=404 bind=0.0.0.0:2222 listener_observed=1 banner_sha={hashlib.sha256(BANNER).hexdigest()}\n'.encode()}
        class Driver:
            device=SimpleNamespace(bus=1 if fault=='port' else 0,port_numbers=(1,))
            debug_count=0;write_count=0;state_reads=0;heartbeat_reads=0
            selected='';reply=b''
            def write(self,data):
                size,function,seq,*rest=HEADER.unpack_from(data);body=data[HEADER.size:]
                group,command=struct.unpack_from('<HH',body);payload=b''
                if command==0x0f:self.selected=body[5:-1].decode().replace('/tmp/jiritsu/../..','',1)
                elif command==0x10:
                    self.write_count+=1;files[self.selected]=body[7:]
                    if fault=='baseline_race' and self.selected==p['helper']:files['/etc/ld.so.preload']=b''
                elif command==5:
                    self.debug_count+=1
                    if fault=='debug_transport':raise OSError('模拟DEBUG失步')
                    files[p['state']]=f'A7R5-ROOT-1 {RUN} DONE 0 uid=0 euid=0 bytes={len(text)}\n'.encode()
                    files[p['output']]=text
                    files['/etc/ld.so.preload']=b'foreign' if fault=='neutral' else b'\n'*512
                elif command==0x11:
                    if self.selected==p['heartbeat']:
                        self.heartbeat_reads+=1
                        elapsed=61000 if fault=='expired' else (1000 if fault=='frozen' else self.heartbeat_reads*1000)
                        payload=f'A7R5_PRIVATE_ALIVE {RUN} parent=101 child=303 ttl=600 elapsed_ms={elapsed} parent_unchanged=1\n'.encode()
                    else:payload=files[self.selected]
                    if fault=='helper_readback' and self.selected==p['helper']:payload=b'wrong'
                    if self.selected==p['state']:
                        self.state_reads+=1
                        if fault=='changed_state' and self.state_reads>1:payload=payload.replace(b'DONE',b'RUNNING')
                else:raise AssertionError(command)
                content=struct.pack('<I',0)+payload
                self.reply=HEADER.pack(len(content),0x40,seq+(1 if fault=='header' else 0),0,0,0,0)+content
            def read(self,n):
                value=self.reply[:n];self.reply=self.reply[n:];return value
        return Driver(),op.Operation(root,dict(run_id=RUN,location_id=0x00100000),phase),output

    def test_deploy_withholds_stop_on_unsafe_state_without_debug_retry(self):
        for fault in ('success','baseline','baseline_race','header','helper_readback','debug_transport','public','namespace','frozen','expired','neutral','changed_state','banner','port'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                driver,operation,output=self.fixture(Path(tmp),fault,'deploy');report={};now=[0.0]
                def sleep(n):now[0]+=n
                with patch.object(op.time,'monotonic',side_effect=lambda:now[0]),patch.object(op.time,'sleep',side_effect=sleep):
                    if fault=='success':
                        operation(driver,output,lambda *a,**kw:None,report)
                        self.assertTrue(operation.safe_to_stop);self.assertTrue(report['guest_final_result_pending'])
                        self.assertTrue(report['ssh_startup_verified']);self.assertFalse(report['ssh_root_login_verified'])
                    else:
                        with self.assertRaises((ValueError,PermissionError,OSError,TimeoutError)):operation(driver,output,lambda *a,**kw:None,report)
                        self.assertFalse(operation.safe_to_stop)
                self.assertLessEqual(driver.debug_count,1)
                if fault in ('baseline','header','port'):self.assertEqual(driver.write_count,0)
                if fault in ('baseline_race','helper_readback'):self.assertEqual(driver.debug_count,0)

    def test_collect_never_writes_and_requires_complete_cleanup(self):
        for fault in ('success','early_clean','mixed','not_reaped','baseline'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                driver,operation,output=self.fixture(Path(tmp),fault,'collect');report={}
                if fault in ('success','early_clean'):
                    operation(driver,output,lambda *a,**kw:None,report)
                    self.assertTrue(operation.safe_to_stop);self.assertTrue(report['guest_final_cleanup_verified'])
                    self.assertEqual(report['guest_experiment_succeeded'],fault=='success')
                else:
                    with self.assertRaises((ValueError,PermissionError)):operation(driver,output,lambda *a,**kw:None,report)
                    self.assertFalse(operation.safe_to_stop)
                self.assertEqual(driver.write_count,0);self.assertEqual(driver.debug_count,0)

    def test_device_switch_is_required_before_loading_backend(self):
        with self.assertRaises(PermissionError):op.execute('/nonexistent','deploy')


class Approval(unittest.TestCase):
    def test_dependencies_do_not_follow_sudo_home(self):
        with patch.object(Path,'home',side_effect=AssertionError('不能从sudo HOME发现依赖')):
            self.assertTrue(op.dependencies().is_dir())

    def test_each_stage_requires_its_own_approval_and_unused_lock(self):
        with tempfile.TemporaryDirectory() as tmp,patch.object(op,'check',return_value=dict(run_id=RUN)):
            root=Path(tmp).resolve();(root/'operation.json').write_text('{}')
            with self.assertRaises(FileNotFoundError):op.checked_approval(root,'deploy')
            (root/'approval-deploy.json').write_text(json.dumps(op.approval(root,'deploy',False)))
            with self.assertRaises(PermissionError):op.checked_approval(root,'deploy')
            (root/'approval-deploy.json').write_text(json.dumps(op.approval(root,'deploy',True)))
            self.assertEqual(op.checked_approval(root,'deploy')['run_id'],RUN)
            (root/'ATTEMPT_LOCK_DEPLOY').mkdir()
            with self.assertRaises(FileExistsError):op.checked_approval(root,'deploy')
            prior=root/'result-deploy';prior.mkdir();result=prior/'phase-result.json'
            for recovery,wait in ((False,0),(True,float('inf')),(True,0)):
                result.write_text(json.dumps(dict(protocol_gate_passed=True,host_recovery_verified=recovery,collect_not_before_unix=wait)))
                (root/'approval-collect.json').write_text(json.dumps(op.approval(root,'collect',True)))
                if recovery and wait==0:self.assertEqual(op.checked_approval(root,'collect')['run_id'],RUN)
                else:
                    with self.assertRaises(PermissionError):op.checked_approval(root,'collect')
            # 之后改变上一次回执，必须重新明确批准，不能复用已绑定的批准。
            result.write_text(result.read_text()+'\n')
            with self.assertRaises(PermissionError):op.checked_approval(root,'collect')


if __name__=='__main__':unittest.main(verbosity=2)
