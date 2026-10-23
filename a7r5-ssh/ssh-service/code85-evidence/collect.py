"""只读回收旧SSH失败证据；默认离线检查，实机执行须独立批准。"""
from collections import Counter
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import sys

import evidence_policy as policy
import host_state
from read_only import FileResultError, HEADER, READ, ReadChannel

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
    return dict(schema='a7r5-code85-evidence-v1', run_id=policy.RUN, risk=policy.RISK,
                location_id=host_state.LOCATION, bus=0, ports=[1], initial_pid=0x0e0a,
                fixed_reads=[list(row) for row in policy.READS], max_file_requests=20,
                authentication_start=True, normal_and_service_authentication=True,
                file_writes=0, debug=0, start_ssh=False, network_connections=0,
                max_stop_attempts=1, session_seconds=100, host_observation_seconds=45,
                automatic_retry=False, automatic_power_cycle=False)


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


STAGES = {
    0: '子进程正常清理结束；父85仍需保留当时父视图检查失败的可能',
    101: '子进程父关系、死亡信号或后代接管初始化',
    102: '私有挂载命名空间创建或传播隔离',
    103: '挂载传播状态检查',
    104: '私有/var的tmpfs挂载或空间检查',
    105: '私有目录创建和权限检查',
    106: '私有账户副本生成、只读绑定或回读检查',
    107: '私有sshd配置创建',
    108: '日志创建或后续日志管道创建，须结合启动标记',
    109: '安装目录主机密钥的类型、所有者或权限检查',
    110: '原厂sshd配置自检启动或等待，须结合诊断日志',
    111: '主机公钥读取、RAM保存或命名空间差异检查',
    112: 'PRIVATE_READY通知写入',
    114: '启动前端口监听表检查，可能是占用或读取/解析失败',
    115: '原厂sshd派生失败',
    116: '原厂sshd退出或等待失败',
    117: '监听状态读取、建立或存活检查',
    120: '本机回环SSH标识验证或启动回执保存',
    124: '私有/dev/pts目录检查或devpts挂载',
}


def fixed_reads(driver, out, log):
    channel = ReadChannel(driver, log)
    result = dict(run_id=policy.RUN, reads=[], gate_passed=False, code85_exact_cause_resolved=False,
                  current_account_files_independently_read=False, current_listener_table_read=False)
    child = None
    try:
        for label, path, limit in policy.READS:
            log('fixed_read', label=label, path=path, limit=limit)
            try:
                raw = channel.read_next(label, path, limit)
            except FileResultError as exc:
                result['reads'].append(dict(label=label, path=path, result=f'0x{exc.result:08x}', absence_proven=False))
                if (label != 'diagnostic' or exc.result != 0x10000006 or child is None
                        or not policy.diagnostic_unreadable_allowed(child)):
                    raise
                result['diagnostic'] = dict(status='unreadable_early_stage', absence_proven=False)
                continue
            (out / (label + '.bin')).write_bytes(raw)
            result['reads'].append(dict(label=label, path=path, bytes=len(raw), sha256=policy.digest(raw)))
            if label == 'version' and policy.digest(raw) != policy.HASHES['/version.txt']:
                raise ValueError('版本对照不符')
            if label.startswith('preload-'):
                result[label] = dict(exact_512_newlines=raw == policy.NEUTRAL, bytes=len(raw), sha256=policy.digest(raw))
                if raw != policy.NEUTRAL:
                    raise ValueError('预加载不是精确512换行，保存后停止，不覆盖')
            if label == 'root-state' and raw != policy.STATE:
                raise ValueError('本次root状态不符')
            if label in ('root-output', 'parent-before', 'parent-after') and raw != policy.FINAL:
                raise ValueError('旧会话、父终态不符或发生变化')
            if label == 'child-result':
                child = policy.child_result(raw)
                result['child'] = child
                result['failure_stage'] = STAGES[child['code']]
                result['stage_identified'] = True
                result['exact_failing_call_not_identified'] = True
            if label == 'diagnostic':
                result['diagnostic'] = dict(status='readable' if raw else 'readable_empty',
                                            bytes=len(raw), sha256=policy.digest(raw))
            if label == 'heartbeat' and raw != b'A7R5_PRIVATE_ENDED\n':
                raise ValueError('不是已结束心跳，不STOP')
        result['gate_passed'] = True
        return result
    except Exception as exc:
        result['failure'] = type(exc).__name__ + ': ' + str(exc)
        raise
    finally:
        result['file_reads_attempted'] = channel.index
        result['protocol_responses_completed'] = channel.sequence - 1
        save(out / 'evidence-assessment.json', result)


def endpoints(interface):
    rows = [dict(address=int(ep.bEndpointAddress), attributes=int(ep.bmAttributes),
                 max_packet=int(ep.wMaxPacketSize), interval=int(ep.bInterval)) for ep in interface]
    if (interface.bInterfaceNumber, interface.bAlternateSetting) != (0, 0):
        raise ValueError('不是接口0/alt0')
    if len({row['address'] for row in rows}) != len(rows):
        raise ValueError('重复端点')
    for row in rows:
        if row['address'] & 0x70 or not row['address'] & 15 or not 0 < row['max_packet'] <= 1024:
            raise ValueError('非法端点地址或包长')
    ins = [row for row in rows if row['attributes'] & 3 == 2 and row['address'] & 128]
    outs = [row for row in rows if row['attributes'] & 3 == 2 and not row['address'] & 128]
    if not ins or not outs:
        raise ValueError('缺少双向bulk端点')
    return dict(descriptors=rows, selected_in=ins[0]['address'], selected_out=outs[0]['address'],
                rule='first_bulk_each_direction_in_descriptor_order')


class Operation:
    def __init__(self, output):
        self.output = output
        self.safe_to_stop = False
        self.interfaces_seen = 0

    def interface_checked(self, device, interface):
        if (device.bus, tuple(device.port_numbers or ()), device.idProduct) not in (
                (0, (1,), 0x0e0a), (0, (1,), 0x0336)):
            raise ValueError('接口打开前物理端口或身份改变')
        self.interfaces_seen += 1
        raw = dict(pid=device.idProduct, bus=device.bus, ports=list(device.port_numbers or ()),
                   number=int(interface.bInterfaceNumber), alternate=int(interface.bAlternateSetting),
                   interface_class=int(interface.bInterfaceClass), subclass=int(interface.bInterfaceSubClass),
                   protocol=int(interface.bInterfaceProtocol),
                   endpoints=[dict(address=int(ep.bEndpointAddress), attributes=int(ep.bmAttributes),
                                   max_packet=int(ep.wMaxPacketSize), interval=int(ep.bInterval)) for ep in interface])
        save(self.output / f'interface-{self.interfaces_seen}.json', raw)
        if self.interfaces_seen > 2:
            raise ValueError('接口打开次数超限')
        selection = endpoints(interface)
        save(self.output / f'endpoint-selection-{self.interfaces_seen}.json', selection)

    @staticmethod
    def guard_packet(data):
        if len(data) < HEADER.size + 7:
            raise PermissionError('拒绝过短或其他命令')
        size, function, sequence, *metadata_fields = HEADER.unpack_from(data)
        body = data[HEADER.size:]
        if size != len(body) or function != 0x40 or not 1 <= sequence <= 20 or any(metadata_fields):
            raise PermissionError('拒绝非固定读取报文')
        allowed = {b'\x01\x10\x0f\x00\0' +
                   (path if path.startswith('/tmp/jiritsu/') else '/tmp/jiritsu/../..' + path).encode('ascii') + b'\0'
                   for _, path, _ in policy.READS}
        if body != READ and body not in allowed:
            raise PermissionError('拒绝写入、DEBUG或非固定路径')

    def __call__(self, driver, output, log, report):
        # 固定读取完成前safe_to_stop始终为False；异常不自动退出服务。
        value = fixed_reads(driver, output, log)
        self.safe_to_stop = value['gate_passed']
        report.update(code85_evidence_collected=True, preload_neutral_verified=True,
                      old_session_child_cleanup_receipt_verified=True,
                      current_account_files_independently_read=False,
                      current_listener_table_read=False)


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
    result = dict(run_id=policy.RUN, camera_file_writes=0, debug=0, ssh_connections=0,
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
        result.update(evidence_collected=report.get('code85_evidence_collected', False),
                      stop_attempts=report.get('service_stop_attempts', 0),
                      first_authentication_passed=report.get('first_authentication_passed', False),
                      second_authentication_passed=report.get('second_authentication_passed', False))
        if result['stop_attempts'] > 1:
            raise ValueError('STOP次数违反门槛')
        if report.get('failure'):
            raise ValueError(report['failure'])
        if not result['evidence_collected'] or result['stop_attempts'] != 1:
            raise ValueError('固定读取或退出门槛未完整通过')
        def take(label, timeout=5):
            value = host_state.snapshot(output, label, timeout)
            save(output / (label + '.json'), value)
            return value
        proof = host_state.observe(baseline, take)
        save(output / 'host-recovery.json', proof)
        result['host_recovery_verified'] = proof['recovered']
        result['execution_succeeded'] = proof['recovered']
        if not proof['recovered']:
            result['failure'] = 'USB或媒体恢复未确认，不追加操作'
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
