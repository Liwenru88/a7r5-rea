"""默认仅离线核验；一次启动必须有本包的独立批准。"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys

import credentials
import host_state
import native_validation as native
from restart_operation import RestartOperation

HERE = Path(__file__).resolve().parent
RISK = ('两阶段认证/START，上传一个新的一次性执行库，临时改写已知自启预加载指针并一次DEBUG；'
        '执行器在启动服务前恢复原自启指针，调用已安装的启动器一次。'
        'RAM账户及0600密钥副本仅在私有视图创建，原账户与持久密钥不改；'
        '保留固定密码、0.0.0.0:2222无超时后台服务及原有自启配置。'
        '仅接受既有自启指针与启用标记；发现RAM实例或残留则保存证据后停止。'
        '全部门槛通过后一次STOP，普通USB与完整媒体恢复后一次root PTY只读验收。'
        '固定库、状态和输出可能持久残留；预加载恢复失败或门槛失败可能停留服务态，恢复受限。'
        '不重试、不强制清理、不改自启入口、不重启、不自动断电、不操作SD卡。')


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def regular(path):
    path = Path(path).absolute()
    if any(p.is_symlink() for p in (path,*path.parents)) or not path.is_file():
        raise ValueError('拒绝链接或非普通文件')
    return path


def save(path, value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')


def check(approved=False):
    manifest = json.loads(regular(HERE/'operation.json').read_text())
    if manifest['directory'] != str(HERE) or manifest['risk'] != RISK:
        raise ValueError('包绑定不符')
    for name,expected in manifest['files'].items():
        if Path(name).is_absolute() or '..' in Path(name).parts or digest(regular(HERE/name)) != expected:
            raise ValueError('包文件摘要不符：'+name)
    for name,expected in manifest['dependencies'].items():
        if digest(regular(name)) != expected:
            raise ValueError('本机依赖改变')
    if approved:
        expected = dict(accepted=True,operation_sha256=digest(HERE/'operation.json'),risk=RISK)
        if json.loads(regular(HERE/'approval.json').read_text()) != expected:
            raise PermissionError('缺少本包精确批准')
        if (HERE/'ATTEMPT_LOCK').exists() or (HERE/'result').exists():
            raise FileExistsError('本包已使用，不重试')
    return manifest


def execute(device_io=False):
    if not device_io:
        raise PermissionError('缺少实机开关')
    manifest = check(True)
    if sys.platform != 'darwin' or os.geteuid() != 0:
        raise PermissionError('需要本机Terminal管理员认证')
    password = credentials.load(manifest['credential_path'])
    (HERE/'ATTEMPT_LOCK').mkdir(mode=0o700)
    output = HERE/'result'
    output.mkdir(mode=0o700)
    result = dict(execution_succeeded=False,screen_confirmation_pending=True,automatic_retry=False,
                  autostart_repaired=False,debug_attempts=0,stop_attempts=0,ssh_connections=0)
    try:
        initial = host_state.snapshot(output,'initial')
        save(output/'initial.json',initial)
        baseline = manifest['host_baseline']
        if initial.get('kind') != 'ordinary' or initial['location_id'] != baseline['location_id'] or Counter(map(tuple,initial['media'])) != Counter(map(tuple,baseline['media'])) or set(initial['drivers']) != set(baseline['drivers']):
            raise ValueError('普通USB及完整媒体基线不符，不打开USB后端')
        sys.path[:0] = [str(HERE/'vendor/engine/libs'),str(HERE/'vendor/engine/mac')]
        from system_dump import session
        session.LIBUSB = Path(manifest['libusb'])
        report = session.run_session(output/'session','libusb',_operation=RestartOperation(output/'session',HERE))
        save(output/'session-result.json',report)
        result.update(debug_attempts=report.get('debug_attempts',0),stop_attempts=report.get('service_stop_attempts',0),
                      file_writes=report.get('fixed_writes_attempted',0),protocol_gate_passed=report.get('protocol_gate_passed',False))
        proof = host_state.observe(baseline,lambda label,timeout=5:host_state.snapshot(output,label,timeout))
        save(output/'host-recovery.json',proof)
        result['host_recovery_verified'] = proof['recovered']
        if report.get('failure') or not result['protocol_gate_passed'] or result['stop_attempts'] != 1 or not proof['recovered']:
            raise ValueError('启动或退出恢复门槛未通过；不连接SSH')
        alias = 'a7r5-manual-restart-'+manifest['run_id']
        public = (output/'session/host-public-key.bin').read_bytes()
        if hashlib.sha256(public).hexdigest() != manifest['public_sha256']:
            raise ValueError('公钥摘要不符')
        key,fingerprint = native.public_key(public)
        known = output/'known_hosts'
        known.write_bytes(alias.encode()+b' '+key+b'\n')
        known.chmod(0o600)
        common = ['-F','/dev/null','-o','HostKeyAlias='+alias,'-o','UserKnownHostsFile='+str(known),
                  '-o','GlobalKnownHostsFile=/dev/null','-o','StrictHostKeyChecking=yes',
                  '-o','HostKeyAlgorithms=ecdsa-sha2-nistp256','-o','IdentityAgent=none',
                  '-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password',
                  '-o','NumberOfPasswordPrompts=1','-o','ConnectionAttempts=1','-o','ConnectTimeout=10',
                  '-o','ControlMaster=no','-o','ControlPath=none','-o','ClearAllForwardings=yes','-o','ForwardAgent=no']
        # 只读PTY验收，不创建SFTP测试目录，不重复此前已通过的传输验收。
        script = ('[ -t 0 ] && [ -t 1 ] || exit 71\nprintf "\\nA7R5_SERVICE_TTY '+manifest['run_id']+'\\n"\n/bin/busybox cat /proc/self/status || exit 72\nexit 0\n').encode()
        result['ssh_connections'] = 1
        import tempfile
        with tempfile.TemporaryDirectory(prefix='a7r5-restart-') as temp:
            secret = Path(temp)/'password'
            secret.write_text(password+'\n'); secret.chmod(0o600)
            ask = Path(temp)/'askpass'
            ask.write_text('#!/bin/sh\nexec /bin/cat "$A7R5_PASSWORD_FILE"\n'); ask.chmod(0o700)
            environment = dict(PATH='/usr/bin:/bin',LC_ALL='C',TERM='xterm',SSH_ASKPASS=str(ask),
                               SSH_ASKPASS_REQUIRE='force',DISPLAY='local',A7R5_PASSWORD_FILE=str(secret))
            code,stdout,stderr = native.run_bounded(['/usr/bin/ssh',*common,'-tt','-p','2222','root@'+manifest['target_ip']],script,environment,seconds=25)
        (output/'pty-stdout.txt').write_bytes(stdout.replace(password.encode(),b'[REDACTED]'))
        (output/'pty-stderr.txt').write_bytes(stderr.replace(password.encode(),b'[REDACTED]'))
        if code:
            raise ValueError('PTY单次验收失败，不重连；服务可能仍在运行')
        native.validate_terminal(stdout,manifest['run_id'])
        result.update(execution_succeeded=True,root_pty_verified=True,background_service_left_running=True,
                      trusted_host_key_fingerprint=fingerprint,autostart_pointer_preserved=True)
    except (Exception,KeyboardInterrupt) as exc:
        result['failure'] = type(exc).__name__+': '+str(exc)
    finally:
        save(output/'result.json',result)
        owner = HERE.stat()
        for path in sorted(output.rglob('*'),reverse=True):
            os.chown(path,owner.st_uid,owner.st_gid,follow_symlinks=False)
        os.chown(output,owner.st_uid,owner.st_gid,follow_symlinks=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('check','check-approval','execute'))
    parser.add_argument('--device-io',action='store_true')
    args = parser.parse_args()
    if args.action == 'execute':
        result = execute(args.device_io)
        print(json.dumps(result,ensure_ascii=False,indent=2))
        return 0 if result['execution_succeeded'] else 3
    check(args.action == 'check-approval')
    print('离线材料核对通过；未连接相机。')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
