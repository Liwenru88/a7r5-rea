"""仅本机封包，不导入USB后端、不生成实机批准、不改旧材料。"""
import argparse
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import policy
import recover

SOURCE = Path(__file__).resolve().parent
SERVICE = SOURCE.parent
LAB = SERVICE.parent
INSTALL = SERVICE / 'terminal-packages/no-ttl-install-20261020-03'


def original_passwd():
    # 复用已校验的本机FAT定长读取；只读保存的固件镜像，不挂载或修改它。
    sys.path.insert(0, str(SERVICE))
    spec = importlib.util.spec_from_file_location('code85_verify_reference', SERVICE / 'verify_reference.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.original_passwd()


def prepare(output):
    output = Path(output).absolute()
    if output.parent != SOURCE / 'packages' or output.exists():
        raise ValueError('只允许新的专用恢复包目录，不覆盖旧包或锁')
    if any(path.is_symlink() for path in (output, *output.parents)):
        raise ValueError('不接受软连接输出目录')
    operation = json.loads((INSTALL / 'operation.json').read_text())
    if operation['run_id'] != policy.RUN:
        raise ValueError('原安装会话不符')
    if (INSTALL / 'result-install/worker-state.txt').read_bytes() != policy.STATE:
        raise ValueError('原root状态变化')
    if (INSTALL / 'result-install/worker-output.txt').read_bytes() != policy.FINAL:
        raise ValueError('原父失败终态变化')
    if policy.digest((INSTALL / 'operation.json').read_bytes()) != '8e89d173eb286f5210dee2375d35b9abdea4026572f65c7268143a0b8d2426c6':
        raise ValueError('原安装operation变化')
    output.mkdir(parents=True, mode=0o700)
    for name in ('recover.py', 'host_state.py', 'policy.py', 'prepare.py', '分析与恢复方案.md'):
        shutil.copyfile(SOURCE / name, output / name)
    shutil.copytree(SOURCE / 'tests', output / 'tests', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    shutil.copytree(INSTALL / 'runtime/vendor/engine/libs/usb', output / 'vendor/usb',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    proof = output / 'proof'
    proof.mkdir()
    provenance = {}
    evidence = ['operation.json', 'result-install/worker-state.txt', 'result-install/worker-output.txt',
                'result-install/phase-result.json', 'result-install/events.jsonl',
                'result-install/post-failure-host-observation.json',
                'result-install/independent-failure-assessment.json', 'screen-install-confirmation.json',
                'materials/sources/launcher.c', 'runtime/host.py',
                'runtime/vendor/engine/mac/system_dump/restricted.py']
    for name in evidence:
        source = INSTALL / name
        target = proof / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        provenance[str(source)] = policy.digest(source.read_bytes())
    recover.save(output / 'source-evidence.json', provenance)
    ref = output / 'reference'
    ref.mkdir()
    (ref / 'passwd.bin').write_bytes(original_passwd())
    for source, name in [(LAB / 'reference/version.bin', 'version.bin'),
                         (LAB / 'analysis/network-20261020-v1/original/etc/nsswitch.conf', 'nsswitch.bin'),
                         (LAB / 'analysis/network-20261020-v1/original/etc/ssh/sshd_config', 'sshd-config.bin')]:
        shutil.copyfile(source, ref / name)
    for path, name in [('/etc/passwd', 'passwd.bin'), ('/version.txt', 'version.bin'),
                       ('/etc/nsswitch.conf', 'nsswitch.bin'), ('/etc/ssh/sshd_config', 'sshd-config.bin')]:
        if policy.digest((ref / name).read_bytes()) != policy.HASHES[path]:
            raise ValueError('原件基线摘要不符：' + path)
    launcher = output / 'run-recovery.command'
    command = shlex.quote(str(Path(sys.executable).absolute())) + ' -B ' + shlex.quote(str(output / 'recover.py'))
    launcher.write_text('#!/bin/bash\n# 批准与材料检查在sudo之前；本包只用一次。\nset -euo pipefail\n'
                        + command + ' check-approval\nsudo -- ' + command + ' execute --device-io\n')
    launcher.chmod(0o700)
    subprocess.run(['/bin/bash', '-n', str(launcher)], capture_output=True, check=True)
    python = Path(sys.executable).resolve()
    libusb = Path('/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib').resolve()
    manifest = dict(policy=recover.metadata(), directory=str(output), libusb=str(libusb),
                    host_baseline=operation['host_baseline'],
                    dependencies={str(path): policy.digest(path.read_bytes()) for path in (python, libusb)},
                    files={})
    for path in sorted(output.rglob('*')):
        if path.is_file():
            path.chmod(0o700 if path == launcher else 0o600)
            data = path.read_bytes()
            manifest['files'][str(path.relative_to(output))] = dict(bytes=len(data), sha256=policy.digest(data))
    recover.save(output / 'recovery.json', manifest)
    recover.save(output / 'approval-template.json', dict(recovery_sha256=policy.digest((output / 'recovery.json').read_bytes()),
                                                        accepted=False, risk=policy.RISK))
    # 无approval.json、无尝试锁、无结果目录；封包后仍须单独确认。
    return dict(directory=str(output), manifest_sha256=policy.digest((output / 'recovery.json').read_bytes()),
                camera_execution_approved=False, run_id=policy.RUN)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    print(json.dumps(prepare(parser.parse_args().output), ensure_ascii=False, indent=2))
