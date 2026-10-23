"""仅在批准与一次性锁之后加载；复用封存的 A7R5 USB 协议引擎。"""
import json
import os
import re
import time
from pathlib import Path

from lab import ROOT, digest, engine, parse_preflight, save
from recovery import RecoveryPending, observe_recovery, parse_host_tree


def host_snapshot(*, timeout=15):
    import plistlib
    import subprocess
    tree=plistlib.loads(subprocess.run(['/usr/sbin/ioreg','-a','-l','-r','-c','IOUSBHostDevice'],
                                     capture_output=True,check=True,timeout=timeout).stdout)
    return parse_host_tree(tree)


class PreflightOperation:
    def __init__(self, directory, operation):
        self.directory=Path(directory); self.operation=operation; self.safe_to_stop=False

    def __call__(self,driver,output,log,report):
        engine()
        from system_dump.restricted import RestrictedChannel,Deployment,neutral,MAX_ARTIFACT
        from system_dump.session import FileResultError
        ports=tuple(driver.device.port_numbers or ())
        location=(driver.device.bus<<24)|sum(p<<(20-4*i) for i,p in enumerate(ports))
        if not ports or location!=0x01100000: raise ValueError('实机端口变化')
        run=self.operation['run_id']; prefix='/tmp/jiritsu/a7r5-'+run
        payload=(self.directory/'preflight.arm64.so').read_bytes()
        writes={prefix+'.so':(payload,),'/etc/ld.so.preload':((prefix+'.so\n').encode(),neutral)}
        reads={prefix+'.so':MAX_ARTIFACT,'/etc/ld.so.preload':4096,'/version.txt':4096,prefix+'.state':512,prefix+'.output':32768}
        class Exact(RestrictedChannel):
            baseline=False
            def read(self,path,limit):
                raw=super().read(path,limit)
                if path=='/etc/ld.so.preload' and not self.baseline:
                    if raw!=neutral: raise PermissionError('预加载不是精确512换行基线')
                    self.baseline=True
                return raw
        ch=Exact(driver,writes,reads,log); deploy=Deployment(ch,run,payload,output,False)
        try:
            deploy.arm(); deploy.trigger()
            deadline=time.monotonic()+65
            while time.monotonic()<deadline:
                try: raw=ch.read(prefix+'.state',512)
                except FileResultError as exc:
                    if exc.result!=0x10000006: raise
                    time.sleep(.2); continue
                m=re.fullmatch(rb'A7R5-ROOT-1 ([0-9a-f]{32}) (RUNNING|DONE|FAILED|TIMEOUT) ([0-9]+) uid=([0-9]+) euid=([0-9]+) bytes=(-?[0-9]+)\n',raw)
                if not m or m[1].decode()!=run or (m[4],m[5])!=(b'0',b'0'): raise ValueError('旧会话、非root或状态格式不符')
                (output/'last-state.txt').write_bytes(raw)
                if m[2] in (b'FAILED',b'TIMEOUT'): raise RuntimeError('预检执行失败，不自动STOP')
                if m[2]==b'DONE':
                    if m[3]!=b'0' or not 0<=int(m[6])<32768: raise ValueError('脚本失败或输出超限')
                    data=ch.read(prefix+'.output',32768)
                    if len(data)!=int(m[6]): raise ValueError('输出长度不符')
                    (output/'preflight-output.txt').write_bytes(data)
                    assessment=parse_preflight(data,run)
                    if ch.read('/etc/ld.so.preload',4096)!=neutral or ch.read(prefix+'.state',512)!=raw:
                        raise ValueError('预加载或重复终态不符')
                    save(output/'assessment.json',assessment)
                    report.update(preflight_complete=True,preload_neutral_verified=True,ssh_started=False,account_modified=False)
                    report.update(communication_verified=True,firmware_version_source='version_sha256_matched')
                    self.safe_to_stop=True
                    return
                time.sleep(.2)
            raise TimeoutError('未取得完整预检终态')
        finally:
            if not deploy.state['debug_attempted'] and not deploy.safe_to_stop and ch.usable:
                try: deploy.disarm_before_debug()
                except Exception as exc: log('pre_debug_disarm_failed',message=str(exc))
            if not deploy.state['debug_attempted']:
                self.safe_to_stop=bool(ch.usable and getattr(ch,'baseline',False) and deploy.safe_to_stop)
            report.update(deployment_state=deploy.state,automatic_service_exit_permitted=self.safe_to_stop)
            # 保留旧字段名供调用者兼容；它们表示调用尝试，不能当作写入完成回执。
            report.update(camera_file_write_commands_sent=bool(deploy.state.get('payload_write_attempted')
                              or deploy.state.get('arm_write_attempted')),
                          preload_written=bool(deploy.state.get('arm_write_attempted')),
                          debug_commands_sent=bool(deploy.state.get('debug_attempted')),
                          action_flags_semantics='attempted_not_confirmed')


def save_result(output, name, value):
    path=output/name
    save(path,value)
    # 引擎交还证据之后新生成的报告也交还同一用户；不改历史文件权限。
    if os.geteuid()==0:
        owner=output.parent.stat()
        os.chown(path,owner.st_uid,owner.st_gid,follow_symlinks=False)


def run_preflight(directory,operation):
    engine()
    from system_dump.session import run_session
    before=host_snapshot(); output=directory/'result'
    report=run_session(output,'libusb',_operation=PreflightOperation(directory,operation))
    if report.get('automatic_service_exit_permitted') and report.get('service_stop_attempts')==1:
        recovery=observe_recovery(before,host_snapshot)
    else:
        recovery=dict(recovered=False,observations=[],reason='stop_not_attempted_or_gate_withheld',
                      source='host_ioreg_only',camera_requests_sent=0)
    save_result(output,'host-recovery.json',recovery)
    recovered=recovery['recovered']
    report.update(execution_succeeded=bool(report.get('preflight_complete') and report.get('preload_neutral_verified')
                 and recovered and not report.get('failure')),
                 host_recovery_verified=recovered,screen_confirmation_pending=True,
                 acceptance_complete=False,research_residue_cleaned=False)
    report['result_status']=('PREFLIGHT_PASSED_HOST_RECOVERED_SCREEN_PENDING' if report['execution_succeeded']
                             else 'EXECUTION_OR_HOST_RECOVERY_FAILED')
    save_result(output,'preflight-result.json',report)
    return report
