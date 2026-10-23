"""只编译新候选；不枚举设备、不建立连接、不修改旧材料。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
import uuid

ROOT=Path(__file__).resolve().parent
SERVICE=ROOT.parent
LAB=SERVICE.parent
sys.path.insert(0,str(SERVICE))
import credentials


def digest(path):
    with Path(path).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def compile_target(source, output, includes):
    libc=LAB/'vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.25.so'
    cmd=['/opt/homebrew/opt/llvm/bin/clang','--target=aarch64-linux-gnu',
         '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld','-nostdlib','-ffreestanding',
         '-fno-builtin','-fno-stack-protector','-fPIE','-pie','-O2','-Wall','-Wextra','-Werror',
         '-Wl,--no-undefined','-Wl,-e,_start','-Wl,-z,max-page-size=65536',
         '-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1','-I',str(includes),
         str(LAB/'src/start.S'),str(source),str(libc),'-o',str(output)]
    result=subprocess.run(cmd,capture_output=True,text=True,timeout=60)
    if result.returncode:raise RuntimeError(result.stderr)
    return dict(command=cmd,sha256=digest(output),bytes=output.stat().st_size)


def build(directory,password_hash,*,seconds=600,run=None,qemu_only=False):
    if not credentials.valid_hash(password_hash):raise ValueError('密码哈希格式不符')
    if seconds not in (0,600):raise ValueError('仅接受600秒候选或显式无超时版本')
    run=run or uuid.uuid4().hex
    if not re.fullmatch('[a-f0-9]{32}',run):raise ValueError('会话ID不符')
    directory=Path(directory).absolute()
    if any(p.is_symlink() for p in (directory,*directory.parents)):raise ValueError('拒绝链接构建路径')
    directory.mkdir(parents=True,exist_ok=False,mode=0o700)
    install='/tmp/jiritsu/a7r5-original-'+run
    ram='a7r5-original-'+run
    private='/var/run/'+ram
    config=f'''Port 2223
AddressFamily inet
ListenAddress 0.0.0.0
HostKey {private}/host_ecdsa
PidFile {private}/sshd.pid
AuthorizedKeysFile none
PermitRootLogin yes
PubkeyAuthentication no
AuthenticationMethods password
PasswordAuthentication yes
PermitEmptyPasswords no
ChallengeResponseAuthentication no
UsePAM no
StrictModes yes
AllowUsers root
MaxSessions 4
MaxStartups 1
MaxAuthTries 1
LoginGraceTime 10
AllowTcpForwarding no
AllowStreamLocalForwarding no
AllowAgentForwarding no
X11Forwarding no
PermitTunnel no
PermitTTY yes
PermitUserEnvironment no
PermitUserRC no
PrintLastLog no
UseDNS no
Subsystem sftp {install}/sftp-server.arm64
ForceCommand {install}/session.arm64
PrintMotd no
LogLevel ERROR
'''
    values=dict(SOURCE_KEY_DIR="/var/run/a7r5-ssh-5e551f1a97774fa1885f15799583d09b",ORIGIN_HOLDER_EXE="/simulation/origin-holder" if qemu_only else "/usr/bin/bootin.elf",INSTALL_DIR=install,RUN_ID=run,RAM_NAME=ram,PRIVATE_DIR=private,
                PASSWORD_HASH=password_hash,SSH_CONFIG=config,
                EXPECTED_PASSWD_SHA='4a691edcd492167bb3d538e4e15c24dd5fbc45785afcf2beddb3fbd39e097398')
    header=directory/'config.h'
    header.write_text(''.join('#define '+k+' '+json.dumps(v)+'\n' for k,v in values.items())+'#define SSH_SECONDS '+str(seconds)+'\n#define SOURCE_KEY_BYTES 505\n')
    header.chmod(0o600)
    binaries={}
    for source,name in [('launcher.c','ssh-original.arm64'),('session.c','session.arm64'),('anchor.c','anchor.arm64')]:
        binaries[name]=compile_target(ROOT/source,directory/name,directory)
    result=dict(run_id=run,install_directory=install,ram_directory='/tmp_network/'+ram,
                port=2223,seconds=seconds,qemu_only=qemu_only,binaries=binaries,autostart=False,camera_io=False,
                source_sha256={str(p.relative_to(LAB.parent)):digest(p) for p in
                    [ROOT/'launcher.c',ROOT/'proof.h',ROOT/'session.c',ROOT/'anchor.c',ROOT/'build_candidate.py',
                     SERVICE/'private_account.h',SERVICE/'private_hostkey.h',LAB/'src/ns_abi.h',LAB/'src/ns_sha256.h',LAB/'src/start.S']})
    (directory/'build.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return result


if __name__=='__main__':
    p=argparse.ArgumentParser(description='仅本机构建；密码从本地提示输入，不放命令行')
    p.add_argument('directory',type=Path);p.add_argument('--no-timeout',action='store_true')
    a=p.parse_args()
    import getpass
    result=build(a.directory,credentials.make_hash(getpass.getpass('候选SSH口令：')),seconds=0 if a.no_timeout else 600)
    print(json.dumps(dict(run_id=result['run_id'],camera_io=False,port=2223),ensure_ascii=False))
