#!/usr/bin/env python3
"""一键更新 A7R5 更新器信任环境（支持 libjit 与 kit 双引擎、动态 USB 端口、0336 自动恢复与闭环验证）。"""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import sys
import uuid

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
PROJECT = HERE.parents[1]
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

import builder
import host_usb
from operations import KitTrustOperation, LibjitTrustOperation
import usb_session

LOCK_PATH = Path('/private/tmp/local.a7r5.trust_update.lock')


def progress(message):
    print(f'[trust-update] {message}', flush=True)


@contextmanager
def process_lock():
    """仅防止同一时刻并发脚本抢占相机，不残留持久门禁。"""
    fd = os.open(LOCK_PATH, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o666)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise PermissionError('已有 trust-update 任务正在运行，请等待其结束') from None
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
    out_dir = base / f'trust-update-{stamp}-{run_id[:8]}'
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    return out_dir


def run_check_only():
    """只读检测当前 USB 连接端口、相机模式（0e0a/0336/096f）与存储状态。"""
    status = host_usb.snapshot()
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0 if status.get('present') else 1


def run_restore_only():
    """若当前处于 0336 服务通道模式，则发送单次 STOP 并观察恢复为普通 MSC。"""
    run_id = uuid.uuid4().hex
    out_dir = _create_run_dir(run_id)
    result = {'action': 'restore_only', 'run_id': run_id, 'logs': str(out_dir), 'succeeded': False}
    try:
        with process_lock():
            baseline, recovery = host_usb.ensure_ordinary_mode(out_dir=out_dir, log_fn=progress)
        result.update(succeeded=True, baseline=baseline, pre_recovery=recovery)
    except Exception as exc:
        result['failure'] = f'{type(exc).__name__}: {exc}'
    finally:
        (out_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        _chown_tree(out_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['succeeded'] else 3


def run_update(
    engine,
    *,
    timeout_seconds=120,
    host_mod=host_usb,
    builder_mod=builder,
    session_fn=usb_session.run_session,
    out_dir=None,
    fixture_target=None,
):
    """执行完整闭环：模式识别/0336预恢复 → 载荷编译 → 0e0a→0336 双重认证 → 258扇区写入校验 → STOP恢复0e0a。"""
    run_id = uuid.uuid4().hex
    out_dir = Path(out_dir) if out_dir is not None else _create_run_dir(run_id)
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    result = {
        'action': 'update_trust',
        'engine': engine,
        'run_id': run_id,
        'logs': str(out_dir),
        'succeeded': False,
        'ordinary_usb_restored': False,
    }

    try:
        progress(f'开始执行信任环境更新 (引擎={engine}, 会话={run_id[:8]})')
        baseline, pre_recovery = host_mod.ensure_ordinary_mode(out_dir=out_dir, log_fn=progress)
        result['baseline'] = baseline
        result['pre_recovery'] = pre_recovery
        progress(
            f'已确认普通 MSC 端口：location=0x{baseline["location_id"]:08x}, '
            f'bus={baseline["bus"]}, ports={baseline["ports"]}'
        )

        progress('正在加载 258 扇区写入配方并交叉编译原生载荷...')
        materials = builder_mod.load_trust_materials()
        pkg_dir = out_dir / 'package'
        builder_mod.build_package(
            pkg_dir,
            engine,
            run_id,
            baseline,
            materials,
            fixture_target=fixture_target,
        )

        op_cls = LibjitTrustOperation if engine == 'libjit' else KitTrustOperation
        operation = op_cls(pkg_dir)

        progress('正在触发服务通道并执行写入与机内/主机双重校验（请勿断电或拔插 USB）...')
        session_report = session_fn(out_dir / 'session', operation, timeout_seconds=timeout_seconds)
        result['session_report'] = session_report

        stop_ok = session_report.get('service_stop_result') == 'returned' or (
            session_report.get('service_stop_result') == 'stalled'
            and session_report.get('service_stop_backend_error_code') == -9
        )
        expected_writes = 2 if engine == 'libjit' else 2
        op_ok = (
            not session_report.get('failure')
            and session_report.get('protocol_gate_passed') is True
            and session_report.get('native_write_complete') is True
            and session_report.get('planned_sector_readback_verified') is True
            and session_report.get('preload_unchanged') is True
            and session_report.get('trigger_attempts') == 1
            and session_report.get('fixed_writes_attempted') == expected_writes
            and session_report.get('service_stop_attempts') == 1
            and stop_ok
        )

        if not op_ok:
            raise RuntimeError(session_report.get('failure') or '机内写入、回读校验或退出服务条件未全部通过')

        progress('机内操作与 STOP 已完成，正在确认相机稳定恢复至普通 MSC 模式...')
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
            raise RuntimeError('写入与校验已完成，但 45 秒内未观察到普通 MSC 模式稳定恢复')

        result['succeeded'] = True
        progress('信任环境更新闭环完成，相机已恢复普通 MSC 模式。')
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
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-only', action='store_true', help='仅检测当前 USB 端口与连接模式，不提权、不修改设备')
    mode.add_argument('--restore-only', action='store_true', help='若当前处于 0336 服务模式，仅恢复为普通 MSC 模式')
    parser.add_argument('--timeout', type=int, default=120, help='USB 会话超时上限（秒，默认 120）')
    args = parser.parse_args(argv)

    if sys.platform != 'darwin':
        parser.error('当前脚本仅支持 macOS')
    if args.timeout < 30 or args.timeout > 600:
        parser.error('--timeout 范围应为 30~600 秒')

    if args.check_only:
        return run_check_only()

    if os.geteuid() != 0:
        progress('即将申请本机管理员权限 (sudo) 以接管相机 USB 接口，请在下方输入电脑密码：')
        # 保留 .venv 软链接路径，避免 resolve() 后绕过 pyvenv.cfg 丢失虚拟环境依赖
        os.execv('/usr/bin/sudo', ['sudo', os.path.abspath(sys.executable), '-B', str(Path(__file__).resolve()), *sys.argv[1:]])

    if args.restore_only:
        return run_restore_only()

    with process_lock():
        result = run_update(args.engine, timeout_seconds=args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['succeeded'] else 3


if __name__ == '__main__':
    raise SystemExit(main())
