"""从本机封存材料准备只读补证包，不枚举设备、不生成执行批准。"""
import argparse
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import collect
import evidence_policy as policy

SOURCE = Path(__file__).resolve().parent
SERVICE = SOURCE.parent
INSTALL = SERVICE / 'terminal-packages/no-ttl-install-20261020-03'
RECOVERY = SERVICE / 'recovery-code85/packages/code85-recovery-20261021-02'


def replace_once(raw, old, new):
    if raw.count(old) != 1:
        raise ValueError('原通信引擎结构变化，不猜测替换')
    return raw.replace(old, new)


def prepare(output):
    output = Path(output).absolute()
    if output.parent != SOURCE / 'packages' or output.exists():
        raise ValueError('只接受新的补证包，不覆盖旧包和锁')
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError('拒绝链接目录')
    original = json.loads((INSTALL / 'operation.json').read_text())
    if policy.digest((INSTALL / 'operation.json').read_bytes()) != '8e89d173eb286f5210dee2375d35b9abdea4026572f65c7268143a0b8d2426c6':
        raise ValueError('原安装绑定变化')
    final = json.loads((RECOVERY / 'result/final-acceptance.json').read_text())
    if (final['run_id'] != policy.RUN or not final['host_recovery_verified'] or not final['screen_normal']
            or final['camera_protocol_requests'] != 0 or not final['guest_evidence_not_collected']):
        raise ValueError('前次主机/屏幕证据或未回收范围变化')
    output.mkdir(mode=0o700, parents=True)
    provenance = {}
    def copy(source, target):
        raw = collect.regular(source).read_bytes()
        relative = str(source.relative_to(INSTALL)) if source.is_relative_to(INSTALL) else None
        if relative in original['files'] and policy.digest(raw) != original['files'][relative]['sha256']:
            raise ValueError('原包文件变化：' + relative)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
        provenance[str(source)] = policy.digest(raw)
    for name in ('collect.py', 'evidence_policy.py', 'read_only.py', 'host_state.py', 'prepare.py', '实施与停止方案.md'):
        copy(SOURCE / name, output / name)
    for source in (SOURCE / 'tests').glob('*.py'):
        copy(source, output / 'tests' / source.name)
    engine = INSTALL / 'runtime/vendor/engine'
    for name in ('usb', 'Cryptodome'):
        for source in (engine / 'libs' / name).rglob('*'):
            if (source.is_file() and '__pycache__' not in source.parts and 'SelfTest' not in source.parts
                    and source.suffix not in ('.pyc', '.pyi') and source.name != '.DS_Store'):
                copy(source, output / 'vendor/engine/libs' / source.relative_to(engine / 'libs'))
    for source in (engine / 'sources/workspaces/j/work/sony-pmca-re/pmca').rglob('*.py'):
        copy(source, output / 'vendor/engine' / source.relative_to(engine))
    mac = engine / 'mac/system_dump'
    for name in ('__init__.py', 'core.py', 'preflight.py', 'supplement.py', 'environment.py',
                 'images.py', 'usb_adapter.py', 'session.py'):
        copy(mac / name, output / 'vendor/engine/mac/system_dump' / name)
    session_path = output / 'vendor/engine/mac/system_dump/session.py'
    raw = session_path.read_text()
    raw = replace_once(raw, '    if transport not in ("libusb", "native-host"): raise ValueError("未知通信后端")\n',
                       '    if transport != "libusb" or _operation is None: raise PermissionError("只允许本包固定补证操作")\n')
    raw = replace_once(raw, 'Path(__file__).with_name("preflight.py"), Path(__file__).with_name("cli.py"),',
                       'Path(__file__).with_name("preflight.py"),')
    raw = replace_once(raw, '(7500 if _operation is not None else 100)', '100')
    raw = replace_once(raw, 'if _operation is not None: report["profile"] = "restricted-dump"',
                       'if _operation is not None: report["profile"] = "code85-fixed-read"')
    raw = replace_once(raw, 'reason="预加载或任务状态未确认；可能仍在写卡"',
                       'reason="本次固定证据或前后预加载未全部确认；不自动退出服务"')
    raw = replace_once(raw, '            interface = device.get_active_configuration()[(0, 0)]\n',
                       '            interface = device.get_active_configuration()[(0, 0)]\n'
                       '            if _operation is None: raise PermissionError("本包只允许固定补证操作")\n'
                       '            _operation.interface_checked(device, interface)\n')
    raw = replace_once(raw, '            count = self.device.write(self.ep_out, data, timeout=timeout())\n',
                       '            if self.phase != "auth": _operation.guard_packet(data)\n'
                       '            count = self.device.write(self.ep_out, data, timeout=timeout())\n')
    raw = replace_once(raw, '            if count != len(data): raise IOError("USB 短写；不重试请求")\n',
                       '            if count != len(data): raise IOError("USB 短写；不重试请求")\n'
                       '            return count\n')
    # 退出后只由主机IORegistry观察，不再由libusb反复枚举恢复身份。
    begin = raw.index('        if port is not None and safe_exit:\n')
    end = raw.index('        if strict:\n', begin)
    raw = raw[:begin] + '        # 退出后只由外层主机元数据观察器核对；不再libusb枚举。\n' + raw[end:]
    session_path.write_text(raw)
    collect.save(output / 'engine-policy.json', dict(
        original_sha256=policy.digest((mac / 'session.py').read_bytes()),
        bundled_sha256=policy.digest(session_path.read_bytes()),
        changes=['只允许本包固定libusb补证入口', '会话上限100秒', '接口描述符和固定只读报文门槛',
                 '返回已核对写入长度', '退出后仅主机元数据观察'],
        unchanged_authentication_algorithm=True, inherited_claim_attempts_per_phase=1))
    proof = output / 'proof'
    for name in ('result-install/worker-state.txt', 'result-install/worker-output.txt',
                 'result-install/phase-result.json', 'result-install/independent-failure-assessment.json',
                 'materials/sources/launcher.c'):
        copy(INSTALL / name, proof / 'install' / name)
    for name in ('result/final-acceptance.json', 'result/independent-host-acceptance.json',
                 'result/screen-confirmation.json'):
        copy(RECOVERY / name, proof / 'recovery-02' / name)
    copy(RECOVERY / 'reference/version.bin', output / 'reference/version.bin')
    collect.save(output / 'source-provenance.json', provenance)
    launcher = output / 'run-collect.command'
    command = shlex.quote(str(Path(sys.executable).absolute())) + ' -B ' + shlex.quote(str(output / 'collect.py'))
    launcher.write_text('#!/bin/bash\n# 本次独立批准在sudo之前核对；不重试。\nset -euo pipefail\n'
                        + command + ' check-approval\nsudo -- ' + command + ' execute --device-io\n')
    subprocess.run(['/bin/bash', '-n', str(launcher)], capture_output=True, check=True)
    python = Path(sys.executable).resolve()
    usb = Path('/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib').resolve()
    operation = dict(policy=collect.metadata(), directory=str(output), libusb=str(usb),
                     host_baseline=original['host_baseline'],
                     dependencies={str(path): policy.digest(path.read_bytes()) for path in (python, usb)}, files={})
    for path in sorted(output.rglob('*')):
        if path.is_file():
            path.chmod(0o700 if path == launcher else 0o600)
            operation['files'][str(path.relative_to(output))] = dict(bytes=path.stat().st_size, sha256=policy.digest(path.read_bytes()))
    collect.save(output / 'operation.json', operation)
    collect.save(output / 'approval-template.json', dict(accepted=False, risk=policy.RISK,
                 operation_sha256=policy.digest((output / 'operation.json').read_bytes())))
    return dict(package=str(output), run_id=policy.RUN, device_io=False, approval_created=False)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    print(json.dumps(prepare(parser.parse_args().output), ensure_ascii=False, indent=2))
