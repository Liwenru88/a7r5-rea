"""无USB、无网络：真实帧交互门槛及原生执行器恢复契约。"""
import hashlib
import json
from pathlib import Path
import resource
import struct
import subprocess
import sys
import tempfile
import time
from unittest.mock import patch
import unittest

SOURCE = Path(__file__).resolve().parents[1]
PACKAGE = SOURCE if (SOURCE/'config.json').exists() else SOURCE/'packages/restart-20261021-01'
sys.path.insert(0,str(PACKAGE))
import restart_operation as restart
from transport import HEADER


class Driver:
    def __init__(self,op,fault=''):
        self.op,self.fault = op,fault
        self.files = {'/version.txt':(PACKAGE/'reference/version.bin').read_bytes(),
                      '/etc/ld.so.preload':op.baseline,op.auto+'/enabled':(op.config['auto_id']+'\n').encode(),
                      op.auto+'/ssh-service.arm64':(PACKAGE/'reference/helper.arm64').read_bytes(),
                      op.auto+'/boot.so':(PACKAGE/'reference/boot.so').read_bytes()}
        if fault=='baseline': self.files['/etc/ld.so.preload']=b'unknown\n'
        if fault=='hook': self.files[op.auto+'/boot.so']=b'corrupt'
        if fault=='existing': self.files[op.ram+'/child-result']=b'old failure evidence\n'
        self.writes,self.debugs,self.beats = [],0,0
        self.selected,self.reply = '',b''

    def start(self):
        op = self.op
        pub = (PACKAGE/'reference/host-public-key').read_bytes()
        banner = b'SSH-2.0-OpenSSH_7.9p1\r\n'
        output = ('A7R5_PRIVATE_LAUNCH '+op.service+' READY\nA7R5_MANUAL_RESTART_OK\n').encode()
        self.files.update({op.prefix+'.state':('A7R5-ROOT-1 '+op.run+' DONE 0 uid=0 euid=0 bytes='+str(len(output))+'\n').encode(),
                          op.prefix+'.output':output,'/etc/ld.so.preload':op.baseline,
                          op.ram+'/ready':('A7R5_PRIVATE_READY '+op.service+' parent=600 child=601 uid=0 euid=0 ttl=0 parent_unchanged=1 private_account_changed=1 parent_ns=mnt:[100] child_ns=mnt:[101] host_public_sha='+hashlib.sha256(pub).hexdigest()+'\n').encode(),
                          op.ram+'/host-public-key':pub,op.ram+'/banner':banner,
                          op.ram+'/started':('A7R5_WILDCARD_STARTED '+op.service+' pid=602 bind=0.0.0.0:2222 listener_observed=1 banner_sha='+hashlib.sha256(banner).hexdigest()+'\n').encode(),
                          op.ram+'/hostkey-copy':('A7R5_RAM_HOSTKEY1 '+op.service+' stage=0 errno=0 verified=1 source_mode=100755 source_uid=0 source_gid=0 source_bytes=505 dest_mode=100600 dest_uid=0 dest_gid=0 dest_bytes=505 dest_tmpfs=1 source_unchanged=1 partial_removed=0 private_key_logged=0\n').encode()})
        if self.fault=='restore':self.files['/etc/ld.so.preload']=op.arm
        if self.fault=='terminal':self.files[op.prefix+'.state']=b'FAILED\n'
        if self.fault=='public':self.files[op.ram+'/host-public-key']=b'untrusted\n'

    def write(self,packet):
        self.op.guard_packet(packet)
        _,function,seq,*_=HEADER.unpack_from(packet)
        body=packet[HEADER.size:];cmd=struct.unpack_from('<HH',body)[1]
        code,data=0,b''
        if cmd==15:
            self.selected=body[5:-1].decode().replace('/tmp/jiritsu/../..','',1)
        elif cmd==16:
            self.files[self.selected]=body[7:];self.writes.append(self.selected)
            if self.fault=='readback' and self.selected.endswith('.so'):self.files[self.selected]=b'corrupt'
        elif cmd==5:
            self.debugs+=1
            if self.fault=='debug_transport':raise OSError('synthetic USB failure')
            self.start()
        elif cmd==17:
            if self.debugs and self.selected==self.op.ram+'/heartbeat':
                self.beats+=1
                elapsed=0 if self.fault=='heartbeat' else self.beats*2000
                self.files[self.selected]=('A7R5_PRIVATE_ALIVE '+self.op.service+' parent=600 child=601 ttl=0 elapsed_ms='+str(elapsed)+' parent_unchanged=1\n').encode()
            if self.selected not in self.files:code=0x10000006
            else:data=self.files[self.selected]
        else:raise AssertionError(cmd)
        raw=struct.pack('<I',code)+data
        self.reply=HEADER.pack(len(raw),function,seq,3,1,2,0)+raw
        return len(packet)

    def read(self,size):
        raw,self.reply=self.reply[:size],self.reply[size:]
        return raw


class Contract(unittest.TestCase):
    def test_fixed_restart_and_fail_closed(self):
        for fault in ('','baseline','hook','existing','readback','debug_transport','terminal','restore','heartbeat','public'):
            with self.subTest(fault=fault),tempfile.TemporaryDirectory() as temp:
                out=Path(temp);op=restart.RestartOperation(out,PACKAGE);driver=Driver(op,fault);report={}
                with patch.object(restart.time,'sleep'):
                    if fault:
                        with self.assertRaises((ValueError,OSError)):
                            op(driver,out,lambda *a,**k:None,report)
                        self.assertFalse(op.safe_to_stop)
                    else:
                        op(driver,out,lambda *a,**k:None,report)
                        self.assertTrue(op.safe_to_stop)
                        self.assertEqual(driver.writes,[op.prefix+'.so','/etc/ld.so.preload'])
                self.assertLessEqual(driver.debugs,1)
                if fault in ('baseline','hook','existing'):self.assertEqual(driver.writes,[])
                if fault=='existing':self.assertTrue((out/'boot-evidence-05.bin').exists())
                self.assertTrue((out/'assessment.json').exists())

    def test_real_executor_restores_original_pointer_before_task(self):
        for wrong in ('','gate','preload'):
            with self.subTest(wrong=wrong),tempfile.TemporaryDirectory() as temp:
                root=Path(temp).resolve();header=root/'root_config.h'
                arm=b'/tmp/fixture-once.so\n';restore=b'/etc/existing-autostart/boot.so\n'
                (root/'preload').write_bytes(b'unknown\n' if wrong=='preload' else arm)
                (root/'gate').write_bytes(b'wrong' if wrong=='gate' else b'/bin/sh\0-c\0/bin/date -s 070421422017.26\0')
                values=dict(RUN_ID='fixture',STATE_PATH=str(root/'state'),OUTPUT_PATH=str(root/'output'),ARM_BYTES=arm.decode(),
                            PRELOAD_PATH=str(root/'preload'),GATE_PATH=str(root/'gate'),TASK_SCRIPT="printf 'HOST_OK\\n'",RESTORE_BYTES=restore.decode())
                header.write_text(''.join('#define '+k+' '+json.dumps(v)+'\n' for k,v in values.items())+'#define TASK_SECONDS 2U\n#define OUTPUT_LIMIT 32768U\n')
                source=root/'root_once.c';source.write_bytes((PACKAGE/'materials/root_once.c').read_bytes())
                binary=root/'contract'
                subprocess.run(['/usr/bin/clang','-Wall','-Wextra','-Werror','-DA7R5_HOST_TEST',str(source),'-o',str(binary)],capture_output=True,check=True,timeout=20)
                def limit():resource.setrlimit(resource.RLIMIT_NOFILE,(128,128))
                done=subprocess.run([str(binary)],capture_output=True,timeout=5,preexec_fn=limit)
                if wrong:
                    self.assertEqual(done.returncode,100 if wrong=='gate' else 92)
                    self.assertEqual((root/'preload').read_bytes(),arm if wrong=='gate' else b'unknown\n')
                    self.assertFalse((root/'output').exists())
                else:
                    self.assertEqual(done.returncode,0)
                    until=time.monotonic()+4
                    while time.monotonic()<until:
                        if (root/'state').exists() and b'DONE 0' in (root/'state').read_bytes():break
                        time.sleep(.02)
                    self.assertIn(b'DONE 0',(root/'state').read_bytes())
                    self.assertEqual((root/'preload').read_bytes(),restore)
                    self.assertEqual((root/'output').read_bytes(),b'HOST_OK\n')


if __name__=='__main__':unittest.main()
