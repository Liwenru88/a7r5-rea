"""stock-absence 信任写入任务协议（本仓库 258/233 通用）；改编自 a7rv-workbench Apache-2.0 模板。"""

import hashlib
import base64
import json
import os
from pathlib import Path
import re
import time
from libjit_operation import Operation as BaseOperation
from transport import Channel, FileResultError
from common import save,write_payload


def persist_readback_progress(output,checkpoint,chunk=None):
    if chunk is not None:
        fd=os.open(chunk,os.O_RDWR|os.O_NOFOLLOW)
        try:os.fchmod(fd,0o600);os.fsync(fd)
        finally:os.close(fd)
    pending=output/'.trust-readback-checkpoint.new'
    save(pending,checkpoint);os.replace(pending,output/'trust-readback-checkpoint.json')
    fd=os.open(output,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
    try:os.fsync(fd)
    finally:os.close(fd)


def validate_journal(raw,run,plan,*,force=False):
    if not raw.endswith(b'\n'):raise ValueError('日志尾部缺失')
    pattern=re.compile(r'A7R5_TRUST '+re.escape(run)+r' ([A-Z_]+) completed=(\d+) offset=(-?\d+) code=(-?\d+)')
    actual=[]
    for line in raw.decode('ascii').splitlines():
        match=pattern.fullmatch(line)
        if match is None:raise ValueError('日志格式或会话不符')
        actual.append((match[1],int(match[2]),int(match[3]),int(match[4])))
    expected=[('FORCE_PREIMAGE_CAPTURED' if force else 'PREIMAGE_VERIFIED',0,-1,0)]
    for index,row in enumerate(plan['rows']):
        expected += [('WRITE_BEGIN',index,row['offset'],0),('WRITE_RETURNED',index+1,row['offset'],0)]
        if index==len(plan['rows'])-1 or row['phase']!=plan['rows'][index+1]['phase']:
            expected.append(('PHASE_SYNC_RETURNED',index+1,row['offset'],0))
    total=len(plan['rows'])
    expected += [('FULL_LOGICAL_READBACK_MATCH',total,-1,0),('REOPENED_FULL_CAPTURE_MATCH',total,-1,0),('COMPLETED',total,-1,0)]
    if actual!=expected:raise ValueError('日志阶段、计数、偏移或结果不符')
    return True

# 摘要由 config.json 提供（本仓库为 1c97db… → 745b5ce9…）
class Operation(BaseOperation):
    packet_limit=4096
    usb_read_size=8192
    strict_usb_reads=True
    MARKER=b'A7R5_TRUST_STOCK_V1_FULL_16K'
    def __init__(self,bundle,channel_factory=Channel,clock=time.monotonic,sleep=time.sleep):
        super().__init__(bundle,channel_factory)
        if self.config.get('force_install')is not False:raise ValueError('Force mode is forbidden')
        if self.config.get('preload_policy')!='stock-absent-v1' or self.config.get('trust_readback_format')!='stock-full-16k-v1':raise ValueError('Policy mismatch')
        self.source_sha=self.config.get('source_sha256');self.candidate_sha=self.config.get('candidate_sha256')
        if not (isinstance(self.source_sha,str) and re.fullmatch('[0-9a-f]{64}',self.source_sha) and isinstance(self.candidate_sha,str) and re.fullmatch('[0-9a-f]{64}',self.candidate_sha)):raise ValueError('Image binding missing')
        self.configure_ram_control('ram-v2',self.MARKER)
        self.clock,self.sleep=clock,sleep;self.may_have_written=False
        self.force=False;plan_raw=(self.bundle/'materials/write-plan.json').read_bytes()
        if self.config.get('plan_sha256') and hashlib.sha256(plan_raw).hexdigest()!=self.config['plan_sha256']:raise ValueError('Plan identity changed')
        self.plan=json.loads(plan_raw)
        self.source=(self.bundle/'materials/source.logical.img').read_bytes()
        self.expected_candidate=(self.bundle/'materials/candidate.logical.img').read_bytes()
        if len(self.source)!=25100288 or len(self.expected_candidate)!=25100288 or hashlib.sha256(self.source).hexdigest()!=self.source_sha or hashlib.sha256(self.expected_candidate).hexdigest()!=self.candidate_sha:raise ValueError('Full images changed')
        self.validate_plan()
        self.reads['/tmp/jiritsu/libJit.so']=1048576;self.reads['/tmp/ld.so.preload']=4096
        self.reads[self.config['journal_path']]=131072
        self.chunks=int(self.config['chunks']);self.chunk_bytes=int(self.config['chunk_bytes'])
        self.parts=[(self.config['readback_path']+'.part-'+str(i),self.chunk_bytes)for i in range(self.chunks)]
        self.reads.update(self.parts)
    def validate_plan(self):
        p=self.plan
        count=len(p['rows'])
        if (p.get('source_sha256')!=self.source_sha or p.get('candidate_sha256')!=self.candidate_sha or
            p.get('partition_bytes')!=25100288 or p.get('changed_sectors')!=count or p.get('logical_write_bytes')!=count*512 or
            p.get('automatic_retry')is not False or p.get('automatic_rollback')is not False):raise ValueError('Unbound write plan')
        rows=p['rows'];offsets=[r['offset']for r in rows]
        actual={i for i in range(0,25100288,512)if self.source[i:i+512]!=self.expected_candidate[i:i+512]}
        if len(rows)!=count or len(set(offsets))!=count or set(offsets)!=actual:raise ValueError('Plan scope mismatch')
        phases=[r['phase']for r in rows]
        if count and phases!=['initrd']*(count-1)+['checksum']:raise ValueError('Phase ordering mismatch')
        for r in rows:
            at=r['offset']
            if at%512 or not 0<=at<=25100288-512 or r['bytes']!=512:raise ValueError('Invalid sector')
            if hashlib.sha256(self.source[at:at+512]).hexdigest()!=r['before_sha256']or hashlib.sha256(self.expected_candidate[at:at+512]).hexdigest()!=r['after_sha256']:raise ValueError('Sector hash mismatch')
    def __call__(self,driver,output,log,report):
        self.output=Path(output);channel=self.channel_factory(driver,self,log)
        report.update(fixed_writes_attempted=0,trigger_attempts=0,preload_written=False,debug_commands_sent=False,
            protocol_gate_passed=False,partition_write_may_have_started=False,native_write_complete=False,
            force_install=False,trust_control_layout='ram-v2',trust_readback_format='stock-full-16k-v1',
            complete_partition_readback_verified=False,worker_timeout_kill=False)
        def read(label,path):
            raw=channel.read(path,self.reads[path]);(self.output/(label+'.bin')).write_bytes(raw);return raw
        def service_preload_unknown(label):
            for i,path in enumerate(['/etc/ld.so.preload','/tmp/ld.so.preload']):
                try:read(label+'-'+str(i),path)
                except FileResultError as error:
                    if error.result!=0x10000006:raise
                    log('preload_service_unknown',path=path,absence_proven=False)
                else:raise ValueError('Preload became readable; refuse stock-absence operation')
        def candidate(label,path):
            try:read(label,path)
            except FileResultError as error:
                if error.result!=0x10000006:raise
                log('stat_failed_candidate',path=path,absence_proven=False);return
            raise ValueError('Fixed path already readable; do not overwrite: '+path)
        def put(path,data):
            if path in self.written:raise PermissionError('No repeated upload')
            self.written.add(path);report['fixed_writes_attempted']+=1
            if path=='/tmp/jiritsu/libJit.so':
                self.may_have_written=True;report.update(trigger_attempts=1,partition_write_may_have_started=True)
            channel.put(path,data)
        if hashlib.sha256(read('version','/version.txt')).hexdigest()!=self.config['version_sha256']:raise ValueError('Version mismatch')
        if hashlib.sha256(read('loader','/usr/lib/libJiritsu.so')).hexdigest()!=self.config['loader_sha256']:raise ValueError('Loader mismatch')
        service_preload_unknown('preload-before')
        for i,path in enumerate(['/tmp/jiritsu/libJit.so','/tmp/jbusy',self.ticket_path,*[self.prefix+s for s in ('.claim','.state','.state.new','.output')]]):candidate('candidate-'+str(i),path)
        service_preload_unknown('preload-before-upload')
        put(self.ticket_path,self.ticket)
        if read('ticket-readback',self.ticket_path)!=self.ticket:raise ValueError('Ticket mismatch')
        put('/tmp/jiritsu/libJit.so',self.payload)
        terminal=None;deadline=self.clock()+self.config['observe_seconds']
        for i in range(100):
            if self.clock()>=deadline:break
            try:raw=read('state-'+str(i),self.prefix+'.state')
            except FileResultError as e:
                if e.result!=0x10000006:raise
                self.sleep(.6);continue
            m=re.fullmatch(rb'A7R5-JIT-1 '+self.run.encode()+rb' (RUNNING|DONE|FAILED|TIMEOUT) (\d+) uid=(\d+) euid=(\d+) bytes=(-?\d+) disarmed=(\d+) children=(-?\d+)'
                rb'(?: precheck_reason=(\d+) precheck_pid=(-?\d+) precheck_fd=(-?\d+) precheck_error=(-?\d+) precheck_device=(\d+) partition_writes=(0)'
                rb'| resource_reason=(\d+) resource_error=(-?\d+) memory_available_kib=(-?\d+) memory_required_kib=(\d+) ram_available_bytes=(-?\d+) partition_writes=(0))?\n',raw)
            if not m or m.group(3,4)!=(b'0',b'0'):raise ValueError('Malformed worker status')
            if m[1]in (b'FAILED',b'TIMEOUT'):
                report['native_failure_status']=raw.decode('ascii');raise RuntimeError('Worker failed; preserve state, no STOP or retry')
            if m[1]==b'DONE':
                if m[2]!=b'0'or m.group(6,7)!=(b'1',b'0')or not 0<int(m[5])<32768 or m[8]is not None or m[14]is not None:raise ValueError('Invalid completion status')
                terminal=raw;size=int(m[5]);break
            self.sleep(.6)
        if terminal is None:raise TimeoutError('Only host observation stops; do not kill worker or retry')
        data=read('native-output',self.prefix+'.output')
        count=len(self.plan['rows'])
        expected=(self.config['expected_output_begin']+'A7R5_TRUST_STOCK_COMPLETE '+self.candidate_sha+f' sectors={count} bytes={count*512} reopened=1 chunks={self.chunks} chunk_bytes={self.chunk_bytes} preload=absent-v1\n'+self.config['expected_output_end']).encode()
        if data!=expected or len(data)!=size:raise ValueError('Native attestation mismatch')
        journal=read('native-journal',self.config['journal_path']);validate_journal(journal,self.run,self.plan,force=False)
        report.update(native_write_complete=True,native_full_readback_verified=True,native_reopened_readback_verified=True,
            native_logical_partition_sha256=self.candidate_sha,logical_sectors_written=count,logical_write_bytes=count*512)
        receipt=dict(run_id=self.run,source_sha256=self.source_sha,candidate_sha256=self.candidate_sha,
            terminal_sha256=hashlib.sha256(terminal).hexdigest(),journal_sha256=hashlib.sha256(journal).hexdigest())
        save(self.output/'trust-native-verified.json',receipt)
        digest=hashlib.sha256();raw=bytearray();report.update(trust_readback_state='downloading',trust_readback_completed_chunks=0,trust_readback_total_chunks=self.chunks)
        checkpoint=dict(receipt,completed_chunks=0,completed_bytes=0,host_verified=False)
        try:
            for index,(path,n)in enumerate(self.parts):
                label='readback-'+str(index);part=read(label,path)
                if len(part)!=n:raise ValueError('Short readback chunk')
                if part!=self.expected_candidate[index*self.chunk_bytes:(index+1)*self.chunk_bytes]:raise ValueError('Readback bytes differ from candidate')
                raw.extend(part);digest.update(part);checkpoint.update(completed_chunks=index+1,completed_bytes=len(raw),completed_sha256=digest.hexdigest())
                persist_readback_progress(self.output,checkpoint,self.output/(label+'.bin'));report['trust_readback_completed_chunks']=index+1
            if len(raw)!=25100288 or digest.hexdigest()!=self.candidate_sha or raw!=self.expected_candidate:raise ValueError('Full readback mismatch')
            service_preload_unknown('preload-after')
            if read('state-repeat',self.prefix+'.state')!=terminal:raise ValueError('Worker state changed')
            destination=self.output/'partition1.readback.bin'
            fd=os.open(destination,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
            with os.fdopen(fd,'wb')as f:
                f.write(raw);f.flush();os.fsync(f.fileno())
                if hasattr(__import__('fcntl'),'F_FULLFSYNC'):__import__('fcntl').fcntl(f,__import__('fcntl').F_FULLFSYNC)
            if hashlib.sha256(destination.read_bytes()).hexdigest()!=self.candidate_sha:raise ValueError('Persisted readback mismatch')
            checkpoint.update(host_verified=True);persist_readback_progress(self.output,checkpoint)
        except BaseException:
            report['trust_readback_state']='failed';raise
        report.update(protocol_gate_passed=True,root_task_done=True,preload_unchanged=True,preload_state='absent-v1',
            self_unlink_receipt=True,complete_partition_readback_verified=True,trust_readback_state='complete',
            logical_partition_sha256=self.candidate_sha,readback_persisted=True)
        self.safe_to_stop=True
