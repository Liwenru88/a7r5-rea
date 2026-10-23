"""kit触发适配：原512换行门槛保留，异常不自动补写/STOP。"""
import hashlib
import re
import struct
import time
from libjit_operation import Operation as JitOperation
from transport import Channel,FileResultError,HEADER,READ,wire

NEUTRAL=b'\n'*512
DEBUG=struct.pack('<HH',0x1001,5)+b'\0\0\0'


class Operation(JitOperation):
    def __init__(self,bundle,channel_factory=Channel):
        # 共用已验证的端口、接口指纹记录和通道，不执行libJit的上传路径。
        import json
        from pathlib import Path
        self.bundle=Path(bundle);self.config=json.loads((self.bundle/'config.json').read_text())
        self.run=self.config['run_id'];self.prefix='/tmp/jiritsu/a7r5-'+self.run
        self.payload=(self.bundle/'materials/payload.so').read_bytes();self.output=None
        self.interfaces_seen=0;self.permitted_packet=None;self.safe_to_stop=False;self.channel_factory=channel_factory
        self.arm=(self.prefix+'.so\n').encode();self.debug_attempted=False;self.allow_debug=False
        self.reads={'/version.txt':4096,'/usr/lib/libJiritsu.so':self.config['loader_bytes'],'/etc/ld.so.preload':4096,
                    '/tmp/jbusy':64,self.prefix+'.so':131072,self.prefix+'.state':512,
                    self.prefix+'.state.new':512,self.prefix+'.output':32768}
        self.writes={self.prefix+'.so':self.payload,'/etc/ld.so.preload':self.arm}

    def guard_packet(self,packet):
        if packet[HEADER.size:]==DEBUG:
            if not self.allow_debug or packet!=self.permitted_packet:raise PermissionError('未开放DEBUG或重复触发')
            size,function,sequence,*meta=HEADER.unpack_from(packet)
            if size!=len(DEBUG) or function!=64 or any(meta) or not 1<=sequence<=512:raise PermissionError('DEBUG帧不符')
        else:super().guard_packet(packet)

    def __call__(self,driver,output,log,report):
        from pathlib import Path
        self.output=Path(output);channel=self.channel_factory(driver,self,log)
        report.update(trigger_attempts=0,fixed_writes_attempted=0,debug_commands_sent=False,
                      preload_written=False,protocol_gate_passed=False)
        def read(label,path):
            raw=channel.read(path,self.reads[path]);(self.output/(label+'.bin')).write_bytes(raw);return raw
        def put(path,data):
            report['fixed_writes_attempted']+=1
            if path=='/etc/ld.so.preload':report['preload_written']=True
            channel.put(path,data)
        if hashlib.sha256(read('version','/version.txt')).hexdigest()!=self.config['version_sha256']:raise ValueError('版本不符')
        if hashlib.sha256(read('loader','/usr/lib/libJiritsu.so')).hexdigest()!=self.config['loader_sha256']:raise ValueError('加载库不符')
        if read('preload-before','/etc/ld.so.preload')!=NEUTRAL:raise PermissionError('kit只接受512换行，不覆盖自启或未知预加载')
        for i,path in enumerate(['/tmp/jbusy',self.prefix+'.so',self.prefix+'.state',self.prefix+'.state.new',self.prefix+'.output']):
            try:read('candidate-'+str(i),path)
            except FileResultError as exc:
                if exc.result!=0x10000006:raise
                log('stat_failed_candidate',path=path,absence_proven=False)
            else:raise ValueError('本次固定路径已有可读内容')
        put(self.prefix+'.so',self.payload)
        if read('payload-readback',self.prefix+'.so')!=self.payload:raise ValueError('载荷读回不符')
        if read('preload-before-arm','/etc/ld.so.preload')!=NEUTRAL:raise ValueError('预加载变化')
        put('/etc/ld.so.preload',self.arm)
        if read('preload-armed','/etc/ld.so.preload')!=self.arm:raise ValueError('预加载读回不符')
        self.allow_debug=True;self.debug_attempted=True
        report.update(trigger_attempts=1,debug_commands_sent=True)
        try:channel.exchange(DEBUG,4)
        finally:self.allow_debug=False
        terminal=None;deadline=time.monotonic()+self.config['task_seconds']+20
        for i in range(200):
            if time.monotonic()>=deadline:break
            try:raw=read(f'state-{i:03}',self.prefix+'.state')
            except FileResultError as exc:
                if exc.result!=0x10000006:raise
                time.sleep(.2);continue
            match=re.fullmatch(rb'A7R5-ROOT-1 '+self.run.encode()+rb' (RUNNING|DONE|FAILED|TIMEOUT) (\d+) uid=(\d+) euid=(\d+) bytes=(-?\d+)\n',raw)
            if not match or match.group(3,4)!=(b'0',b'0'):raise ValueError('旧状态或非root')
            if match[1] in (b'FAILED',b'TIMEOUT'):raise RuntimeError('kit任务失败，不自动STOP')
            if match[1]==b'DONE':
                size=int(match[5])
                if match[2]!=b'0' or not 0<size<32768:raise ValueError('退出码或输出长度不符')
                terminal=raw;break
            time.sleep(.2)
        if terminal is None:raise TimeoutError('kit没有完整成功终态')
        raw=read('shell-output',self.prefix+'.output')
        if len(raw)!=size or not raw.startswith(self.config['expected_output_begin'].encode()) or not raw.endswith(self.config['expected_output_end'].encode()):raise ValueError('输出或标记不符')
        if read('preload-after','/etc/ld.so.preload')!=NEUTRAL:raise ValueError('未中和到512换行')
        if read('state-repeat',self.prefix+'.state')!=terminal:raise ValueError('重复终态不同')
        self.safe_to_stop=True
        report.update(root_task_done=True,root_uid=0,root_euid=0,protocol_gate_passed=True,
                      preload_neutral_verified=True,shell_output_bytes=size,
                      shell_output_sha256=hashlib.sha256(raw).hexdigest())
