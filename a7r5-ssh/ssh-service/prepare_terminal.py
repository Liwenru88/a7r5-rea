"""只复制/封存本机材料；不导入设备、枚举USB、创建批准或打开Terminal。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

import package
import service_dispatch as dispatch

ROOT=Path(__file__).resolve().parent
LAB=ROOT.parent


def sha(path):
    with Path(path).open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()


def prepare(output):
    output=Path(output).absolute()
    if output.parent!=ROOT/'terminal-packages' or any(p.is_symlink() for p in (output,*output.parents)):raise ValueError('只允许本模块新的专用Terminal目录')
    if output.exists():raise FileExistsError('不覆盖旧包或锁')
    materials=ROOT/'packages/service-native-20261020-01';m=package.check(materials)
    if m['run_id']!=dispatch.RUN or m['qemu_only'] is not False:raise ValueError('仅封装本次正式候选')
    output.parent.mkdir(exist_ok=True,mode=0o700);output.mkdir(mode=0o700)
    shutil.copytree(materials,output/'materials')
    runtime=output/'runtime';runtime.mkdir(mode=0o700)
    for source,name in ((ROOT/'service_dispatch.py','service_dispatch.py'),(ROOT/'native_validation.py','native_validation.py'),(ROOT/'credentials.py','credentials.py'),
                        (LAB/'lab.py','lab.py'),(LAB/'recovery.py','recovery.py'),(LAB/'ssh-password-fixed/host.py','host.py')):
        shutil.copyfile(source,runtime/name)
    for name in ('libs','mac'):
        shutil.copytree(LAB/'vendor/engine'/name,runtime/'vendor/engine'/name,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store'))
    (runtime/'reference').mkdir()
    shutil.copyfile(LAB/'reference/version.bin',runtime/'reference/version.bin')
    pmca=Path('vendor/engine/sources/workspaces/j/work/sony-pmca-re/pmca')
    shutil.copytree(LAB/pmca,runtime/pmca,ignore=shutil.ignore_patterns('__pycache__','*.pyc','.DS_Store'))
    adapter=runtime/'vendor/engine/mac/system_dump/usb_adapter.py';raw=adapter.read_text()
    if raw.count('range(1, 6)')!=1 or raw.count('or attempt == 5')!=1:raise ValueError('接口接管源策略不符，停止封装')
    adapter.write_text(raw.replace('range(1, 6)','range(1, 2)').replace('or attempt == 5','or attempt == 1'))
    provenance=dict(original_adapter_sha256=sha(LAB/'vendor/engine/mac/system_dump/usb_adapter.py'),
                    bundled_adapter_sha256=sha(adapter),change='接口接管循环和失败终止条件同时由5次收紧为1次；首次异常直接抛出，协议与旧原件不变')
    (output/'engine-policy-provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
    old=LAB/'ssh-password-fixed/packages/fixed-password-600s-20261020-01'
    proof=output/'proof';proof.mkdir(mode=0o700)
    accepted=json.loads((old/'result-collect/independent-final-acceptance.json').read_text())
    for name in accepted['evidence']:
        source=old/name if name=='screen-collect-confirmation.json' else old/'result-collect'/name
        shutil.copyfile(source,proof/name)
    shutil.copyfile(old/'result-collect/independent-final-acceptance.json',proof/'independent-final-acceptance.json')
    shutil.copytree(ROOT/'dispatch-tests',output/'tests',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    shutil.copyfile(ROOT/'Terminal包实施方案.md',output/'实施方案.md')
    python=Path(sys.executable).resolve();openssl=Path('/opt/homebrew/opt/openssl/bin/openssl').resolve();usb=Path('/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib').resolve()
    dependencies={str(p):sha(p) for p in (python,openssl,usb,Path('/usr/bin/ssh'),Path('/usr/bin/scp'))}
    command=output/'run-install.command'
    script=('#!/bin/bash\n# 仅本次独立批准后一次执行；本包不会生成批准。\nset -euo pipefail\n'
            +shlex.quote(str(Path(sys.executable).absolute()))+' -B '+shlex.quote(str(runtime/'service_dispatch.py'))+' check-approval --operation '+shlex.quote(str(output))+'\n'
            +'sudo -- '+shlex.quote(str(Path(sys.executable).absolute()))+' -B '+shlex.quote(str(runtime/'service_dispatch.py'))+' execute --operation '+shlex.quote(str(output))+' --device-io\n')
    command.write_text(script);command.chmod(0o700)
    subprocess.run(['/bin/bash','-n',str(command)],check=True,capture_output=True)
    baseline=json.loads((proof/'host-recovery.json').read_text())['after']
    op=dict(schema='a7r5-no-ttl-install-dispatch-v1',directory=str(output),run_id=dispatch.RUN,target_ip=dispatch.TARGET,port=2222,ttl_seconds=0,
            location_id=dispatch.LOCATION,autostart_enabled=False,persistent_account_write=False,network_connections_max=3,debug_max=1,stop_max=1,risk=dispatch.RISK,
            host_baseline=baseline,python=str(python),launcher_python=str(Path(sys.executable).absolute()),openssl=str(openssl),libusb=str(usb),
            credential_path=str(ROOT/'fixed-password-input'),dependencies=dependencies,files={})
    for file in sorted(output.rglob('*')):
        if file.is_file():
            file.chmod(0o700 if file==command else 0o600)
            op['files'][str(file.relative_to(output))]=dict(bytes=file.stat().st_size,sha256=sha(file))
    dispatch.save(output/'operation.json',op)
    dispatch.save(output/'approval-install-template.json',dispatch.approval(op))
    # 本地封存不能代替实机安装批准；故意不创建approval-install.json。
    checked=subprocess.run([str(Path(sys.executable).absolute()),'-B',str(runtime/'service_dispatch.py'),'check','--operation',str(output)],capture_output=True,text=True,timeout=30)
    if checked.returncode:raise RuntimeError('Terminal材料核对失败，保留新包与诊断；不执行实机')
    return op


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('output',type=Path);args=parser.parse_args()
    op=prepare(args.output);print(json.dumps(dict(directory=op['directory'],run_id=op['run_id'],prepared_offline=True,camera_installation_approved=False),ensure_ascii=False))
