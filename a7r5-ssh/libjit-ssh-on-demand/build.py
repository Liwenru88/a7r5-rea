"""仅本机构建；不导入USB，不执行用户脚本，不使用相机私钥。"""
from pathlib import Path
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid

HERE = Path(__file__).resolve().parent
PROJECT = next(p for p in HERE.parents if (p/'a7r5-exec/sdk/libc-2.25.so').is_file())
SERVICE = PROJECT / 'a7r5-ssh/ssh-service'
sys.path.append(str(SERVICE))
import credentials


def sha(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def save(path, value):
    with Path(path).open('x', encoding='utf-8') as handle:
        os.fchmod(handle.fileno(), 0o600)
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')


def compile_target(source, output, includes, *, shared=False, extra_libraries=()):
    source, output, includes = map(Path, (source, output, includes))
    cmd = ['/opt/homebrew/opt/llvm/bin/clang', '--target=aarch64-linux-gnu',
           '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld', '-nostdlib', '-ffreestanding',
           '-fno-builtin', '-fno-stack-protector', '-O2', '-Wall', '-Wextra', '-Werror',
           '-Wl,--no-undefined', '-Wl,-z,max-page-size=65536', '-I', str(includes),
           '-I', str(HERE / 'src')]
    if shared:
        cmd += ['-fPIC', '-shared', '-fvisibility=hidden', '-Wl,-init,_init', str(source)]
    else:
        cmd += ['-fPIE', '-pie', '-Wl,-e,_start', '-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1',
                str(HERE / 'src/start.S'), str(source), str(PROJECT / 'a7r5-exec/sdk/libc-2.25.so')]
    cmd += [str(p) for p in extra_libraries] + ['-o', str(output)]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    save(output.with_suffix(output.suffix + '.build.json'), dict(argv=cmd, exit_code=result.returncode,
                                                              stdout=result.stdout, stderr=result.stderr))
    if result.returncode:
        raise RuntimeError(result.stderr)
    output.chmod(0o600)
    from elftools.elf.elffile import ELFFile
    with output.open('rb') as handle:
        elf = ELFFile(handle)
        dynamic = list(elf.get_section_by_name('.dynamic').iter_tags())
        needed = [tag.needed for tag in dynamic if tag.entry.d_tag == 'DT_NEEDED']
        assert elf['e_machine'] == 'EM_AARCH64' and elf['e_type'] == 'ET_DYN'
        if shared:
            assert not needed and any(tag.entry.d_tag == 'DT_INIT' for tag in dynamic)
            assert not [s.name for s in elf.get_section_by_name('.dynsym').iter_symbols()
                        if s.name and s['st_shndx'] == 'SHN_UNDEF']
        else:
            assert needed == ['libc.so.6'] + (['libdl.so.2'] if extra_libraries else [])
    return dict(bytes=output.stat().st_size, sha256=sha(output), needed=needed)


def build(directory, password_hash, *, seconds=0, run=None, qemu_only=False):
    if not credentials.valid_hash(password_hash):
        raise ValueError('口令哈希格式不符')
    if type(seconds) is not int or not 0 <= seconds <= 86400:
        raise ValueError('寿命须为0（不限时）或1至86400秒')
    run = run or uuid.uuid4().hex
    if not re.fullmatch('[a-f0-9]{32}', run):
        raise ValueError('会话ID不符')
    directory = Path(directory).absolute()
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError('拒绝链接构建路径')
    directory.mkdir(parents=True, exist_ok=False, mode=0o700)
    # Senser固定写入接口不提供mkdir；使用随机前缀平铺，load阶段不执行机内代码。
    prefix = '/tmp/jiritsu/a7r5-ljssh-' + run
    ram_name = 'a7r5-libjit-ssh-' + run
    private = '/var/run/' + ram_name
    config = f'''Port 2222
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
Subsystem sftp {prefix}.sftp
ForceCommand {prefix}.session
PrintMotd no
LogLevel ERROR
'''
    values = dict(RUN_ID=run, RAM_NAME=ram_name, PRIVATE_DIR=private,
                  SERVICE_PATH=prefix+'.service', SESSION_PATH=prefix+'.session', SFTP_PATH=prefix+'.sftp',
                  PASSWORD_HASH=password_hash, SSH_CONFIG=config,
                  EXPECTED_PASSWD_SHA='4a691edcd492167bb3d538e4e15c24dd5fbc45785afcf2beddb3fbd39e097398')
    header = ''.join('#define '+k+' '+json.dumps(v)+'\n' for k, v in values.items())
    (directory/'config.h').write_text(header+f'#define SSH_SECONDS {seconds}\n')
    (directory/'config.h').chmod(0o600)
    trigger = dict(RUN_ID=run, SERVICE_PATH=prefix+'.service', SESSION_PATH=prefix+'.session',
                   SFTP_PATH=prefix+'.sftp', LIBJIT_PATH='/tmp/jiritsu/libJit.so',
                   TICKET_PATH=prefix+'.ticket', TICKET_BYTES='A7R5_SSH_START '+run+'\n',
                   CLAIM_PATH=prefix+'.claim', STATE_PATH=prefix+'.trigger-state', STATE_NEW=prefix+'.trigger-new')
    (directory/'jit_config.h').write_text(''.join('#define '+k+' '+json.dumps(v)+'\n' for k,v in trigger.items()))
    artifacts = {}
    for source, name, shared in [('launcher.c','service.arm64',False), ('session.c','session.arm64',False),
                                  ('trigger.c','libJit.so',True)]:
        artifacts[name] = compile_target(HERE/'src'/source, directory/name, directory, shared=shared)
    vendor = SERVICE/'original-view/vendor'
    for name in ['sftp-server.arm64','sftp-provenance.json','sftp-COPYRIGHT']:
        shutil.copyfile(vendor/name, directory/name)
        (directory/name).chmod(0o600)
    provenance = json.loads((directory/'sftp-provenance.json').read_text())
    if sha(directory/'sftp-server.arm64') != provenance['binary_sha256']:
        raise ValueError('SFTP来源摘要变化')
    artifacts['sftp-server.arm64'] = dict(bytes=(directory/'sftp-server.arm64').stat().st_size,
                                          sha256=sha(directory/'sftp-server.arm64'))
    (directory/'ticket.bin').write_text(trigger['TICKET_BYTES'])
    result = dict(schema='a7r5-libjit-ssh-build-1', run_id=run, prefix=prefix,
                  ram_directory='/tmp_network/'+ram_name, port=2222, ttl_seconds=seconds,
                  qemu_only=qemu_only, autostart=False, camera_io=False, artifacts=artifacts,
                  uploads={prefix+'.service':'service.arm64', prefix+'.session':'session.arm64',
                           prefix+'.sftp':'sftp-server.arm64'},
                  source_sha256={str(p.relative_to(HERE)):sha(p) for p in sorted((HERE/'src').iterdir())})
    save(directory/'build.json', result)
    return result
