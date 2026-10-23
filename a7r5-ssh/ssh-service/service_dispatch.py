"""无TTL服务专用调度；check/check-approval纯本机，execute需独立批准及--device-io。"""
import argparse
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

import credentials
import native_validation

RUN='2f94aea65af84dc6ab01a667752d283c'
PREDECESSOR='6193b144e80448d2af587262b31f2f17'
LOCATION=0x00100000
TARGET='10.10.10.177'
NEUTRAL=b'\n'*512
RISK=('一次固定文件安装、认证/START及一次DEBUG，精确512换行基线；'
      '完整root终端与SFTP，0.0.0.0:2222无TTL，本次开机内持续后台运行；'
      '不修改持久账户、不创建自启标记、不写永久预加载、不重启。'
      'USB恢复后仅对10.10.10.177进行一次PTY和两次默认SCP，RAM写65536字节测试文件；'
      '固定文件/密钥/测试数据残留、短密码长期暴露、root误写与恢复受限风险。'
      'USB切换仅正常卸载所属媒体，不读写卡内容、不格式化；异常停止，不重试或自动断电。'
      '本次不自动执行第二次回收或停止无TTL服务。')


def digest(path):
    path=Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file():raise ValueError('拒绝链接或非普通文件')
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def save(path,value):
    fd=os.open(path,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as stream:json.dump(value,stream,ensure_ascii=False,indent=2);stream.write('\n')


def paths(run):
    if run!=RUN:raise ValueError('拒绝非本次固定会话')
    prefix='/tmp/jiritsu/a7r5-'+run;ram='/tmp_network/a7r5-ssh-'+run
    return dict(payload=prefix+'.so',state=prefix+'.state',output=prefix+'.output',ready=ram+'/ready',heartbeat=ram+'/heartbeat',
                public=ram+'/host-public-key',started=ram+'/started',banner=ram+'/banner')


def read_json(path):
    digest(path)
    return json.loads(Path(path).read_text())


def check(directory):
    directory=Path(directory).absolute();op=read_json(directory/'operation.json')
    expected=dict(schema='a7r5-no-ttl-install-dispatch-v1',directory=str(directory),run_id=RUN,target_ip=TARGET,port=2222,ttl_seconds=0,
                  location_id=LOCATION,autostart_enabled=False,persistent_account_write=False,network_connections_max=3,debug_max=1,stop_max=1,risk=RISK)
    for key,value in expected.items():
        if type(op.get(key)) is not type(value) or op[key]!=value:raise ValueError('固定调度范围不符：'+key)
    for name,info in op['files'].items():
        file=directory/name
        if Path(name).is_absolute() or '..' in Path(name).parts or file.stat().st_size!=info['bytes'] or digest(file)!=info['sha256']:raise ValueError('调度材料变化：'+name)
    found={str(p.relative_to(directory)) for group in ('runtime','materials','proof','tests') for p in (directory/group).rglob('*') if p.is_file()}
    if found!={name for name in op['files'] if name.split('/')[0] in ('runtime','materials','proof','tests')}:raise ValueError('封存材料集合变化')
    for name,info in op['dependencies'].items():
        if digest(Path(name))!=info:raise ValueError('绑定本机运行时变化')
    if str(Path('/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib').resolve())!=op['libusb']:raise ValueError('libusb入口指向变化')
    if str(Path(sys.executable).resolve())!=op['python']:raise ValueError('Python解释器路径不符')
    m=read_json(directory/'materials/manifest.json')
    if m.get('qemu_only') is not False or m.get('run_id')!=RUN or m.get('camera_installation_approved') is not False or m.get('autostart_enabled') is not False:raise ValueError('材料不是本次未批准正式候选')
    prefix='/tmp/jiritsu/a7r5-'+RUN
    expected_map={'ssh-service.arm64':prefix+'.service-helper','boot-hook.so':prefix+'.boot-hook.so','control.sh':prefix+'.control.sh','stage.sh':prefix+'.stage.sh','root.arm64.so':prefix+'.so'}
    if m['upload_map']!=expected_map:raise ValueError('上传白名单变化')
    config=(directory/'materials/config.h').read_text()
    if '#define SSH_SECONDS 0\n' not in config or 'ForceCommand ' in config or 'PermitTTY yes\\n' not in config or 'Subsystem sftp internal-sftp\\n' not in config:raise ValueError('载荷配置不是无TTL终端/SFTP候选')
    password=credentials.load(op['credential_path'])
    match=re.search(r'^#define PASSWORD_HASH (".*")$',config,re.M)
    encoded=json.loads(match[1]) if match else ''
    if not credentials.valid_hash(encoded):raise ValueError('私有口令哈希格式不符')
    salt=encoded.split('$')[3]
    result=subprocess.run([op['openssl'],'passwd','-6','-salt','rounds=10000$'+salt,'-stdin'],input=password+'\n',text=True,capture_output=True,timeout=15)
    if result.returncode or not hmac.compare_digest(result.stdout.strip(),encoded):raise ValueError('本机受限凭据与载荷不匹配')
    proof=read_json(directory/'proof/independent-final-acceptance.json')
    screen=read_json(directory/'proof/screen-collect-confirmation.json')
    if proof.get('run_id')!=PREDECESSOR or proof.get('status')!='COLLECTION_CLEAN_HOST_AND_SCREEN_ACCEPTED' or proof.get('screen_normal') is not True or screen.get('screen_normal') is not True or screen.get('source')!='direct_human_reply':raise PermissionError('旧会话独立回收证据不符')
    for name,sha in proof['evidence'].items():
        if digest(directory/'proof'/name)!=sha:raise PermissionError('旧回收证据链变化')
    for key in ('parent_originals_unchanged_receipt','child_tree_reaped_receipt','listener_absent_receipt','preload_exact_512_newlines_verified','host_recovery_verified'):
        if proof.get(key) is not True:raise PermissionError('旧会话清理门槛不完整')
    if op['host_baseline']!=read_json(directory/'proof/host-recovery.json')['after']:raise ValueError('主机媒体基线与旧回收证明不符')
    return op


def approval(op,authorization_sha=None,accepted=False):
    return dict(schema='a7r5-no-ttl-install-approval-v1',run_id=RUN,accepted=accepted,
                operation_sha256=digest(Path(op['directory'])/'operation.json'),risk=RISK,authorization_sha256=authorization_sha,
                target_ip_confirmed=accepted,independent_power_confirmed=accepted,screen_normal_confirmed=accepted,no_other_clients_confirmed=accepted,
                normal_media_unmount_accepted=accepted,fixed_writes_and_debug_once_accepted=accepted,root_tty_scp_and_no_ttl_accepted=accepted,
                autostart_approved=False,second_session_approved=False)


def checked_approval(directory):
    op=check(directory);directory=Path(directory)
    auth=read_json(directory/'user-authorization-install.json')
    if auth.get('source')!='direct_human_message' or auth.get('run_id')!=RUN or auth.get('risk')!=RISK or auth.get('execute_installation') is not True:raise PermissionError('缺少本次人工安装授权记录')
    accepted=read_json(directory/'approval-install.json')
    if accepted!=approval(op,digest(directory/'user-authorization-install.json'),True):raise PermissionError('缺少绑定本包的独立实机批准')
    for name in ('ATTEMPT_LOCK_INSTALL','result-install'):
        if (directory/name).exists() or (directory/name).is_symlink():raise FileExistsError('安装已尝试，不重试')
    return op


def ready(raw):
    m=re.fullmatch(rb'A7R5_PRIVATE_READY '+RUN.encode()+rb' parent=(\d+) child=(\d+) uid=0 euid=0 ttl=0 parent_unchanged=1 private_account_changed=1 parent_ns=(mnt:\[\d+\]) child_ns=(mnt:\[\d+\]) host_public_sha=([0-9a-f]{64})\n',raw)
    if not m or min(int(m[1]),int(m[2]))<=1 or m[1]==m[2] or m[3]==m[4]:raise ValueError('本次无TTL READY身份/隔离不符')
    return dict(parent=int(m[1]),child=int(m[2]),public_sha=m[5].decode())


def heartbeat(raw,identity):
    m=re.fullmatch(rb'A7R5_PRIVATE_ALIVE '+RUN.encode()+rb' parent=(\d+) child=(\d+) ttl=0 elapsed_ms=(\d+) parent_unchanged=1\n',raw)
    if not m or (int(m[1]),int(m[2]))!=(identity['parent'],identity['child']) or not 0<=int(m[3])<=60000:raise ValueError('无TTL初次心跳不符或非新启动')
    return int(m[3])


class InstallOperation:
    def __init__(self,directory,op):self.directory=Path(directory);self.op=op;self.safe_to_stop=False

    def __call__(self,driver,output,log,report):
        import lab
        lab.engine()
        from system_dump.restricted import RestrictedChannel,Deployment,MAX_ARTIFACT
        from system_dump.session import FileResultError
        ports=tuple(driver.device.port_numbers or ())
        if not ports or (driver.device.bus<<24)|sum(x<<(20-4*i) for i,x in enumerate(ports))!=LOCATION:raise ValueError('物理端口变化')
        m=read_json(self.directory/'materials/manifest.json');p=paths(RUN);output=Path(output)
        uploads={target:(self.directory/'materials'/name).read_bytes() for name,target in m['upload_map'].items()}
        writes={target:(data,) for target,data in uploads.items()}
        writes['/etc/ld.so.preload']=((p['payload']+'\n').encode(),NEUTRAL)
        reads={'/version.txt':4096,'/etc/ld.so.preload':4096,**{target:MAX_ARTIFACT for target in uploads},
               p['state']:512,p['output']:32768,p['ready']:1024,p['heartbeat']:512,p['public']:512,p['started']:1024,p['banner']:256}
        class Exact(RestrictedChannel):
            arm_attempted=False
            def put(self,path,data):
                report['camera_file_write_commands_sent']=True
                if path=='/etc/ld.so.preload':self.arm_attempted=True
                return super().put(path,data)
            def read(self,path,limit):
                raw=super().read(path,limit)
                if path=='/etc/ld.so.preload' and not self.arm_attempted and raw!=NEUTRAL:raise PermissionError('非精确512换行基线')
                return raw
        ch=Exact(driver,writes,reads,log);deploy=None
        try:
            if hashlib.sha256(ch.read('/version.txt',4096)).hexdigest()!=lab.VERSION_SHA:raise ValueError('版本不符')
            if ch.read('/etc/ld.so.preload',4096)!=NEUTRAL:raise PermissionError('未知预加载')
            # 根载荷由Deployment上传/回读，避免重复上传第5项。
            for target,data in uploads.items():
                if target==p['payload']:continue
                ch.put(target,data)
                if ch.read(target,MAX_ARTIFACT)!=data:raise ValueError('固定上传回读不符')
            deploy=Deployment(ch,RUN,uploads[p['payload']],output,False);deploy.arm();deploy.trigger()
            deadline=time.monotonic()+65
            while True:
                if time.monotonic()>=deadline:raise TimeoutError('root入口无终态')
                try:state=ch.read(p['state'],512)
                except FileResultError as exc:
                    if exc.result!=0x10000006:raise
                    time.sleep(.2);continue
                (output/'worker-state.txt').write_bytes(state)
                match=re.fullmatch(rb'A7R5-ROOT-1 '+RUN.encode()+rb' (RUNNING|DONE|FAILED|TIMEOUT) (\d+) uid=0 euid=0 bytes=(\d+)\n',state)
                if not match or match[1] in (b'FAILED',b'TIMEOUT'):raise ValueError('root入口失败或旧状态')
                if match[1]==b'DONE':break
                time.sleep(.2)
            expected=('A7R5_PRIVATE_LAUNCH '+RUN+' READY\nA7R5_SERVICE_STAGED_AUTOSTART_DISABLED\n').encode()
            data=ch.read(p['output'],32768);(output/'worker-output.txt').write_bytes(data)
            if match[2]!=b'0' or int(match[3])!=len(data) or data!=expected:raise ValueError('root输出未完整通过安装门槛')
            raw=ch.read(p['ready'],1024);identity=ready(raw);public=ch.read(p['public'],512)
            if hashlib.sha256(public).hexdigest()!=identity['public_sha']:raise ValueError('公钥摘要不符')
            native_validation.public_key(public)
            started=ch.read(p['started'],1024);banner=ch.read(p['banner'],256)
            start=re.fullmatch(rb'A7R5_WILDCARD_STARTED '+RUN.encode()+rb' pid=(\d+) bind=0\.0\.0\.0:2222 listener_observed=1 banner_sha=([0-9a-f]{64})\n',started)
            if not start or int(start[1])<=1 or int(start[1]) in (identity['parent'],identity['child']) or not re.fullmatch(rb'SSH-2\.0-[ -~]+\r?\n',banner) or len(banner)>256 or hashlib.sha256(banner).hexdigest().encode()!=start[2]:raise ValueError('监听/banner回执不符')
            first=heartbeat(ch.read(p['heartbeat'],512),identity);until=time.monotonic()+3
            while True:
                if time.monotonic()>=until:raise TimeoutError('无TTL心跳未前进')
                time.sleep(.2);beat=ch.read(p['heartbeat'],512);last=heartbeat(beat,identity)
                if last>first:break
                if last<first:raise ValueError('心跳倒退')
            if ch.read(p['ready'],1024)!=raw or ch.read(p['state'],512)!=state or ch.read(p['started'],1024)!=started:raise ValueError('重复状态变化')
            if ch.read('/etc/ld.so.preload',4096)!=NEUTRAL:raise ValueError('最终中和不符')
            for name,content in (('ready.txt',raw),('heartbeat.txt',beat),('host-public-key',public),('started.txt',started),('ssh-banner.txt',banner)):(output/name).write_bytes(content)
            report.update(profile='service-no-ttl-install',protocol_gate_passed=True,preload_neutral_verified=True,communication_verified=True,
                          firmware_version_source='version_sha256_matched',host_public_sha256=identity['public_sha'],observer_identity=identity,
                          private_ready=True,ttl_seconds=0,autostart_enabled=False,global_account_final_verification_pending=True,
                          final_service_cleanup_pending=True)
            self.safe_to_stop=True
        finally:
            if deploy:
                if not deploy.state['debug_attempted'] and not deploy.safe_to_stop and ch.usable:
                    try:deploy.disarm_before_debug()
                    except Exception as exc:log('pre_debug_disarm_failed',error_type=type(exc).__name__)
                report.update(deployment_state=deploy.state,debug_commands_sent=bool(deploy.state['debug_attempted']),preload_written=bool(deploy.state.get('arm_write_attempted')))
            report['automatic_service_exit_permitted']=self.safe_to_stop


def execute(directory,device_io=False):
    # 所有批准和一次性门槛都先于主机枚举/后端导入。
    if not device_io:raise PermissionError('缺少--device-io；不打开设备')
    directory=Path(directory).absolute();op=checked_approval(directory)
    if sys.platform!='darwin' or os.geteuid()!=0:raise PermissionError('须在专用Terminal完成本机sudo认证')
    (directory/'ATTEMPT_LOCK_INSTALL').mkdir(mode=0o700)
    save(directory/'ATTEMPT_LOCK_INSTALL/attempt.json',dict(run_id=RUN,started_unix=time.time(),retry_permitted=False))
    try:return execute_approved(directory,op)
    except BaseException as exc:
        save(directory/'ATTEMPT_LOCK_INSTALL/failure.json',dict(run_id=RUN,error_type=type(exc).__name__,retry_permitted=False,automatic_power_cycle=False))
        raise


def execute_approved(directory,op):
    # 仅execute完成独立批准和一次性锁后可进入。
    import host
    import lab
    import recovery
    lab.engine()
    from system_dump.session import run_session
    before=json.loads(json.dumps(host.snapshot(LOCATION)))
    if before!=op['host_baseline']:raise ValueError('主机身份、驱动或媒体与封存基线不符；本次尝试停止')
    output=directory/'result-install';report=run_session(output,'libusb',_operation=InstallOperation(directory,op))
    observed=(recovery.observe_recovery(before,lambda **kw:host.snapshot(LOCATION,**kw))
              if report.get('protocol_gate_passed') and report.get('service_stop_attempts')==1 else dict(recovered=False,reason='gate_withheld',camera_requests_sent=0))
    save(output/'host-recovery.json',observed)
    report.update(run_id=RUN,host_recovery_verified=observed['recovered'],mac_network_connections=0,autostart_enabled=False,
                  acceptance_complete=False,screen_confirmation_pending=True,automatic_second_session=False,final_service_cleanup_pending=True)
    if report.get('protocol_gate_passed') and observed['recovered'] and not report.get('failure'):
        try:native_validation.verify(op,directory,output,report,credentials.load(op['credential_path']))
        except BaseException as exc:
            report.update(network_failure=type(exc).__name__+': 本次网络验收已停止；不输出敏感错误上下文',background_service_may_be_running=True)
    report['execution_succeeded']=bool(report.get('protocol_gate_passed') and observed['recovered'] and report.get('real_pty_verified') and report.get('scp_roundtrip_verified') and not report.get('failure') and not report.get('network_failure'))
    save(output/'phase-result.json',report)
    if os.geteuid()==0:
        owner=directory.stat()
        for file in output.iterdir():os.chown(file,owner.st_uid,owner.st_gid,follow_symlinks=False)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['check','check-approval','execute']);parser.add_argument('--operation',type=Path,required=True)
    parser.add_argument('--device-io',action='store_true');args=parser.parse_args()
    if args.action=='check':value=check(args.operation)
    elif args.action=='check-approval':value=checked_approval(args.operation)
    else:value=execute(args.operation,args.device_io)
    if args.action=='execute':
        print(json.dumps(value,ensure_ascii=False,indent=2));return 0 if value['execution_succeeded'] else 3
    print(json.dumps(dict(check='passed',run_id=value['run_id'],camera_io=False),ensure_ascii=False));return 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (Exception,KeyboardInterrupt) as exc:
        print('停止：'+type(exc).__name__+'；请核对本次本机门槛或证据，不重试。',file=sys.stderr);raise SystemExit(2)
