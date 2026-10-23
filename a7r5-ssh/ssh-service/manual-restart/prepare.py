"""封装手动启动包；不枚举USB，不联网，不生成执行批准。"""
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import uuid

SOURCE = Path(__file__).resolve().parent
SERVICE = SOURCE.parent
WORK = next(p for p in SOURCE.parents if (p/'a7r5-qemu/runtime/manifest.json').is_file())
OLD = SERVICE/'ram-key-fix/packages/ram-key-install-20261021-01'
AUTO = SERVICE/'autostart/packages/autostart-20261021-02'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    output = SOURCE/'packages/restart-20261021-01'
    if output.exists():
        raise FileExistsError('不覆盖旧包')
    # 校验引用的关键启动器，不读取或复制私钥。
    auto = json.loads((AUTO/'operation.json').read_text())
    if sha(AUTO/'materials/ssh-service.arm64') != auto['payloads']['ssh-service.arm64']['sha256']:
        raise ValueError('启动器变化')
    output.mkdir(parents=True,mode=0o700)
    run = uuid.uuid4().hex
    config = json.loads((OLD/'config.json').read_text())
    config.update(run_id=run,service_run=auto['service_run'],auto_dir=auto['auto_dir'],auto_id=auto['auto_id'],
                  helper_sha256=auto['payloads']['ssh-service.arm64']['sha256'],public_sha256=auto['public_sha256'],
                  hook_sha256=auto['payloads']['boot.so']['sha256'])
    (output/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    provenance = {}
    def copy(src,dst):
        if src.is_symlink():
            raise ValueError('拒绝链接源文件')
        dst.parent.mkdir(parents=True,exist_ok=True)
        dst.write_bytes(src.read_bytes())
        provenance[str(src)] = sha(src)
    for name in ('runner.py','restart_operation.py','prepare.py','seal.py','实施与停止方案.md'):
        copy(SOURCE/name,output/name)
    copy(AUTO/'materials/ssh-service.arm64',output/'reference/helper.arm64')
    copy(AUTO/'materials/boot.so',output/'reference/boot.so')
    copy(AUTO/'materials/trusted-host-public-key',output/'reference/host-public-key')
    copy(OLD/'proof/device/session/version.bin',output/'reference/version.bin')
    for name in ('interface_guard.py','transport.py','host_state.py','policy.py','credentials.py','native_validation.py'):
        copy(OLD/name,output/name)
    for src in (OLD/'vendor').rglob('*'):
        if src.is_file() and '__pycache__' not in src.parts and src.suffix != '.pyc':
            copy(src,output/src.relative_to(OLD))
    for src in (SOURCE/'tests').glob('*.py'):
        copy(src,output/'tests'/src.name)
    raw = (OLD/'materials/sources/root_once.c').read_text()
    # 在精确触发后恢复现有自启指针；不能沿用历史中和为512换行的执行器。
    changes = [
        ('char raw[1024], blank[512];','char raw[1024];\n    const char blank[] = RESTORE_BYTES;'),
        ("    memset(blank, '\\n', sizeof(blank));\n",''),
        ('allwrite(fd, blank, sizeof(blank))','allwrite(fd, blank, sizeof(blank)-1)'),
        ('n != 512 || memcmp(raw, blank, 512)','n != (int)sizeof(blank)-1 || memcmp(raw, blank, sizeof(blank)-1)')]
    for before,after in changes:
        if raw.count(before) != 1:
            raise ValueError('原执行器结构变化')
        raw = raw.replace(before,after)
    materials = output/'materials'
    materials.mkdir()
    (materials/'root_once.c').write_text(raw)
    prefix = '/tmp/jiritsu/a7r5-'+run
    auto_dir = auto['auto_dir']
    baseline = auto_dir+'/boot.so\n'
    ram = auto['ram_root']
    task = ('set -eu\nPATH=/bin:/usr/bin:/usr/sbin\nexport PATH\n'
            'hash() { [ -f "$1" ] && [ ! -L "$1" ] || return 1; value=$(/usr/bin/openssl dgst -sha256 "$1") || return 1; printf "%s" "${value##* }"; }\n')
    checks = {
        '/etc/ld.so.preload':hashlib.sha256(baseline.encode()).hexdigest(),
        auto_dir+'/enabled':hashlib.sha256((auto['auto_id']+'\n').encode()).hexdigest(),
        auto_dir+'/ssh-service.arm64':config['helper_sha256'],
        '/etc/passwd':'4a691edcd492167bb3d538e4e15c24dd5fbc45785afcf2beddb3fbd39e097398',
        '/usr/sbin/sshd':'a6b871ef0da3990ea0d25d7996ee79c3bfc29385d4eb1670892814c0e1472534',
        '/version.txt':config['version_sha256']}
    for path,expected in checks.items():
        task += '[ "$(hash '+shlex.quote(path)+')" = '+shlex.quote(expected)+' ]\n'
    task += '[ ! -e /etc/shadow ] && [ ! -L /etc/shadow ]\n'
    task += '[ ! -e '+shlex.quote(ram)+' ] && [ ! -L '+shlex.quote(ram)+' ]\n'
    task += shlex.quote(auto_dir+'/ssh-service.arm64')+' --launch\nprintf "%s\\n" A7R5_MANUAL_RESTART_OK\n'
    (materials/'task.sh').write_text(task)
    constants = dict(RUN_ID=run,STATE_PATH=prefix+'.state',OUTPUT_PATH=prefix+'.output',ARM_BYTES=prefix+'.so\n',
                     PRELOAD_PATH='/etc/ld.so.preload',GATE_PATH='/proc/self/cmdline',TASK_SCRIPT=task,RESTORE_BYTES=baseline)
    header = ''.join('#define '+key+' '+json.dumps(value)+'\n' for key,value in constants.items())
    (materials/'root_config.h').write_text(header+'#define TASK_SECONDS 45U\n#define OUTPUT_LIMIT 32768U\n')
    libc = WORK/'a7r5-ssh/vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.25.so'
    if sha(libc) != 'f9104526eb7e5d2ea533c1a209bb0b83e69367f569e4c966895c8e106e6382c9':
        raise ValueError('libc摘要不符')
    command = ['/opt/homebrew/opt/llvm/bin/clang','--target=aarch64-linux-gnu','--ld-path=/opt/homebrew/opt/lld/bin/ld.lld',
               '-nostdlib','-ffreestanding','-fno-builtin','-fno-stack-protector','-O2','-Wall','-Wextra','-Werror',
               '-fPIC','-shared','-fvisibility=hidden','-Wl,--no-undefined','-Wl,-z,max-page-size=65536',
               '-I',str(materials),str(materials/'root_once.c'),str(libc),'-o',str(materials/'root.arm64.so')]
    subprocess.run(command,check=True,capture_output=True,timeout=60)
    verification = output/'verification'; verification.mkdir()
    (verification/'build.json').write_text(json.dumps(dict(command=command,bytes=(materials/'root.arm64.so').stat().st_size,
        sha256=sha(materials/'root.arm64.so'),camera_io=False),indent=2)+'\n')
    (output/'source-provenance.json').write_text(json.dumps(provenance,indent=2)+'\n')
    entry = output/'run-restart-once.command'
    invoke = shlex.quote(str(WORK/'a7r5-qemu/.venv/bin/python'))+' -B '+shlex.quote(str(output/'runner.py'))
    entry.write_text('#!/bin/bash\nset -euo pipefail\n'+invoke+' check-approval\nsudo -- '+invoke+' execute --device-io\n')
    entry.chmod(0o700)
    subprocess.run(['/bin/bash','-n',str(entry)],check=True)
    print(json.dumps(dict(package=str(output),run_id=run,device_io=False,approval_created=False),ensure_ascii=False))


if __name__ == '__main__':
    main()
