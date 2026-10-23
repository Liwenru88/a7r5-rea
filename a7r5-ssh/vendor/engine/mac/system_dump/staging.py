"""生成未批准的 Terminal 候选包；不打开 Terminal、不申请 sudo、不打开设备。"""
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile

from .bundle import load_bundle, LIBC
from .environment import ROOT
from .restricted import save_json


def stage_candidate(bundle_path, record_path):
    bundle_path = Path(bundle_path).absolute()
    value, digest = load_bundle(bundle_path)
    base = Path(tempfile.mkdtemp(prefix="a7r5-dump-candidate-", dir="/private/tmp"))
    # 只复用既有打包清单的库文件来源，不复用任何批准标记、输出或锁。
    old = json.loads((ROOT/"mac/system_dump/evidence/supplement-implementation-20261017/staging.json").read_text())
    for name, record in old["files"].items():
        if not (name.startswith("libs/") or name.startswith("sources/workspaces/j/work/sony-pmca-re/")): continue
        source=Path(record["source"])
        if hashlib.sha256(source.read_bytes()).hexdigest()!=record["sha256"]:
            raise ValueError(f"既有依赖已变化：{name}")
        target=base/name
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
    import elftools
    package = Path(elftools.__file__).parent
    for source in package.rglob('*'):
        if not source.is_file() or '__pycache__' in source.parts or source.suffix=='.pyc': continue
        target=base/'libs/elftools'/source.relative_to(package)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
    for source in [ROOT/"mac/a7r5_dump.py", *sorted((ROOT/"mac/system_dump").glob("*.py")), ROOT/"mac/system_dump/payload/a7r5_worker.c", LIBC]:
        target=base/source.relative_to(ROOT)
        target.parent.mkdir(parents=True,exist_ok=True)
        shutil.copyfile(source,target)
    shutil.copytree(bundle_path,base/"bundle")
    (base/"evidence").mkdir()
    sources={str(p.relative_to(base)):hashlib.sha256(p.read_bytes()).hexdigest() for p in base.rglob('*') if p.is_file()}
    save_json(base/"source-manifest.json",sources)
    manifest_sha=hashlib.sha256((base/"source-manifest.json").read_bytes()).hexdigest()
    bootstrap='''"""固定转存候选启动器；缺少批准时不导入设备代码。"""
import hashlib,json,sys
from pathlib import Path
base=Path(__file__).resolve().parent
if sys.argv[1:]==['--help']:
    print('A7R5 一次性固定转存候选包；须先确认真实卡、未知预加载覆盖与一次 DEBUG 风险。')
    raise SystemExit(0)
verify_only=sys.argv[1:]==['--verify-offline']
if sys.argv[1:] and not verify_only: raise SystemExit('本包不接受其他命令或输出路径')
approval=base/'approval.json'
if not verify_only and (not approval.is_file() or approval.is_symlink()):
    print('尚未收到本次实机批准，禁止启动 USB 会话。')
    raise SystemExit(3)
raw=(base/'source-manifest.json').read_bytes()
if hashlib.sha256(raw).hexdigest()!=MANIFEST_SHA: raise SystemExit('来源清单已变化')
for name,expected in json.loads(raw).items():
    path=base/name
    if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest()!=expected:
        raise SystemExit('候选包摘要变化：'+name)
sys.path[:0]=[str(base/'libs'),str(base/'mac')]
if verify_only:
    import usb.core,usb.backend.libusb1
    def forbidden(*a,**k): raise AssertionError('离线核验禁止打开 USB')
    usb.core.find=forbidden
    usb.backend.libusb1.get_backend=forbidden
    usb.backend.libusb1._LibUSB.__init__=forbidden
    from system_dump.bundle import load_bundle
    load_bundle(base/'bundle')
    print('候选材料、目标 ELF 与依赖核验通过；USB 入口已封锁。')
    raise SystemExit(0)
from system_dump.cli import main
raise SystemExit(main(['service-dump','--bundle',str(base/'bundle'),'--approval',str(approval),'--output',str(base/'evidence/run-dump')]))
'''.replace('MANIFEST_SHA',repr(manifest_sha))
    (base/"bootstrap.py").write_text(bootstrap)
    python=str(Path(sys.executable).resolve())
    bootstrap_sha=hashlib.sha256((base/"bootstrap.py").read_bytes()).hexdigest()
    launcher=f'''#!/bin/zsh
# 只生成候选启动器；本轮未批准，不打开相机或 Terminal。
set -eu
umask 077
task_stage={shlex.quote(str(base))}
task_python={shlex.quote(python)}
[[ -f "$task_stage/approval.json" && ! -L "$task_stage/approval.json" ]] || {{ print '尚未收到本次实机批准，禁止启动 USB 会话。'; exit 3; }}
[[ ! -e "$task_stage/bundle/ATTEMPT_LOCK" && ! -e "$task_stage/evidence/run-dump" ]] || {{ print '已尝试或存在输出；禁止重跑。'; exit 4; }}
task_hash=$(/usr/bin/shasum -a 256 "$task_stage/bootstrap.py")
[[ "$task_hash" = {shlex.quote(bootstrap_sha)}* ]] || {{ print '启动器摘要改变'; exit 5; }}
print '仅在本机 Terminal 中输入 sudo 密码。失败后不要重新启动。'
set +e
/usr/bin/sudo "$task_python" -B -I -S "$task_stage/bootstrap.py" > "$task_stage/evidence/terminal.log" 2>&1
task_status=$?
print -r -- "$task_status" > "$task_stage/evidence/terminal-exit-code.txt"
print "会话已返回，退出码 $task_status。请核对报告，不能仅据此拔卡或断电。"
exit "$task_status"
'''
    (base/"start-dump-terminal.command").write_text(launcher)
    (base/"start-dump-terminal.command").chmod(0o700)
    syntax=subprocess.run(["/bin/zsh","-n",str(base/"start-dump-terminal.command")],capture_output=True,text=True)
    if syntax.returncode: raise ValueError(syntax.stderr)
    probes=[]
    for command,expected_code in (([python,"-B","-I","-S",str(base/"bootstrap.py")],3),
                                  (["/bin/zsh",str(base/"start-dump-terminal.command")],3),
                                  ([python,"-B","-I","-S",str(base/"bootstrap.py"),"--verify-offline"],0)):
        result=subprocess.run(command,capture_output=True,text=True,timeout=10)
        if result.returncode!=expected_code: raise ValueError("候选包阻断或离线核验失败："+result.stderr)
        probes.append({"argv":command,"exit_code":result.returncode,"stdout":result.stdout})
    record={"stage":str(base),"bundle_sha256":digest,"files":len(sources),"bootstrap_sha256":bootstrap_sha,
            "source_manifest_sha256":manifest_sha,"unapproved_probes":probes,"approval_file_exists":False,
            "attempt_lock_exists":(base/"bundle/ATTEMPT_LOCK").exists(),"usb_enumerated":False,
            "camera_execution_authorized":False,"terminal_opened":False,"sudo_requested":False}
    save_json(Path(record_path),record)
    return record
