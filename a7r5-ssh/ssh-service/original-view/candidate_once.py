"""候选材料管理；默认check纯离线，stage/start/stop须逐次明确批准。"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import tempfile

HERE=Path(__file__).resolve().parent


def sha(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def regular(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file():raise ValueError('拒绝链接或非普通文件')
    return path


def project():
    return next(p for p in HERE.parents if (p/'a7r5-exec/TOOL.json').is_file())


def check(directory):
    directory=Path(directory).absolute();value=json.loads(regular(directory/'manifest.json').read_text())
    run=value.get('run_id','')
    if directory.stat().st_mode & 0o077:raise PermissionError('材料目录必须仅当前用户可访问')
    if any(p.is_symlink() for p in directory.rglob('*')):raise ValueError('材料中出现符号链接')
    if value.get('schema')!='a7r5-original-view-1' or not re.fullmatch('[0-9a-f]{32}',run):raise ValueError('材料类型或会话不符')
    if value.get('port')!=2223 or value.get('ip')!='10.10.10.177' or value.get('autostart') is not False or value.get('live_approved') is not False:raise ValueError('固定范围变化')
    if value.get('uploads')!=['ssh-original.arm64','session.arm64','sftp-server.arm64','anchor.arm64','start.sh']:raise ValueError('固定上传集合变化')
    if value.get('install_directory')!='/tmp/jiritsu/a7r5-original-'+run or value.get('seconds')!=600:raise ValueError('候选寿命或路径变化')
    for name,expected in value['files'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or sha(regular(directory/name))!=expected:raise ValueError('材料变化：'+name)
    found={str(p.relative_to(directory)) for p in directory.rglob('*') if p.is_file() and '.state' not in p.relative_to(directory).parts}
    if found!=set(value['files'])|{'manifest.json'}:raise ValueError('材料文件集合变化')
    return value


def phrase(directory,action):return 'ACCEPT-'+action.upper()+'-'+sha(Path(directory)/'manifest.json')[:16]


PREDECESSOR='d00feed5c41c44d2b31e7a8102755eec'


def original_prior_recovery_closed():
    directory=project()/'a7r5-exec/runs'/PREDECESSOR
    failed=regular(directory/'result/result.json');value=json.loads(failed.read_text())
    if value.get('run_id')!=PREDECESSOR:raise PermissionError('旧会话绑定不符')
    if value.get('execution_succeeded') is True and value.get('host_recovery_verified') is True:
        screen=json.loads(regular(directory/'result/screen-confirmation.json').read_text())
        if screen.get('screen_normal') is True and screen.get('run_id')==PREDECESSOR and screen.get('operation_sha256')==value.get('operation_sha256'):return
    closure=directory/'result/recovery-closure.json'
    if not closure.is_file():raise PermissionError('旧失败会话没有独立恢复收口；标记缺失不代表恢复，不建立连接')
    c=json.loads(regular(closure).read_text())
    if c.get('schema')!='a7r5-recovery-closure-1' or c.get('run_id')!=PREDECESSOR or c.get('failed_result_sha256')!=sha(failed) or c.get('operation_sha256')!=value.get('operation_sha256') or c.get('approved_by_user') is not True:raise PermissionError('旧会话恢复收口绑定不符')
    for kind in ['host','screen']:
        relative=Path(c[kind+'_evidence'])
        if relative.is_absolute() or '..' in relative.parts:raise PermissionError('恢复证据必须绑定工程内普通文件')
        file=regular(project()/relative)
        if sha(file)!=c[kind+'_sha256']:raise PermissionError('恢复证据摘要变化')
        evidence=json.loads(file.read_text())
        if kind=='host' and evidence.get('recovered') is not True:raise PermissionError('普通USB/媒体恢复未通过')
        if kind=='screen' and (evidence.get('screen_normal') is not True or evidence.get('source')!='user_explicit_confirmation'):raise PermissionError('没有人工屏幕回执')


ARCHIVE_SHA={'archived-closure.json': '7bca4793208ea4e240fef0f5bb2848d0812e3ee54d156f7e68fe71985d648dff', 'archived-host.json': 'ee087e091fa1fff00dff44082d8fa3ae23260980adc036887461e65d4193e0e6'}


def archived_prior_recovery_closed():
    # 仅识别本次已存在的归档，不生成批准、不把原失败改判成功。
    data={}
    for name,want in ARCHIVE_SHA.items():
        path=regular(HERE/'compat-proof'/name)
        if sha(path)!=want:raise PermissionError('归档恢复证据变化')
        data[name]=json.loads(path.read_text())
    c=data['archived-closure.json'];h=data['archived-host.json'];binding=c.get('old_binding',{})
    if c.get('schema')!='a7r5-late-host-recovery-1' or binding.get('run_id')!=PREDECESSOR or binding.get('operation_sha256')!='1020f365844e8c5b4a7417932675e1e1ca0ec4b24ba9fdd7784920b9d1a189fe':raise PermissionError('归档不是原失败会话')
    if c.get('original_result_sha256')!='688daec230a7d2c126da82ab04fa46cf34485efef242e6aae38839692252e262' or c.get('original_failure_reclassified') is not False or c.get('old_task_readonly') is not True:raise PermissionError('归档没有保留原失败边界')
    if c.get('host_proof_sha256')!=ARCHIVE_SHA['archived-host.json'] or c.get('user_screen_normal') is not True or c.get('remaining_recovery_unknown') is not False:raise PermissionError('归档恢复或屏幕门槛未通过')
    rows=h.get('observations',[])
    if h.get('recovered') is not True or len(rows)<2 or h.get('camera_protocol_requests')!=0:raise PermissionError('归档缺少两次主机恢复')
    for row in rows[-2:]:
        snap=row.get('snapshot',{})
        if row.get('status')!='matching' or snap.get('kind')!='ordinary' or snap.get('pid')!=0x0e0a or snap.get('model')!='ILCE-7RM5':raise PermissionError('归档USB身份或媒体匹配失败')


def prior_recovery_closed():
    original=project()/'a7r5-exec/runs'/PREDECESSOR/'result/result.json'
    if original.is_file():return original_prior_recovery_closed()
    return archived_prior_recovery_closed()


def guard(directory,action,accept,device_io,anchor=None):
    m=check(directory)
    for name,want in json.loads(regular(HERE/'compat-proof/exec-binding.json').read_text()).items():
        if sha(regular(name))!=want:raise PermissionError('当前执行器变化，需重新离线核对')
    if m.get('qemu_only') is not False:raise PermissionError('QEMU材料禁止联网安装')
    if not device_io or accept!=phrase(directory,action):raise PermissionError('没有本阶段的明确批准，不建立连接')
    if (project()/'a7r5-exec/PENDING_RECOVERY.json').exists():raise PermissionError('现有快捷工具仍待恢复；不得绕过门禁连接或安装')
    prior_recovery_closed()
    if action=='start':verify_anchor(directory,anchor,m)
    state=Path(directory)/'.state';state.mkdir(mode=0o700,exist_ok=True)
    lock=state/(action+'-ATTEMPT_LOCK');lock.mkdir(mode=0o700)
    return m,state


def verify_anchor(directory,anchor,m):
    stage=Path(directory)/'.state/stage-result.json'
    if not stage.is_file() or json.loads(stage.read_text()).get('passed') is not True:raise ValueError('尚未完成本次上传')
    anchor=Path(anchor).absolute() if anchor else Path('/nonexistent')
    if anchor.parent!=project()/'a7r5-exec/runs':raise ValueError('仅接受原快捷工具中的本次封存会话')
    task=regular(anchor/'task.sh')
    if task.read_bytes()!=regular(Path(directory)/'anchor-task.sh').read_bytes():raise ValueError('锚点任务不是本包固定任务')
    result=json.loads(regular(anchor/'result/result.json').read_text())
    screen=json.loads(regular(Path(directory)/'.state/anchor-screen.json').read_text())
    if not result.get('execution_succeeded') or not result.get('host_recovery_verified') or not screen.get('screen_normal') or result.get('engine')!='libjit':raise ValueError('锚点任务、主机恢复或屏幕门槛未通过')
    operation=regular(anchor/'operation.json')
    for receipt in [result,screen]:
        if receipt.get('run_id')!=anchor.name or receipt.get('operation_sha256')!=sha(operation):raise ValueError('锚点结果绑定变化')
    subprocess.run([str(project()/'.venv/bin/python'),'-B',str(project()/'a7r5-exec/exec.py'),'check','--run',str(anchor)],capture_output=True,check=True,timeout=30)
    output=regular(anchor/'result/session/shell-output.bin').read_bytes()
    if result.get('protocol_gate_passed') is not True or result.get('root_task_done') is not True or result.get('root_uid')!=0 or result.get('root_euid')!=0 or result.get('preload_unchanged') is not True or result.get('debug_commands_sent') is not False or result.get('service_stop_attempts')!=1 or result.get('fixed_writes_attempted')!=2 or result.get('trigger_attempts')!=1 or result.get('shell_output_sha256')!=sha(anchor/'result/session/shell-output.bin'):raise ValueError('锚点任务详细门槛未通过')
    expected=('A7R5_ORIGIN_ANCHOR '+m['run_id']+' SEALED original_view_matched=1 daemon_started=0\n').encode()
    if expected not in output:raise ValueError('没有本次原始视图锚点回执')


class Master:
    def __init__(self,directory,m,state):
        self.directory=Path(directory);self.m=m;self.state=state;self.control=None
        self.common=['-F','/dev/null','-o','HostKeyAlias=a7r5-original-'+m['run_id'],'-o','UserKnownHostsFile='+str(self.directory/'known_hosts'),'-o','GlobalKnownHostsFile=/dev/null','-o','StrictHostKeyChecking=yes','-o','IdentityAgent=none','-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','NumberOfPasswordPrompts=1','-o','ConnectTimeout=10']
    def __enter__(self):
        self.control=tempfile.TemporaryDirectory(prefix='a7r5-ov-',dir='/tmp');self.socket=str(Path(self.control.name)/'ssh.sock')
        self._run(['/usr/bin/ssh',*self.common,'-M','-N','-f','-o','ControlPath='+self.socket,'-o','ControlPersist=60','-p','2222','root@'+self.m['ip']], 'connect',terminal=True)
        return self
    def _run(self,cmd,label,terminal=False):
        result=subprocess.run(cmd,capture_output=not terminal,timeout=120 if terminal else 40)
        if not terminal:
            (self.state/(label+'.stdout')).write_bytes(result.stdout);(self.state/(label+'.stderr')).write_bytes(result.stderr)
        if result.returncode:raise RuntimeError(label+'失败，退出码'+str(result.returncode)+'；停止，不追加相机请求')
        return result.stdout if not terminal else b''
    def shared(self):
        # 主连接消失时禁止回落为第二次连接或再次认证。
        return [*self.common,'-o','ControlPath='+self.socket,'-o','ControlMaster=no','-o','ProxyCommand=/usr/bin/false']
    def command(self,script,label):
        return self._run(['/usr/bin/ssh',*self.shared(),'-T','-p','2222','root@'+self.m['ip'],script],label)
    def upload(self,items):
        batch=self.state/'sftp.batch'
        def quoted(p):return '"'+str(p).replace('\\','\\\\').replace('"','\\"')+'"'
        batch.write_text(''.join('put '+quoted(self.directory/name)+' '+quoted(self.m['install_directory']+'/'+name)+'\n' for name in items))
        return self._run(['/usr/bin/sftp',*self.shared(),'-b',str(batch),'-P','2222','root@'+self.m['ip']],'upload')
    def __exit__(self,*error):
        # 这里只关闭Mac本机复用连接，不发送相机恢复、停止或重试请求。
        subprocess.run(['/usr/bin/ssh','-S',self.socket,'-O','exit','root@'+self.m['ip']],capture_output=True,timeout=5)
        self.control.cleanup()


def _execute(directory,action,accept,device_io,anchor=None,transport=Master):
    directory=Path(directory).absolute();m,state=guard(directory,action,accept,device_io,anchor)
    result=dict(action=action,run_id=m['run_id'],passed=False,automatic_retry=False,autostart=False)
    try:
        with transport(directory,m,state) as remote:
            if action=='stage':
                reply=remote.command((directory/'stage-prepare.sh').read_text(),'stage-prepare')
                if reply!=('A7R5_STAGE_EMPTY '+m['run_id']+'\n').encode():raise ValueError('上传前回执不符')
                remote.upload(m['uploads'])
                reply=remote.command((directory/'stage-verify.sh').read_text(),'stage-verify')
                if reply!=('A7R5_STAGE_VERIFIED '+m['run_id']+'\n').encode():raise ValueError('上传校验回执不符')
            elif action=='start':
                reply=remote.command('/bin/sh '+shlex.quote(m['install_directory']+'/start.sh'),'start')
                if reply!=('A7R5_PRIVATE_LAUNCH '+m['run_id']+' READY\n').encode():raise ValueError('新候选未READY')
            elif action=='stop':
                reply=remote.command(shlex.quote(m['install_directory']+'/ssh-original.arm64')+' --stop','stop')
                pattern=rb'A7R5_PRIVATE_RESULT '+m['run_id'].encode()+rb' code=0 parent_unchanged=[01] child_tree_reaped=1 child_terminal_seen=1 listener_absent=1 changes_observed=[01]\n'
                if not re.fullmatch(pattern,reply):raise ValueError('候选清理门槛未通过')
            else:raise ValueError('未知阶段')
            result['passed']=True
    except BaseException as exc:
        result['failure']=type(exc).__name__+': '+str(exc)
    finally:
        (state/(action+'-result.json')).write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


def execute(directory,action,accept,device_io,anchor=None,transport=Master):
    if action not in ['stage','start','stop']:raise ValueError('未知阶段')
    check(directory)
    if not device_io or accept!=phrase(directory,action):raise PermissionError('没有本阶段明确批准，不建立连接')
    with (project()/'a7r5-exec/ACTIVE_SESSION.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        return _execute(directory,action,accept,device_io,anchor,transport)


def main():
    p=argparse.ArgumentParser(description='默认仅核对本机；实机逐阶段批准，旧2222和自启不变')
    p.add_argument('action',choices=['check','stage','prepare-anchor','confirm-anchor-screen','start','stop']);p.add_argument('--package',type=Path,default=HERE)
    p.add_argument('--accept');p.add_argument('--device-io',action='store_true');p.add_argument('--anchor-run',type=Path);p.add_argument('--screen-normal',action='store_true')
    a=p.parse_args();m=check(a.package)
    if a.action=='check':
        try:prior_recovery_closed();prior_closed=True
        except (OSError,ValueError,PermissionError):prior_closed=False
        print(json.dumps(dict(run_id=m['run_id'],offline_only=True,prior_recovery_closed=prior_closed,pending_recovery=(project()/'a7r5-exec/PENDING_RECOVERY.json').exists(),phases={n:phrase(a.package,n) for n in ['stage','start','stop']}),ensure_ascii=False));return 0
    if a.action=='confirm-anchor-screen':
        if not a.screen_normal or not a.anchor_run:raise PermissionError('须人工确认本次屏幕正常')
        result=json.loads(regular(a.anchor_run/'result/result.json').read_text())
        if result.get('execution_succeeded') is not True or result.get('host_recovery_verified') is not True:raise ValueError('不能用屏幕确认覆盖失败')
        receipt=dict(run_id=a.anchor_run.name,operation_sha256=sha(a.anchor_run/'operation.json'),screen_normal=True,source='user_explicit_confirmation')
        path=a.package/'.state/anchor-screen.json'
        with path.open('x') as f:json.dump(receipt,f,ensure_ascii=False,indent=2)
        try:verify_anchor(a.package,a.anchor_run,m)
        except Exception:
            # 失败收据保留，不删除或自动重试；start仍重新核对全部门槛。
            raise
        print(json.dumps(dict(camera_requests=0,screen_normal=True)));return 0
    if a.action=='prepare-anchor':
        if (a.package/'.state/anchor-run.json').exists():raise FileExistsError('已经封存锚点任务，不重复准备')
        value=subprocess.run([str(project()/'.venv/bin/python'),'-B',str(project()/'a7r5-exec/exec.py'),'prepare','--engine','libjit','--script',str(a.package/'anchor-task.sh'),'--timeout','15'],capture_output=True,text=True,check=True,timeout=60)
        state=a.package/'.state';state.mkdir(exist_ok=True,mode=0o700);(state/'anchor-run.json').write_text(value.stdout)
        print(value.stdout);return 0
    result=execute(a.package,a.action,a.accept,a.device_io,a.anchor_run)
    print(json.dumps(result,ensure_ascii=False));return 0 if result['passed'] else 3


if __name__=='__main__':
    try:raise SystemExit(main())
    except Exception as error:print(type(error).__name__+': '+str(error));raise SystemExit(2)
