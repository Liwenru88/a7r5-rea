"""专用libJit事务；完整日志、整分区回读及重复终态通过才开放一次STOP。"""
import hashlib
import json
from pathlib import Path
import re
import time
from libjit_operation import Operation as BaseOperation
from transport import Channel, FileResultError


def validate_journal(raw,run,plan):
    if not raw.endswith(b'\n'):raise ValueError('日志尾部缺失')
    pattern=re.compile(r'A7R5_TRUST '+re.escape(run)+r' ([A-Z_]+) completed=(\d+) offset=(-?\d+) code=(-?\d+)')
    actual=[]
    for line in raw.decode('ascii').splitlines():
        match=pattern.fullmatch(line)
        if match is None:raise ValueError('日志格式或会话不符')
        actual.append((match[1],int(match[2]),int(match[3]),int(match[4])))
    expected=[('PREIMAGE_VERIFIED',0,-1,0)]
    for index,row in enumerate(plan['rows']):
        expected += [('WRITE_BEGIN',index,row['offset'],0),('WRITE_RETURNED',index+1,row['offset'],0)]
        if index==len(plan['rows'])-1 or row['phase']!=plan['rows'][index+1]['phase']:
            expected.append(('PHASE_SYNC_RETURNED',index+1,row['offset'],0))
    expected += [('FULL_LOGICAL_READBACK_MATCH',258,-1,0),('REOPENED_FULL_CAPTURE_MATCH',258,-1,0),('COMPLETED',258,-1,0)]
    if actual!=expected:raise ValueError('日志阶段、计数、偏移或结果不符')
    return True


class Operation(BaseOperation):
    def __init__(self,bundle,channel_factory=Channel,clock=time.monotonic,sleep=time.sleep):
        super().__init__(bundle,channel_factory)
        self.clock,self.sleep=clock,sleep
        self.reads['/tmp/jiritsu/libJit.so']=1048576
        self.reads[self.config['journal_path']]=131072
        self.reads[self.config['readback_path']]=25100288
        self.may_have_written=False
        self.plan=json.loads((self.bundle/'materials/write-plan.json').read_text())
        self.expected_candidate=(self.bundle/'materials/candidate.logical.img').read_bytes()

    def __call__(self,driver,output,log,report):
        self.output=Path(output);channel=self.channel_factory(driver,self,log)
        report.update(trigger_attempts=0,fixed_writes_attempted=0,debug_commands_sent=False,
            preload_written=False,protocol_gate_passed=False,partition_write_may_have_started=False,
            complete_partition_readback_verified=False,worker_timeout_kill=False)
        def read(label,path):
            raw=channel.read(path,self.reads[path]);(self.output/(label+'.bin')).write_bytes(raw);return raw
        def candidate(label,path):
            try:read(label,path)
            except FileResultError as error:
                if error.result!=0x10000006:raise
                log('stat_failed_candidate',path=path,absence_proven=False);return
            raise ValueError('固定路径已有可读内容，不覆盖：'+path)
        def put(path,data):
            if path in self.written:raise PermissionError('禁止重复上传')
            self.written.add(path);report['fixed_writes_attempted']+=1
            if path=='/tmp/jiritsu/libJit.so':
                self.trigger_attempts+=1;self.may_have_written=True
                report.update(trigger_attempts=self.trigger_attempts,partition_write_may_have_started=True)
            channel.put(path,data)
        if hashlib.sha256(read('version','/version.txt')).hexdigest()!=self.config['version_sha256']:raise ValueError('版本不符')
        if hashlib.sha256(read('loader','/usr/lib/libJiritsu.so')).hexdigest()!=self.config['loader_sha256']:raise ValueError('加载库不符')
        baseline=bytes.fromhex(self.config['expected_preload_hex'])
        if read('preload-before','/etc/ld.so.preload')!=baseline:raise ValueError('精确预加载基线不符')
        for index,path in enumerate(['/tmp/jiritsu/libJit.so','/tmp/jbusy',*[self.prefix+s for s in ('.ticket','.claim','.state','.state.new','.output')]]):
            candidate(f'candidate-{index}',path)
        if read('preload-before-upload','/etc/ld.so.preload')!=baseline:raise ValueError('上传前预加载变化')
        put(self.prefix+'.ticket',self.ticket)
        if read('ticket-readback',self.prefix+'.ticket')!=self.ticket:raise ValueError('票据不符')
        put('/tmp/jiritsu/libJit.so',self.payload)
        deadline=self.clock()+self.config['observe_seconds'];terminal=None
        for index in range(100):
            if self.clock()>=deadline:break
            try:raw=read(f'state-{index:03}',self.prefix+'.state')
            except FileResultError as error:
                if error.result!=0x10000006:raise
                self.sleep(.6);continue
            match=re.fullmatch(rb'A7R5-JIT-1 '+self.run.encode()+rb' (RUNNING|DONE|FAILED|TIMEOUT) (\d+) uid=(\d+) euid=(\d+) bytes=(-?\d+) disarmed=(\d+) children=(-?\d+)\n',raw)
            if not match or match.group(3,4)!=(b'0',b'0'):raise ValueError('状态会话或root身份不符')
            if match[1] in (b'FAILED',b'TIMEOUT'):raise RuntimeError('原生任务失败，不STOP、不重试：'+raw.decode().strip())
            if match[1]==b'DONE':
                if match[2]!=b'0' or match.group(6,7)!=(b'1',b'0'):raise ValueError('成功终态门槛不符')
                size=int(match[5])
                if not 0<size<32768:raise ValueError('输出长度无效')
                terminal=raw;break
            self.sleep(.6)
        if terminal is None:raise TimeoutError('只停止主机观察，不终止写入进程，不STOP或重试')
        expected=(self.config['expected_output_begin']+'A7R5_TRUST_COMPLETE '+self.config['candidate_sha256']+
            ' sectors=258 bytes=132096 reopened=1\n'+self.config['expected_output_end']).encode()
        data=read('native-output',self.prefix+'.output')
        if data!=expected or len(data)!=size:raise ValueError('固定原生输出不符')
        journal=read('native-journal',self.config['journal_path']);validate_journal(journal,self.run,self.plan)
        raw=read('partition1.logical',self.config['readback_path'])
        if len(raw)!=25100288 or hashlib.sha256(raw).hexdigest()!=self.config['candidate_sha256'] or raw!=self.expected_candidate:
            raise ValueError('完整分区回读与候选不符，禁止STOP')
        if read('preload-after','/etc/ld.so.preload')!=baseline:raise ValueError('预加载变化')
        if read('state-repeat',self.prefix+'.state')!=terminal:raise ValueError('重复终态变化')
        report.update(protocol_gate_passed=True,root_task_done=True,root_uid=0,root_euid=0,
            preload_unchanged=True,self_unlink_receipt=True,complete_partition_readback_verified=True,
            logical_partition_sha256=hashlib.sha256(raw).hexdigest(),patch_sectors=258,logical_write_bytes=132096,
            shell_output_bytes=len(data),shell_output_sha256=hashlib.sha256(data).hexdigest())
        self.safe_to_stop=True
