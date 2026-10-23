"""仅调用已安装的启动器，不重装账户、密钥或自启钩子。"""
import hashlib
import json
from pathlib import Path
import re
import time

from interface_guard import InterfaceGuard
from transport import Channel, FileResultError
import policy


class RestartOperation(InterfaceGuard):
    def __init__(self, output, bundle):
        self.output, self.bundle = Path(output), Path(bundle)
        self.config = json.loads((self.bundle / 'config.json').read_text())
        self.run = self.config['run_id']
        self.service = self.config['service_run']
        self.prefix = '/tmp/jiritsu/a7r5-' + self.run
        self.ram = '/tmp_network/a7r5-ssh-' + self.service
        self.auto = self.config['auto_dir']
        self.baseline = (self.auto + '/boot.so\n').encode()
        self.arm = (self.prefix + '.so\n').encode()
        self.payload = (self.bundle / 'materials/root.arm64.so').read_bytes()
        self.reads = {'/version.txt':4096, '/etc/ld.so.preload':4096,
                      self.auto+'/enabled':64, self.auto+'/ssh-service.arm64':65536, self.auto+'/boot.so':65536,
                      self.prefix+'.so':len(self.payload), self.prefix+'.state':512,
                      self.prefix+'.output':32768}
        claim = '/tmp_network/a7r5-autostart-' + self.config['auto_id'] + '.claim'
        self.evidence = {claim+'/attempt':256, claim+'/current-boot-suppressed':64,
                         **{self.ram+'/'+n:limit for n,limit in (
                             ('ready',1024),('heartbeat',512),('result',1024),
                             ('child-result',1024),('diagnostic',4096),('started',1024),
                             ('hostkey-copy',1024),('host-public-key',512),('banner',256))}}
        self.reads.update(self.evidence)
        self.writes = {self.prefix+'.so':self.payload, '/etc/ld.so.preload':self.arm}
        self.safe_to_stop = False
        self.interfaces_seen = 0
        self.permitted_packet = None

    def __call__(self, driver, output, log, report):
        channel = Channel(driver, self, log)
        result = {'restart_run':self.run, 'service_run':self.service, 'gate_passed':False,
                  'autostart_repaired':False, 'private_key_read':False}
        def read(label, path):
            raw = channel.read(path, self.reads[path])
            (output/(label+'.bin')).write_bytes(raw)
            return raw
        def expect(label, path, raw):
            if read(label, path) != raw:
                raise ValueError('固定内容不符：'+label)
        def unavailable(label, path):
            try:
                read(label, path)
            except FileResultError as exc:
                if exc.result != 0x10000006:
                    raise
                log('unreadable', label=label, path=path, absence_proven=False)
                return
            raise ValueError('已有实例或残留；仅保存证据，不覆盖：'+label)
        try:
            if hashlib.sha256(read('version','/version.txt')).hexdigest() != self.config['version_sha256']:
                raise ValueError('版本不符')
            expect('preload-before','/etc/ld.so.preload',self.baseline)
            expect('enabled',self.auto+'/enabled',(self.config['auto_id']+'\n').encode())
            helper = read('installed-helper', self.auto+'/ssh-service.arm64')
            if hashlib.sha256(helper).hexdigest() != self.config['helper_sha256']:
                raise ValueError('已安装启动器摘要不符')
            if hashlib.sha256(read('installed-hook',self.auto+'/boot.so')).hexdigest() != self.config['hook_sha256']:
                raise ValueError('原自启库摘要不符，不恢复未知加载库')
            # 全部先落盘；不能在遇到首个残留时丢掉其余启动失败证据。
            present = []
            for index,path in enumerate(self.evidence):
                try:
                    read('boot-evidence-%02d'%index,path)
                    if path.startswith(self.ram+'/'):
                        present.append(path)
                except FileResultError as exc:
                    if exc.result != 0x10000006:
                        raise
                    log('boot_evidence_unreadable',path=path,absence_proven=False)
            if present:
                raise ValueError('RAM实例证据已存在，停止；不得当作空白现场重复启动')
            for suffix in ('.so','.state','.output'):
                unavailable('fresh'+suffix,self.prefix+suffix)
            expect('preload-before-upload','/etc/ld.so.preload',self.baseline)
            channel.put(self.prefix+'.so',self.payload)
            expect('payload-readback',self.prefix+'.so',self.payload)
            expect('preload-before-arm','/etc/ld.so.preload',self.baseline)
            channel.put('/etc/ld.so.preload',self.arm)
            expect('preload-armed','/etc/ld.so.preload',self.arm)
            channel.debug()
            terminal = None
            for index in range(50):
                try:
                    state = read('state-%02d'%index,self.prefix+'.state')
                except FileResultError as exc:
                    if exc.result != 0x10000006:
                        raise
                    state = None
                if state is not None and state != ('A7R5-ROOT-1 '+self.run+' RUNNING 0 uid=0 euid=0 bytes=0\n').encode():
                    terminal = re.fullmatch(rb'A7R5-ROOT-1 '+self.run.encode()+rb' DONE 0 uid=0 euid=0 bytes=(\d{1,5})\n',state)
                    if not terminal or not 0<int(terminal[1])<32768:
                        raise ValueError('启动任务失败或终态不符，不重试')
                    break
                if index < 49:
                    time.sleep(1)
            if terminal is None:
                raise TimeoutError('启动任务未在限时内完成，不重发DEBUG')
            raw = read('worker-output',self.prefix+'.output')
            expected = ('A7R5_PRIVATE_LAUNCH '+self.service+' READY\nA7R5_MANUAL_RESTART_OK\n').encode()
            if len(raw) != int(terminal[1]) or raw != expected:
                raise ValueError('启动回执不符')
            ready = read('ready',self.ram+'/ready')
            identity = policy.ready(ready,self.service)
            policy.hostkey_receipt(read('hostkey-copy',self.ram+'/hostkey-copy'),self.service)
            public = read('host-public-key',self.ram+'/host-public-key')
            if hashlib.sha256(public).hexdigest() != self.config['public_sha256'] or identity['public_sha'] != self.config['public_sha256']:
                raise ValueError('主机公钥不符')
            banner = read('banner',self.ram+'/banner')
            if not re.fullmatch(rb'SSH-2\.0-[ -~]+\r?\n',banner):
                raise ValueError('SSH标识不符')
            started = read('started',self.ram+'/started')
            match = re.fullmatch(rb'A7R5_WILDCARD_STARTED '+self.service.encode()+rb' pid=(\d+) bind=0\.0\.0\.0:2222 listener_observed=1 banner_sha=([0-9a-f]{64})\n',started)
            if not match or int(match[1])<=1 or int(match[1]) in (identity['parent'],identity['child']) or match[2].decode()!=hashlib.sha256(banner).hexdigest():
                raise ValueError('监听回执不符')
            first = policy.heartbeat(read('heartbeat-first',self.ram+'/heartbeat'),self.service,identity)
            time.sleep(2)
            last = policy.heartbeat(read('heartbeat-last',self.ram+'/heartbeat'),self.service,identity)
            if last <= first:
                raise ValueError('心跳未前进')
            expect('ready-repeat',self.ram+'/ready',ready)
            expect('state-repeat',self.prefix+'.state',state)
            expect('preload-after','/etc/ld.so.preload',self.baseline)
            self.safe_to_stop = True
            result.update(gate_passed=True,observer_identity=identity,autostart_pointer_preserved=True)
        finally:
            self.permitted_packet = None
            result.update(file_reads_attempted=channel.reads,fixed_writes_attempted=channel.writes,
                          debug_attempts=channel.debug_attempts)
            report.update(protocol_gate_passed=self.safe_to_stop,preload_neutral_verified=False,
                          camera_file_write_commands_sent=channel.writes>0,
                          debug_commands_sent=channel.debug_attempts>0,**result)
            (output/'assessment.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
