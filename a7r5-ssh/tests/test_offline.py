"""普通文件、受控子进程和批准拒绝测试；不枚举设备、不使用主机网络。"""
import base64
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import lab

RUN='1234abcd'*4
PUB='ssh-ed25519 '+base64.b64encode(b'\0\0\0\x0bssh-ed25519\0\0\0\x20'+b'K'*32).decode()


class Policy(unittest.TestCase):
    def test_fixed_public_key_only_configuration(self):
        value=lab.ssh_config(RUN,'192.168.1.20',PUB,20)
        conf=value['configuration']
        for line in ('StrictModes yes','PasswordAuthentication no','AllowTcpForwarding no','PermitTTY no','ForceCommand /bin/busybox cat /proc/self/status'):
            self.assertIn(line+'\n',conf)
        self.assertNotIn('0.0.0.0',conf)
        self.assertFalse(value['production_deployment_enabled'])
        self.assertFalse(value['account_modification_enabled'])

    def test_config_rejects_injection_and_unbounded_listener(self):
        for address in ('0.0.0.0','224.0.0.1','8.8.8.8','127.0.0.1\nPermitRootLogin yes'):
            with self.subTest(address=address),self.assertRaises(ValueError): lab.ssh_config(RUN,address,PUB)
        for public in (PUB+' comment',PUB+'\nPermitRootLogin yes','command="id" '+PUB,'ssh-ed25519 AAAA'):
            with self.subTest(public=public),self.assertRaises(ValueError): lab.ssh_config(RUN,'127.0.0.1',public)
        for seconds in (0,31,3600):
            with self.assertRaises(ValueError): lab.ssh_config(RUN,'127.0.0.1',PUB,seconds)

    def test_preflight_rejects_incomplete_old_nonroot_and_wrong_binary(self):
        data=(f'A7R5_SSH_PREFLIGHT_BEGIN {RUN}\nUID 0\nEUID 0\nVERSION_SHA256 {lab.VERSION_SHA}\n'
              f'SSHD_SHA256 {lab.SSHD_SHA}\nROOT_SHELL /bin/false\nA7R5_SSH_PREFLIGHT_COMPLETE {RUN}\n').encode()
        result=lab.parse_preflight(data,RUN)
        self.assertTrue(result['account_change_required']); self.assertFalse(result['deployment_allowed'])
        for faulty in (data[:-1],data.replace(b'UID 0',b'UID 1'),data.replace(lab.SSHD_SHA.encode(),b'0'*64),data.replace(RUN.encode(),b'0'*32),data+b'extra\n',data.replace(b'ROOT_SHELL',b'ROOT_SHELL /bin/sh\nROOT_SHELL')):
            with self.subTest(faulty=faulty[:60]),self.assertRaises(ValueError): lab.parse_preflight(faulty,RUN)

    def test_no_device_work_before_two_explicit_gates(self):
        with tempfile.TemporaryDirectory() as tmp,patch('subprocess.run',side_effect=AssertionError('不应启动子进程')):
            with self.assertRaises(PermissionError): lab.execute_preflight(Path(tmp).resolve())
            with self.assertRaises(FileNotFoundError): lab.execute_preflight(Path(tmp).resolve(),True)
        self.assertNotIn('usb.core',sys.modules)

    def test_terminal_without_approval_does_not_invoke_sudo(self):
        with tempfile.TemporaryDirectory() as tmp:
            env=dict(os.environ,A7R5_SSH_OPERATION=tmp)
            result=subprocess.run(['/bin/bash',str(lab.ROOT/'start-preflight.command')],env=env,capture_output=True,text=True,timeout=5)
        self.assertEqual(result.returncode,2);self.assertIn('缺少本次实机批准',result.stdout)

    def test_safe_files_reject_symlink_and_device(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);(p/'file').write_bytes(b'data');(p/'link').symlink_to(p/'file')
            with self.assertRaises(ValueError): lab.digest(p/'link')
            with self.assertRaises(ValueError): lab.regular('/dev/null')

    def test_serial_socket_close_contract(self):
        from qemu_verify import SerialSocket
        connection=SerialSocket(None,0)
        self.assertFalse(connection._closed)
        connection.close()
        self.assertTrue(connection._closed)
        self.assertEqual(connection.send(b'closed'),0)


class RootWorker(unittest.TestCase):
    def test_same_c_exact_gate_disarm_timeout_and_output_limits(self):
        for fault in ('gate','preload','success','timeout','overflow'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                p=Path(tmp);script={'timeout':'/bin/sleep 10','overflow':'while :; do echo abcdefghijklmnopqrstuvwxyz; done'}.get(fault,'echo root-worker-ok')
                (p/'root_config.h').write_text(lab.root_header(RUN,script,1,directory=str(p),preload=str(p/'preload'),gate=str(p/'gate')))
                arm=(str(p)+'/a7r5-'+RUN+'.so\n').encode()
                (p/'preload').write_bytes(b'foreign' if fault=='preload' else arm)
                (p/'gate').write_bytes(b'wrong\0' if fault=='gate' else b'/bin/sh\0-c\0/bin/date -s 070421422017.26\0')
                exe=p/'worker'
                subprocess.run(['/usr/bin/clang','-DA7R5_HOST_TEST','-O1','-Wall','-Wextra','-Werror','-I',str(p),str(lab.ROOT/'src/root_once.c'),'-o',str(exe)],check=True,capture_output=True)
                result=subprocess.run([str(exe)],capture_output=True,timeout=5)
                state=p/f'a7r5-{RUN}.state'
                if fault=='gate':
                    self.assertEqual(result.returncode,100);self.assertFalse(state.exists());self.assertEqual((p/'preload').read_bytes(),arm);continue
                deadline=time.monotonic()+7;text=''
                while time.monotonic()<deadline:
                    text=state.read_text() if state.exists() else ''
                    if any(' '+phase+' ' in text for phase in ('DONE','FAILED','TIMEOUT')):break
                    time.sleep(.02)
                expected={'preload':' FAILED 92 ','success':' DONE 0 ','timeout':' TIMEOUT 85 ','overflow':' FAILED 83 '}[fault]
                self.assertIn(expected,text)
                self.assertEqual((p/'preload').read_bytes(),b'foreign' if fault=='preload' else b'\n'*512)


class Supervisor(unittest.TestCase):
    def test_supervisor_ttl_signal_early_exit_and_foreign_process(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);helper=p/'fake-sshd'
            helper.write_text('#!/bin/sh\nexec /bin/sleep 60\n');helper.chmod(0o700)
            exe=p/'supervisor'
            subprocess.run(['/usr/bin/clang','-DHOST_TEST','-DSSHD_EXE='+json.dumps(str(helper)),
                            '-O1','-Wall','-Wextra','-Werror',str(lab.ROOT/'src/supervisor.c'),'-o',str(exe)],check=True,capture_output=True)
            foreign=subprocess.Popen(['/bin/sleep','60'])
            try:
                for method in ('signal','ttl','early'):
                    if method=='early': helper.write_text('#!/bin/sh\nexit 42\n')
                    child=subprocess.Popen([str(exe),str(p/'config'),'5' if method=='ttl' else '30'],stdout=subprocess.PIPE)
                    self.assertEqual(child.stdout.readline(),b'SUPERVISOR_SPAWNED\n')
                    if method=='signal': child.send_signal(signal.SIGTERM)
                    out,_=child.communicate(timeout=10)
                    self.assertEqual(child.returncode,73 if method=='early' else 0)
                    self.assertIn(b'SUPERVISOR_STOPPED_NO_OWNED_CHILDREN',out)
                    self.assertIsNone(foreign.poll())
            finally:
                foreign.terminate();foreign.wait(timeout=3)


class Protocol(unittest.TestCase):
    def test_real_protocol_readback_gates_and_single_debug(self):
        import struct
        from types import SimpleNamespace
        lab.engine()
        from system_dump.usb_adapter import HEADER
        from device import PreflightOperation
        for fault in ('success','preload','payload','debug_transport','old_state','nonroot','output_length','neutral','changed_state','header'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                directory=Path(tmp);(directory/'preflight.arm64.so').write_bytes(b'fixed-elf-fixture')
                output=directory/'result';output.mkdir()
                text=(f'A7R5_SSH_PREFLIGHT_BEGIN {RUN}\nUID 0\nEUID 0\nVERSION_SHA256 {lab.VERSION_SHA}\n'
                      f'SSHD_SHA256 {lab.SSHD_SHA}\nROOT_SHELL /bin/false\nA7R5_SSH_PREFLIGHT_COMPLETE {RUN}\n').encode()
                prefix='/tmp/jiritsu/a7r5-'+RUN
                files={'/version.txt':(lab.ROOT/'reference/version.bin').read_bytes(),'/etc/ld.so.preload':b'other' if fault=='preload' else b'\n'*512}
                class Driver:
                    device=SimpleNamespace(bus=1,port_numbers=(1,))
                    debug_count=0;write_count=0;state_reads=0
                    selected='';reply=b''
                    def write(self,data):
                        size,function,seq,*rest=HEADER.unpack_from(data);body=data[HEADER.size:]
                        group,command=struct.unpack_from('<HH',body);payload=b''
                        if command==0x0f:
                            self.selected=body[5:-1].decode().replace('/tmp/jiritsu/../..','',1)
                        elif command==0x10:
                            self.write_count+=1;files[self.selected]=body[7:]
                        elif command==5:
                            self.debug_count+=1
                            if fault=='debug_transport': raise OSError('模拟DEBUG传输失败')
                            files[prefix+'.output']=text
                            state_run='0'*32 if fault=='old_state' else RUN
                            uid=1 if fault=='nonroot' else 0
                            files[prefix+'.state']=(f'A7R5-ROOT-1 {state_run} DONE 0 uid={uid} euid=0 bytes={len(text)+(1 if fault=="output_length" else 0)}\n').encode()
                            files['/etc/ld.so.preload']=b'foreign' if fault=='neutral' else b'\n'*512
                        elif command==0x11:
                            payload=files[self.selected]
                            if fault=='payload' and self.selected==prefix+'.so': payload=b'wrong'
                            if self.selected==prefix+'.state':
                                self.state_reads+=1
                                if fault=='changed_state' and self.state_reads==2: payload=payload.replace(b'DONE',b'RUNNING')
                        else: raise AssertionError(command)
                        content=struct.pack('<I',0)+payload
                        self.reply=HEADER.pack(len(content),0x40,seq+(1 if fault=='header' else 0),0,0,0,0)+content
                    def read(self,n):
                        value=self.reply[:n];self.reply=self.reply[n:];return value
                driver=Driver();op=PreflightOperation(directory,dict(run_id=RUN));report={}
                if fault=='success':
                    op(driver,output,lambda *a,**kw:None,report)
                    self.assertTrue(op.safe_to_stop);self.assertTrue(report['preflight_complete'])
                    self.assertFalse(report['ssh_started']);self.assertFalse(report['account_modified'])
                else:
                    with self.assertRaises((ValueError,PermissionError,OSError)):
                        op(driver,output,lambda *a,**kw:None,report)
                    if fault not in ('payload',): self.assertFalse(op.safe_to_stop)
                self.assertLessEqual(driver.debug_count,1)
                # 这些旧字段记录调用尝试，失败也不能留下默认 false。
                self.assertEqual(report['camera_file_write_commands_sent'],driver.write_count>0)
                self.assertEqual(report['debug_commands_sent'],driver.debug_count>0)
                self.assertEqual(report['preload_written'],fault not in ('preload','header','payload'))
                if fault in ('preload','header'): self.assertEqual(driver.write_count,0)
                if fault=='payload':
                    self.assertEqual(driver.debug_count,0);self.assertEqual(files['/etc/ld.so.preload'],b'\n'*512)


class Package(unittest.TestCase):
    def test_unapproved_aarch64_package_and_tamper_rejection(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp).resolve()/'once'; value=lab.build_preflight(p)
            self.assertEqual(lab.check(p)['run_id'],value['run_id'])
            self.assertFalse((p/'approval.json').exists());self.assertFalse((p/'ATTEMPT_LOCK').exists())
            self.assertFalse(json.loads((p/'approval-template.json').read_text())['accepted'])
            with self.assertRaises(PermissionError):lab.execute_preflight(p)
            # 未接受模板即使改名也不能越过 sudo 前的门槛。
            (p/'approval.json').write_bytes((p/'approval-template.json').read_bytes())
            with self.assertRaises(PermissionError):lab.checked_approval(p)
            env=dict(os.environ,A7R5_SSH_OPERATION=str(p))
            refused=subprocess.run(['/bin/bash',str(lab.ROOT/'start-preflight.command')],env=env,capture_output=True,text=True,timeout=5)
            self.assertEqual(refused.returncode,2);self.assertIn('缺少绑定本次材料',refused.stderr)
            (p/'task.sh').write_text('modified')
            with self.assertRaises(ValueError):lab.check(p)


if __name__=='__main__': unittest.main(verbosity=2)
