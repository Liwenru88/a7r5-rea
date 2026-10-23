"""只允许本次封存路径；载入、触发、停服、回收分别为一次USB会话。"""
import hashlib
import json
from pathlib import Path
import re
import struct
import time
from transport import Channel, FileResultError, HEADER, READ, wire
import policy


class Operation:
    def __init__(self, package, action, channel_factory=Channel):
        self.package, self.action = Path(package), action
        self.config = json.loads((self.package/'config.json').read_text())
        self.materials = self.package/'materials'
        self.build = json.loads((self.materials/'build.json').read_text())
        self.run, self.prefix, self.ram = (self.build[k] for k in ['run_id','prefix','ram_directory'])
        self.reads = {'/version.txt':4096, '/usr/lib/libJiritsu.so':self.config['loader_bytes'],
                      '/etc/ld.so.preload':4096, '/tmp/jiritsu/libJit.so':65536, '/tmp/jbusy':64,
                      self.prefix+'.ticket':128, self.prefix+'.claim':128,
                      self.prefix+'.trigger-state':512, self.prefix+'.trigger-new':512,
                      self.ram+'/stop-request':64}
        self.uploads = {path:(self.materials/name).read_bytes() for path,name in self.build['uploads'].items()}
        self.reads.update({path:len(data) for path,data in self.uploads.items()})
        self.reads.update({self.ram+'/'+name:limit for name,limit in
                          [('ready',1024),('heartbeat',512),('host-public-key',512),('hostkey-check',256),
                           ('banner',256),('started',1024),('result',1024),('child-result',1024),('diagnostic',4096)]})
        self.writes = {'load-once':self.uploads,
                       'start-once':{self.prefix+'.ticket':(self.materials/'ticket.bin').read_bytes(),
                                     '/tmp/jiritsu/libJit.so':(self.materials/'libJit.so').read_bytes()},
                       'stop-once':{self.ram+'/stop-request':self.run.encode()}, 'collect-once':{}}[action]
        self.safe_to_stop = False
        self.permitted_packet = None
        self.output = None
        self.interfaces_seen = 0
        self.channel_factory = channel_factory

    def interface_checked(self, device, interface):
        raw = dict(pid=int(device.idProduct), bus=device.bus, ports=list(device.port_numbers or ()),
                   number=int(interface.bInterfaceNumber), alternate=int(interface.bAlternateSetting),
                   interface_class=int(interface.bInterfaceClass), subclass=int(interface.bInterfaceSubClass),
                   protocol=int(interface.bInterfaceProtocol), endpoints=[dict(address=int(e.bEndpointAddress),
                   attributes=int(e.bmAttributes), max_packet=int(e.wMaxPacketSize), interval=int(e.bInterval)) for e in interface])
        self.interfaces_seen += 1
        if self.output is None:
            raise ValueError('没有本次日志目录')
        (self.output/f'interface-{self.interfaces_seen}.json').write_text(json.dumps(raw,indent=2))
        if raw != self.config['interfaces'].get(f'interface-{self.interfaces_seen}.json'):
            raise ValueError('接口指纹不符，不更换端点')

    def guard_packet(self, packet):
        if packet != self.permitted_packet or len(packet)<HEADER.size+7:
            raise PermissionError('非本次精确请求')
        size,function,sequence,*meta = HEADER.unpack_from(packet)
        body = packet[HEADER.size:]
        allowed = {struct.pack('<HH',0x1001,15)+b'\0'+wire(p)+b'\0' for p in self.reads}
        allowed |= {struct.pack('<HH',0x1001,16)+b'\0\xff\0'+d for d in self.writes.values()}
        if size != len(body) or function != 0x40 or not 1<=sequence<=512 or any(meta) or body not in allowed|{READ}:
            raise PermissionError('禁止额外命令、DEBUG及非白名单路径')

    def __call__(self, driver, output, log, report):
        self.output = Path(output)
        channel = self.channel_factory(driver,self,log)
        attempts = set()
        report.update(fixed_writes_attempted=0, trigger_attempts=0, preload_written=False,
                      debug_commands_sent=False, protocol_gate_passed=False, action=self.action)
        def read(label,path):
            raw = channel.read(path,self.reads[path])
            (self.output/(label+'.bin')).write_bytes(raw)
            return raw
        def absent(label,path):
            try:
                read(label,path)
            except FileResultError as exc:
                if exc.result!=0x10000006:
                    raise
                log('candidate_unreadable',path=path,absence_proven=False)
                return
            raise ValueError('冲突或已有实例：'+path)
        def put(path,data):
            if path in attempts:
                raise PermissionError('不允许重写或重试')
            attempts.add(path)
            report['fixed_writes_attempted']+=1
            if path=='/tmp/jiritsu/libJit.so':
                report['trigger_attempts']+=1
            channel.put(path,data)
        def same(label,path,expected):
            if read(label,path)!=expected:
                raise ValueError('固定内容变化：'+label)
        def neutral(label):
            same(label,'/etc/ld.so.preload',policy.BASELINE)
        def get_ready():
            raw = read('ready',self.ram+'/ready')
            identity = policy.ready(raw,self.run,self.build['ttl_seconds'])
            public = read('host-public-key',self.ram+'/host-public-key')
            policy.public_key(public,identity['public_sha'])
            if self.action in ('stop-once','collect-once'):
                saved = (self.package/'.state/start-once/host-public-key').read_bytes()
                if saved!=public:
                    raise ValueError('已启动实例主机公钥变化')
            return raw,identity,public
        if hashlib.sha256(read('version','/version.txt')).hexdigest()!=self.config['version_sha256']:
            raise ValueError('版本不符')
        if hashlib.sha256(read('loader','/usr/lib/libJiritsu.so')).hexdigest()!=self.config['loader_sha256']:
            raise ValueError('加载库摘要不符')
        neutral('preload-before')
        if self.action=='load-once':
            for number,path in enumerate(self.uploads):
                absent(f'candidate-{number}',path)
            for number,(path,data) in enumerate(self.uploads.items()):
                put(path,data)
                same(f'upload-{number}',path,data)
        elif self.action=='start-once':
            for number,(path,data) in enumerate(self.uploads.items()):
                same(f'loaded-{number}',path,data)
            for number,path in enumerate(['/tmp/jiritsu/libJit.so','/tmp/jbusy',self.prefix+'.ticket',
                                           self.prefix+'.claim',self.prefix+'.trigger-state',self.prefix+'.trigger-new',
                                           self.ram+'/ready',self.ram+'/result']):
                absent(f'candidate-{number}',path)
            neutral('preload-before-trigger')
            put(self.prefix+'.ticket',self.writes[self.prefix+'.ticket'])
            same('ticket',self.prefix+'.ticket',self.writes[self.prefix+'.ticket'])
            put('/tmp/jiritsu/libJit.so',self.writes['/tmp/jiritsu/libJit.so'])
            deadline=time.monotonic()+40
            for number in range(50):
                try:
                    raw=read(f'ready-poll-{number}',self.ram+'/ready')
                except FileResultError as exc:
                    if exc.result!=0x10000006:
                        raise
                else:
                    policy.ready(raw,self.run,self.build['ttl_seconds'])
                    break
                if time.monotonic()>=deadline:
                    raise TimeoutError('启动未READY，不补发')
                time.sleep(.5)
            else:
                raise TimeoutError('启动未READY')
            ready,identity,public=get_ready()
            same('claim',self.prefix+'.claim',(self.materials/'ticket.bin').read_bytes())
            same('hostkey-check',self.ram+'/hostkey-check',b'A7R5_RAM_GENERATED_HOSTKEY verified=1 mode=600 tmpfs=1 private_key_logged=0\n')
            banner=read('banner',self.ram+'/banner')
            if not re.fullmatch(rb'SSH-2\.0-[ -~]+\r?\n',banner):
                raise ValueError('SSH标识不符')
            started=read('started',self.ram+'/started')
            match=re.fullmatch(rb'A7R5_WILDCARD_STARTED '+self.run.encode()+rb' pid=(\d+) bind=0\.0\.0\.0:2222 listener_observed=1 banner_sha=([0-9a-f]{64})\n',started)
            if not match or int(match[1])<=1 or int(match[1]) in (identity['parent'],identity['child']) or match[2].decode()!=hashlib.sha256(banner).hexdigest():
                raise ValueError('监听证据不符')
            first=policy.heartbeat(read('heartbeat-first',self.ram+'/heartbeat'),self.run,identity,self.build['ttl_seconds'])
            time.sleep(2)
            last=policy.heartbeat(read('heartbeat-last',self.ram+'/heartbeat'),self.run,identity,self.build['ttl_seconds'])
            if last<=first:
                raise ValueError('心跳没有前进')
            same('ready-repeat',self.ram+'/ready',ready)
            (self.output.parent/'host-public-key').write_bytes(public)
            report['service_ready']=True
        else:
            ready,identity,public=get_ready()
            if self.action=='stop-once':
                policy.heartbeat(read('heartbeat-before-stop',self.ram+'/heartbeat'),self.run,identity,self.build['ttl_seconds'],allow_changes=True)
                absent('stop-candidate',self.ram+'/stop-request')
                absent('terminal-candidate',self.ram+'/result')
                put(self.ram+'/stop-request',self.run.encode())
            terminal=None
            deadline=time.monotonic()+20
            for number in range(32):
                try:
                    terminal=read(f'terminal-{number}',self.ram+'/result')
                except FileResultError as exc:
                    if exc.result!=0x10000006 or self.action=='collect-once':
                        raise
                else:
                    break
                if time.monotonic()>=deadline:
                    raise TimeoutError('清理回执未完成')
                time.sleep(.5)
            if terminal is None:
                raise TimeoutError('无清理终态')
            child=read('child-terminal',self.ram+'/child-result')
            report.update(policy.terminal(terminal,child,self.run))
            same('terminal-repeat',self.ram+'/result',terminal)
            same('heartbeat-ended',self.ram+'/heartbeat',b'A7R5_PRIVATE_ENDED\n')
            report['service_ended']=True
        neutral('preload-after')
        self.safe_to_stop=True
        report.update(protocol_gate_passed=True,preload_unchanged=True,
                      camera_file_write_commands_sent=bool(attempts))
