"""libJit简化执行与kit原有恢复门槛；导入不初始化设备。"""
from contextlib import contextmanager
import fcntl
import json
import os
from pathlib import Path
import sys

import core


@contextmanager
def exclusive():
    path=core.safe(core.HERE/'ACTIVE_SESSION.lock')
    with path.open('a') as handle:
        fcntl.flock(handle,fcntl.LOCK_EX|fcntl.LOCK_NB)
        yield


def snapshot_runtime():
    sys.path.insert(0,str(core.HERE/'runtime'))
    import host_state
    return host_state


def camera_session(directory,op):
    sys.path[:0]=[str(core.HERE/'runtime'),str(core.HERE/'vendor/engine/libs'),str(core.HERE/'vendor/engine/mac')]
    from system_dump import session
    if op['engine']=='libjit':from libjit_operation import Operation
    else:from kit_operation import Operation
    operation=Operation(directory);operation.output=directory/'result/session'
    return session.run_session(directory/'result/session','libusb',_operation=operation)


def execute(directory,device_io=False):
    directory=core.safe(directory)
    if not device_io:raise PermissionError('没有显式设备开关，不观察设备')
    op=core.load(directory)
    simple=op['engine']=='libjit'
    if not simple:op=core.approved(directory)
    if sys.platform!='darwin' or os.geteuid()!=0:raise PermissionError('仅允许macOS Terminal本机sudo执行')
    with exclusive():
        pending=core.HERE/'PENDING_RECOVERY.json'
        if not simple:
            if pending.exists():raise PermissionError('另有未完成屏幕确认或待恢复会话，禁止新尝试')
            (directory/'ATTEMPT_LOCK').mkdir(mode=0o700)
        out=directory/'result';out.mkdir(mode=0o700)
        binding=dict(run_id=op['run_id'],directory=str(directory),operation_sha256=core.sha(directory/'operation.json'))
        if not simple:core.save(pending,binding)
        result=dict(**binding,engine=op['engine'],execution_succeeded=False,protocol_gate_passed=False,
                    fixed_writes_attempted=0,trigger_attempts=0,service_stop_attempts=0,preload_written=False,
                    debug_commands_sent=False,host_recovery_verified=False,screen_confirmation_pending=not simple,
                    automatic_retry=False,script_is_sandboxed=False)
        try:
            host=snapshot_runtime();baseline=json.loads((directory/'config.json').read_text())['host_baseline']
            initial=host.snapshot(out,'initial')
            if (initial.get('kind')!='ordinary' or initial['location_id']!=baseline['location_id']
                    or initial['media']!=baseline['media'] or initial['drivers']!=baseline['drivers']):
                raise ValueError('普通USB、端口或完整媒体基线不同，不打开USB')
            report=camera_session(directory,op)
            core.save(out/'session-result.json',report)
            for key in ['protocol_gate_passed','fixed_writes_attempted','trigger_attempts','service_stop_attempts',
                        'preload_written','debug_commands_sent','root_task_done','root_uid','root_euid',
                        'preload_unchanged','preload_neutral_verified','shell_output_bytes','shell_output_sha256',
                        'service_stop_result','service_stop_error']:
                if key in report:result[key]=report[key]
            # 传输异常后不追加协议请求；这里只观察主机。
            proof=host.observe(baseline,lambda label,timeout=5:host.snapshot(out,label,timeout))
            core.save(out/'host-recovery.json',proof);result['host_recovery_verified']=proof['recovered']
            expected_preload=report.get('preload_unchanged') if op['engine']=='libjit' else report.get('preload_neutral_verified')
            result['execution_succeeded']=bool(not report.get('failure') and report.get('protocol_gate_passed')
                and report.get('root_task_done') and report.get('trigger_attempts')==1
                and report.get('fixed_writes_attempted')==2 and report.get('service_stop_attempts')==1
                and expected_preload and proof['recovered'])
            if not result['execution_succeeded']:raise RuntimeError(report.get('failure','任务或主机恢复门槛未全部通过'))
        except (Exception,KeyboardInterrupt) as exc:
            result['failure']=type(exc).__name__+': '+str(exc)
        finally:
            core.save(out/'result.json',result)
            owner=directory.stat()
            paths=[out,*out.rglob('*'),core.HERE/'ACTIVE_SESSION.lock']
            if not simple:paths+=[directory/'ATTEMPT_LOCK',pending]
            for path in paths:
                if path.is_symlink():raise ValueError('输出出现链接')
                os.chown(path,owner.st_uid,owner.st_gid,follow_symlinks=False)
        return result


def confirm_screen(directory,screen_normal=False):
    directory=core.safe(directory)
    if not screen_normal:raise PermissionError('须人工确认屏幕正常')
    with exclusive():
        op=core.load(directory)
        if op['engine']=='libjit':raise ValueError('libJit无需屏幕确认；请直接查看执行结果')
        result=json.loads(core.regular(directory/'result/result.json').read_text())
        expected=dict(run_id=op['run_id'],directory=str(directory),operation_sha256=core.sha(directory/'operation.json'))
        if any(result.get(k)!=v for k,v in expected.items()) or not result['execution_succeeded'] or not result['host_recovery_verified']:
            raise ValueError('不能用屏幕确认覆盖任务或主机恢复失败')
        approval=json.loads(core.regular(directory/'approval.json').read_text())
        if approval!=core.approval_for(directory,op,True):raise ValueError('批准不符')
        pending=core.HERE/'PENDING_RECOVERY.json'
        if json.loads(core.regular(pending).read_text())!=expected:raise ValueError('不是当前待确认会话')
        core.save(directory/'result/screen-confirmation.json',dict(**expected,screen_normal=True,source='user_explicit_confirmation'))
        pending.unlink()  # 仅解除本工具的本机门禁，保留会话永久尝试锁和全部日志。
        return dict(screen_normal=True,completed=True,run_id=op['run_id'],camera_requests=0)
