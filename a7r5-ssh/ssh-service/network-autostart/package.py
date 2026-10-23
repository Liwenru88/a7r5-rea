"""冻结离线材料及未批准入口；不联网、不运行SSH或设备工具。"""
from pathlib import Path
import hashlib
import json
import re
import shlex
import shutil
import subprocess
import sys
import zipfile

import credentials
import runner
from native_validation import public_key
from build import HERE,WORK,OLD,LIVE,sha


def main():
    op=json.loads((HERE/'operation.json').read_text())
    regression=json.loads((HERE/'verification/regression.json').read_text())
    text=(HERE/'verification/regression.txt').read_text()
    passed=re.search(r'(\d+) passed',text)
    guest=json.loads((HERE/'verification/guest.json').read_text())
    rebuild=json.loads((HERE/'verification/rebuild.json').read_text())
    if regression['exit_code'] or not passed or guest['status']!='passed' or rebuild['status']!='passed':raise ValueError('离线验证不完整')
    for name,digest in guest['fixture_core_sources'].items():
        if sha(HERE/'src'/name)!=digest:raise ValueError('QEMU验证后核心源码变化')
    audit={}
    for name,record in op['payloads'].items():
        p=HERE/'materials'/name
        if sha(p)!=record['sha256']:raise ValueError('载荷变化')
        details=subprocess.run(['/opt/homebrew/opt/llvm/bin/llvm-readelf','-h','-l','-d','-s',str(p)],capture_output=True,text=True,check=True).stdout
        if 'AArch64' not in details:raise ValueError('目标架构不符')
        if name=='control.static' and ('INTERP' in details or '(NEEDED)' in details):raise ValueError('恢复工具不是独立静态ELF')
        if name=='network.so' and ('(INIT_ARRAY)' not in details or 'libc.so.6' not in details):raise ValueError('触发库依赖或构造函数不符')
        (HERE/'verification'/('elf-'+name+'.txt')).write_text(details)
        audit[name]=dict(bytes=p.stat().st_size,sha256=sha(p),aarch64=True,static=name=='control.static')
    runner.save(HERE/'verification/elf-audit.json',dict(status='passed',camera_io=False,payloads=audit))
    critical=[OLD/'seal.json',OLD/'operation.json',OLD/'materials/boot.so',OLD/'materials/control.static',OLD/'materials/ssh-service.arm64',
              OLD/'result-enable/installation-receipt.json',LIVE/'final-acceptance.json',LIVE/'screen-confirmation.json']
    old_before={str(p):sha(p) for p in critical}
    name=op['package_name'];package=HERE/'packages'/name
    package.mkdir(parents=True,exist_ok=False,mode=0o700)
    provenance={}
    def copy(src,relative):
        src=Path(src)
        if src.is_symlink():raise ValueError('拒绝链接源文件')
        dst=package/relative;dst.parent.mkdir(parents=True,exist_ok=True)
        dst.write_bytes(src.read_bytes());dst.chmod(0o600)
        provenance[str(src)]=sha(src)
    for name in ['runner.py','mount_policy.py','credentials.py','native_validation.py','build.py','rebuild.py','verify_guest.py','package.py','实施与恢复方案.md','验证记录.md']:
        copy(HERE/name,name)
    for folder in ['src','sdk','materials','tests','verification']:
        for p in sorted((HERE/folder).rglob('*')):
            if p.is_file() and '__pycache__' not in p.parts and p.suffix not in ['.pyc','.pyo']:
                copy(p,str(p.relative_to(HERE)))
    copy(OLD/'src/boot_hook.c','reference/old-boot_hook.c')
    for p in critical:copy(p,'reference/'+p.name if p==LIVE/'screen-confirmation.json' else 'reference/'+('manual-' if p.is_relative_to(LIVE) else 'previous-')+p.name)
    for name in ['analysis-receipt.json','stdout-readable.txt','network-hook-stdout.txt','network-mapping-stdout.txt']:
        copy(HERE.parent/'startup-entry-review-20261021-105355'/name,'reference/live-entry-review/'+name)
    runtime=Path(sys.executable).resolve()
    op['dependencies']={str(p):sha(p) for p in [runtime,Path('/usr/bin/ssh'),Path('/usr/bin/scp')]}
    op['offline_tests']=int(passed[1]);op['device_payload_bytes']=sum(v['bytes'] for v in op['payloads'].values())
    runner.save(package/'operation.json',op)
    runner.save(package/'source-provenance.json',provenance)
    key,fingerprint=public_key((package/'materials/trusted-host-public-key').read_bytes())
    (package/'known_hosts').write_bytes(('a7r5-netstart-'+op['net_id']+' ').encode()+key+b'\n')
    secret=HERE.parent/'fixed-password-input'
    invoke=shlex.quote(str(WORK/'a7r5-qemu/.venv/bin/python'))+' -B runner.py '
    for action,label in [('install','01-安装网络触发自启'),('rollback','02-回滚旧入口'),('neutralize','03-中和预加载')]:
        path=package/(label+'.command')
        path.write_text('#!/bin/zsh\nset -euo pipefail\ncd -- "${0:A:h}"\nexec '+invoke+action+' --approval approval-'+action+'.json --credentials '+shlex.quote(str(secret))+'\n')
        path.chmod(0o700)
    path=package/'00-仅核对离线材料.command'
    path.write_text('#!/bin/zsh\nset -euo pipefail\ncd -- "${0:A:h}"\nexec '+invoke+'install --dry-run\n');path.chmod(0o700)
    for path in package.glob('*.command'):subprocess.run(['/bin/zsh','-n',str(path)],capture_output=True,check=True)
    (package/'请先阅读.md').write_text('# 待确认，未安装相机\n\n先阅读[实施与恢复方案](实施与恢复方案.md)及[验证记录](验证记录.md)。本包是已有SSH服务的自启入口升级包，依赖旧设备目录及密钥，不是空白机身的完整安装包。\n\n仅`00-仅核对离线材料.command`无需执行批准，其余入口都要求独立批准文件和一次性锁。本轮不创建批准文件、不打开Terminal、不连接相机。\n\n固定目标`10.10.10.177:2222`；主机密钥指纹`'+fingerprint+'`。安装最多6次SSH/SCP连接、2个载荷上传、约'+str(op['device_payload_bytes'])+'字节二进制，加目录/标记/回滚指针开销；不启动服务、不重启、不操作USB协议或SD卡。\n\n不能把QEMU夹具通过理解为真实开机自启。安装与开关机验收分别确认。密码明文与相机私钥不在包内；凭据仍位于本机包外0600文件，Python和系统SSH/SCP是运行依赖。\n\n生产ELF可用rebuild.py在临时目录重建并逐字节比对；SDK libc来自本机合法固件的只读材料，源码和依赖摘要已保存。不要在封存包中重跑build.py或覆盖测试证据；需要复验时使用工作副本。\n')
    (package/'紧急恢复固定命令.md').write_text('# 仅在恢复动作另行确认后使用\n\n已有root交互终端仍可用时，以下使用shell内建exec直接进入静态程序，不先执行其他动态工具：\n\n```sh\nexec '+op['net_dir']+'/control.static neutralize\n```\n\n它仅识别本包的新/旧指针和512换行，不处理未知指针，不杀SSH。执行器退出会关闭该终端。若控制器缺失/损坏、没有可用终端或没有已验证的root入口，本包不能保证救回，不要擅自断电、删库或重跑安装。\n\n回滚旧入口可用`02-回滚旧入口.command`，中和可用`03-中和预加载.command`；各自需要批准，且不能当作重新启用或重装入口。\n')
    entries={str(p.relative_to(package)):sha(p) for p in sorted(package.rglob('*')) if p.is_file()}
    runner.save(package/'seal.json',dict(schema='a7r5-network-autostart-seal-v1',files=entries))
    sealed=sha(package/'seal.json')
    for action in runner.ACTIONS:
        runner.save(package/('approval-'+action+'.template.json'),dict(schema='a7r5-network-autostart-approval-v1',action=action,net_id=op['net_id'],seal_sha256=sealed,
            approved=False,risk=runner.RISK,no_reboot=True,preserve_current_service=True))
    password=credentials.load(secret).encode()
    for p in package.rglob('*'):
        if p.is_symlink():raise ValueError('包内出现链接')
        if p.is_file() and password in p.read_bytes():raise ValueError('材料含明文凭据，不封包')
    runner.verify(package)
    (package/'checksums.sha256').write_text(''.join(sha(p)+'  '+str(p.relative_to(package))+'\n' for p in sorted(package.rglob('*')) if p.is_file()))
    for p in package.rglob('*'):
        if p.is_file() and p.suffix!='.command':p.chmod(0o600)
    archive=package.with_suffix('.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(package.rglob('*')):
            if p.is_file():z.write(p,package.name+'/'+str(p.relative_to(package)))
    archive.chmod(0o600)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('ZIP CRC错误')
        for entry in z.infolist():
            if hashlib.sha256(z.read(entry)).hexdigest()!=sha(package.parent/entry.filename):raise ValueError('ZIP内容与包不同')
    archive.with_suffix('.zip.sha256').write_text(sha(archive)+'  '+archive.name+'\n')
    if any(sha(Path(path))!=digest for path,digest in old_before.items()):raise ValueError('旧包或证据变化')
    receipt=dict(status='SEALED_OFFLINE_ONLY_AWAITING_APPROVAL',package=str(package),archive=str(archive),zip_bytes=archive.stat().st_size,
        archive_sha256=sha(archive),seal_sha256=sealed,net_id=op['net_id'],tests=int(passed[1]),qemu_fixture_passed=True,
        byte_identical_rebuild=True,device_payload_bytes=op['device_payload_bytes'],approved=False,camera_io=False,
        real_boot_verified=False,real_warmboot_verified=False,network_trigger_on_device_verified=False,
        current_ssh_untouched=True,old_packages_and_locks_preserved=True,plaintext_password_included=False,camera_private_key_included=False)
    runner.save(HERE/'交付摘要.json',receipt)
    print(json.dumps(receipt,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
