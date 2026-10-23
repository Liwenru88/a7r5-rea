"""私有视图SSH一次性材料；准备/核对不访问设备，执行须独立批准。"""
import argparse
import base64
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import sys
import time

import build

ROOT=build.ROOT
sys.path.insert(0,str(build.LAB))
import lab
RISK=('固定载荷和启动器可能持久残留；精确512换行预加载基线，认证/START及一次DEBUG。'
      '只在私有RAM账户副本修改root shell，生成RAM主机密钥，指定IPv4:2222密钥认证；'
      '180秒内仅允许固定身份命令，不开放PTY、转发或SFTP。指定IP出现时可能在STOP前监听；'
      '主机恢复通过后仅一次SSH连接。符合门槛才一次STOP；异常不重试、不自动断电。'
      '客体最终清理结果需另行批准固定读回，不能依靠SSH作为恢复通道。')


def dependencies():
    import pwd
    # sudo 可能切换 HOME；依赖绑定材料所有者，不从管理员家目录重新发现。
    owner=Path(pwd.getpwuid(build.LAB.stat().st_uid).pw_dir)
    found=list((owner/'.codex/skills/ssh-skill/.venv/lib').glob('python*/site-packages'))
    if len(found)!=1:raise ValueError('无法唯一定位已安装的SSH客户端依赖')
    sys.path.append(str(found[0]))
    return found[0]


def dependency_hashes():
    base=dependencies()
    files=[p for name in ('paramiko','cryptography','nacl') for p in (base/name).rglob('*')
           if p.is_file() and '__pycache__' not in p.parts and (p.suffix=='.py' or p.name.endswith('.so'))]
    if not files:raise ValueError('缺少SSH客户端依赖')
    return {str(p.resolve()):lab.digest(p.resolve()) for p in sorted(files)}


def paths(run):
    if not re.fullmatch('[0-9a-f]{32}',run):raise ValueError('无效会话')
    prefix='/tmp/jiritsu/a7r5-'+run
    ram='/tmp_network/a7r5-ssh-'+run
    return dict(helper=prefix+'.ssh-helper',payload=prefix+'.so',state=prefix+'.state',output=prefix+'.output',
                ready=ram+'/ready',heartbeat=ram+'/heartbeat',public=ram+'/host-public-key',
                result=ram+'/result',child=ram+'/child-result',diagnostic=ram+'/diagnostic')


def save(path,value):
    with Path(path).open('x',encoding='utf-8') as f:json.dump(value,f,ensure_ascii=False,indent=2);f.write('\n')


def sources():
    return {'private/'+p.name:lab.digest(p) for p in ROOT.glob('*') if p.suffix in ('.py','.c','.h')}|{'lab/'+k:v for k,v in lab.sources().items()}


def regular_directory(directory):
    directory=Path(directory).absolute()
    if directory.parent!=ROOT/'packages' or not re.fullmatch('[a-z0-9][a-z0-9-]{0,63}',directory.name):raise ValueError('操作目录超出本次材料根')
    if any(p.is_symlink() for p in (directory,*directory.parents)):raise ValueError('拒绝链接目录')
    return directory


def prepare(name,address):
    directory=regular_directory(ROOT/'packages'/name)
    directory.parent.mkdir(exist_ok=True,mode=0o700)
    if directory.exists():raise FileExistsError('不覆盖现有操作')
    dependencies()
    from cryptography.hazmat.primitives.asymmetric import ed25519
    from cryptography.hazmat.primitives import serialization
    key=ed25519.Ed25519PrivateKey.generate()
    public=key.public_key().public_bytes(serialization.Encoding.OpenSSH,serialization.PublicFormat.OpenSSH).decode()
    value=build.build(directory,public,address,180)
    secret=key.private_bytes(serialization.Encoding.PEM,serialization.PrivateFormat.OpenSSH,serialization.NoEncryption())
    fd=os.open(directory/'client-key',os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'wb') as f:f.write(secret)
    (directory/'client-key.pub').write_text(public+'\n')
    run=value['run_id'];p=paths(run)
    checks={p['helper']:value['binary_sha256'],'/version.txt':lab.VERSION_SHA,'/usr/sbin/sshd':lab.SSHD_SHA,
            '/etc/nsswitch.conf':'3cb6f73826acc6786500cbac5f7a6a6ce11c807621eaa67d3f0dcebbe556f929',
            '/etc/ssh/sshd_config':'fdccb272a96cc8b100116c8142b60b2bfd200390895770d2f263d07921db195d'}
    script='set -eu\n'
    for file,sha in checks.items():script+='sum=$(/usr/bin/openssl dgst -sha256 '+file+'); [ "${sum##* }" = '+shlex.quote(sha)+' ]\n'
    script+='/bin/busybox chmod 700 '+p['helper']+'\nexec '+p['helper']+' --launch\n'
    (directory/'task.sh').write_text(script)
    (directory/'root_config.h').write_text(lab.root_header(run,script,40))
    subprocess=__import__('subprocess')
    subprocess.run(['/bin/sh','-n'],input=script,text=True,check=True,capture_output=True)
    payload=directory/'root.arm64.so'
    import isolation
    root_build=isolation.compile_target(build.LAB/'src/root_once.c',payload,directory,shared=True)
    save(directory/'root-build.json',root_build)
    for phase in ('deploy','collect'):
        launcher=directory/('run-'+phase+'.command')
        text=('#!/bin/bash\n# 缺少本阶段批准即拒绝；不会生成批准或自动开启下一会话。\nset -euo pipefail\n'
              +shlex.quote(str(Path(sys.executable).absolute()))+' -B '+shlex.quote(str(ROOT/'operation.py'))+' check-approval --operation '+shlex.quote(str(directory))+' --phase '+phase+'\n'
              +'sudo -- '+shlex.quote(str(Path(sys.executable).absolute()))+' -B '+shlex.quote(str(ROOT/'operation.py'))+' execute --operation '+shlex.quote(str(directory))+' --phase '+phase+' --device-io\n')
        launcher.write_text(text);launcher.chmod(0o700)
    op=dict(schema='a7r5-private-ssh-1',run_id=run,directory=str(directory),address=address,port=2222,seconds=180,
            risk=RISK,sources=sources(),artifacts={f.name:lab.digest(f) for f in directory.iterdir() if f.is_file()},
            python=str(Path(sys.executable).resolve()),python_sha256=lab.digest(Path(sys.executable).resolve()),
            libusb_sha256=lab.digest(Path('/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib').resolve()),
            client_dependencies=dependency_hashes(),
            fixed_command_only=True,persistent_account_write=False,automatic_second_session=False)
    save(directory/'operation.json',op)
    for phase in ('deploy','collect'):save(directory/('approval-'+phase+'-template.json'),approval(directory,phase,False))
    return op


def check(directory):
    directory=regular_directory(directory)
    value=json.loads(lab.regular(directory/'operation.json').read_text())
    if value['schema']!='a7r5-private-ssh-1' or value['directory']!=str(directory) or value['risk']!=RISK or value['port']!=2222 or value['seconds']!=180:
        raise ValueError('操作范围不符')
    paths(value['run_id'])
    import ipaddress
    ip=ipaddress.IPv4Address(value['address'])
    if str(ip)!=value['address'] or not any(ip in ipaddress.IPv4Network(n) for n in ('10.0.0.0/8','172.16.0.0/12','192.168.0.0/16')):raise ValueError('目标地址不符')
    if value['sources']!=sources():raise ValueError('材料源码变化')
    if value['fixed_command_only'] is not True or value['persistent_account_write'] is not False or value['automatic_second_session'] is not False:raise ValueError('权限范围变化')
    expected={'config.h','private-sshd.arm64','build.json','client-key','client-key.pub','task.sh','root_config.h','root.arm64.so','root-build.json','run-deploy.command','run-collect.command'}
    if set(value['artifacts'])!=expected:raise ValueError('材料集合变化')
    for name,sha in value['artifacts'].items():
        if lab.digest(directory/name)!=sha:raise ValueError('材料摘要变化：'+name)
    if value['python']!=str(Path(sys.executable).resolve()) or value['python_sha256']!=lab.digest(Path(sys.executable).resolve()) or value['libusb_sha256']!=lab.digest(Path('/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib').resolve()) or value['client_dependencies']!=dependency_hashes():raise ValueError('运行时变化')
    if (directory/'client-key').stat().st_mode&0o077:raise PermissionError('客户端私钥权限过宽')
    return value


def approval(directory,phase,accepted=False):
    if phase not in ('deploy','collect'):raise ValueError('无效阶段')
    op=check(directory);prior=Path(directory)/'result-deploy/phase-result.json'
    return dict(schema='a7r5-private-ssh-approval-1',run_id=op['run_id'],phase=phase,accepted=accepted,
                operation_sha256=lab.digest(Path(directory)/'operation.json'),risk=RISK,
                camera_fixed_writes=phase=='deploy',authentication_start=True,debug_once=phase=='deploy',
                private_account_view_changed=phase=='deploy',persistent_account_write=False,
                ssh_fixed_command_once=phase=='deploy',conditional_stop_once=True,automatic_second_session=False,
                prior_screen_normal=phase=='collect' and accepted,
                prior_sha256=lab.digest(prior) if phase=='collect' and accepted else None)


def checked_approval(directory,phase):
    op=check(directory);directory=Path(directory)
    accepted=json.loads(lab.regular(directory/('approval-'+phase+'.json')).read_text())
    if accepted.get('accepted') is not True or accepted!=approval(directory,phase,True):raise PermissionError('缺少本阶段明确批准')
    if (directory/('ATTEMPT_LOCK_'+phase.upper())).exists() or (directory/('result-'+phase)).exists():raise FileExistsError('本阶段已尝试，不重试')
    if phase=='collect':
        prior=json.loads(lab.regular(directory/'result-deploy/phase-result.json').read_text())
        if not prior.get('protocol_gate_passed') or not prior.get('host_recovery_verified') or time.time()<prior['collect_not_before_unix']:raise PermissionError('前次恢复或清理等待门槛不符')
    return op


def ready(raw,run):
    pattern=(r'A7R5_PRIVATE_READY '+run+r' parent=(\d+) child=(\d+) uid=0 euid=0 ttl=180 parent_unchanged=1 private_account_changed=1 parent_ns=(mnt:\[\d+\]) child_ns=(mnt:\[\d+\]) host_public_sha=([0-9a-f]{64})\n')
    m=re.fullmatch(pattern,raw.decode('ascii'))
    if not m or min(int(m[1]),int(m[2]))<=1 or m[1]==m[2] or m[3]==m[4]:raise ValueError('READY身份或隔离不符')
    return dict(parent=int(m[1]),child=int(m[2]),public_sha=m[5])


def heartbeat(raw,run,identity):
    m=re.fullmatch(r'A7R5_PRIVATE_ALIVE '+run+r' parent=(\d+) child=(\d+) ttl=180 elapsed_ms=(\d+) parent_unchanged=1\n',raw.decode('ascii'))
    if not m or (int(m[1]),int(m[2]))!=(identity['parent'],identity['child']) or not 0<=int(m[3])<=60000:raise ValueError('心跳已结束、身份变化或剩余寿命不足120秒')
    return int(m[3])


class Operation:
    def __init__(self,directory,op,phase):self.directory=Path(directory);self.op=op;self.phase=phase;self.safe_to_stop=False
    def __call__(self,driver,output,log,report):
        lab.engine()
        from system_dump.restricted import RestrictedChannel,Deployment,neutral,MAX_ARTIFACT
        from system_dump.session import FileResultError
        run=self.op['run_id'];p=paths(run);report['profile']='private-ssh-'+self.phase
        ports=tuple(driver.device.port_numbers or ())
        if not ports or (driver.device.bus<<24)|sum(x<<(20-4*i) for i,x in enumerate(ports))!=0x01100000:raise ValueError('物理端口变化')
        reads={'/version.txt':4096,'/etc/ld.so.preload':4096,p['ready']:1024,p['heartbeat']:512,p['public']:512,
               p['state']:512,p['output']:32768,p['result']:1024,p['child']:1024,p['diagnostic']:4096}
        writes={};deploy=None
        if self.phase=='deploy':
            helper=(self.directory/'private-sshd.arm64').read_bytes();payload=(self.directory/'root.arm64.so').read_bytes()
            writes={p['helper']:(helper,),p['payload']:(payload,),'/etc/ld.so.preload':((p['payload']+'\n').encode(),neutral)}
            reads.update({p['helper']:MAX_ARTIFACT,p['payload']:MAX_ARTIFACT})
        class Exact(RestrictedChannel):
            arm_attempted=False
            def put(self,path,data):
                if path=='/etc/ld.so.preload':self.arm_attempted=True
                return super().put(path,data)
            def read(self,path,limit):
                raw=super().read(path,limit)
                if path=='/etc/ld.so.preload' and not self.arm_attempted and raw!=neutral:raise PermissionError('非精确512换行基线')
                return raw
        ch=Exact(driver,writes,reads,log);stop_deadline=None
        try:
            if hashlib.sha256(ch.read('/version.txt',4096)).hexdigest()!=lab.VERSION_SHA:raise ValueError('版本不符')
            if ch.read('/etc/ld.so.preload',4096)!=neutral:raise PermissionError('预加载基线不符')
            if self.phase=='deploy':
                report['camera_file_write_commands_sent']=True
                ch.put(p['helper'],helper)
                if ch.read(p['helper'],MAX_ARTIFACT)!=helper:raise ValueError('启动器回读不符')
                deploy=Deployment(ch,run,payload,output,False);deploy.arm();deploy.trigger()
                until=time.monotonic()+65
                while True:
                    if time.monotonic()>=until:raise TimeoutError('固定入口无终态')
                    try:state=ch.read(p['state'],512)
                    except FileResultError as exc:
                        if exc.result!=0x10000006:raise
                        time.sleep(.2);continue
                    (output/'worker-state.txt').write_bytes(state)
                    m=re.fullmatch(rb'A7R5-ROOT-1 '+run.encode()+rb' (RUNNING|DONE|FAILED|TIMEOUT) (\d+) uid=0 euid=0 bytes=(\d+)\n',state)
                    if not m or m[1] in (b'FAILED',b'TIMEOUT'):raise ValueError('固定入口失败、非root或旧状态')
                    if m[1]==b'DONE':break
                    time.sleep(.2)
                data=ch.read(p['output'],32768);(output/'worker-output.txt').write_bytes(data)
                if m[2]!=b'0' or len(data)!=int(m[3]) or data!=(f'A7R5_PRIVATE_LAUNCH {run} READY\n').encode():raise ValueError('固定入口未完整READY')
                raw=ch.read(p['ready'],1024);identity=ready(raw,run);public=ch.read(p['public'],512)
                if hashlib.sha256(public).hexdigest()!=identity['public_sha']:raise ValueError('主机公钥摘要不符')
                match=re.fullmatch(rb'ecdsa-sha2-nistp256 ([A-Za-z0-9+/=]+)(?: [ -~]*)?\n',public)
                if not match:raise ValueError('主机公钥格式不符')
                base64.b64decode(match[1],validate=True)
                first=heartbeat(ch.read(p['heartbeat'],512),run,identity);until=time.monotonic()+3
                while True:
                    if time.monotonic()>=until:raise TimeoutError('心跳未前进')
                    time.sleep(.2);read_started=time.monotonic();beat=ch.read(p['heartbeat'],512);last=heartbeat(beat,run,identity)
                    if last>first:break
                    if last<first:raise ValueError('心跳倒退')
                stop_deadline=read_started+180-last/1000-110
                if ch.read(p['ready'],1024)!=raw or ch.read(p['state'],512)!=state:raise ValueError('重复READY/入口终态变化')
                (output/'ready.txt').write_bytes(raw);(output/'heartbeat.txt').write_bytes(beat);(output/'host-public-key').write_bytes(public)
                report.update(private_ready=True,host_public_key_verified=True,observer_identity=identity,
                              host_public_sha256=identity['public_sha'],private_account_view_changed=True,
                              global_account_final_verification_pending=True,guest_final_result_pending=True)
            else:
                final=ch.read(p['result'],1024);child=ch.read(p['child'],1024)
                (output/'guest-result-raw.txt').write_bytes(final);(output/'guest-child-raw.txt').write_bytes(child)
                if not re.fullmatch(rb'A7R5_PRIVATE_RESULT '+run.encode()+rb' code=0 parent_unchanged=1 child_tree_reaped=1 child_terminal_seen=1 listener_absent=1\n',final):raise ValueError('最终父视图或清理门槛不符')
                if child!=b'PRIVATE_RESULT code=0 errno=0 sshd_attempted=1 listener_observed=1 children_reaped=1 private_account_changed=1\n':raise ValueError('私有SSH子树终态不符')
                if ch.read(p['result'],1024)!=final:raise ValueError('重复终态变化')
                report.update(guest_final_cleanup_verified=True,parent_account_nss_config_unchanged_receipt=True,listener_absence_verified=True)
            if ch.read('/etc/ld.so.preload',4096)!=neutral:raise ValueError('中和不符')
            if stop_deadline is not None and time.monotonic()>=stop_deadline:raise TimeoutError('复核耗尽STOP、主机恢复和SSH窗口余量')
            report.update(protocol_gate_passed=True,preload_neutral_verified=True,communication_verified=True,firmware_version_source='version_sha256_matched')
            self.safe_to_stop=True
        finally:
            if deploy:
                if not deploy.state['debug_attempted'] and not deploy.safe_to_stop and ch.usable:
                    try:deploy.disarm_before_debug()
                    except Exception as exc:log('pre_debug_disarm_failed',message=str(exc))
                report.update(deployment_state=deploy.state,debug_commands_sent=bool(deploy.state['debug_attempted']),preload_written=bool(deploy.state.get('arm_write_attempted')))
            report['automatic_service_exit_permitted']=self.safe_to_stop


def client_once(op,output,report):
    dependencies()
    import socket
    import paramiko
    report.update(client_connect_attempted=False,ssh_authentication_attempted=False,ssh_fixed_command_verified=False)
    public=(output/'host-public-key').read_bytes()
    key_raw=base64.b64decode(public.split()[1],validate=True)
    if hashlib.sha256(public).hexdigest()!=report['host_public_sha256']:raise ValueError('可信主机公钥变化')
    key=paramiko.Ed25519Key.from_private_key_file(str(Path(op['directory'])/'client-key'))
    connection=socket.socket(socket.AF_INET,socket.SOCK_STREAM);transport=None
    deadline=time.monotonic()+20
    def remaining():
        value=min(8,deadline-time.monotonic())
        if value<=0:raise TimeoutError('单次SSH窗口截止')
        return value
    try:
        connection.settimeout(remaining());report['client_connect_attempted']=True
        connection.connect((op['address'],2222))
        transport=paramiko.Transport(connection);transport.banner_timeout=remaining()
        transport.start_client(timeout=remaining())
        if transport.get_remote_server_key().asbytes()!=key_raw:raise ValueError('SSH主机指纹不符，不认证')
        report['host_fingerprint_matched']=True;report['ssh_authentication_attempted']=True
        transport.auth_timeout=remaining()
        transport.auth_publickey('root',key)
        if not transport.is_authenticated():raise PermissionError('指定公钥认证未通过')
        channel=transport.open_session(timeout=remaining());channel.settimeout(remaining());channel.exec_command('id')
        data=b''
        while True:
            channel.settimeout(remaining());chunk=channel.recv(4096-len(data))
            if not chunk:break
            data+=chunk
            if len(data)>=4096:raise ValueError('固定身份输出超限')
        while not channel.exit_status_ready():remaining();time.sleep(.05)
        status=channel.recv_exit_status();channel.close();(output/'ssh-identity-raw.txt').write_bytes(data)
        if status or any(not re.search(rb'^'+name+rb':\s+0\s+0\s+0\s+0\s*$',data,re.M) for name in (b'Uid',b'Gid')):raise ValueError('SSH固定root身份未通过')
        report.update(ssh_fixed_command_verified=True,ssh_command_exit=status)
    finally:
        if transport is not None:transport.close()
        connection.close()


def execute(directory,phase,device_io=False):
    if not device_io:raise PermissionError('缺少明确实机开关')
    directory=regular_directory(directory);op=checked_approval(directory,phase)
    if sys.platform!='darwin' or os.geteuid()!=0:raise PermissionError('须在本次Terminal完成本机认证')
    (directory/('ATTEMPT_LOCK_'+phase.upper())).mkdir(mode=0o700)
    import device
    lab.engine()
    from system_dump.session import run_session
    before=device.host_snapshot();output=directory/('result-'+phase)
    report=run_session(output,'libusb',_operation=Operation(directory,op,phase))
    recovery=(device.observe_recovery(before,device.host_snapshot) if report.get('protocol_gate_passed') and report.get('service_stop_attempts')==1 else dict(recovered=False,reason='gate_withheld'))
    device.save_result(output,'host-recovery.json',recovery)
    report.update(run_id=op['run_id'],phase=phase,host_recovery_verified=recovery['recovered'],screen_confirmation_pending=True,
                  acceptance_complete=False,collect_not_before_unix=time.time()+190,automatic_second_session=False,persistent_account_write=False)
    if phase=='deploy' and report.get('protocol_gate_passed') and recovery['recovered'] and not report.get('failure'):
        try:client_once(op,output,report)
        except Exception as exc:report['ssh_failure']=type(exc).__name__+': '+str(exc)
    report['execution_succeeded']=bool(report.get('protocol_gate_passed') and recovery['recovered'] and not report.get('failure') and (phase=='collect' or report.get('ssh_fixed_command_verified')))
    device.save_result(output,'phase-result.json',report)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__);sub=p.add_subparsers(dest='action',required=True)
    a=sub.add_parser('prepare');a.add_argument('--name',required=True);a.add_argument('--address',required=True)
    for name in ('check','check-approval','execute'):
        a=sub.add_parser(name);a.add_argument('--operation',type=Path,required=True)
        if name!='check':a.add_argument('--phase',choices=('deploy','collect'),required=True)
        if name=='execute':a.add_argument('--device-io',action='store_true')
    a=p.parse_args()
    if a.action=='prepare':value=prepare(a.name,a.address)
    elif a.action=='check':value=check(a.operation)
    elif a.action=='check-approval':value=checked_approval(a.operation,a.phase)
    else:value=execute(a.operation,a.phase,a.device_io)
    print(json.dumps({k:v for k,v in value.items() if k not in ('sources','artifacts')},ensure_ascii=False,indent=2))
    return 3 if a.action=='execute' and not value['execution_succeeded'] else 0


if __name__=='__main__':
    try:raise SystemExit(main())
    except (Exception,KeyboardInterrupt) as exc:print('停止：'+type(exc).__name__+': '+str(exc),file=sys.stderr);raise SystemExit(2)
