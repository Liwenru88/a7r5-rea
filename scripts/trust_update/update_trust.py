#!/usr/bin/env python3
"""一键自动转存 cnflasha1 并更新 A7R5 更新器信任环境。

流程（全自动，无需预先准备本机镜像）：
1. 动态识别 USB 端口；若相机滞留在 0336 服务模式则自动 STOP 预恢复；
2. 进入服务通道只读转存 /dev/cnflasha1（25,100,288 字节）到本机 `.local/trust-update-*/cnflasha1.img`，
   机内两次整分区读取摘要一致、主机下载摘要一致、本次 RAM 副本已清理后才继续；
3. 用刚取回的本机镜像现场计算写入计划，再进入服务通道写入 258 计划扇区；
4. 机内写入后的整分区摘要必须等于计划候选（即落盘分区与计划目标逐字节一致），主机 9 块计划扇区回读一致，最后 STOP 恢复普通 MSC。
"""
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
import capture as capture_flow
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


def _apply_failure_hint(result, exc):
    """转存门控失败时保留机内报告；若相机按设计停留在 0336，给出恢复指引。"""
    capture_report = getattr(exc, 'report', None) or result.get('capture_report')
    if capture_report:
        result['capture_report'] = capture_report
    if isinstance(capture_report, dict) and capture_report.get('recovery_required'):
        hint = (
            '相机仍停留在 0336 服务模式（转存失败已按设计保留现场、未自动 STOP）：'
            '请执行 update_trust.py --restore-only 或重新插拔相机后重试'
        )
        result['recovery_hint'] = hint
        progress(hint)


def _write_result(out_dir, result):
    (out_dir / 'result.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    _chown_tree(out_dir)


def _observe_restore(host_mod, baseline, out_dir, label):
    """确认同一物理端口连续两次快照回到基线普通 MSC 状态。"""
    Path(out_dir).mkdir(parents=True, exist_ok=True)
    proof = host_mod.observe_ordinary(
        baseline['location_id'],
        take=lambda tag, timeout=5: host_mod.snapshot(out_dir, tag, timeout=timeout, location=None),
        baseline=baseline,
        seconds=45,
        interval=1.5,
    )
    if not proof.get('recovered'):
        raise RuntimeError(
            f'{label} 45 秒内未观察到普通 MSC 模式稳定恢复：{proof.get("reason", "未知原因")}'
            '；若相机停留在 0336 服务模式，请执行 update_trust.py --restore-only 后重试'
        )
    return proof


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
        _write_result(out_dir, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['succeeded'] else 3


def _run_capture_stage(
    engine,
    out_dir,
    *,
    timeout_seconds,
    host_mod,
    capture_mod,
    builder_mod,
    session_fn,
    fixture_target=None,
):
    """第 1 步：自动转存 cnflasha1 并落盘本机镜像，随后确认相机回到普通 MSC。"""
    verify_toolchain = getattr(builder_mod, 'verify_toolchain', None)
    if verify_toolchain is not None:
        verify_toolchain()
    progress('第 1 步：自动转存机内 cnflasha1 镜像（只读，不改写任何分区）...')
    (out_dir / 'capture-baseline').mkdir(parents=True, exist_ok=True)
    baseline, pre_recovery = host_mod.ensure_ordinary_mode(out_dir=out_dir / 'capture-baseline', log_fn=progress)
    captured = capture_mod.run_capture(
        engine,
        baseline,
        out_dir / 'capture',
        timeout_seconds=timeout_seconds,
        builder_mod=builder_mod,
        session_fn=session_fn,
        fixture_target=fixture_target,
        log_fn=progress,
    )
    image_path = out_dir / 'cnflasha1.img'
    receipt = capture_mod.persist_image(
        Path(captured['session']),
        image_path,
        report=captured['report'],
        run_id=captured['run_id'],
        chunk_count=captured['chunk_count'],
        chunk_bytes=captured['chunk_bytes'],
        partition_bytes=captured['partition_bytes'],
    )
    progress(f'cnflasha1 已转存并复核：{image_path} sha256={receipt["sha256"]}')
    progress('正在确认相机稳定恢复普通 MSC 模式...')
    restore_proof = _observe_restore(host_mod, baseline, out_dir / 'capture-recovery', '转存后')
    return {
        'baseline': baseline,
        'pre_recovery': pre_recovery,
        'run_id': captured['run_id'],
        'session': captured['session'],
        'report': captured['report'],
        'image': image_path,
        'receipt': receipt,
        'restore': restore_proof,
    }


def run_capture_only(
    engine,
    *,
    capture_timeout_seconds=300,
    capture_mod=None,
    host_mod=host_usb,
    builder_mod=builder,
    session_fn=usb_session.run_session,
    out_dir=None,
    fixture_target=None,
):
    """只执行自动转存，不写入信任环境；输出本机镜像路径供人工复核或离线复用。"""
    run_id = uuid.uuid4().hex
    out_dir = Path(out_dir) if out_dir is not None else _create_run_dir(run_id)
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    result = {
        'action': 'capture_cnflasha1',
        'engine': engine,
        'run_id': run_id,
        'logs': str(out_dir),
        'succeeded': False,
        'ordinary_usb_restored': False,
    }
    try:
        stage = _run_capture_stage(
            engine,
            out_dir,
            timeout_seconds=capture_timeout_seconds,
            host_mod=host_mod,
            capture_mod=capture_mod or capture_flow,
            builder_mod=builder_mod,
            session_fn=session_fn,
            fixture_target=fixture_target,
        )
        try:
            inspection = builder_mod.inspect_trust_image(stage['image'])
        except (ValueError, KeyError, OSError) as exc:
            inspection = {'status': 'unparsable', 'error': f'{type(exc).__name__}: {exc}'}
        result.update(
            capture_run_id=stage['run_id'],
            capture_session=stage['session'],
            captured_image=str(stage['image']),
            capture_receipt=stage['receipt'],
            capture_report=stage['report'],
            inspection=inspection,
            ordinary_usb_restored=True,
            succeeded=True,
        )
        progress(
            'cnflasha1 转存完成，相机已恢复普通 MSC 模式；'
            f'一号分区状态判定：{inspection.get("status")}'
        )
    except (Exception, KeyboardInterrupt) as exc:
        result['failure'] = f'{type(exc).__name__}: {exc}'
        _apply_failure_hint(result, exc)
        progress(f'已停止：{result["failure"]}')
    finally:
        _write_result(out_dir, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['succeeded'] else 3


def run_update(
    engine,
    *,
    timeout_seconds=120,
    capture_timeout_seconds=300,
    preimage_path=None,
    trust_mode='replace-key',
    auto_capture=None,
    capture_mod=None,
    host_mod=host_usb,
    builder_mod=builder,
    session_fn=usb_session.run_session,
    out_dir=None,
    fixture_target=None,
):
    """默认全自动：转存 cnflasha1 → 现场计算计划 → 写入 → 双重校验 → STOP 恢复普通 MSC。"""
    run_id = uuid.uuid4().hex
    out_dir = Path(out_dir) if out_dir is not None else _create_run_dir(run_id)
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    auto_capture = (preimage_path is None) if auto_capture is None else auto_capture
    capture_mod = capture_mod or capture_flow
    result = {
        'action': 'update_trust',
        'engine': engine,
        'run_id': run_id,
        'logs': str(out_dir),
        'succeeded': False,
        'ordinary_usb_restored': False,
        'capture_mode': 'auto' if auto_capture else ('preimage' if preimage_path is not None else 'prepared'),
    }

    try:
        progress(f'开始执行信任环境更新 (引擎={engine}, 会话={run_id[:8]})')
        image_path = Path(preimage_path) if preimage_path is not None else None
        if auto_capture:
            stage = _run_capture_stage(
                engine,
                out_dir,
                timeout_seconds=capture_timeout_seconds,
                host_mod=host_mod,
                capture_mod=capture_mod,
                builder_mod=builder_mod,
                session_fn=session_fn,
                fixture_target=fixture_target,
            )
            image_path = stage['image']
            result['capture_run_id'] = stage['run_id']
            result['capture_session'] = stage['session']
            result['capture_receipt'] = stage['receipt']
            result['capture_report'] = stage['report']
            result['capture_usb_restored'] = True
        elif image_path is not None:
            result['preimage'] = str(image_path)

        progress('第 2 步：确认普通 MSC 端口并准备写入配方与原生载荷...')
        (out_dir / 'update-baseline').mkdir(parents=True, exist_ok=True)
        baseline, pre_recovery = host_mod.ensure_ordinary_mode(
            out_dir=out_dir / 'update-baseline', log_fn=progress
        )
        result['baseline'] = baseline
        result['pre_recovery'] = pre_recovery
        progress(
            f'已确认普通 MSC 端口：location=0x{baseline["location_id"]:08x}, '
            f'bus={baseline["bus"]}, ports={baseline["ports"]}'
        )

        if image_path is not None:
            try:
                inspection = builder_mod.inspect_trust_image(image_path, mode=trust_mode)
            except (ValueError, KeyError, OSError) as exc:
                raise RuntimeError(f'无法解析本机镜像的一号分区结构：{type(exc).__name__}: {exc}') from exc
            result['inspection'] = inspection
            progress(f'一号分区状态判定：{inspection["status"]} (sha256={inspection["sha256"]})')
            if inspection.get('status') == 'unknown':
                progress('一号分区状态未识别，将按实测镜像尝试生成计划；若与 4.00 固件基线不符会立即中止。')
            if inspection.get('status') == 'already_updated':
                result.update(succeeded=True, skipped='already_updated', ordinary_usb_restored=True)
                progress('机内一号分区已是目标信任态，无需写入；相机保持普通 MSC 模式。')
                return result
            receipt = result.get('capture_receipt')
            if receipt is not None and inspection.get('sha256') != receipt.get('sha256'):
                raise RuntimeError('本机镜像回执摘要与实测复核摘要不一致')

        materials = (
            builder_mod.load_trust_materials(image_path, mode=trust_mode)
            if image_path is not None
            else builder_mod.load_trust_materials()
        )
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

        stop_ok = capture_flow.stop_result_ok(session_report)
        expected_writes = 2
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
        if session_report.get('preimage_drift'):
            drift = session_report['preimage_drift']
            result.setdefault('warnings', []).append(
                '写入前机内前像与转存镜像不一致（应由其它进程在两次会话之间改动分区），'
                '但写入后整分区摘要与计划候选一致，落盘结果仍为目标信任态：'
                f'机内 {drift["device_source_sha256"]} / 计划 {drift["plan_source_sha256"]}'
            )
            progress(result['warnings'][-1])

        progress('机内操作与 STOP 已完成，正在确认相机稳定恢复至普通 MSC 模式...')
        proof = _observe_restore(host_mod, baseline, out_dir / 'host-recovery', '更新后')
        result['host_recovery'] = proof
        result['ordinary_usb_restored'] = True

        result['succeeded'] = True
        if result['capture_mode'] == 'auto':
            progress('信任环境更新闭环完成：cnflasha1 已自动转存并写入，相机已恢复普通 MSC 模式。')
        else:
            progress('信任环境更新闭环完成，相机已恢复普通 MSC 模式。')
    except (Exception, KeyboardInterrupt) as exc:
        result['failure'] = f'{type(exc).__name__}: {exc}'
        _apply_failure_hint(result, exc)
        progress(f'已停止：{result["failure"]}')
    finally:
        _write_result(out_dir, result)

    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--engine', choices=('libjit', 'kit'), default='libjit', help='选择触发方式：libjit 或 kit')
    parser.add_argument(
        '--preimage',
        type=Path,
        help='跳过自动转存，直接使用已有本机 cnflasha1 镜像离线现算写入计划（离线复核/复用场景）',
    )
    parser.add_argument('--mode', choices=('replace-key', 'skip-key'), default='replace-key', help='补丁模式（默认 replace-key）')
    parser.add_argument(
        '--no-capture',
        action='store_true',
        help='跳过自动转存，改用 a7r5-desktop/prepared/engine/ 的既有写入材料（离线开发/复核）',
    )
    parser.add_argument('--capture-timeout', type=int, default=300, help='自动转存会话超时上限（秒，默认 300）')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--check-only', action='store_true', help='仅检测当前 USB 端口与连接模式，不提权、不修改设备')
    mode.add_argument('--restore-only', action='store_true', help='若当前处于 0336 服务模式，仅恢复为普通 MSC 模式')
    mode.add_argument('--capture-only', action='store_true', help='仅自动转存 cnflasha1 到本机，不写入信任环境')
    parser.add_argument('--timeout', type=int, default=120, help='信任写入会话超时上限（秒，默认 120）')
    args = parser.parse_args(argv)

    if sys.platform != 'darwin':
        parser.error('当前脚本仅支持 macOS')
    if args.timeout < 30 or args.timeout > 600:
        parser.error('--timeout 范围应为 30~600 秒')
    if args.capture_timeout < 60 or args.capture_timeout > 900:
        parser.error('--capture-timeout 范围应为 60~900 秒')
    if args.capture_only and args.preimage is not None:
        parser.error('--capture-only 与 --preimage 不能同时使用')
    if args.no_capture and (args.capture_only or args.preimage is not None):
        parser.error('--no-capture 不能与 --capture-only / --preimage 同时使用')

    if args.check_only:
        return run_check_only()

    if os.geteuid() != 0:
        progress('即将申请本机管理员权限 (sudo) 以接管相机 USB 接口，请在下方输入电脑密码：')
        # 保留 .venv 软链接路径，避免 resolve() 后绕过 pyvenv.cfg 丢失虚拟环境依赖
        os.execv('/usr/bin/sudo', ['sudo', os.path.abspath(sys.executable), '-B', str(Path(__file__).resolve()), *sys.argv[1:]])

    if args.restore_only:
        return run_restore_only()

    if args.capture_only:
        with process_lock():
            return run_capture_only(args.engine, capture_timeout_seconds=args.capture_timeout)

    with process_lock():
        result = run_update(
            args.engine,
            timeout_seconds=args.timeout,
            capture_timeout_seconds=args.capture_timeout,
            preimage_path=args.preimage,
            trust_mode=args.mode,
            auto_capture=False if args.no_capture else None,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result['succeeded'] else 3


if __name__ == '__main__':
    raise SystemExit(main())