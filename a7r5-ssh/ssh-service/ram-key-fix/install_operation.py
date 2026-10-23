"""固定无TTL安装：全部客体门槛保存成功后才允许一次STOP。"""
import json
from pathlib import Path
import re
import time

from interface_guard import InterfaceGuard
import native_validation
import policy
from transport import Channel,FileResultError

HERE=Path(__file__).resolve().parent


class InstallOperation(InterfaceGuard):
    def __init__(self,output,bundle=None):
        self.output=Path(output);self.bundle=HERE if bundle is None else Path(bundle)
        self.config=json.loads((self.bundle/'config.json').read_text());self.run=self.config['run_id']
        if not re.fullmatch('[0-9a-f]{32}',self.run) or self.run==policy.PREDECESSOR:raise ValueError('新会话不符')
        m=json.loads((self.bundle/'materials/manifest.json').read_text())
        if m['run_id']!=self.run or m['ttl_seconds']!=0 or m['autostart_enabled']:raise ValueError('候选范围不符')
        self.prefix='/tmp/jiritsu/a7r5-'+self.run;self.ram='/tmp_network/a7r5-ssh-'+self.run
        self.uploads={target:(self.bundle/'materials'/name).read_bytes() for name,target in m['upload_map'].items()}
        self.arm=(self.prefix+'.so\n').encode()
        self.writes={**self.uploads,'/etc/ld.so.preload':self.arm}
        self.reads={'/version.txt':4096,'/etc/ld.so.preload':4096,
                    '/tmp/jiritsu/a7r5-'+policy.PREDECESSOR+'.state':512,
                    self.prefix+'.state':512,self.prefix+'.output':32768,
                    **{target:len(raw) for target,raw in self.uploads.items()},
                    **{self.ram+'/'+name:limit for name,limit in (
                        ('hostkey-copy',1024),('ready',1024),('heartbeat',512),('host-public-key',512),
                        ('started',1024),('banner',256),('child-result',1024),('diagnostic',4096))}}
        self.safe_to_stop=False;self.interfaces_seen=0;self.permitted_packet=None

    def __call__(self,driver,output,log,report):
        ch=Channel(driver,self,log)
        result=dict(run_id=self.run,gate_passed=False,ssh_start_attempted_by_host=False,
                    no_ttl=True,autostart_enabled=False,private_key_bytes_transferred_to_mac=False)
        def read(label,path):
            log('fixed_read_attempt',label=label,path=path)
            raw=ch.read(path,self.reads[path]);(output/(label+'.bin')).write_bytes(raw);return raw
        def expect(label,path,wanted):
            raw=read(label,path)
            if raw!=wanted:raise ValueError('固定内容不符：'+label)
            return raw
        try:
            version=read('version','/version.txt')
            if policy.digest(version)!=self.config['version_sha256']:raise ValueError('版本不符')
            expect('preload-before','/etc/ld.so.preload',policy.NEUTRAL)
            expect('predecessor-state','/tmp/jiritsu/a7r5-'+policy.PREDECESSOR+'.state',
                   (self.bundle/'proof/device/session/state-repeat.bin').read_bytes())
            for index,path in enumerate([self.prefix+'.state',self.prefix+'.output',*self.uploads]):
                try:read(f'fresh-{index}',path)
                except FileResultError as exc:
                    if exc.result!=0x10000006:raise
                    log('new_nonce_unreadable',path=path,absence_proven=False)
                else:raise ValueError('新nonce路径已可读，拒绝覆盖')
            for index,(path,raw) in enumerate(self.uploads.items()):
                ch.put(path,raw);expect(f'upload-{index}-readback',path,raw)
            expect('preload-before-arm','/etc/ld.so.preload',policy.NEUTRAL)
            ch.put('/etc/ld.so.preload',self.arm);expect('preload-armed','/etc/ld.so.preload',self.arm)
            ch.debug()
            terminal=None
            for index in range(66):
                try:state=read(f'state-{index:02}',self.prefix+'.state')
                except FileResultError as exc:
                    if exc.result!=0x10000006:raise
                    state=None
                if state is not None:
                    if state!=f'A7R5-ROOT-1 {self.run} RUNNING 0 uid=0 euid=0 bytes=0\n'.encode():
                        terminal=re.fullmatch(rb'A7R5-ROOT-1 '+self.run.encode()+rb' DONE (\d{1,3}) uid=0 euid=0 bytes=(\d{1,5})\n',state)
                        if not terminal or int(terminal[1])>255 or not 0<int(terminal[2])<32768:raise ValueError('root终态失败或不符')
                        break
                if index<65:time.sleep(1)
            if terminal is None:raise TimeoutError('root有界观察到期，不重发DEBUG')
            raw=read('worker-output',self.prefix+'.output')
            if len(raw)!=int(terminal[2]):raise ValueError('root输出长度不符')
            if terminal[1]!=b'0':
                for name in ('hostkey-copy','child-result','diagnostic'):
                    try:read('failure-'+name,self.ram+'/'+name)
                    except FileResultError as exc:
                        if exc.result!=0x10000006:raise
                        log('failure_evidence_unreadable',name=name,absence_proven=False)
                raise ValueError('载荷DONE非零；固定补证结束，不STOP')
            expected=(f'A7R5_PRIVATE_LAUNCH {self.run} READY\nA7R5_SERVICE_STAGED_AUTOSTART_DISABLED\n').encode()
            if raw!=expected:raise ValueError('安装输出未完整通过')
            metadata=read('hostkey-copy',self.ram+'/hostkey-copy')
            result['ram_hostkey']=policy.hostkey_receipt(metadata,self.run)
            ready=read('ready',self.ram+'/ready');identity=policy.ready(ready,self.run)
            public=read('host-public-key',self.ram+'/host-public-key')
            native_validation.public_key(public)
            if policy.digest(public)!=identity['public_sha']:raise ValueError('主机公钥摘要不符')
            (output/'host-public-key').write_bytes(public)
            started=read('started',self.ram+'/started');banner=read('banner',self.ram+'/banner')
            match=re.fullmatch(rb'A7R5_WILDCARD_STARTED '+self.run.encode()+rb' pid=(\d+) bind=0\.0\.0\.0:2222 listener_observed=1 banner_sha=([0-9a-f]{64})\n',started)
            if (not match or int(match[1])<=1 or int(match[1]) in (identity['parent'],identity['child'])
                    or not re.fullmatch(rb'SSH-2\.0-[ -~]+\r?\n',banner) or len(banner)>256
                    or policy.digest(banner).encode()!=match[2]):raise ValueError('监听/banner回执不符')
            first=policy.heartbeat(read('heartbeat-first',self.ram+'/heartbeat'),self.run,identity)
            progressed=False
            for index in range(4):
                time.sleep(1)
                last=policy.heartbeat(read(f'heartbeat-{index}',self.ram+'/heartbeat'),self.run,identity)
                if last<first:raise ValueError('心跳倒退')
                if last>first:progressed=True;break
            if not progressed:raise TimeoutError('后台心跳未前进')
            expect('ready-repeat',self.ram+'/ready',ready)
            expect('hostkey-copy-repeat',self.ram+'/hostkey-copy',metadata)
            expect('state-repeat',self.prefix+'.state',state)
            expect('started-repeat',self.ram+'/started',started)
            expect('preload-after','/etc/ld.so.preload',policy.NEUTRAL)
            result.update(gate_passed=True,host_public_sha256=identity['public_sha'],observer_identity=identity)
        except BaseException as exc:
            result['failure']=type(exc).__name__+': '+str(exc);raise
        finally:
            self.permitted_packet=None
            result.update(file_reads_attempted=ch.reads,fixed_writes_attempted=ch.writes,debug_attempts=ch.debug_attempts,
                          responses_completed=ch.sequence-1)
            report.update(camera_file_write_commands_sent=ch.writes>0,debug_commands_sent=ch.debug_attempts>0,
                          fixed_writes_attempted=ch.writes,debug_attempts=ch.debug_attempts,file_request_attempts=ch.reads)
            (output/'assessment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        self.safe_to_stop=True
        report.update(profile='ram-key-no-ttl-install',protocol_gate_passed=True,ram_hostkey_verified=True,
                      preload_neutral_verified=True,host_public_sha256=identity['public_sha'],observer_identity=identity,
                      ttl_seconds=0,autostart_enabled=False,final_service_cleanup_pending=True)
