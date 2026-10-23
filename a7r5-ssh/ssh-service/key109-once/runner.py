"""固定元数据单次探针；默认离线核对，实机须独立批准。"""
from collections import Counter
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

import policy
from operation import Operation
import host_state

HERE = Path(__file__).resolve().parent


def save(path, value):
    with path.open('w', encoding='utf-8') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())


def regular(path):
    if any(item.is_symlink() for item in (path, *path.parents)) or not path.is_file():
        raise ValueError('拒绝链接或非普通材料：' + str(path))
    return path


def metadata():
    return dict(schema='a7r5-key109-metadata-once-v1', target_session=policy.TARGET, risk=policy.RISK,
                max_debug_attempts=1, fixed_uploads=2, preload_writes=1, authentication_start=True,
                ssh_started=False, key_content_read=False, account_writes=0, sd_operations=0,
                max_stop_attempts=1, max_state_observations=16, session_seconds=100,
                host_observation_seconds=45, automatic_retry=False, automatic_power_cycle=False)


def check(approved=False):
    value = json.loads(regular(HERE / 'operation.json').read_text())
    if value['policy'] != metadata() or value['directory'] != str(HERE):
        raise ValueError('本次目录、会话或策略变化')
    for name, expected in value['files'].items():
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('清单路径越界')
        raw = regular(HERE / relative).read_bytes()
        if dict(bytes=len(raw), sha256=policy.digest(raw)) != expected:
            raise ValueError('材料摘要不符：' + name)
    for name, expected in value['dependencies'].items():
        if policy.digest(regular(Path(name)).read_bytes()) != expected:
            raise ValueError('本机依赖变化：' + name)
    if approved:
        approval = json.loads(regular(HERE / 'approval.json').read_text())
        expected = dict(accepted=True, operation_sha256=policy.digest((HERE / 'operation.json').read_bytes()),
                        risk=policy.RISK)
        if approval != expected or approval.get('accepted') is not True:
            raise PermissionError('缺少本次独立实机批准')
        if (HERE / 'ATTEMPT_LOCK').exists() or (HERE / 'result').exists():
            raise FileExistsError('本包已经使用，不重试')
    return value


def load_engine(manifest):
    sys.path[:0] = [str(HERE / 'vendor/engine/libs'), str(HERE / 'vendor/engine/mac')]
    from system_dump import session
    session.LIBUSB = Path(manifest['libusb'])
    return session.run_session


def execute(device_io=False):
    if not device_io:
        raise PermissionError('缺少实机执行开关')
    manifest = check(True)
    if sys.platform != 'darwin' or os.geteuid() != 0:
        raise PermissionError('需本机Terminal管理员认证')
    (HERE / 'ATTEMPT_LOCK').mkdir(mode=0o700)
    output = HERE / 'result'
    output.mkdir(mode=0o700)
    result = dict(run_id=json.loads((HERE / 'config.json').read_text())['run_id'], ssh_connections=0,
                  evidence_collected=False, stop_attempts=0, host_recovery_verified=False,
                  screen_confirmation_pending=True, execution_succeeded=False)
    try:
        initial = host_state.snapshot(output, 'initial')
        save(output / 'initial.json', initial)
        baseline = manifest['host_baseline']
        if (initial['kind'] != 'ordinary'
                or Counter(tuple(row) for row in initial['media']) != Counter(tuple(row) for row in baseline['media'])
                or set(initial['drivers']) != set(baseline['drivers'])):
            raise ValueError('必须从原端口普通身份和完整媒体基线开始；不接续未知服务态')
        operation = Operation(output / 'session')
        report = load_engine(manifest)(output / 'session', 'libusb', _operation=operation)
        save(output / 'session-result.json', report)
        result.update(evidence_collected=report.get('metadata_probe_completed', False),
                      fixed_writes_attempted=report.get('fixed_writes_attempted', 0),
                      debug_attempts=report.get('debug_attempts', 0),
                      stop_attempts=report.get('service_stop_attempts', 0),
                      first_authentication_passed=report.get('first_authentication_passed', False),
                      second_authentication_passed=report.get('second_authentication_passed', False))
        if result['stop_attempts'] > 1:
            raise ValueError('STOP次数违反门槛')
        session_ok = not report.get('failure') and result['evidence_collected'] and result['stop_attempts'] == 1
        if not session_ok:
            result['failure'] = report.get('failure', '探针或退出门槛未完整通过')
        def take(label, timeout=5):
            value = host_state.snapshot(output, label, timeout)
            save(output / (label + '.json'), value)
            return value
        proof = host_state.observe(baseline, take)
        save(output / 'host-recovery.json', proof)
        result['host_recovery_verified'] = proof['recovered']
        result['execution_succeeded'] = proof['recovered'] and session_ok
        if not proof['recovered']:
            result['host_recovery_failure'] = 'USB或媒体恢复未确认，不追加操作'
            result.setdefault('failure', result['host_recovery_failure'])
    except (Exception, KeyboardInterrupt) as exc:
        result['failure'] = type(exc).__name__ + ': ' + str(exc)
    finally:
        save(output / 'result.json', result)
        owner = HERE.stat()
        for path in sorted(output.rglob('*'), reverse=True):
            os.chown(path, owner.st_uid, owner.st_gid, follow_symlinks=False)
        os.chown(output, owner.st_uid, owner.st_gid, follow_symlinks=False)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'check-approval', 'execute'))
    parser.add_argument('--device-io', action='store_true')
    args = parser.parse_args()
    if args.action == 'execute':
        value = execute(args.device_io)
        print(json.dumps(value, ensure_ascii=False, indent=2))
        return 0 if value['execution_succeeded'] else 3
    check(args.action == 'check-approval')
    print('离线材料核对通过；未枚举USB、未发送相机请求。')
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt) as exc:
        print('停止：' + type(exc).__name__ + ': ' + str(exc), file=sys.stderr)
        raise SystemExit(2)
