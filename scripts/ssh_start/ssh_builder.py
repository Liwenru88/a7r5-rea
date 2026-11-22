"""SSH 口令哈希生成与 libjit/kit 双引擎 AArch64 二进制交叉编译构建器。"""
import hashlib
import json
from pathlib import Path
import re
import secrets
import shutil
import subprocess

from elftools.elf.elffile import ELFFile

PROJECT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
SSH_SRC = PROJECT / 'a7r5-ssh/libjit-ssh-on-demand/src'
SFTP_VENDOR = PROJECT / 'a7r5-ssh/ssh-service/original-view/vendor'
LIBC_SDK = PROJECT / 'a7r5-exec/sdk/libc-2.25.so'
DESKTOP_ENGINE = PROJECT / 'a7r5-desktop/engine'
PREPARED_ENGINE = PROJECT / 'a7r5-desktop/prepared/engine'

CLANG = Path('/opt/homebrew/opt/llvm/bin/clang')
LLD = Path('/opt/homebrew/opt/lld/bin/ld.lld')
OPENSSL = Path('/opt/homebrew/opt/openssl/bin/openssl')

HASH_PATTERN = re.compile(r'\$6\$rounds=10000\$[A-Za-z0-9./]{16}\$[A-Za-z0-9./]{86}')
EXPECTED_PASSWD_SHA = '4a691edcd492167bb3d538e4e15c24dd5fbc45785afcf2beddb3fbd39e097398'


def sha256_file(path):
    with Path(path).open('rb') as handle:
        return hashlib.file_digest(handle, 'sha256').hexdigest()


def validate_password(password):
    """校验用户口令：8~128 字符，不允许控制字符，UTF-8 不超过 512 字节。"""
    if (
        not isinstance(password, str)
        or not 8 <= len(password) <= 128
        or any(ord(c) < 32 or ord(c) == 127 for c in password)
        or len(password.encode('utf-8')) > 512
    ):
        raise ValueError('SSH 密码须为 8~128 个非控制字符')


def make_password_hash(password):
    """调用 openssl 生成 SHA-512 crypt ($6$rounds=10000$...) 哈希。"""
    validate_password(password)
    if not OPENSSL.is_file():
        raise FileNotFoundError(f'缺少 openssl：{OPENSSL}')
    alphabet = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789./'
    salt = ''.join(secrets.choice(alphabet) for _ in range(16))
    proc = subprocess.run(
        [str(OPENSSL), 'passwd', '-6', '-salt', f'rounds=10000${salt}', '-stdin'],
        input=password + '\n',
        text=True,
        capture_output=True,
        timeout=15,
    )
    value = proc.stdout.strip()
    if proc.returncode != 0 or not HASH_PATTERN.fullmatch(value):
        raise RuntimeError('生成 SSH 密码哈希失败')
    return value


def verify_toolchain():
    for tool in (CLANG, LLD, LIBC_SDK):
        if not tool.exists():
            raise FileNotFoundError(f'缺少构建依赖：{tool}')


def _compile_elf(source, output, include_dir, *, shared=False):
    cmd = [
        str(CLANG),
        '--target=aarch64-linux-gnu',
        '--ld-path=' + str(LLD),
        '-nostdlib',
        '-ffreestanding',
        '-fno-builtin',
        '-fno-stack-protector',
        '-O2',
        '-Wall',
        '-Wextra',
        '-Werror',
        '-Wl,--no-undefined',
        '-Wl,-z,max-page-size=65536',
        '-I',
        str(include_dir),
        '-I',
        str(SSH_SRC),
    ]
    if shared:
        cmd += ['-fPIC', '-shared', '-fvisibility=hidden', '-Wl,-init,_init', str(source)]
    else:
        cmd += [
            '-fPIE',
            '-pie',
            '-Wl,-e,_start',
            '-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1',
            str(SSH_SRC / 'start.S'),
            str(source),
            str(LIBC_SDK),
        ]
    cmd += ['-o', str(output)]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    if proc.returncode != 0:
        raise RuntimeError(f'编译 {source.name} 失败：\n{proc.stderr}')

    with Path(output).open('rb') as handle:
        elf = ELFFile(handle)
        if elf['e_machine'] != 'EM_AARCH64' or elf['e_type'] != 'ET_DYN':
            raise ValueError(f'{output.name} ELF 架构或类型错误')
        dynamic = list(elf.get_section_by_name('.dynamic').iter_tags())
        needed = [t.needed for t in dynamic if t.entry.d_tag == 'DT_NEEDED']
        undefined = [
            s.name
            for s in elf.get_section_by_name('.dynsym').iter_symbols()
            if s.name and s['st_shndx'] == 'SHN_UNDEF'
        ]
        if shared:
            if needed or undefined or not any(t.entry.d_tag == 'DT_INIT' for t in dynamic):
                raise ValueError(f'{output.name} 共享库依赖或入口不符合要求')
        else:
            if needed != ['libc.so.6']:
                raise ValueError(f'{output.name} 可执行文件依赖不符合要求：{needed}')
    return Path(output).read_bytes()


def load_profile():
    path = DESKTOP_ENGINE / 'profile.json'
    if not path.is_file():
        path = PREPARED_ENGINE / 'profile.json'
    return json.loads(path.read_text())


def build_ssh_package(package_dir, engine, run_id, password_hash, baseline_host, *, ttl_seconds=0):
    """构建完整 SSH 运行包（支持 libjit 与 kit 双引擎，绑定实时 USB 端口）。"""
    if engine not in ('libjit', 'kit'):
        raise ValueError(f'不支持的引擎：{engine}')
    if not HASH_PATTERN.fullmatch(password_hash):
        raise ValueError('密码哈希格式不符')
    if type(ttl_seconds) is not int or not 0 <= ttl_seconds <= 86400:
        raise ValueError('TTL 范围须为 0~86400 秒')
    verify_toolchain()

    package_dir = Path(package_dir)
    mat_dir = package_dir / 'materials'
    build_dir = package_dir / 'build'
    mat_dir.mkdir(parents=True, exist_ok=True)
    build_dir.mkdir(parents=True, exist_ok=True)

    # 将程序与控制文件平铺到 /tmp_wbshd 内存盘，避免消耗 /tmp/jiritsu (nflasha6 FAT12) 根目录槽位
    prefix = '/tmp_wbshd/a7r5-ljssh-' + run_id
    ram_name = 'a7r5-libjit-ssh-' + run_id
    private = '/var/run/' + ram_name
    ram_directory = '/tmp_network/' + ram_name

    sshd_config = f'''Port 2222
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
    config_defs = {
        'RUN_ID': run_id,
        'RAM_NAME': ram_name,
        'PRIVATE_DIR': private,
        'SERVICE_PATH': prefix + '.service',
        'SESSION_PATH': prefix + '.session',
        'SFTP_PATH': prefix + '.sftp',
        'PASSWORD_HASH': password_hash,
        'SSH_CONFIG': sshd_config,
        'EXPECTED_PASSWD_SHA': EXPECTED_PASSWD_SHA,
    }
    (build_dir / 'config.h').write_text(
        ''.join(f'#define {k} {json.dumps(v)}\n' for k, v in config_defs.items()) + f'#define SSH_SECONDS {ttl_seconds}\n'
    )

    _compile_elf(SSH_SRC / 'launcher.c', mat_dir / 'service.arm64', build_dir, shared=False)
    _compile_elf(SSH_SRC / 'session.c', mat_dir / 'session.arm64', build_dir, shared=False)

    shutil.copyfile(SFTP_VENDOR / 'sftp-server.arm64', mat_dir / 'sftp-server.arm64')
    provenance = json.loads((SFTP_VENDOR / 'sftp-provenance.json').read_text())
    if sha256_file(mat_dir / 'sftp-server.arm64') != provenance['binary_sha256']:
        raise ValueError('sftp-server.arm64 摘要与来源清单不符')

    profile = load_profile()
    bus, ports = baseline_host['bus'], baseline_host['ports']
    for row in profile['interfaces'].values():
        row['bus'] = bus
        row['ports'] = ports

    base_trigger = {
        'RUN_ID': run_id,
        'SERVICE_PATH': prefix + '.service',
        'SESSION_PATH': prefix + '.session',
        'SFTP_PATH': prefix + '.sftp',
        'LIBJIT_PATH': '/tmp/jiritsu/libJit.so',
        'TICKET_PATH': prefix + '.ticket',
        'TICKET_BYTES': f'A7R5_SSH_START {run_id}\n',
        'CLAIM_PATH': prefix + '.claim',
        'STATE_PATH': prefix + '.trigger-state',
        'STATE_NEW': prefix + '.trigger-new',
    }
    if engine == 'libjit':
        (build_dir / 'jit_config.h').write_text(
            ''.join(f'#define {k} {json.dumps(v)}\n' for k, v in base_trigger.items())
        )
        _compile_elf(SSH_SRC / 'trigger.c', mat_dir / 'libJit.so', build_dir, shared=True)
        (mat_dir / 'ticket.bin').write_text(base_trigger['TICKET_BYTES'])
    else:
        kit_so = f'/tmp_wbshd/a7r5-ssh-{run_id}.so'
        for name, hex_bytes in profile['preload_baselines']:
            sub_dir = build_dir / f'kit-{name}'
            sub_dir.mkdir(parents=True, exist_ok=True)
            kit_defs = dict(
                base_trigger,
                PRELOAD_PATH='/etc/ld.so.preload',
                GATE_PATH='/proc/self/cmdline',
                KIT_SO_PATH=kit_so,
                ARM_BYTES=kit_so + '\n',
                RESTORE_PRELOAD=bytes.fromhex(hex_bytes).decode('ascii'),
            )
            (sub_dir / 'jit_config.h').write_text(
                ''.join(f'#define {k} {json.dumps(v)}\n' for k, v in kit_defs.items())
            )
            _compile_elf(HERE / 'kit-ssh-trigger.c', mat_dir / f'kit-{name}.so', sub_dir, shared=True)

    uploads = {
        prefix + '.service': 'service.arm64',
        prefix + '.session': 'session.arm64',
        prefix + '.sftp': 'sftp-server.arm64',
    }
    build_meta = {
        'run_id': run_id,
        'engine': engine,
        'prefix': prefix,
        'ram_directory': ram_directory,
        'port': 2222,
        'ttl_seconds': ttl_seconds,
        'uploads': uploads,
    }
    (mat_dir / 'build.json').write_text(json.dumps(build_meta, ensure_ascii=False, indent=2) + '\n')

    cfg = {
        'run_id': run_id,
        'engine': engine,
        'interfaces': profile['interfaces'],
        'host_baseline': baseline_host,
        'version_sha256': profile['version_sha256'],
        'loader_sha256': profile['loader_sha256'],
        'loader_bytes': profile['loader_bytes'],
        'preload_baselines': profile['preload_baselines'],
    }
    (package_dir / 'config.json').write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + '\n')
    return cfg, build_meta
