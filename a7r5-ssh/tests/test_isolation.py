"""命名空间/跨STOP契约测试：本机仅使用临时普通文件、替身及本次进程。"""
import contextlib
import hashlib
import io
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import lab
import isolation as ns

RUN='cafe1234'*4


class Launcher(unittest.TestCase):
    def run_fixture(self,failure=0,seconds=2,relocate=False):
        temp=tempfile.TemporaryDirectory();self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        header=ns.config_header(RUN,test=dict(root=root,failure=failure)).replace('#define PROBE_SECONDS 2',f'#define PROBE_SECONDS {seconds}')
        (root/'ns_config.h').write_text(header)
        (root/'ram_parent').mkdir();(root/'ram_parent').chmod(0o1777);(root/'var_path').mkdir()
        original=b'root:*:0:0:root:/root:/bin/false\nsshd:*:77:77:sshd:/var/run/sshd:/bin/false\n'
        (root/'passwd_path').write_bytes(original)
        for name,data in [('test_mounts','fixture-original-mounts\n'),('net_dev_path','lo wlan0\n'),
                          ('net_route_path','Iface Destination Gateway\n'),('net_ip_path','IPV4 wlan0 192.168.1.20\n')]:
            (root/name).write_text(data)
        binary=root/'probe'
        built=subprocess.run(['/usr/bin/clang','-DNS_HOST_TEST','-O1','-Wall','-Wextra','-Werror',
                              '-I',str(root),str(lab.ROOT/'src/ns_probe.c'),'-o',str(binary)],capture_output=True,text=True)
        self.assertEqual(built.returncode,0,built.stderr)
        started=time.monotonic()
        reply=subprocess.run([str(binary),'--launch'],capture_output=True,timeout=3)
        elapsed=time.monotonic()-started
        runtime=root/'ram_parent/run_dir'
        if relocate:
            runtime.rename(root/'relocated');runtime.mkdir();runtime=root/'relocated'
        result=runtime/'result_path';deadline=time.monotonic()+seconds+6
        while time.monotonic()<deadline and not result.exists():time.sleep(.03)
        self.assertTrue(result.exists(),reply.stderr)
        # 完成收据最后写出，额外短等只等待本次已知进程自行结束。
        time.sleep(.05)
        text=result.read_text()
        values=dict(line.split('=',1) for line in text.splitlines()[1:-1])
        trace=runtime/'trace_path'
        self.assertEqual((root/'passwd_path').read_bytes(),original)
        self.assertFalse((root/'marker_path').exists())
        self.assertEqual(hashlib.sha256(trace.read_bytes()).hexdigest(),values['trace_sha256'])
        self.assertEqual(trace.stat().st_size,int(values['trace_bytes']))
        self.assertEqual(values['child_reaped'],'1')
        self.assertEqual(values['ssh_started'],'0');self.assertEqual(values['account_modified'],'0')
        return root,values,reply,elapsed

    def test_success_ttl_closes_output_and_preserves_accounts(self):
        root,result,reply,elapsed=self.run_fixture(seconds=5)
        self.assertEqual(reply.returncode,0,reply.stderr)
        self.assertIn(b'outcome=READY\n',reply.stdout)
        self.assertLess(elapsed,3)
        self.assertEqual(result['code'],'0');self.assertEqual(result['isolation_verified'],'1')
        self.assertEqual(result['parent_unchanged'],'1')
        self.assertEqual((root/'private_passwd').read_bytes(),(root/'passwd_path').read_bytes())
        self.assertTrue((root/'ram_parent/run_dir/heartbeat_path').read_text().startswith('A7R5_NS_ENDED'))

    def test_ram_directory_replacement_does_not_redirect_background_writes(self):
        root,result,reply,_=self.run_fixture(relocate=True)
        self.assertEqual(reply.returncode,0);self.assertEqual(result['code'],'0')
        self.assertTrue((root/'relocated/result_path').exists())
        self.assertEqual(list((root/'ram_parent/run_dir').iterdir()),[])

    def test_failed_isolation_never_falls_back_to_global_writes(self):
        for failure in (61,62,64,65,66,67,69,74,78):
            with self.subTest(failure=failure):
                root,result,reply,_=self.run_fixture(failure)
                self.assertEqual(result['code'],str(failure))
                self.assertEqual(result['parent_unchanged'],'1')
                self.assertEqual(reply.returncode,0)
                if failure in (61,62,64,65):self.assertFalse((root/'private_passwd').exists())
                if failure in (61,62,64,65,66,67,69):
                    self.assertIn(b'NEGATIVE_CLEAN',reply.stdout);self.assertEqual(result['errno'],'1')

    def test_parent_mismatch_is_never_clean_success(self):
        _,result,reply,_=self.run_fixture(73)
        self.assertNotEqual(reply.returncode,0)
        self.assertEqual(result['parent_unchanged'],'0');self.assertEqual(result['code'],'84')

    def test_sha256_vectors_against_standard_library(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);source=root/'hash.c';exe=root/'hash'
            source.write_text('#include <stdio.h>\n#include <string.h>\n#include <stdint.h>\n#include "ns_sha256.h"\nint main(void){char raw[65536],out[65];size_t n=fread(raw,1,sizeof(raw),stdin);sha_bytes(raw,n,out);puts(out);return 0;}\n')
            subprocess.run(['/usr/bin/clang','-O1','-Wall','-Wextra','-Werror','-I',str(lab.ROOT/'src'),str(source),'-o',str(exe)],check=True,capture_output=True)
            for raw in (b'',b'abc',b'a'*55,b'b'*64,b'c'*1024,bytes(range(256))*256):
                result=subprocess.run([str(exe)],input=raw,capture_output=True,check=True)
                self.assertEqual(result.stdout.strip().decode(),hashlib.sha256(raw).hexdigest())


class Gates(unittest.TestCase):
    def test_no_device_or_sudo_before_phase_approval(self):
        with tempfile.TemporaryDirectory() as tmp,patch('subprocess.run',side_effect=AssertionError('不能运行子进程')):
            tmp=Path(tmp).resolve()
            with self.assertRaises(PermissionError):ns.execute(tmp,'probe')
            with self.assertRaises(FileNotFoundError):ns.execute(tmp,'probe',True)
            with self.assertRaises(FileNotFoundError):ns.execute(tmp,'collect',True)

    def test_ready_and_heartbeat_reject_old_identity_and_expiry(self):
        raw=(f'A7R5_NS_READY {RUN} pid=101 ticks=202 child=303 uid=0 euid=0 ttl=75 isolation=1 parent_unchanged=1 account_modified=0 ssh_started=0 passwd_sha={ns.PASSWD_SHA} parent_ns=mnt:[1] child_ns=mnt:[2] net_ns=net:[3]\n').encode()
        identity=ns.ready(raw,RUN)
        for bad in (raw.replace(b'uid=0',b'uid=1'),raw.replace(b'child_ns=mnt:[2]',b'child_ns=mnt:[1]'),raw.replace(RUN.encode(),b'0'*32),raw+b'extra\n'):
            with self.assertRaises(ValueError):ns.ready(bad,RUN)
        beat=(f'A7R5_NS_ALIVE {RUN} pid=101 ticks=202 child=303 seq=3 elapsed_ms=10000 ttl=75 parent_unchanged=1\n').encode()
        self.assertEqual(ns.heartbeat(beat,RUN,identity),(3,10000))
        for bad in (beat.replace(b'ticks=202',b'ticks=999'),beat.replace(b'elapsed_ms=10000',b'elapsed_ms=50000'),beat.replace(b'ALIVE',b'ENDED')):
            with self.assertRaises(ValueError):ns.heartbeat(bad,RUN,identity)

    def test_result_requires_root_cleanup_and_exact_fields(self):
        value=dict(code=0,errno=0,uid=0,euid=0,pid=101,ticks=202,child=303,isolation_verified=1,
                   parent_unchanged=1,passwd_unchanged=1,child_reaped=1,network_hint=0,samples=16,
                   trace_bytes=0,trace_sha256=hashlib.sha256(b'').hexdigest(),ssh_started=0,account_modified=0)
        def raw(data):return ('A7R5_NS_RESULT '+RUN+'\n'+''.join(k+'='+str(v)+'\n' for k,v in data.items())+'END '+RUN+'\n').encode()
        self.assertEqual(ns.fields(raw(value),RUN,'complete')['samples'],16)
        for key,changed in (('uid',1),('child_reaped',0),('parent_unchanged',0),('passwd_unchanged',0),('ssh_started',1),('account_modified',1),('isolation_verified',0),('trace_bytes',65537),('code',61)):
            with self.subTest(key=key),self.assertRaises(ValueError):ns.fields(raw(dict(value,**{key:changed})),RUN,'complete')
        negative=dict(value,code=61,isolation_verified=0,samples=0)
        self.assertEqual(ns.fields(raw(negative),RUN,'negative')['code'],61)
        with self.assertRaises(ValueError):ns.fields(raw(value).replace(b'code=0\n',b'code=0\ncode=0\n'),RUN,'complete')

    def test_sealed_package_phase_approvals_and_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            directory=Path(tmp).resolve()/'once';operation=ns.prepare(directory)
            self.assertEqual(ns.check(directory)['run_id'],operation['run_id'])
            self.assertFalse((directory/'approval-probe.json').exists())
            for phase in ('probe','collect'):
                template=json.loads((directory/f'approval-{phase}-template.json').read_text())
                self.assertFalse(template['accepted']);self.assertFalse(template['start_ssh'])
                self.assertFalse(template['account_modification'])
                refused=subprocess.run(['/bin/bash',str(directory/f'run-{phase}.command')],capture_output=True,text=True,timeout=5)
                self.assertEqual(refused.returncode,2,refused.stdout+refused.stderr)
                (directory/f'approval-{phase}.json').write_text(json.dumps(template))
                with self.assertRaises(PermissionError if phase=='probe' else FileNotFoundError):ns.checked_approval(directory,phase)
            (directory/'approval-probe.json').write_text(json.dumps(ns.approval(operation,'probe')))
            self.assertEqual(ns.checked_approval(directory,'probe')['run_id'],operation['run_id'])
            (directory/'ATTEMPT_LOCK_PROBE').mkdir()
            with self.assertRaises(FileExistsError):ns.checked_approval(directory,'probe')
            result=directory/'result-probe';result.mkdir()
            proof=dict(run_id=operation['run_id'],execution_succeeded=True,host_recovery_verified=True,
                       probe_outcome='READY_FOR_STOP',collect_not_before_unix=time.time()+100)
            (result/'phase-result.json').write_text(json.dumps(proof))
            (directory/'approval-collect.json').write_text(json.dumps(ns.approval(operation,'collect')))
            with self.assertRaises(PermissionError):ns.checked_approval(directory,'collect')
            proof['collect_not_before_unix']=0
            (result/'phase-result.json').write_text(json.dumps(proof))
            with self.assertRaises(PermissionError):ns.checked_approval(directory,'collect')
            (directory/'approval-collect.json').write_text(json.dumps(ns.approval(operation,'collect')))
            self.assertEqual(ns.checked_approval(directory,'collect')['run_id'],operation['run_id'])
            (directory/'task.sh').write_text('tampered')
            with self.assertRaises(ValueError):ns.check(directory)


class Protocol(unittest.TestCase):
    def fixture(self,root,fault,phase):
        import struct
        lab.engine()
        from system_dump.usb_adapter import HEADER
        p=ns.paths(RUN)
        (root/'ns-probe.arm64').write_bytes(b'fixed-helper')
        (root/'isolation.arm64.so').write_bytes(b'fixed-payload')
        output=root/'evidence';output.mkdir()
        text=(f'A7R5_NS_LAUNCH {RUN} outcome='+('NEGATIVE_CLEAN' if fault=='negative' else 'READY')+'\n').encode()
        ready=(f'A7R5_NS_READY {RUN} pid=101 ticks=202 child=303 uid=0 euid=0 ttl=75 isolation=1 parent_unchanged=1 account_modified=0 ssh_started=0 passwd_sha={ns.PASSWD_SHA} parent_ns=mnt:[1] child_ns=mnt:[2] net_ns=net:[3]\n').encode()
        if fault=='ready_hash':ready=ready.replace(ns.PASSWD_SHA.encode(),b'0'*64)
        if fault=='namespace':ready=ready.replace(b'child_ns=mnt:[2]',b'child_ns=mnt:[1]')
        trace=b'IPV4 wlan0 192.168.1.20\n'
        terminal=dict(code=61 if fault=='negative' else 0,errno=1 if fault=='negative' else 0,
                      uid=0,euid=0,pid=101,ticks=202,child=303,isolation_verified=0 if fault=='negative' else 1,
                      parent_unchanged=0 if fault=='parent_changed' else 1,passwd_unchanged=1,
                      child_reaped=0 if fault=='not_reaped' else 1,network_hint=1,samples=16,
                      trace_bytes=len(trace),trace_sha256=hashlib.sha256(trace).hexdigest(),ssh_started=0,account_modified=0)
        result=('A7R5_NS_RESULT '+RUN+'\n'+''.join(k+'='+str(v)+'\n' for k,v in terminal.items())+'END '+RUN+'\n').encode()
        files={'/version.txt':(lab.ROOT/'reference/version.bin').read_bytes(),
               '/etc/ld.so.preload':b'other' if fault=='baseline' else b'\n'*512,
               p['ready']:ready,p['result']:result,p['trace']:trace+b'bad' if fault=='trace' else trace}
        if phase=='collect':
            prior=root/'result-probe';prior.mkdir()
            (prior/'phase-result.json').write_text(json.dumps(dict(observer_identity=dict(pid=101,ticks=202,child=303))))
        class Driver:
            device=SimpleNamespace(bus=1,port_numbers=(1,))
            debug_count=0;write_count=0;state_reads=0;ready_reads=0;heartbeat_reads=0
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
                    files[p['state']]=(f'A7R5-ROOT-1 {RUN} DONE 0 uid=0 euid=0 bytes={len(text)}\n').encode()
                    if fault=='old_state':files[p['state']]=files[p['state']].replace(RUN.encode(),b'0'*32)
                    if fault=='nonroot':files[p['state']]=files[p['state']].replace(b'uid=0',b'uid=1')
                    files[p['output']]=text
                    files['/etc/ld.so.preload']=b'foreign' if fault=='neutral' else b'\n'*512
                elif command==0x11:
                    if self.selected==p['heartbeat']:
                        self.heartbeat_reads+=1
                        sequence=1 if fault=='frozen' else self.heartbeat_reads
                        elapsed=50000 if fault=='expired' else sequence*5000
                        payload=(f'A7R5_NS_ALIVE {RUN} pid=101 ticks=202 child=303 seq={sequence} elapsed_ms={elapsed} ttl=75 parent_unchanged=1\n').encode()
                    else:payload=files[self.selected]
                    if fault=='helper_readback' and self.selected==p['helper']:payload=b'wrong'
                    if self.selected==p['state']:
                        self.state_reads+=1
                        if fault=='changed_state' and self.state_reads>1:payload=payload.replace(b'DONE',b'RUNNING')
                    if self.selected==p['ready']:
                        self.ready_reads+=1
                        if fault=='changed_ready' and self.ready_reads>1:payload+=b'extra'
                else:raise AssertionError(command)
                content=struct.pack('<I',0)+payload
                self.reply=HEADER.pack(len(content),0x40,seq+(1 if fault=='header' else 0),0,0,0,0)+content
            def read(self,n):
                value=self.reply[:n];self.reply=self.reply[n:];return value
        return Driver(),ns.ProbeOperation(root,dict(run_id=RUN),phase),output

    def test_cross_stop_ready_and_failures_use_real_restricted_protocol(self):
        for fault in ('success','negative','header','baseline','baseline_race','helper_readback','debug_transport',
                      'old_state','nonroot','ready_hash','namespace','frozen','expired','neutral','changed_ready','changed_state'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                driver,operation,output=self.fixture(Path(tmp),fault,'probe');report={};now=[0.0]
                def sleep(seconds):now[0]+=seconds
                with patch.object(ns.time,'monotonic',side_effect=lambda:now[0]),patch.object(ns.time,'sleep',side_effect=sleep):
                    if fault in ('success','negative'):
                        operation(driver,output,lambda *a,**kw:None,report)
                        self.assertTrue(operation.safe_to_stop);self.assertTrue(report['protocol_gate_passed'])
                        self.assertFalse(report['ssh_started']);self.assertFalse(report['account_modified'])
                        self.assertEqual(report['probe_outcome'],'READY_FOR_STOP' if fault=='success' else 'NEGATIVE_CLEAN')
                    else:
                        with self.assertRaises((ValueError,PermissionError,OSError,TimeoutError)):
                            operation(driver,output,lambda *a,**kw:None,report)
                        self.assertFalse(operation.safe_to_stop)
                self.assertLessEqual(driver.debug_count,1)
                if fault in ('baseline','header'):self.assertEqual(driver.write_count,0)
                if fault in ('baseline_race','helper_readback'):self.assertEqual(driver.debug_count,0)

    def test_collect_is_readonly_and_checks_unchanged_terminal_result(self):
        for fault in ('success','parent_changed','not_reaped','trace'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as tmp:
                driver,operation,output=self.fixture(Path(tmp),fault,'collect');report={}
                if fault=='success':
                    operation(driver,output,lambda *a,**kw:None,report)
                    self.assertTrue(operation.safe_to_stop)
                    self.assertEqual(report['nonloopback_ipv4_observed'],[dict(interface='wlan0',address='192.168.1.20')])
                    self.assertFalse(report['lan_reachability_verified'])
                else:
                    with self.assertRaises(ValueError):operation(driver,output,lambda *a,**kw:None,report)
                    self.assertFalse(operation.safe_to_stop)
                    self.assertTrue((output/'guest-result-raw.bin').exists())
                self.assertEqual(driver.debug_count,0);self.assertEqual(driver.write_count,0)


if __name__=='__main__':unittest.main(verbosity=2)
