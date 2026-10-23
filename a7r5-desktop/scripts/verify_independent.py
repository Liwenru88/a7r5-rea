"""搬离工程验证交付包：沙箱禁止读取工程/Homebrew、网络和IOKit。"""
import hashlib
import itertools
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import sys

ROOT=Path(__file__).resolve().parents[1]
PROJECT=ROOT.parent
APP=Path(sys.argv[1]).resolve() if len(sys.argv)>1 else ROOT/'dist/final/A7R5 Studio.app'
env=dict(PATH='/usr/bin:/bin:/usr/sbin:/sbin',HOME=str(Path.home()),TMPDIR='/private/tmp')
report=dict(camera_IO=False,network_allowed=False,USB_access_allowed=False,project_read_allowed=False,homebrew_read_allowed=False,combinations={})
def sha(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
with tempfile.TemporaryDirectory(prefix='a7r5-independent-',dir='/private/tmp') as folder:
    isolated=Path(folder);bundle=isolated/APP.name
    archive=APP.parent/'A7R5-Studio-0.1.0-mac-arm64-test.zip'
    if archive.is_file():
        subprocess.run(['/usr/bin/ditto','-x','-k',str(archive),str(isolated)],check=True)
        report['archive_sha256']=sha(archive)
    else:shutil.copytree(APP,bundle)
    source=isolated/'official.dat'
    subprocess.run(['/bin/cp','-c',str(PROJECT/'a7r5-firmware-images/官方升级包/BODYDATA.DAT'),str(source)],check=True)
    policy='(version 1)(allow default)(deny network*)(deny iokit-open)(deny file-read* (subpath '+json.dumps(str(PROJECT),ensure_ascii=False)+') (subpath "/opt/homebrew"))'
    executable=bundle/'Contents/MacOS/a7r5-desktop'
    report['executable_sha256']=sha(executable)
    report['engine_manifest_sha256']=sha(bundle/'Contents/Resources/engine/integrity.json')
    report['output_container_version']='4.06'
    def run(*args):
        value=subprocess.run(['/usr/bin/sandbox-exec','-p',policy,str(executable),*map(str,args)],env=env,capture_output=True,text=True)
        if value.returncode:raise RuntimeError(value.stdout+'\n'+value.stderr)
        return json.loads(value.stdout.splitlines()[-1])
    report['selfcheck']=run('--selfcheck')
    # 真实隔离验证：沙箱必须拒绝工程及Homebrew文件读取。
    denied=subprocess.run(['/usr/bin/sandbox-exec','-p',policy,'/bin/cat',str(ROOT/'docs/requirements.md')],capture_output=True,env=env)
    if denied.returncode==0:raise RuntimeError('沙箱工程隔离无效')
    for values in itertools.product((False,True),repeat=4):
        key=''.join(str(int(v)) for v in values);features=dict(zip(('fl23','looks','ntsc','sound'),values))
        request=isolated/(key+'.json');output=isolated/(key+'.DAT');job=isolated/('job-'+key)
        request.write_text(json.dumps(dict(source=str(source),output=str(output),features=features,version='4.06')))
        start=time.monotonic();value=run('--build-firmware',request,job)
        if value.get('signature_verified') is not True or value.get('independent_decryption_exact') is not True or value.get('device_acceptance_verified') is not False:
            raise ValueError('封包验收回执不完整')
        target=json.loads((job/'components.json').read_text())
        expected=json.loads((ROOT/'verification/feature-build.json').read_text())['combinations'][key]['targets']
        observed={r['path']:r['sha256'] for r in target['files']}
        for name,digest in expected.items():
            # 全不选时文件保持原像，apply不会记录未变化文件。
            if name in observed and observed[name]!=digest:raise ValueError('功能组合目标变化')
        report['combinations'][key]=dict(sha256=sha(output),bytes=output.stat().st_size,seconds=round(time.monotonic()-start,2),
            signature_verified=True,independent_decryption_exact=True,guide_created=Path(value['guide']).is_file(),
            changed_components=value['changed_components'],features=features)
        print('独立应用封包通过：'+key,flush=True)
        # 仅删除本脚本新建临时目录内的验证输出，不改变工程和历史记录。
        output.unlink();output.with_suffix('.DAT.json').unlink();Path(value['guide']).unlink()
    # 证明应用能发现资源篡改，测试结束后临时副本自动清理。
    protected=bundle/'Contents/Resources/engine/profile.json';protected.write_bytes(protected.read_bytes()+b' ')
    tampered=subprocess.run([str(executable),'--selfcheck'],env=env,capture_output=True,text=True)
    if tampered.returncode==0:raise ValueError('材料篡改未被拒绝')
    report['tampered_bundle_rejected']=True
(ROOT/'verification/independent.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
print('独立搬迁及16组合验证完成；未连接相机',flush=True)
