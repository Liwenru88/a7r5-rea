#!/usr/bin/env python3
"""SSH 离线材料与一次性预检；默认命令不导入或枚举 USB。"""
import argparse
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import uuid

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
SSHD_SHA = 'a6b871ef0da3990ea0d25d7996ee79c3bfc29385d4eb1670892814c0e1472534'
VERSION_SHA = '34c44c5d2974d822eb8c43953317c8ccecaa51b72ffad8693d1cd3261a4fa79b'
RISK = ('仅运行固定 SSH 预检脚本；认证/START、固定载荷与预加载写入、一次 DEBUG；'
        '精确512换行基线，不覆盖未知内容，不修改账户、不启动SSH；符合门槛才一次STOP。'
        '预加载中和不等于还原，保留载荷/状态/输出残留，异常不重试、不断电。')


def regular(path):
    path = Path(path).absolute()
    if path.is_relative_to('/dev') or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError('拒绝设备或链接路径')
    import stat
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError('仅接受普通文件')
    return path


def digest(path):
    with regular(path).open('rb') as f:
        return hashlib.file_digest(f, 'sha256').hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as f:
        json.dump(value, f, ensure_ascii=False, indent=2)
        f.write('\n')


def sources():
    files = [*ROOT.glob('*.py'), ROOT/'start-preflight.command']
    for directory in ('src', 'vendor'):
        files += [p for p in (ROOT/directory).rglob('*') if p.is_file() and '__pycache__' not in p.parts]
    return {str(p.relative_to(ROOT)): digest(p) for p in sorted(files)}


def engine():
    sys.path[:0] = [str(ROOT/'vendor/engine/libs'), str(ROOT/'vendor/engine/mac')]


def root_header(run, script, seconds, *, directory='/tmp/jiritsu', preload='/etc/ld.so.preload', gate='/proc/self/cmdline'):
    if not re.fullmatch('[0-9a-f]{32}', run) or not 1 <= seconds <= 300:
        raise ValueError('无效会话或时限')
    prefix = directory+'/a7r5-'+run
    values = dict(RUN_ID=run, STATE_PATH=prefix+'.state', OUTPUT_PATH=prefix+'.output',
                  ARM_BYTES=prefix+'.so\n', PRELOAD_PATH=preload, GATE_PATH=gate, TASK_SCRIPT=script)
    return '\n'.join('#define '+k+' '+json.dumps(v) for k,v in values.items())+f'\n#define TASK_SECONDS {seconds}U\n#define OUTPUT_LIMIT 32768U\n'


def preflight_script(run):
    return (ROOT/'src/preflight.sh').read_text().replace('@RUN@', run)


def build_preflight(output):
    output = Path(output).absolute()
    if output.is_relative_to('/dev') or any(p.is_symlink() for p in (output,*output.parents)):
        raise ValueError('输出不能经过链接或设备目录')
    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    run = uuid.uuid4().hex
    script = preflight_script(run)
    subprocess.run(['/bin/sh','-n'], input=script, text=True, check=True)
    (output/'task.sh').write_text(script)
    (output/'root_config.h').write_text(root_header(run, script, 45))
    compiler = Path('/opt/homebrew/opt/llvm/bin/clang').resolve()
    # lld 依据调用名选择驱动，命令中必须保留 ld.lld 名称。
    linker = Path('/opt/homebrew/opt/lld/bin/ld.lld')
    libc = ROOT/'vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.25.so'
    payload = output/'preflight.arm64.so'
    command = [str(compiler),'--target=aarch64-linux-gnu','--ld-path='+str(linker),'-nostdlib',
               '-ffreestanding','-fPIC','-fno-builtin','-fno-stack-protector','-fvisibility=hidden',
               '-O2','-Wall','-Wextra','-Werror','-DA7R5_SSH_PREFLIGHT','-shared','-Wl,--no-undefined','-Wl,-z,max-page-size=65536',
               '-I',str(output),str(ROOT/'src/root_once.c'),str(ROOT/'src/preflight_fs.c'),str(libc),'-o',str(payload)]
    result = subprocess.run(command, capture_output=True, text=True, timeout=90)
    save(output/'build.json', dict(command=command, exit_code=result.returncode, stdout=result.stdout, stderr=result.stderr))
    if result.returncode:
        raise RuntimeError('载荷构建失败，保留日志')
    engine()
    from system_dump.environment import static_payload_check
    checked = static_payload_check(payload, digest(payload))
    save(output/'elf-verification.json', checked)
    (output/'preload-arm.bin').write_bytes(('/tmp/jiritsu/a7r5-'+run+'.so\n').encode())
    (output/'preload-neutral.bin').write_bytes(b'\n'*512)
    value = dict(schema='a7r5-ssh-preflight-1', kind='preflight', run_id=run,
                 material_root=str(ROOT), operation_directory=str(output), risk=RISK,
                 camera_execution_verified=False, ssh_deployment_enabled=False,
                 target=dict(model='ILCE-7RM5', firmware='4.00', normal_pid=0x0e0a, service_pid=0x0336, location_id=0x01100000),
                 sources=sources(), runtime={str(Path(sys.executable).resolve()):digest(Path(sys.executable).resolve()),
                    '/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib':hashlib.sha256(Path('/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib').read_bytes()).hexdigest()},
                 artifacts={p.name:digest(p) for p in output.iterdir() if p.is_file()})
    save(output/'operation.json', value)
    save(output/'approval-template.json', approval_expected(value, digest(output/'operation.json'), accepted=False))
    return value


def approval_expected(value, operation_sha, accepted=True):
    return dict(schema='a7r5-ssh-preflight-approval-1', run_id=value['run_id'], operation_sha256=operation_sha,
                accepted=accepted, risk=value['risk'], account_changes=False, start_ssh=False,
                fixed_file_writes=True, authentication_start=True, debug_once=True, conditional_stop_once=True)


def check(directory):
    if ROOT.stat().st_mode & 0o077:
        raise PermissionError('材料根目录须设为700，避免其他本机账户修改待sudo执行的材料')
    directory = regular(Path(directory)/'operation.json').parent
    value = json.loads((directory/'operation.json').read_text())
    if (value.get('schema')!='a7r5-ssh-preflight-1' or value.get('kind')!='preflight'
            or value.get('material_root')!=str(ROOT) or value.get('operation_directory')!=str(directory)
            or not re.fullmatch('[0-9a-f]{32}', value.get('run_id','')) or value.get('risk')!=RISK
            or value.get('ssh_deployment_enabled') is not False
            or value.get('target')!=dict(model='ILCE-7RM5', firmware='4.00', normal_pid=0x0e0a, service_pid=0x0336, location_id=0x01100000)):
        raise ValueError('身份、位置或操作范围不符，移动后须重新准备')
    if value['sources']!=sources():
        raise ValueError('材料摘要变化，旧包失效')
    expected={'task.sh','root_config.h','preflight.arm64.so','preload-arm.bin','preload-neutral.bin','build.json','elf-verification.json'}
    if set(value['artifacts'])!=expected:
        raise ValueError('固定材料集合变化')
    for name,sha in value['artifacts'].items():
        if digest(directory/name)!=sha: raise ValueError('固定材料变化：'+name)
    for name,sha in value['runtime'].items():
        # Homebrew 的安装路径本身可能是受管理链接，校验最终普通文件身份。
        if digest(Path(name).resolve())!=sha: raise ValueError('运行依赖变化：'+name)
    if (directory/'preload-neutral.bin').read_bytes()!=b'\n'*512:
        raise ValueError('预加载基线变化')
    return value


def checked_approval(directory):
    directory=Path(directory).absolute()
    approval=json.loads(regular(directory/'approval.json').read_text())
    value=check(directory)
    if approval!=approval_expected(value,digest(directory/'operation.json')):
        raise PermissionError('缺少绑定本次材料的实机批准')
    if (directory/'ATTEMPT_LOCK').exists() or (directory/'result').exists():
        raise FileExistsError('已有尝试或结果，禁止重试')
    return value


def execute_preflight(directory, device_io=False):
    directory=Path(directory).absolute()
    # 此门槛早于加载设备模块、主机元数据或 libusb。
    if not device_io: raise PermissionError('没有显式实机执行开关；本轮仅离线')
    value=checked_approval(directory)
    if sys.platform!='darwin' or os.geteuid()!=0:
        raise PermissionError('须在确认后的 macOS Terminal 本机认证')
    if (directory/'result').exists(): raise FileExistsError('已有结果，禁止重试')
    (directory/'ATTEMPT_LOCK').mkdir(mode=0o700)
    from device import run_preflight
    return run_preflight(directory,value)


def parse_preflight(data, run):
    text=data.decode('utf-8',errors='strict')
    if len(data)>=32768 or text.count('A7R5_SSH_PREFLIGHT_BEGIN '+run+'\n')!=1 or not text.endswith('A7R5_SSH_PREFLIGHT_COMPLETE '+run+'\n'):
        raise ValueError('预检不完整、超限或会话不符')
    def one(tag):
        values=re.findall('^'+re.escape(tag)+' (.*)$',text,re.M)
        if len(values)!=1: raise ValueError('缺少或重复字段：'+tag)
        return values[0]
    if one('UID')!='0' or one('EUID')!='0': raise ValueError('预检不是root')
    if one('VERSION_SHA256')!=VERSION_SHA: raise ValueError('版本基线不符')
    if one('SSHD_SHA256')!=SSHD_SHA: raise ValueError('sshd基线不符')
    shell=one('ROOT_SHELL')
    return dict(preflight_complete=True, root_shell=shell, account_change_required=shell!='/bin/sh',
                deployment_allowed=False, review_required=True,
                reason='还需审查挂载、空间、账户、网络与独立批准；不自动启动SSH')


def ssh_config(run, address, public_key, seconds=20):
    import base64
    if not re.fullmatch('[0-9a-f]{32}',run) or not 5<=seconds<=30:
        raise ValueError('无效会话或时限')
    ip=ipaddress.IPv4Address(address)
    if ip.is_unspecified or ip.is_multicast or ip.is_reserved or (not ip.is_private and not ip.is_loopback):
        raise ValueError('只允许明确的局域网或回环IPv4地址')
    parts=public_key.strip().split()
    if len(parts)!=2 or parts[0]!='ssh-ed25519': raise ValueError('只接受无选项、无注释的ed25519公钥')
    raw=base64.b64decode(parts[1],validate=True)
    if len(raw)!=51 or raw[:19]!=b'\0\0\0\x0bssh-ed25519\0\0\0\x20': raise ValueError('公钥格式不符')
    d='/tmp_network/a7r5-ssh-'+run
    conf=f'''Port 2222
AddressFamily inet
ListenAddress {ip}
HostKey {d}/host_ecdsa
PidFile {d}/sshd.pid
AuthorizedKeysFile {d}/authorized_keys
PermitRootLogin prohibit-password
PubkeyAuthentication yes
PasswordAuthentication no
ChallengeResponseAuthentication no
UsePAM no
StrictModes yes
AllowUsers root
MaxSessions 1
MaxStartups 1
MaxAuthTries 1
LoginGraceTime 10
AllowTcpForwarding no
AllowAgentForwarding no
X11Forwarding no
PermitTunnel no
PermitTTY no
ForceCommand /bin/busybox cat /proc/self/status
LogLevel ERROR
'''
    return dict(directory=d,configuration=conf,public_key=' '.join(parts)+'\n',seconds=seconds,
                interactive_shell_enabled=False,account_modification_enabled=False,
                production_deployment_enabled=False)


def smoke_script(run,address,public_key,supervisor_sha,seconds=20):
    if not re.fullmatch('[0-9a-f]{64}',supervisor_sha): raise ValueError('缺少固定监督器摘要')
    config=ssh_config(run,address,public_key,seconds)
    values={'SSHD_SHA':SSHD_SHA,'SUPERVISOR':'/tmp/jiritsu/a7r5-'+run+'.supervisor',
            'SUPERVISOR_SHA':supervisor_sha,'DIRECTORY':config['directory'],
            'PUBLIC_KEY':config['public_key'].strip(),'CONFIG':config['configuration'],'SECONDS':str(seconds)}
    script=(ROOT/'src/prepare-smoke.sh').read_text()
    for name,value in values.items(): script=script.replace('@'+name+'@',value)
    if re.search('@[A-Z_]+@',script): raise ValueError('模板未完全固定')
    subprocess.run(['/bin/sh','-n'],input=script,text=True,check=True,capture_output=True)
    return script


def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest='action',required=True)
    q=sub.add_parser('prepare-preflight'); q.add_argument('--output',type=Path,required=True)
    for cmd in ('check','check-approval','execute-preflight'):
        q=sub.add_parser(cmd); q.add_argument('--operation',type=Path,required=True)
        if cmd=='execute-preflight': q.add_argument('--device-io',action='store_true')
    a=p.parse_args()
    if a.action=='prepare-preflight': value=build_preflight(a.output)
    elif a.action=='check': value=check(a.operation)
    elif a.action=='check-approval': value=checked_approval(a.operation)
    else: value=execute_preflight(a.operation,a.device_io)
    print(json.dumps({k:v for k,v in value.items() if k not in ('sources','runtime','artifacts')},ensure_ascii=False,indent=2))
    if a.action=='execute-preflight' and value.get('execution_succeeded') is not True:
        return 3
    return 0


if __name__=='__main__':
    try: raise SystemExit(main())
    except (Exception,KeyboardInterrupt) as exc:
        print('停止：'+type(exc).__name__+': '+str(exc),file=sys.stderr); raise SystemExit(2)
