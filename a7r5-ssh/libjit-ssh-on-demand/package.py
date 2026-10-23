"""prepare仅本机：封装三份载入材料和独立libJit启动票据。"""
import argparse
from pathlib import Path
import json
import os
import shlex
import shutil
import sys
import build


def prepare(directory,password_file,*,seconds=0,qemu_only=False):
    # 保留原8位数字文件入口；客户端直接传入内存中的口令。
    password=build.credentials.load(password_file)
    return prepare_password(directory,password,seconds=seconds,qemu_only=qemu_only)


def prepare_password(directory,password,*,seconds=0,qemu_only=False):
    password_hash=build.credentials.make_hash(password)
    del password
    directory=Path(directory).absolute()
    if any(p.is_symlink() for p in (directory,*directory.parents)):
        raise ValueError('拒绝链接封包路径')
    directory.mkdir(mode=0o700,parents=True,exist_ok=False)
    material=build.build(directory/'materials',password_hash,seconds=seconds,qemu_only=qemu_only)
    for name in ['tool.py','operation.py','policy.py','build.py','package.py','README.md','方案.md',
                 '实机执行与恢复清单.md','verify_qemu.py','verify_flow.py']:
        shutil.copyfile(build.HERE/name,directory/name)
    shutil.copytree(build.HERE/'src',directory/'src')
    shutil.copytree(build.HERE/'tests',directory/'tests',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    proof=directory/'verification';proof.mkdir()
    for name in ['release.json','离线验收记录.md']:
        candidate=build.HERE/'verification'/name
        if candidate.is_file():shutil.copyfile(candidate,proof/name)
    runtime=directory/'runtime';runtime.mkdir()
    for name in ['transport.py','host_state.py']:
        shutil.copyfile(build.PROJECT/'a7r5-exec/runtime'/name,runtime/name)
    shutil.copytree(build.PROJECT/'a7r5-exec/vendor',runtime/'vendor',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
    profile=json.loads((build.PROJECT/'a7r5-exec/runtime/profile.json').read_text())
    build.save(directory/'config.json',{k:profile[k] for k in ['interfaces','host_baseline','version_sha256','loader_sha256','loader_bytes']})
    python=str(build.PROJECT/'.venv/bin/python')
    for action in ['load-once','start-once','stop-once','collect-once']:
        text='#!/bin/zsh\nset -eu\nTASK_DIR="${0:A:h}"\n'
        text+='printf "%s\\n" '+shlex.quote('本阶段：'+action+'。仅在已确认实机范围后输入check显示的批准短语：')+'\n'
        text+='read -r task_accept\nexec sudo '+shlex.quote(python)+' -B "$TASK_DIR/tool.py" '+action+' --package "$TASK_DIR" --device-io --accept "$task_accept"\n'
        (directory/(action+'.command')).write_text(text)
    # 敏感哈希和全部材料限制为本机私有；不拷贝明文口令。
    for p in directory.rglob('*'):
        p.chmod(0o700 if p.is_dir() or p.suffix=='.command' else 0o600)
    manifest=dict(schema='a7r5-libjit-ssh-package-1',directory=str(directory),project=str(build.PROJECT),
                  coordinator=str(build.HERE),run_id=material['run_id'],ttl_seconds=seconds,qemu_only=qemu_only,
                  python_real=str(Path(sys.executable).resolve()),autostart=False,camera_execution_verified=False,
                  files={str(p.relative_to(directory)):build.sha(p) for p in sorted(directory.rglob('*')) if p.is_file()},
                  dependencies={str(p):build.sha(p) for p in [Path(sys.executable).resolve(),Path('/opt/homebrew/opt/libusb/lib/libusb-1.0.dylib').resolve()]})
    build.save(directory/'manifest.json',manifest)
    return manifest


if __name__=='__main__':
    p=argparse.ArgumentParser(description='仅本机封包，不枚举USB或建立网络连接')
    p.add_argument('directory',type=Path)
    p.add_argument('--password-file',type=Path,required=True)
    p.add_argument('--ttl',type=int,default=0)
    a=p.parse_args()
    m=prepare(a.directory,a.password_file,seconds=a.ttl)
    print(json.dumps(dict(package=m['directory'],run_id=m['run_id'],ttl_seconds=m['ttl_seconds'],offline_only=True),ensure_ascii=False))
