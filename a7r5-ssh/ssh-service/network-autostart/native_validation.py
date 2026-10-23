"""系统OpenSSH的有界一次性验收；导入不会联网，调用者必须先通过USB恢复门槛。"""
import base64
import hashlib
import os
from pathlib import Path
import re
import selectors
import signal
import struct
import subprocess
import tempfile
import time


def public_key(raw):
    match=re.fullmatch(rb'ecdsa-sha2-nistp256 ([A-Za-z0-9+/=]+)(?: [ -~]*)?\n',raw)
    if not match:raise ValueError('可信USB主机公钥格式不符')
    blob=base64.b64decode(match[1],validate=True);fields=[];offset=0
    for _ in range(3):
        if offset+4>len(blob):raise ValueError('主机公钥结构不完整')
        size=struct.unpack_from('>I',blob,offset)[0];offset+=4
        if size>len(blob)-offset:raise ValueError('主机公钥字段越界')
        fields.append(blob[offset:offset+size]);offset+=size
    if offset!=len(blob) or fields[:2]!=[b'ecdsa-sha2-nistp256',b'nistp256'] or len(fields[2])!=65 or fields[2][0]!=4:raise ValueError('主机公钥类型或点编码不符')
    return b'ecdsa-sha2-nistp256 '+match[1], 'SHA256:'+base64.b64encode(hashlib.sha256(blob).digest()).decode().rstrip('=')


def run_bounded(command,stdin,environment,*,seconds=30,stdout_limit=8192,stderr_limit=4096):
    """独立进程组，有界读取；错误后只回收本客户端，不重建连接。"""
    process=subprocess.Popen(command,stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,
                             env=environment,start_new_session=True)
    stdout=bytearray();stderr=bytearray();deadline=time.monotonic()+seconds
    try:
        if stdin:process.stdin.write(stdin);process.stdin.flush()
        process.stdin.close()
        with selectors.DefaultSelector() as selector:
            selector.register(process.stdout,selectors.EVENT_READ,(stdout,stdout_limit))
            selector.register(process.stderr,selectors.EVENT_READ,(stderr,stderr_limit))
            while selector.get_map():
                left=deadline-time.monotonic()
                if left<=0:raise TimeoutError('本次系统SSH/SCP达到总时限，不重连')
                for key,_ in selector.select(min(.1,left)):
                    target,limit=key.data;chunk=os.read(key.fileobj.fileno(),min(4096,limit-len(target)+1))
                    if not chunk:selector.unregister(key.fileobj);continue
                    target.extend(chunk)
                    if len(target)>limit:raise ValueError('本次系统SSH/SCP输出超限')
            left=deadline-time.monotonic()
            if left<=0:raise TimeoutError('本次系统SSH/SCP退出超时')
            return process.wait(timeout=left),bytes(stdout),bytes(stderr)
    finally:
        if process.poll() is None:
            try:os.killpg(process.pid,signal.SIGTERM)
            except ProcessLookupError:pass
            except PermissionError:process.terminate()
            try:process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                try:os.killpg(process.pid,signal.SIGKILL)
                except ProcessLookupError:pass
                except PermissionError:process.kill()
                process.wait(timeout=2)
        for stream in (process.stdin,process.stdout,process.stderr):stream.close()


def terminal_script(run):
    if not re.fullmatch('[0-9a-f]{32}',run):raise ValueError('会话不符')
    path='/tmp_network/a7r5-ssh-transfer-'+run
    return ("[ -t 0 ] && [ -t 1 ] || exit 71\n"
            "printf '\\nA7R5_SERVICE_TTY "+run+"\\n'\n"
            "/bin/busybox cat /proc/self/status || exit 72\n"
            "[ ! -e "+path+" ] && [ ! -L "+path+" ] || exit 73\n"
            "/bin/busybox mkdir "+path+" || exit 74\nexit 0\n").encode()


def validate_terminal(raw,run):
    clean=raw.replace(b'\r',b'')
    if b'\nA7R5_SERVICE_TTY '+run.encode()+b'\n' not in clean:raise ValueError('PTY属性检查或固定标记未通过')
    for field in (b'Uid',b'Gid'):
        rows=re.findall(rb'^'+field+rb':[ \t]+([^\n]+)$',clean,re.M)
        if len(rows)!=1 or rows[0].split()!=[b'0']*4:raise ValueError('交互终端UID/GID不是四项0')


def verify(op,directory,output,report,password,*,runner=run_bounded):
    if not report.get('protocol_gate_passed') or not report.get('host_recovery_verified') or report.get('service_stop_attempts')!=1 or report.get('failure'):raise PermissionError('USB协议/恢复门槛未通过，不联网')
    run=op['run_id'];output=Path(output)
    raw=(output/'host-public-key').read_bytes()
    if hashlib.sha256(raw).hexdigest()!=report['host_public_sha256']:raise ValueError('USB可信公钥摘要变化，不联网')
    key,fingerprint=public_key(raw);alias='a7r5-service-'+run
    hostfile=output/'known_hosts'
    with hostfile.open('xb') as stream:stream.write(alias.encode()+b' '+key+b'\n')
    hostfile.chmod(0o600)
    report['trusted_host_key_fingerprint']=fingerprint
    common=['-F','/dev/null','-o','HostKeyAlias='+alias,'-o','UserKnownHostsFile='+str(hostfile),'-o','GlobalKnownHostsFile=/dev/null',
            '-o','StrictHostKeyChecking=yes','-o','HostKeyAlgorithms=ecdsa-sha2-nistp256','-o','IdentityAgent=none',
            '-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','NumberOfPasswordPrompts=1',
            '-o','ConnectionAttempts=1','-o','ConnectTimeout=10','-o','ControlMaster=no','-o','ControlPath=none','-o','ClearAllForwardings=yes']
    data=bytes(range(256))*256;source=output/'binary source.bin';source.write_bytes(data);source.chmod(0o600)
    download=output/'binary received.bin'
    target='root@'+op['target_ip'];remote='/tmp_network/a7r5-ssh-transfer-'+run+'/binary transfer.bin'
    # 临时凭据不进入归档；SSH严格校验可信主机公钥之后才会请求口令。
    with tempfile.TemporaryDirectory(prefix='a7r5-askpass-') as temp:
        temp=Path(temp).resolve();secret=temp/'password';secret.write_text(password+'\n');secret.chmod(0o600)
        askpass=temp/'askpass';askpass.write_text('#!/bin/sh\nexec /bin/cat "$A7R5_PASSWORD_FILE"\n');askpass.chmod(0o700)
        environment=dict(PATH='/usr/bin:/bin',LC_ALL='C',TERM='xterm',SSH_ASKPASS=str(askpass),SSH_ASKPASS_REQUIRE='force',DISPLAY='offline',A7R5_PASSWORD_FILE=str(secret))
        commands=[('terminal',['/usr/bin/ssh',*common,'-tt','-p','2222',target],terminal_script(run)),
                  ('upload',['/usr/bin/scp',*common,'-q','-P','2222',str(source),target+':'+remote],None),
                  ('download',['/usr/bin/scp',*common,'-q','-P','2222',target+':'+remote,str(download)],None)]
        report['mac_network_connections']=0
        for stage,command,stdin in commands:
            report['client_stage']=stage
            report['mac_network_connections']+=1
            try:code,stdout,stderr=runner(command,stdin,environment)
            except BaseException:
                report['network_failure_stage']=stage
                raise
            for name,raw in (('stdout',stdout),('stderr',stderr)):
                (output/(stage+'-'+name+'.txt')).write_bytes(raw.replace(password.encode(),b'[REDACTED]'))
            report.setdefault('client_exit_codes',{})[stage]=code
            if code:raise ValueError('系统'+stage+'非零退出，不重连')
            if stage=='terminal':
                validate_terminal(stdout,run)
                report.update(ssh_root_login_verified=True,real_pty_verified=True)
        if download.read_bytes()!=data:raise ValueError('SCP下载内容/长度不符，不重试')
        report.update(scp_roundtrip_verified=True,transfer_bytes=len(data),transfer_sha256=hashlib.sha256(data).hexdigest(),
                      remote_test_directory='/tmp_network/a7r5-ssh-transfer-'+run,background_service_left_running=True,final_service_cleanup_pending=True)
