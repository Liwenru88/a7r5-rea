"""只有本次批准、macOS管理员和显式设备开关齐全才接入USB。"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import subprocess
import sys

from build import HERE, MODULE, check, digest, regular, safe, save


def approved(directory):
    directory=safe(directory);manifest=check(directory)
    expected=dict(accepted=True,run_id=manifest['run_id'],manifest_sha256=digest(directory/'manifest.json'))
    value=json.loads(regular(directory/'approval.json').read_text())
    if value!=expected:raise PermissionError('没有本次精确批准')
    if any((directory/p).exists()for p in ('ATTEMPT_LOCK','result')):raise FileExistsError('本次已经尝试，不重跑')
    return manifest


def authorize(directory,accept):
    directory=safe(directory);manifest=check(directory)
    if accept!='APPROVE-'+digest(directory/'manifest.json')[:20]:raise PermissionError('本次风险短语不符')
    if any((directory/p).exists()for p in ('ATTEMPT_LOCK','result')):raise FileExistsError('本次已经尝试')
    save(directory/'approval.json',dict(accepted=True,run_id=manifest['run_id'],manifest_sha256=digest(directory/'manifest.json')))
    return dict(approved=True,run_id=manifest['run_id'],camera_IO=False)


def runtime():
    sys.path[:0]=[str(HERE/'runtime'),str(HERE/'vendor/engine/libs'),str(HERE/'vendor/engine/mac')]
    import host_state
    from operation import Operation
    from system_dump import session
    return host_state,Operation,session


@contextmanager
def exclusive():
    neighbor=MODULE.parent/'a7r5-exec'
    lock=safe(neighbor/'ACTIVE_SESSION.lock' if neighbor.is_dir() else HERE/'ACTIVE_SESSION.lock')
    with lock.open('a')as stream:
        fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def run_attempt(directory,host,Operation,session):
    """已批准入口内部的单次流程；测试使用无设备的替身后端。"""
    directory=safe(directory);cfg=json.loads((directory/'config.json').read_text())
    pending=HERE/'PENDING_RECOVERY.json'
    if pending.exists() or (MODULE.parent/'a7r5-exec/PENDING_RECOVERY.json').exists():
        raise PermissionError('有待恢复记录；本模块不解除或绕过')
    (directory/'ATTEMPT_LOCK').mkdir(mode=0o700)
    out=directory/'result';out.mkdir(mode=0o700)
    binding=dict(run_id=cfg['run_id'],directory=str(directory),manifest_sha256=digest(directory/'manifest.json'))
    save(pending,binding)
    result=dict(**binding,execution_succeeded=False,partition_write_may_have_started=False,
        complete_partition_readback_verified=False,host_recovery_verified=False,
        service_stop_attempts=0,automatic_retry=False,automatic_reboot=False,
        worker_timeout_kill=False,screen_confirmation_pending=True)
    operation=None
    try:
        initial=host.snapshot(out,'initial');baseline=cfg['host_baseline']
        if initial.get('kind')!='ordinary' or any(initial.get(k)!=baseline[k]for k in ('location_id','model','media','drivers')):
            raise ValueError('普通USB、型号、端口或完整媒体不符，不打开USB后端')
        operation=Operation(directory);operation.output=out/'session'
        report=session.run_session(out/'session','libusb',_operation=operation)
        save(out/'session-result.json',report)
        for key in ('protocol_gate_passed','fixed_writes_attempted','trigger_attempts','service_stop_attempts',
            'preload_written','debug_commands_sent','preload_unchanged','service_stop_result','service_stop_error',
            'logical_partition_sha256','complete_partition_readback_verified','partition_write_may_have_started',
            'patch_sectors','logical_write_bytes'):
            if key in report:result[key]=report[key]
        proof=host.observe(baseline,lambda label,timeout=5:host.snapshot(out,label,timeout))
        save(out/'host-recovery.json',proof);result['host_recovery_verified']=proof['recovered']
        if not (not report.get('failure') and report.get('protocol_gate_passed') and report.get('complete_partition_readback_verified')
            and report.get('preload_unchanged') and report.get('fixed_writes_attempted')==2
            and report.get('trigger_attempts')==1 and report.get('service_stop_attempts')==1 and proof['recovered']):
            raise RuntimeError(report.get('failure','原生写入、完整回读、STOP或媒体恢复未全部通过'))
        result['execution_succeeded']=True
    except (Exception,KeyboardInterrupt) as error:
        result['failure']=type(error).__name__+': '+str(error)
    finally:
        if operation is not None and operation.may_have_written:result['partition_write_may_have_started']=True
        save(out/'result.json',result)
        if os.geteuid()==0:
            owner=directory.stat()
            for p in [out,*out.rglob('*'),directory/'ATTEMPT_LOCK',pending]:
                if p.is_symlink():raise ValueError('证据路径出现链接')
                os.chown(p,owner.st_uid,owner.st_gid,follow_symlinks=False)
    return result


def execute(directory,device_io=False):
    # 批准与参数检查在runtime导入及任何主机观察之前。
    if not device_io:raise PermissionError('没有显式设备开关')
    approved(directory)
    if sys.platform!='darwin' or os.geteuid()!=0:raise PermissionError('只允许macOS专用Terminal内sudo执行')
    with exclusive():
        host,Operation,session=runtime()
        return run_attempt(directory,host,Operation,session)


def terminal(directory):
    approved(directory)
    if sys.platform!='darwin':raise RuntimeError('专用Terminal入口仅支持macOS')
    subprocess.run(['/usr/bin/open','-a','Terminal',str(safe(directory)/'run-once.command')],check=True)
    return dict(terminal_open_requested=True,automatic_retry=False)


def confirm_screen(directory,normal=False):
    directory=safe(directory);manifest=check(directory)
    if not normal:raise PermissionError('须人工确认屏幕正常')
    result=json.loads(regular(directory/'result/result.json').read_text())
    pending=HERE/'PENDING_RECOVERY.json'
    expected=dict(run_id=manifest['run_id'],directory=str(directory),manifest_sha256=digest(directory/'manifest.json'))
    if not result['execution_succeeded'] or not result['host_recovery_verified'] or any(result[k]!=v for k,v in expected.items()):
        raise ValueError('屏幕正常不能覆盖写入或恢复失败')
    if json.loads(regular(pending).read_text())!=expected:raise ValueError('不是当前待确认记录')
    save(directory/'result/screen-confirmation.json',dict(**expected,screen_normal=True,source='user_explicit_confirmation'))
    pending.unlink()  # 只解除成功会话的本机门禁，永久尝试锁和证据保留。
    return dict(completed=True,camera_IO=False)
