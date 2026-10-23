"""固定只读捕获操作；复用已封存传输，不导入或初始化真实USB后端。"""
import hashlib
from pathlib import Path
import re
import time

from libjit_operation import Operation as BaseOperation
from transport import Channel,FileResultError


class Operation(BaseOperation):
    def __init__(self,bundle,channel_factory=Channel,clock=time.monotonic,sleep=time.sleep):
        super().__init__(bundle,channel_factory)
        self.clock,self.sleep=clock,sleep
        self.reads['/tmp/jiritsu/libJit.so']=1048576
        self.reads[self.config['capture_path']]=25100288
        self.may_have_written=False

    def __call__(self,driver,output,log,report):
        self.output=Path(output);channel=self.channel_factory(driver,self,log)
        report.update(fixed_writes_attempted=0,trigger_attempts=0,partition_writes=0,
            preload_written=False,debug_commands_sent=False,protocol_gate_passed=False)
        def read(label,path):
            raw=channel.read(path,self.reads[path]);(self.output/(label+'.bin')).write_bytes(raw);return raw
        def candidate(label,path):
            try:read(label,path)
            except FileResultError as error:
                if error.result!=0x10000006:raise
                log('stat_failed_candidate',path=path,absence_proven=False);return
            raise ValueError('固定路径已有可读内容，停止')
        if hashlib.sha256(read('version','/version.txt')).hexdigest()!=self.config['version_sha256']:raise ValueError('固件版本未知，不触发捕获')
        if hashlib.sha256(read('loader','/usr/lib/libJiritsu.so')).hexdigest()!=self.config['loader_sha256']:raise ValueError('加载库不符')
        baseline=read('preload-before','/etc/ld.so.preload')
        if baseline not in [bytes.fromhex(r[1])for r in self.config['preload_baselines']]:raise ValueError('预加载未知')
        for i,path in enumerate(['/tmp/jiritsu/libJit.so','/tmp/jbusy',*[self.prefix+s for s in ('.ticket','.claim','.state','.state.new','.output')]]):candidate(f'candidate-{i}',path)
        if read('preload-repeat','/etc/ld.so.preload')!=baseline:raise ValueError('捕获前基线变化')
        for path,data in ((self.prefix+'.ticket',self.ticket),('/tmp/jiritsu/libJit.so',self.payload)):
            self.written.add(path);report['fixed_writes_attempted']+=1
            if path.endswith('/libJit.so'):
                self.may_have_written=True;report['trigger_attempts']=1
            channel.put(path,data)
            if path.endswith('.ticket') and read('ticket-readback',path)!=data:raise ValueError('票据读回不符')
        terminal=None;deadline=self.clock()+60
        for index in range(100):
            if self.clock()>=deadline:break
            try:raw=read(f'state-{index}',self.prefix+'.state')
            except FileResultError as error:
                if error.result!=0x10000006:raise
                self.sleep(.5);continue
            m=re.fullmatch(rb'A7R5-JIT-1 '+self.run.encode()+rb' (RUNNING|DONE|FAILED|TIMEOUT) (\d+) uid=(\d+) euid=(\d+) bytes=(-?\d+) disarmed=(\d+) children=(-?\d+)\n',raw)
            if not m or m.group(3,4)!=(b'0',b'0'):raise ValueError('捕获状态身份不符')
            if m[1] in (b'FAILED',b'TIMEOUT'):raise RuntimeError('捕获失败，保留现场，不重试')
            if m[1]==b'DONE':
                if m[2]!=b'0' or m.group(6,7)!=(b'1',b'0') or not 0<int(m[5])<32768:raise ValueError('捕获终态不符')
                terminal=raw;size=int(m[5]);break
            self.sleep(.5)
        if terminal is None:raise TimeoutError('捕获观察超时，不杀工作进程、不STOP')
        data=read('native-output',self.prefix+'.output')
        pattern=(re.escape(self.config['expected_output_begin'].encode())+rb'A7R5_CAPTURE_COMPLETE ([0-9a-f]{64}) bytes=25100288 twice=1\n'+re.escape(self.config['expected_output_end'].encode()))
        match=re.fullmatch(pattern,data)
        if not match or len(data)!=size:raise ValueError('捕获输出不完整')
        raw=read('partition1.logical',self.config['capture_path'])
        if len(raw)!=25100288 or hashlib.sha256(raw).hexdigest()!=match[1].decode():raise ValueError('备份长度或摘要不符')
        if read('preload-after','/etc/ld.so.preload')!=baseline or read('state-repeat',self.prefix+'.state')!=terminal:raise ValueError('捕获后状态或预加载变化')
        self.safe_to_stop=True
        report.update(protocol_gate_passed=True,root_task_done=True,preload_unchanged=True,
            capture_verified=True,capture_sha256=match[1].decode(),capture_bytes=len(raw),partition_writes=0,
            expected_preload_hex=baseline.hex(),self_unlink_receipt=True)
