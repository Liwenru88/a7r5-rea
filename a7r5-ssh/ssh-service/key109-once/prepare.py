"""离线生成独立包，固定新执行nonce；不创建批准或尝试锁。"""
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import uuid

import policy

SOURCE = Path(__file__).resolve().parent
SERVICE = SOURCE.parent
EVIDENCE = SERVICE / 'code85-evidence/packages/code85-evidence-20261021-02'
META = SERVICE / 'key109-offline-20261021'
LAB = SERVICE.parent


def sha(path):
    return policy.digest(path.read_bytes())


def prepare(output):
    output = output.absolute()
    if output.parent != SOURCE / 'packages' or output.exists() or any(p.is_symlink() for p in (output, *output.parents)):
        raise ValueError('只创建新的固定目录，不覆盖旧包')
    final = json.loads((EVIDENCE / 'result/final-acceptance.json').read_text())
    if (final['run_id'] != policy.TARGET or final['child_code'] != 109 or not final['screen_normal']
            or not final['host_recovery_verified'] or final['sshd_attempted']):
        raise ValueError('旧会话事实不符')
    for name, digest in final['evidence_sha256'].items():
        if sha(EVIDENCE / 'result' / name) != digest:
            raise ValueError('已验收证据变化：' + name)
    if sha(META / 'build/key109-metadata.arm64') != policy.PROBE_SHA:
        raise ValueError('探针变化')
    output.mkdir(parents=True, mode=0o700)
    provenance = {}
    def copy(src, dst):
        if src.is_symlink():
            raise ValueError('拒绝链接材料')
        dst.parent.mkdir(parents=True, exist_ok=True)
        raw = src.read_bytes()
        dst.write_bytes(raw)
        provenance[str(src)] = dict(bytes=len(raw), sha256=policy.digest(raw))
    for name in ('runner.py', 'operation.py', 'policy.py', 'transport.py', 'prepare.py', 'seal.py', '实施与停止方案.md'):
        copy(SOURCE / name, output / name)
    for src in (SOURCE / 'tests').glob('*.py'):
        copy(src, output / 'tests' / src.name)
    copy(EVIDENCE / 'host_state.py', output / 'host_state.py')
    for src in (EVIDENCE / 'vendor').rglob('*'):
        if src.is_file() and '__pycache__' not in src.parts and src.suffix != '.pyc':
            copy(src, output / src.relative_to(EVIDENCE))
    for name in ('final-acceptance.json', 'screen-confirmation.json', 'session/child-result.bin',
                 'session/root-state.bin', 'session/interface-1.json', 'session/interface-2.json',
                 'session/preload-after.bin', 'session/version.bin'):
        copy(EVIDENCE / 'result' / name, output / 'proof/device' / name)
    for name in ('verification/result.json', 'verification/native-contract.json', 'verification/legacy-red.json',
                 'src/key109_probe.c', 'src/key109_metadata.h', 'src/ns_abi.h', 'src/start.S', 'build/probe_config.h'):
        copy(META / name, output / 'proof/metadata' / name)
    copy(META / 'build/key109-metadata.arm64', output / 'materials/probe.arm64')
    copy(LAB / 'src/root_once.c', output / 'materials/root_once.c')
    run = uuid.uuid4().hex
    prefix = '/tmp/jiritsu/a7r5-' + run
    task = ("set -eu\nvalue=$(/usr/bin/openssl dgst -sha256 " + shlex.quote(prefix + '.probe') + ")\n"
            '[ "${value##* }" = "' + policy.PROBE_SHA + '" ]\n'
            '/bin/busybox chmod 700 ' + shlex.quote(prefix + '.probe') + '\n'
            'exec ' + shlex.quote(prefix + '.probe') + '\n')
    (output / 'materials/task.sh').write_text(task)
    config = dict(run_id=run, target_session=policy.TARGET, interfaces={name: json.loads(
        (EVIDENCE / 'result/session' / name).read_text()) for name in ('interface-1.json', 'interface-2.json')})
    (output / 'config.json').write_text(json.dumps(config, indent=2) + '\n')
    macros = dict(RUN_ID=run, STATE_PATH=prefix + '.state', OUTPUT_PATH=prefix + '.output',
                  ARM_BYTES=prefix + '.so\n', PRELOAD_PATH='/etc/ld.so.preload', GATE_PATH='/proc/self/cmdline', TASK_SCRIPT=task)
    header = ''.join('#define ' + key + ' ' + json.dumps(value) + '\n' for key, value in macros.items())
    header += '#define TASK_SECONDS 10\n#define OUTPUT_LIMIT 4096\n'
    (output / 'materials/root_config.h').write_text(header)
    libc = LAB / 'vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.25.so'
    if sha(libc) != 'f9104526eb7e5d2ea533c1a209bb0b83e69367f569e4c966895c8e106e6382c9':
        raise ValueError('目标libc变化')
    command = ['/opt/homebrew/opt/llvm/bin/clang', '--target=aarch64-linux-gnu',
               '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld', '-nostdlib', '-ffreestanding', '-fno-builtin',
               '-fno-stack-protector', '-O2', '-Wall', '-Wextra', '-Werror', '-fPIC', '-fvisibility=hidden',
               '-shared', '-Wl,--no-undefined', '-Wl,-z,max-page-size=65536',
               '-I', str(output / 'materials'), str(output / 'materials/root_once.c'), str(libc),
               '-o', str(output / 'materials/root.arm64.so')]
    result = subprocess.run(command, capture_output=True, text=True, timeout=60)
    (output / 'verification').mkdir()
    (output / 'verification/build.json').write_text(json.dumps(dict(command=command, exit_code=result.returncode,
         stdout=result.stdout, stderr=result.stderr, target_libc_sha256=sha(libc)), indent=2) + '\n')
    if result.returncode:
        raise RuntimeError('载荷编译失败，保留失败目录')
    python = Path(sys.executable).absolute()
    cmd = shlex.quote(str(python)) + ' -B ' + shlex.quote(str(output / 'runner.py'))
    launcher = output / 'run-key109-once.command'
    launcher.write_text('#!/bin/bash\n# 先核对独立批准，再请求本机认证；本脚本不重试。\nset -euo pipefail\n' +
                        cmd + ' check-approval\nsudo -- ' + cmd + ' execute --device-io\n')
    launcher.chmod(0o700)
    subprocess.run(['/bin/bash', '-n', str(launcher)], check=True)
    subprocess.run(['/bin/sh', '-n', str(output / 'materials/task.sh')], check=True)
    (output / 'source-provenance.json').write_text(json.dumps(provenance, ensure_ascii=False, indent=2) + '\n')
    return output


if __name__ == '__main__':
    if len(sys.argv) != 2:
        raise SystemExit('需要新的包路径')
    print(prepare(Path(sys.argv[1])))
