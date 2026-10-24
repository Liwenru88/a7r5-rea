"""固定工作区元数据诊断；不读取更新器，不据此认定旧工作进程已经结束。"""
import hashlib
import re

from capture_operation import Operation as CaptureOperation


class Operation(CaptureOperation):
    payload_marker=b'A7R5_WORK_PROBE_READONLY_V2_RAM_BOOTSTRAP'
    cleanup_after_capture=False

    def __init__(self,bundle,**kwargs):
        super().__init__(bundle,**kwargs)
        if self.config.get('capture_control_layout')!='ram-v2':raise ValueError('诊断必须使用新版RAM控制文件')
        for path,_ in self.parts:self.reads.pop(path)
        self.parts=[]
        self.reads[self.prefix+'.work-root']=16896

    def collect(self,read,report,baseline):
        terminal,size=self.wait_terminal(read,report)
        output=read('probe-output',self.prefix+'.output')
        pattern=(re.escape(('A7R5_WORK_PROBE_BEGIN '+self.run+'\n').encode())+
            rb'A7R5_WORK_PROBE fs_type=(\d+) fs_flags=(\d+) available_bytes=(\d+) memory_available_kib=(-?\d+) root_slots=512 free_slots=(\d+) max_free_run=(\d+) snapshot_bytes=16896 sha256=([0-9a-f]{64})\n'+
            re.escape(('A7R5_WORK_PROBE_END '+self.run+'\n').encode()))
        match=re.fullmatch(pattern,output)
        if not match or len(output)!=size:raise ValueError('工作区诊断输出不完整')
        raw=read('work-root',self.prefix+'.work-root')
        if len(raw)!=16896 or hashlib.sha256(raw).hexdigest()!=match[7].decode():raise ValueError('工作区目录元数据摘要不符')
        if read('preload-after','/etc/ld.so.preload')!=baseline or read('state-repeat',self.prefix+'.state')!=terminal:
            raise ValueError('诊断后状态或预加载变化')
        fields=[int(match[index]) for index in range(1,7)]
        if fields[0]!=0x4d44 or not 0<=fields[5]<=fields[4]<=512:raise ValueError('工作区诊断字段异常')
        report.update(work_probe_verified=True,preload_unchanged=True,root_task_done=True,
            work_filesystem_type=fields[0],work_read_only=bool(fields[1]&1),work_available_bytes=fields[2],
            memory_available_kib=fields[3],root_free_slots=fields[4],root_max_free_run=fields[5],
            metadata_sha256=match[7].decode(),partition_writes=0,old_worker_exit_verified=False)
        # 本诊断不证明此前工作进程已结束，始终不开放STOP。
        self.safe_to_stop=False
