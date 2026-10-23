"""封装修复mmcb选卡后的未批准固定转存包；只复制、校验普通文件。"""
from pathlib import Path
import json
import shlex
import shutil
import subprocess
import sys
import tempfile

from mmcb_dump_once import ROOT, load as load_bundle, save, sha


def stage_candidate(bundle_path, plan_path, record_path):
    from system_dump.bundle import LIBC
    from system_dump.usb_adapter import LIBUSB
    import elftools
    bundle_path, plan_path = Path(bundle_path), Path(plan_path)
    value, digest = load_bundle(bundle_path)
    base = Path(tempfile.mkdtemp(prefix='a7r5-mmcb-dump-candidate-', dir='/private/tmp'))
    old = json.loads((ROOT / 'mac/system_dump/evidence/supplement-implementation-20261017/staging.json').read_bytes())
    for name, item in old['files'].items():
        if not (name.startswith('libs/') or name.startswith('sources/workspaces/j/work/sony-pmca-re/')):
            continue
        source = Path(item['source'])
        if sha(source) != item['sha256']:
            raise ValueError('既有封存依赖变化：' + name)
        target = base / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    package = Path(elftools.__file__).parent
    for source in package.rglob('*'):
        if not source.is_file() or '__pycache__' in source.parts or source.suffix == '.pyc':
            continue
        target = base / 'libs/elftools' / source.relative_to(package)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    for source in [ROOT / 'mac/card_diag_once.py', ROOT / 'mac/mmcb_dump_once.py', ROOT / 'mac/a7r5_dump.py',
                   ROOT / 'mac/system_dump/payload/a7r5_worker.c', Path(__file__),
                   *sorted((ROOT / 'mac/system_dump').glob('*.py')), LIBC]:
        target = base / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    shutil.copytree(bundle_path, base / 'bundle')
    shutil.copyfile(plan_path, base / 'EXECUTION_PLAN.txt')
    (base / 'evidence').mkdir()
    python = str(Path(sys.executable).resolve())
    runtime = {p: {'resolved_path': str(Path(p).resolve()), 'sha256': sha(p)} for p in (python, str(LIBUSB))}
    save(base / 'bundle/external-runtime.json', runtime)
    sources = {str(p.relative_to(base)): sha(p) for p in base.rglob('*') if p.is_file()}
    save(base / 'source-manifest.json', sources)
    manifest_sha = sha(base / 'source-manifest.json')
    bootstrap = '''"""固定mmcb2转存启动器；无批准则不观察设备、不请求 sudo。"""
from pathlib import Path
import hashlib,json,sys
base=Path(__file__).resolve().parent
args=sys.argv[1:]
if args==['--help']:
    print('一次性mmcb2转存候选包。须另行批准固定写入、一次DEBUG和指定卡转存；不覆盖未知预加载、不格式化。')
    raise SystemExit(0)
if args not in ([],['--verify-offline'],['--check-approval']):
    raise SystemExit('本包不接受额外命令或输出路径')
verify=args==['--verify-offline']
approval=base/'approval.json'
if not verify and (not approval.is_file() or approval.is_symlink()):
    print('未批准：禁止启动实机转存。')
    raise SystemExit(3)
raw=(base/'source-manifest.json').read_bytes()
if hashlib.sha256(raw).hexdigest()!=MANIFEST_SHA: raise SystemExit('来源清单变化')
for name,digest in json.loads(raw).items():
    path=base/name
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:
        raise SystemExit('候选材料变化：'+name)
sys.path[:0]=[str(base/'libs'),str(base/'mac')]
if verify:
    import usb.core,usb.backend.libusb1
    def forbidden(*a,**k): raise AssertionError('离线核验禁止 USB')
    usb.core.find=forbidden
    usb.backend.libusb1.get_backend=forbidden
    usb.backend.libusb1._LibUSB.__init__=forbidden
from mmcb_dump_once import load as load_bundle,approve,execute
bundle,digest=load_bundle(base/'bundle')
for name,item in json.loads((base/'bundle/external-runtime.json').read_bytes()).items():
    if str(Path(name).resolve())!=item['resolved_path'] or hashlib.sha256(Path(name).read_bytes()).hexdigest()!=item['sha256']:
        raise SystemExit('外部依赖变化')
if verify:
    print('材料、ELF、固定路径和依赖通过；USB 入口已封锁。')
    raise SystemExit(0)
try: approve(json.loads(approval.read_bytes()),bundle,digest)
except (ValueError,PermissionError) as exc:
    print(str(exc));raise SystemExit(3)
if (base/'bundle/ATTEMPT_LOCK').exists() or (base/'evidence/run-mmcb-dump').exists():
    raise SystemExit('已尝试或存在输出；禁止重跑')
if args==['--check-approval']: raise SystemExit(0)
if not (base/'LAUNCH_LOCK').is_dir(): raise SystemExit('必须使用本次固定 Terminal 启动器')
result=execute(base/'bundle',approval,base/'evidence/run-mmcb-dump')
print(json.dumps(result,ensure_ascii=False,indent=2))
raise SystemExit(0 if result.get('card_unmounted_verified') and result.get('ordinary_identity_restored') and 'failure' not in result else 1)
'''.replace('MANIFEST_SHA', repr(manifest_sha))
    (base / 'bootstrap.py').write_text(bootstrap)
    bootstrap_sha = sha(base / 'bootstrap.py')
    launcher = f'''#!/bin/zsh
# 固定转存候选包；缺少本次批准时不请求 sudo。
set -eu
umask 077
task_stage={shlex.quote(str(base))}
task_python={shlex.quote(python)}
[[ -f "$task_stage/approval.json" && ! -L "$task_stage/approval.json" ]] || {{ print '未批准：禁止启动实机转存。'; exit 3; }}
task_hash=$(/usr/bin/shasum -a 256 "$task_stage/bootstrap.py")
[[ "$task_hash" = {shlex.quote(bootstrap_sha)}* ]] || {{ print '启动器摘要改变'; exit 5; }}
task_hash=$(/usr/bin/shasum -a 256 "$task_python")
[[ "$task_hash" = {shlex.quote(runtime[python]['sha256'])}* ]] || {{ print '解释器摘要改变'; exit 5; }}
"$task_python" -B -I -S "$task_stage/bootstrap.py" --check-approval
/bin/mkdir "$task_stage/LAUNCH_LOCK" || {{ print '本包已经启动过，禁止重跑'; exit 4; }}
print '只在本机 Terminal 输入 sudo 密码；异常后不要重新启动。'
set +e
/usr/bin/sudo "$task_python" -B -I -S "$task_stage/bootstrap.py" > "$task_stage/evidence/terminal.log" 2>&1
task_status=$?
print -r -- "$task_status" > "$task_stage/evidence/terminal-exit-code.txt"
print "转存已返回，退出码 $task_status。恢复状态须另行核对；不要自行断电或重跑。"
exit "$task_status"
'''
    launch = base / 'start-mmcb-dump-terminal.command'
    launch.write_text(launcher)
    launch.chmod(0o700)
    syntax = subprocess.run(['/bin/zsh', '-n', str(launch)], capture_output=True, text=True, timeout=10)
    if syntax.returncode:
        raise ValueError(syntax.stderr)
    probes = []
    for command, code in (([python, '-B', '-I', '-S', str(base / 'bootstrap.py')], 3),
                          (['/bin/zsh', str(launch)], 3),
                          ([python, '-B', '-I', '-S', str(base / 'bootstrap.py'), '--verify-offline'], 0)):
        result = subprocess.run(command, capture_output=True, text=True, timeout=20)
        probes.append({'argv': command, 'exit_code': result.returncode, 'stdout': result.stdout, 'stderr': result.stderr})
        if result.returncode != code:
            save(record_path, {'stage': str(base), 'probes': probes, 'failed': True})
            raise ValueError('封包阻断或离线核验失败，见封包记录')
    record = {'stage': str(base), 'run_id': value['run_id'], 'bundle_sha256': digest,
              'payload_sha256': value['payload']['sha256'], 'source_manifest_sha256': manifest_sha,
              'bootstrap_sha256': bootstrap_sha, 'files': len(sources), 'probes': probes,
              'approval_file_exists': False, 'launch_lock_exists': False, 'attempt_lock_exists': False,
              'usb_observed': False, 'camera_protocol_sent': False, 'terminal_opened': False, 'sudo_requested': False}
    save(record_path, record)
    return record


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--plan', type=Path, required=True)
    parser.add_argument('--record', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(stage_candidate(args.bundle, args.plan, args.record), ensure_ascii=False, indent=2))
