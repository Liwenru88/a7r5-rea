#!/usr/bin/env python3
"""使用 kit 方式一键扫描或按白名单安全清理相机 /tmp/jiritsu 历史研究残留，自动恢复普通 MSC 模式。"""
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
TRUST_DIR = PROJECT / 'scripts/trust_update'
for _p in (str(HERE), str(TRUST_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import clean_builder
from clean_operation import CleanJiritsuOperation
import host_usb
import usb_session

LOCK_PATH = Path('/private/tmp/local.a7r5.trust_update.lock')


def progress(message):
    print(f'[clean-jiritsu] {message}', flush=True)


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
    out_dir = base / f'clean-jiritsu-{stamp}-{run_id[:8]}'
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
    return out_dir


def run_clean(
    *,
    apply=True,
    extra_names=(),
    timeout_seconds=120,
    host_mod=host_usb,
    builder_mod=clean_builder,
    session_fn=usb_session.run_session,
    out_dir=None,
):
    """执行一次闭环：0336 预恢复 → 编译 kit 清理载荷 → /tmp_wbshd 执行 → STOP → 确认普通 MSC。"""
    extra = builder_mod.validate_extra_names(extra_names)
    run_id = uuid.uuid4().hex
    out_dir = Path(out_dir) if out_dir is not None else _create_run_dir(run_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    mode_label = 'apply' if apply else 'scan'
    result = {
        'action': 'clean_jiritsu',
        'mode': mode_label,
        'extra_names': extra,
        'run_id': run_id,
        'logs': str(out_dir),
        'succeeded': False,
        'ordinary_usb_restored': False,
    }

    try:
        progress(f'开始执行 /tmp/jiritsu kit {"白名单清理" if apply else "只读扫描"} (会话={run_id[:8]})')
        baseline, pre_recovery = host_mod.ensure_ordinary_mode(out_dir=out_dir, log_fn=progress)
        result['baseline'] = baseline
        result['pre_recovery'] = pre_recovery
        progress(
            f'已确认普通 MSC 端口：location=0x{baseline["location_id"]:08x}, '
            f'bus={baseline["bus"]}, ports={baseline["ports"]}'
        )

        progress('正在交叉编译 kit 清理载荷（零写入 /tmp/jiritsu）...')
        pkg_dir = out_dir / 'package'
        builder_mod.build_clean_package(
            pkg_dir,
            run_id,
            baseline,
            apply=apply,
            extra_names=extra,
        )
        operation = CleanJiritsuOperation(pkg_dir)

        progress('正在通过服务通道上传至 /tmp_wbshd 并执行扫描/清理（请勿断电或拔插 USB）...')
        session_report = session_fn(out_dir / 'session', operation, timeout_seconds=timeout_seconds)
        result['session_report'] = session_report

        stop_ok = session_report.get('service_stop_result') == 'returned' or (
            session_report.get('service_stop_result') == 'stalled'
            and session_report.get('service_stop_backend_error_code') == -9
        )
        op_ok = (
            not session_report.get('failure')
            and session_report.get('protocol_gate_passed') is True
            and session_report.get('preload_unchanged') is True
            and session_report.get('trigger_attempts') == 1
            and session_report.get('service_stop_attempts') == 1
            and stop_ok
        )
        if not op_ok:
            raise RuntimeError(session_report.get('failure') or '机内清理校验或退出服务条件未全部通过')

        progress('机内任务与 STOP 已完成，正在确认相机稳定恢复至普通 MSC 模式...')
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
            raise RuntimeError('机内清理已完成，但 45 秒内未观察到普通 MSC 模式稳定恢复')

        entries_path = out_dir / 'entries.json'
        entries = json.loads(entries_path.read_text()) if entries_path.is_file() else []
        summary = session_report.get('clean_summary', {})
        result.update(
            succeeded=True,
            clean_summary=summary,
            entries_file=str(entries_path),
            deleted_names=[e['name'] for e in entries if e['action'] == 'deleted'],
            kept_names=[e['name'] for e in entries if e['action'] == 'keep'],
            would_delete_names=[e['name'] for e in entries if e['action'] == 'would_delete'],
        )
        progress('完成并已恢复普通 MSC 模式。')
    except (Exception, KeyboardInterrupt) as exc:
        result['failure'] = f'{type(exc).__name__}: {exc}'
        progress(f'已停止：{result["failure"]}')
    finally:
        (out_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
        _chown_tree(out_dir)

    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--scan-only', action='store_true', help='仅只读枚举 /tmp/jiritsu 内容与槽位，不删除任何文件')
    parser.add_argument(
        '--extra-name',
        action='append',
        default=[],
        help='额外指定要同步删除的单级普通文件名（可重复传入）',
    )
    parser.add_argument('--check-only', action='store_true', help='仅检测当前 USB 端口与连接模式，不提权')
    parser.add_argument('--timeout', type=int, default=120, help='USB 会话超时上限（秒，默认 120）')
    args = parser.parse_args(argv)

    if sys.platform != 'darwin':
        parser.error('当前脚本仅支持 macOS')
    if args.timeout < 30 or args.timeout > 600:
        parser.error('--timeout 范围应为 30~600 秒')
    try:
        clean_builder.validate_extra_names(args.extra_name)
    except ValueError as exc:
        parser.error(str(exc))

    if args.check_only:
        status = host_usb.snapshot()
        print(json.dumps(status, ensure_ascii=False, indent=2))
        return 0 if status.get('present') else 1

    if os.geteuid() != 0:
        progress('即将申请本机管理员权限 (sudo) 以接管相机 USB 接口，请在下方输入电脑密码：')
        # 保留 .venv 软链接路径，避免 resolve() 后绕过 pyvenv.cfg 丢失虚拟环境依赖
        os.execv('/usr/bin/sudo', ['sudo', os.path.abspath(sys.executable), '-B', str(Path(__file__).resolve()), *sys.argv[1:]])

    with process_lock():
        result = run_clean(
            apply=not args.scan_only,
            extra_names=args.extra_name,
            timeout_seconds=args.timeout,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['succeeded'] else 3


if __name__ == '__main__':
    raise SystemExit(main())
