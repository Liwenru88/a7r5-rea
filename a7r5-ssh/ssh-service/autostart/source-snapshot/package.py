"""离线生成材料，不枚举USB、不连接网络、不生成实机批准。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys

import build
import credentials


def render(name, values):
    raw=(build.ROOT/'templates'/name).read_text()
    for key,value in values.items():raw=raw.replace('@'+key+'@',value)
    if re.search(r'@[A-Z_]+@',raw):raise ValueError('模板变量未填齐')
    subprocess.run(['/bin/sh','-n'],input=raw,text=True,capture_output=True,check=True)
    return raw


def prepare(directory, *, qemu_only=False):
    password=credentials.load(build.ROOT/'fixed-password-input')
    candidate=build.build(directory,credentials.make_hash(password),'0.0.0.0',0,qemu_only=qemu_only)
    directory=Path(directory)
    sha=lambda raw:hashlib.sha256(raw).hexdigest()
    neutral=b'\n'*512
    values=dict(INSTALL=candidate['install_directory'],RUN=candidate['run_id'],
                NEUTRAL_SHA=sha(neutral),HOOK_LINE_SHA=sha((candidate['install_directory']+'/boot-hook.so\n').encode()),
                MARKER_SHA=sha((candidate['run_id']+'\n').encode()),HELPER_SHA=candidate['binary_sha256'],HOOK_SHA=candidate['hook_sha256'],
                PASSWD_SHA=build.PASSWD_SHA)
    sys.path.insert(0,str(build.LAB))
    import lab
    import isolation
    values.update(SSHD_SHA=lab.SSHD_SHA,VERSION_SHA=lab.VERSION_SHA)
    controller=render('control.sh',values)
    (directory/'control.sh').write_text(controller)
    values['CONTROL_SHA']=sha(controller.encode())
    stage=render('stage.sh',values)
    (directory/'stage.sh').write_text(stage)
    task='set -eu\nsum=$(/usr/bin/openssl dgst -sha256 /tmp/jiritsu/a7r5-'+candidate['run_id']+'.stage.sh)\n[ "${sum##* }" = '+sha(stage.encode())+' ]\nexec /bin/sh /tmp/jiritsu/a7r5-'+candidate['run_id']+'.stage.sh\n'
    (directory/'task.sh').write_text(task)
    (directory/'root_config.h').write_text(lab.root_header(candidate['run_id'],task,60))
    root=isolation.compile_target(build.LAB/'src/root_once.c',directory/'root.arm64.so',directory,shared=True)
    (directory/'root-build.json').write_text(json.dumps(root,ensure_ascii=False,indent=2)+'\n')
    (directory/'preload-neutral.bin').write_bytes(neutral)
    (directory/'preload-arm.bin').write_text('/tmp/jiritsu/a7r5-'+candidate['run_id']+'.so\n')
    (directory/'preload-autostart-candidate.bin').write_text(candidate['install_directory']+'/boot-hook.so\n')
    (directory/'enabled-marker.bin').write_text(candidate['run_id']+'\n')
    source=directory/'sources';source.mkdir(mode=0o700)
    for filename in ('launcher.c','boot_hook.c','private_account.h','private_hostkey.h','build.py','package.py','credentials.py','mac_client.py'):
        shutil.copyfile(build.ROOT/filename,source/filename)
    for filename in ('ns_abi.h','ns_sha256.h','start.S','root_once.c'):
        shutil.copyfile(build.LAB/'src'/filename,source/filename)
    shutil.copytree(build.ROOT/'templates',source/'templates')
    shutil.copytree(build.ROOT/'tests',source/'tests')
    shutil.copyfile(build.ROOT/'verify_qemu.py',source/'verify_qemu.py')
    shutil.copyfile(build.ROOT/'mac_client.py',directory/'mac_client.py')
    shutil.copyfile(build.ROOT/'实施方案.md',directory/'实施方案.md')
    evidence=build.ROOT/'verification/latest-evidence'
    if evidence.is_dir():shutil.copytree(evidence,directory/'verification')
    prefix='/tmp/jiritsu/a7r5-'+candidate['run_id']
    manifest=dict(schema='a7r5-ssh-service-materials-v1',run_id=candidate['run_id'],qemu_only=qemu_only,
                  target_ip='10.10.10.177',port=2222,ttl_seconds=0,install_directory=candidate['install_directory'],ram_directory=candidate['ram_directory'],
                  upload_map={'ssh-service.arm64':prefix+'.service-helper','boot-hook.so':prefix+'.boot-hook.so','control.sh':prefix+'.control.sh','stage.sh':prefix+'.stage.sh','root.arm64.so':prefix+'.so'},
                  persistent_account_write=False,autostart_candidate=True,autostart_enabled=False,
                  camera_installation_approved=False,real_boot_verified=False,predecessor_cleanup_required='6193b144e80448d2af587262b31f2f17',
                  execution_state='OFFLINE_MATERIALS_ONLY',files={})
    for file in sorted(directory.rglob('*')):
        if file.is_file():
            file.chmod(0o600)
            manifest['files'][str(file.relative_to(directory))]=dict(bytes=file.stat().st_size,sha256=build.sha(file))
    (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    (directory/'manifest.json').chmod(0o600)
    return manifest


def check(directory):
    directory=Path(directory).absolute()
    if any(p.is_symlink() for p in (directory,*directory.parents)):raise ValueError('拒绝链接材料路径')
    value=json.loads((directory/'manifest.json').read_text())
    if value.get('schema')!='a7r5-ssh-service-materials-v1' or not re.fullmatch('[0-9a-f]{32}',value.get('run_id','')):raise ValueError('材料类型或会话不符')
    if value.get('camera_installation_approved') is not False or value.get('autostart_enabled') is not False or value.get('execution_state')!='OFFLINE_MATERIALS_ONLY':raise ValueError('材料不是离线未批准状态')
    if value.get('install_directory')!='/tmp/jiritsu/a7r5-ssh-service-'+value['run_id'] or value.get('ttl_seconds')!=0 or value.get('port')!=2222:raise ValueError('固定安装范围变化')
    found={str(p.relative_to(directory)) for p in directory.rglob('*') if p.is_file()}
    if found!=set(value['files'])|{'manifest.json'}:raise ValueError('材料文件集合变化')
    for name,expected in value['files'].items():
        file=directory/name
        if file.is_symlink() or file.stat().st_size!=expected['bytes'] or build.sha(file)!=expected['sha256']:raise ValueError('材料变化：'+name)
    return value


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('action',choices=['prepare','check']);parser.add_argument('directory',type=Path)
    args=parser.parse_args()
    value=prepare(args.directory) if args.action=='prepare' else check(args.directory)
    print(json.dumps(dict(run_id=value['run_id'],directory=str(args.directory),execution_state=value['execution_state']),ensure_ascii=False))
