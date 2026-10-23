"""本机离线封包；不导入或运行SSH、USB实机入口，不生成批准。"""
import hashlib
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys

SOURCE=Path(__file__).resolve().parent
SERVICE=SOURCE.parent
sys.path.insert(0,str(SERVICE))
import package
import policy

PREVIOUS=SERVICE/'key109-once/packages/key109-once-20261021-01'


def prepare(output):
    output=Path(output).absolute()
    if output.parent!=SOURCE/'packages' or output.exists() or any(p.is_symlink() for p in (output,*output.parents)):
        raise ValueError('只创建独立新包，不覆盖旧材料或锁')
    proof=json.loads((PREVIOUS/'result/final-acceptance.json').read_text())
    if (proof['run_id']!=policy.PREDECESSOR or not proof['screen_normal'] or not proof['host_recovery_verified']
            or proof['probe']['metadata']['private']['mode_octal']!='0o100755'):
        raise ValueError('实机0755补证或恢复证据不符')
    output.mkdir(parents=True,mode=0o700)
    material=package.prepare(output/'materials')
    material['predecessor_cleanup_required']=policy.PREDECESSOR
    material['predecessor_kind']='key109_completed_neutral_and_recovered'
    note=('本次以包根实施与停止方案.md为准。密钥使用私有RAM 0600副本；历史验证记录不代表本次实测，'
          '自启候选保持禁用，不创建enabled或长期预加载。\n')
    (output/'materials/实施方案.md').write_text(note)
    material['files']['实施方案.md']=dict(bytes=len(note.encode()),sha256=hashlib.sha256(note.encode()).hexdigest())
    (output/'materials/manifest.json').write_text(json.dumps(material,ensure_ascii=False,indent=2)+'\n')
    run=material['run_id']
    provenance={}
    def copy(src,dst):
        if src.is_symlink():raise ValueError('拒绝链接材料')
        raw=src.read_bytes();dst.parent.mkdir(parents=True,exist_ok=True);dst.write_bytes(raw)
        provenance[str(src)]=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    for name in ('runner.py','install_operation.py','policy.py','interface_guard.py','transport.py','prepare.py','seal.py','verify_guest.py','rebuild.py','key_copy_probe.c','实施与停止方案.md'):
        copy(SOURCE/name,output/name)
    for p in (SOURCE/'tests').glob('*.py'):copy(p,output/'tests'/p.name)
    for name in ('credentials.py','native_validation.py'):copy(SERVICE/name,output/name)
    copy(PREVIOUS/'host_state.py',output/'host_state.py')
    for p in (PREVIOUS/'vendor').rglob('*'):
        if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc':copy(p,output/p.relative_to(PREVIOUS))
    for name in ('final-acceptance.json','screen-confirmation.json','session/state-repeat.bin','session/probe-output.bin',
                 'session/version.bin','session/interface-1.json','session/interface-2.json','host-04.plist','host-05.plist','host-recovery.json'):
        copy(PREVIOUS/'result'/name,output/'proof/device'/name)
    for name in ('tests/test_private_hostkey.c','tests/reproduce_legacy.c','verification/native-contract.json'):
        copy(SOURCE/name,output/'proof/key-copy'/name)
    # 复制相对目录完整的本机测试所需头，仅为离线验证，不上传相机。
    for name in ('private_hostkey.h','private_account.h'):copy(SERVICE/name,output/'test-sources/ssh-service'/name)
    copy(SERVICE.parent/'src/ns_abi.h',output/'test-sources/src/ns_abi.h')
    copy(SOURCE/'tests/test_private_hostkey.c',output/'test-sources/ssh-service/ram-key-fix/tests/test_private_hostkey.c')
    for name in ('launcher.c','private_account.h','private_hostkey.h','boot_hook.c'):
        copy(SERVICE/name,output/'rebuild-sources/ssh-service'/name)
    for name in ('ns_abi.h','ns_sha256.h','start.S','root_once.c'):
        copy(SERVICE.parent/'src'/name,output/'rebuild-sources/src'/name)
    copy(SOURCE/'key_copy_probe.c',output/'rebuild-sources/ssh-service/ram-key-fix/key_copy_probe.c')
    config=dict(run_id=run,predecessor=policy.PREDECESSOR,version_sha256=hashlib.sha256((PREVIOUS/'result/session/version.bin').read_bytes()).hexdigest(),
                interfaces={name:json.loads((PREVIOUS/'result/session'/name).read_text()) for name in ('interface-1.json','interface-2.json')})
    (output/'config.json').write_text(json.dumps(config,indent=2)+'\n')
    command=shlex.quote(str(Path(sys.executable).absolute()))+' -B '+shlex.quote(str(output/'runner.py'))
    script=output/'run-install-once.command'
    script.write_text('#!/bin/bash\n# 先核对独立批准；管理员认证仅在本机Terminal。\nset -euo pipefail\n'+command+
                      ' check-approval\nsudo -- '+command+' execute --device-io\n')
    script.chmod(0o700);subprocess.run(['/bin/bash','-n',str(script)],check=True)
    (output/'source-provenance.json').write_text(json.dumps(provenance,ensure_ascii=False,indent=2)+'\n')
    return dict(package=str(output),run_id=run,device_io=False,ssh_started=False,approval_created=False)


if __name__=='__main__':
    print(json.dumps(prepare(Path(sys.argv[1])),ensure_ascii=False,indent=2))
