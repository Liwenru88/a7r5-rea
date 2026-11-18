#!/usr/bin/env python3
"""一键启动 A7R5 相机 SSH 服务（支持 libjit/kit、动态 USB 端口、0336 自动恢复与闭环）。"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import getpass
import ipaddress
import json
import os
from pathlib import Path
import shlex
import sys
import uuid

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
TRUST_DIR = PROJECT / 'scripts/trust_update'
for _p in (str(HERE), str(TRUST_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import host_usb
import ssh_builder
from ssh_operations import JoinedSSHOperation
import usb_session

LOCK_PATH = Path('/private/tmp/local.a7r5.trust_update.lock')


def progress(message):
    print(f'[ssh-start] {message}', flush=True)


@contextmanager
def process_lock():
    fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o666)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PermissionError('已有相机 USB 任务正在运行，请等待结束后重试') from None
        yield
    finally:
        try:
            fcntl.flock(fd, fcntl.LOCK_UN)
        finally:
            os.close(fd)


def _target_owner():
    uid = os.environ.get('SUDO_UID')
    gid = os.environ.get('SUDO_GID')
    if uid is not None and gid is not None:
        return int(uid), int(gid)
    info = PROJECT.stat()
    return info.st_uid, info.st_gid


def _chown_tree(root):
    if os.geteuid() != 0:
        return
    uid, gid = _target_owner()
    for path in [root, *root.rglob('*')]:
        if not path.is_symlink():
            os.chown(path, uid, gid, follow_symlinks=False)


def _create_run_dir(run_id):
    base = PROJECT / '.local'
    base.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    out_dir = base / f'ssh-start-{stamp}-{run_id[:8]}'
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    return out_dir


def format_login_command(run_id, public_key_line, known_hosts_path, ip=None):
    """写入本次专用 known_hosts 并生成免确认 ssh 登录命令。"""
    alias = f'a7r5-libjit-{run_id}'
    parts = public_key_line.strip().split()
    if len(parts) < 2:
        raise ValueError('主机公钥格式无效')
    known_hosts_path = Path(known_hosts_path)
    known_hosts_path.write_text(f'{alias} {parts[0]} {parts[1]}\n')
    known_hosts_path.chmod(0o600)
    return shlex.join(
        [
            '/usr/bin/ssh',
            '-F',
            '/dev/null',
            '-o',
            f'HostKeyAlias={alias}',
            '-o',
            f'UserKnownHostsFile={known_hosts_path}',
            '-o',
            'GlobalKnownHostsFile=/dev/null',
            '-o',
            'StrictHostKeyChecking=yes',
            '-o',
            'IdentityAgent=none',
            '-o',
            'PubkeyAuthentication=no',
            '-o',
            'PreferredAuthentications=password',
            '-o',
            'NumberOfPasswordPrompts=1',
            '-o',
            'ConnectionAttempts=1',
            '-o',
            'ConnectTimeout=10',
            '-p',
            '2222',
            'root@' + (ip or 'CAMERA_IPV4'),
        ]
    )


def obtain_password_hash(password=None, password_hash=None, *, prompt_fn=getpass.getpass):
    """获取口令并立即转换为不可逆 SHA-512 crypt 哈希，不保留明文。"""
    if password_hash is not None:
        if not ssh_builder.HASH_PATTERN.fullmatch(password_hash):
            raise ValueError('提供的密码哈希格式不符')
        return password_hash
    if password is None:
        password = prompt_fn('请设置本次相机 SSH 登录密码 (8~128位): ')
    return ssh_builder.make_password_hash(password)


def run_ssh_start(
    engine,
    password_hash,
    *,
    ttl_seconds=0,
    ip=None,
    timeout_seconds=120,
    host_mod=host_usb,
    builder_mod=ssh_builder,
    session_fn=usb_session.run_session,
    out_dir=None,
    run_id=None,
):
    """执行闭环：模式检测与 0336 预恢复 → 编译打包 → 单会话加载/启动/验证 → STOP 恢复 0e0a。"""
    run_id = run_id or uuid.uuid4().hex
    out_dir = Path(out_dir) if out_dir is not None else _create_run_dir(run_id)
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    result = {
        'action': 'ssh_start',
        'engine': engine,
        'run_id': run_id,
        'ttl_seconds': ttl_seconds,
        'port': 2222,
        'logs': str(out_dir),
        'succeeded': False,
        'ordinary_usb_restored': False,
    }

    try:
        progress(f'开始一键启动 SSH (引擎={engine}, 会话={run_id[:8]}, ttl={ttl_seconds}s)')
        baseline, pre_recovery = host_mod.ensure_ordinary_mode(out_dir=out_dir, log_fn=progress)
        result['baseline'] = baseline
        result['pre_recovery'] = pre_recovery
        progress(
            f'已确认普通 MSC 端口：location=0x{baseline["location_id"]:08x}, '
            f'bus={baseline["bus"]}, ports={baseline["ports"]}'
        )

        progress('正在交叉编译本次 SSH 载荷并生成运行包...')
        pkg_dir = out_dir / 'package'
        builder_mod.build_ssh_package(pkg_dir, engine, run_id, password_hash, baseline, ttl_seconds=ttl_seconds)
        operation = JoinedSSHOperation(pkg_dir)

        progress('正在通过服务通道上传、拉起 sshd 并核对监听/心跳（请勿断电或拔插 USB）...')
        session_report = session_fn(out_dir / 'session', operation, timeout_seconds=timeout_seconds)
        result['session_report'] = session_report

        stop_ok = session_report.get('service_stop_result') == 'returned' or (
            session_report.get('service_stop_result') == 'stalled'
            and session_report.get('service_stop_backend_error_code') == -9
        )
        op_ok = (
            not session_report.get('failure')
            and session_report.get('protocol_gate_passed') is True
            and session_report.get('service_ready') is True
            and session_report.get('preload_unchanged') is True
            and session_report.get('trigger_attempts') == 1
            and session_report.get('service_stop_attempts') == 1
            and stop_ok
        )
        if not op_ok:
            raise RuntimeError(session_report.get('failure') or 'SSH 启动、监听校验或退出服务条件未全部通过')

        progress('sshd 已就绪且 STOP 已发送，正在确认相机恢复普通 MSC 模式...')
        proof = host_mod.observe_ordinary(
            baseline['location_id'],
            take=lambda label, timeout=5: host_mod.snapshot(out_dir, label, timeout=timeout, location=None),
            baseline=baseline,
            seconds=45,
            interval=1.5,
        )
        result['host_recovery'] = proof
        result['ordinary_usb_restored'] = bool(proof.get('recovered'))
        if not result['ordinary_usb_restored']:
            raise RuntimeError('SSH 已拉起，但 45 秒内未确认普通 MSC 稳定恢复')

        public_key_line = session_report.get('host_public_key') or (out_dir / 'host-public-key').read_text().strip()
        login_cmd = format_login_command(run_id, public_key_line, out_dir / 'known_hosts', ip=ip)
        result.update(
            succeeded=True,
            host_public_key=public_key_line,
            known_hosts=str(out_dir / 'known_hosts'),
            login_command=login_cmd,
        )
        progress('SSH 一键启动闭环完成！')
    except (Exception, KeyboardInterrupt) as exc:
        result['failure'] = f'{type(exc).__name__}: {exc}'
        progress(f'已停止：{result["failure"]}')
    finally:
        (out_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        _chown_tree(out_dir)

    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--engine', choices=('libjit', 'kit'), default='libjit', help='选择触发方式：libjit 或 kit')
    parser.add_argument('--password', help='直接指定本次 SSH 登录密码（8~128位）；不传则隐藏交互输入')
    parser.add_argument('--ttl', type=int, default=0, help='SSH 服务有效时长（秒，0 表示不限时直至关机，默认 0）')
    parser.add_argument('--ip', type=lambda s: str(ipaddress.IPv4Address(s)), help='相机网络 IPv4，仅用于直接生成完整 ssh 命令')
    parser.add_argument('--check-only', action='store_true', help='仅检测当前 USB 端口与连接模式，不提权')
    parser.add_argument('--timeout', type=int, default=120, help='USB 会话超时上限（秒，默认 120）')
    parser.add_argument('--hash-file', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if sys.platform != 'darwin':
        parser.error('当前脚本仅支持 macOS')
    if args.ttl < 0 or args.ttl > 86400:
        parser.error('--ttl 范围应为 0~86400 秒')
    if args.timeout < 30 or args.timeout > 600:
        parser.error('--timeout 范围应为 30~600 秒')

    if args.check_only:
        status = host_usb.snapshot()
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0 if status.get('present') else 1

    if args.hash_file is not None:
        pwd_hash = args.hash_file.read_text().strip()
        try:
            args.hash_file.unlink(missing_ok=True)
        except OSError:
            pass
    else:
        pwd_hash = obtain_password_hash(password=args.password)

    if os.geteuid() != 0:
        run_id = uuid.uuid4().hex
        out_dir = _create_run_dir(run_id)
        hash_file = out_dir / '.pwd.hash'
        fd = os.open(hash_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(pwd_hash + '\n')
        progress('即将申请本机管理员权限 (sudo) 以接管相机 USB 接口，请在下方输入电脑密码：')
        forward = [
            'sudo',
            str(Path(sys.executable).resolve()),
            '-B',
            str(Path(__file__).resolve()),
            '--engine',
            args.engine,
            '--ttl',
            str(args.ttl),
            '--timeout',
            str(args.timeout),
            '--hash-file',
            str(hash_file),
        ]
        if args.ip:
            forward += ['--ip', args.ip]
        os.execv('/usr/bin/sudo', forward)

    with process_lock():
        result = run_ssh_start(
            args.engine,
            pwd_hash,
            ttl_seconds=args.ttl,
            ip=args.ip,
            timeout_seconds=args.timeout,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if result.get('succeeded'):
        print('\n可直接使用的 SSH 登录命令（将 CAMERA_IPV4 替换为相机实际 IP，或使用 --ip 参数）：')
        print(result['login_command'])
        return 0
    return 3


if __name__ == '__main__':
    raise SystemExit(main())
