"""只生成新本机材料包及false批准模板，不执行SSH、Terminal或相机操作。"""
from pathlib import Path
import hashlib,json,os,re,shlex,shutil,subprocess,sys,zipfile
HERE=Path(__file__).resolve().parent
WORK=next(p for p in HERE.parents if (p/'a7r5-qemu/runtime/manifest.json').is_file())
sys.path.append(str(HERE.parent))
import credentials
from native_validation import public_key
from build import sha,call
OLD=WORK/'a7r5-ssh/ssh-service/ram-key-fix/packages/ram-key-install-20261021-01'

def save(p,value):p.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def main():
    tests=(HERE/'verification/pytest.txt').read_text()
    regression=json.loads((HERE/'verification/mount-fix-02/regression.json').read_text())
    if regression['exit_code']!=0 or regression['stdout_sha256']!=sha(HERE/'verification/pytest.txt'):raise ValueError('本批回归证据不符')
    if not re.search(r'\b'+str(regression['passed'])+r' passed\b',tests):raise ValueError('缺少本批测试结果')
    for name,expected in regression['sources_sha256'].items():
        if sha(HERE/name)!=expected:raise ValueError('回归后源文件变化：'+name)
    guest=json.loads((HERE/'verification/guest.json').read_text())
    if guest['status']!='passed' or guest['cleanup']!={'method':'qmp-quit','exit_code':0}:raise ValueError('QEMU证据未通过')
    for name,expected in guest['fixture_core_sources'].items():
        if sha(HERE/'src'/name)!=expected:raise ValueError('QEMU测试源文件已变化')
    if guest['production_controller_sha256']!=sha(HERE/'materials/control.static'):raise ValueError('生产ELF测试证据不符')
    op=json.loads((HERE/'operation.json').read_text());audit={}
    for name,expected in op['payloads'].items():
        p=HERE/'materials'/name
        if p.stat().st_size!=expected['bytes'] or sha(p)!=expected['sha256']:raise ValueError('构建摘要失效')
        output=call(['/opt/homebrew/opt/llvm/bin/llvm-readelf','-h','-l','-d','--version-info',str(p)])
        (HERE/'verification'/('elf-'+name+'.txt')).write_text(output)
        if 'AArch64' not in output:raise ValueError('目标架构错误')
        if name=='control.static':
            undefined=call(['/opt/homebrew/opt/llvm/bin/llvm-nm','-u',str(p)])
            if re.search(r'\b(?:INTERP|DYNAMIC)\b',output) or undefined.strip():raise ValueError('恢复工具仍有动态依赖')
        elif any(tuple(map(int,v.split('.')))> (2,25) for v in re.findall(r'GLIBC_([0-9.]+)',output)):raise ValueError('超出目标glibc')
        audit[name]=dict(sha256=sha(p),static_without_interp=name=='control.static')
    save(HERE/'verification/elf-audit.json',dict(status='passed',camera_io=False,artifacts=audit))
    if sha(OLD/'operation.json')!='76051b07515b79fc88fff1dbd3438de22580bf997ba8901489917dcd2f1e5b2a':raise ValueError('原工作包封印变化')
    sys.path.insert(0,str(WORK/'a7r5-qemu/tools'))
    from runtime_manifest import verified_inputs,verified_libraries
    inputs=verified_inputs();libraries=verified_libraries()
    save(HERE/'verification/preservation.json',dict(status='passed',old_package_operation_sha256=sha(OLD/'operation.json'),
       runtime_files_verified={k:sha(p) for k,p in inputs.items()},runtime_libraries_verified=len(libraries),
       camera_io=False,original_image_write_operations=0,old_package_write_operations=0))
    name=op['package_name']
    if name!='autostart-20261021-02':raise ValueError('仅允许创建02包，不覆盖旧包')
    predecessor=HERE/'packages/autostart-20261021-01'
    previous=json.loads((predecessor/'result-enable/final-status.json').read_text())
    if previous['status']!='STOPPED_BEFORE_UPLOAD_SCREEN_NORMAL' or previous['payload_uploads']!=0 or previous['preload_writes']!=0:raise ValueError('旧会话不是零写入终态，禁止复用设备路径')
    snapshot=json.loads((HERE/'verification/mount-fix-02/old-package-before.json').read_text())
    for relative,record in snapshot.items():
        p=predecessor/relative
        if sha(p)!=record['sha256'] or p.stat().st_size!=record['bytes'] or p.stat().st_mtime_ns!=record['mtime_ns'] or p.stat().st_mode&0o7777!=record['mode']:raise ValueError('旧包或证据发生变化：'+relative)
    if any(sha(HERE/'materials'/n)!=sha(predecessor/'materials'/n) for n in op['payloads']):raise ValueError('此次仅修复主机校验，设备载荷不得变化')
    package=HERE/'packages'/name;package.mkdir(parents=True,exist_ok=False,mode=0o700)
    def copy(source,name):
        source=Path(source);destination=package/name
        if source.is_symlink():raise ValueError('拒绝链接材料')
        destination.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        shutil.copyfile(source,destination);destination.chmod(0o600)
    for name in ('runner.py','build.py','rebuild.py','verify_guest.py','operation.json','实施与恢复方案.md','挂载校验修复与验证.md'):
        copy(HERE/name,name)
    for folder in ('src','materials','tests','verification'):
        for path in sorted((HERE/folder).rglob('*')):
            if path.is_file() and '__pycache__' not in path.parts and path.suffix!='.pyc':copy(path,str(path.relative_to(HERE)))
    for name in ('src/ns_abi.h','src/ns_sha256.h','src/start.S','ssh-service/launcher.c','ssh-service/private_account.h','ssh-service/private_hostkey.h'):
        copy(HERE/'source-snapshot/engine'/name,'source-snapshot/engine/'+name)
    for name in ('credentials.py','native_validation.py'):copy(HERE.parent/name,name)
    for name in ('final-acceptance.json','screen-confirmation.json'):
        copy(OLD/'result'/name,'proof/device/'+name)
    copy(OLD/'materials/config.h','proof/device/config-original.h')
    for path in (predecessor/'result-enable').iterdir():
        if path.is_file():copy(path,'proof/predecessor/'+path.name)
    for name in ('init','init2','initrc/setup_rootfs','initrc/insmod_drv2','initrc/fstab'):
        copy(WORK/'a7r5-ssh/analysis/network-20261020-v1/original/root/sbin'/name,'proof/boot/sbin/'+name)
    for name in ('fstab.ext.txt','bootin.original.elf'):
        copy(HERE.parent/'verification'/name,'proof/boot/'+name)
    key,fingerprint=public_key((package/'materials/trusted-host-public-key').read_bytes())
    (package/'known_hosts').write_bytes(('a7r5-autostart-'+op['auto_id']+' ').encode()+key+b'\n')
    runtime=str(WORK/'a7r5-qemu/.venv/bin/python');secret=str(HERE.parent/'fixed-password-input')
    for action,label in [('enable','01-启用自启'),('disable','02-禁用自启'),('recover','03-受限恢复')]:
        command='exec '+shlex.quote(runtime)+' -B runner.py '+action+' --approval approval-'+action+'.json --credentials '+shlex.quote(secret)
        p=package/(label+'.command');p.write_text('#!/bin/zsh\nset -euo pipefail\ncd -- "${0:A:h}"\n'+command+'\n');p.chmod(0o700)
    p=package/'00-仅核对离线材料.command';p.write_text('#!/bin/zsh\nset -euo pipefail\ncd -- "${0:A:h}"\nexec '+shlex.quote(runtime)+' -B runner.py enable --dry-run\n');p.chmod(0o700)
    (package/'请先阅读.md').write_text('# 待确认，尚未启用\n\n本包通过当前SSH安装自启候选，不操作USB协议，不重启或停止现有服务。先阅读 [实施与恢复方案](实施与恢复方案.md)。\n\n只可先运行 `00-仅核对离线材料.command`；其余入口没有对应批准文件会在联网前拒绝。三个模板均为未批准状态。本轮不创建批准文件或尝试锁，不打开Terminal。\n\n安装与首次重启分别确认；禁用不停止现有SSH。全局预加载可能影响启动；没有已验证的独立救砖能力。新包约54 KiB设备载荷，包内额外包含源文件和离线证据。密码明文及相机私钥不在包内；密码文件沿用本机包外0600文件，操作系统SSH/SCP和Python为运行依赖。\n\n目标 `10.10.10.177:2222`，主机密钥指纹 `'+fingerprint+'`。\n')
    files={str(p.relative_to(package)):sha(p) for p in sorted(package.rglob('*')) if p.is_file()}
    save(package/'seal.json',dict(schema='a7r5-autostart-seal-v1',files=files))
    sealed=sha(package/'seal.json')
    for action in ('enable','disable','recover'):
        save(package/('approval-'+action+'.template.json'),dict(schema='a7r5-autostart-approval-v1',action=action,auto_id=op['auto_id'],
          seal_sha256=sealed,approved=False,accept_persistent_loader_risk=False,no_reboot=True,preserve_current_service=True))
    # 本机明文口令只在内存中用于泄露扫描，不输出或归档。
    password=credentials.load(secret).encode()
    for p in package.rglob('*'):
        if p.is_symlink():raise ValueError('包内出现链接')
        if p.is_file() and password in p.read_bytes():raise ValueError('包内检测到明文口令，停止封包')
    (package/'checksums.sha256').write_text(''.join(sha(p)+'  '+str(p.relative_to(package))+'\n' for p in sorted(package.rglob('*')) if p.is_file()))
    for p in package.rglob('*'):
        if p.is_file() and p.suffix!='.command':p.chmod(0o600)
    archive=package.with_suffix('.zip')
    with zipfile.ZipFile(archive,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=9) as z:
        for p in sorted(package.rglob('*')):
            if p.is_file():z.write(p,package.name+'/'+str(p.relative_to(package)))
    archive.chmod(0o600)
    with zipfile.ZipFile(archive) as z:
        if z.testzip() is not None:raise ValueError('ZIP CRC不通过')
    archive.with_suffix('.zip.sha256').write_text(sha(archive)+'  '+archive.name+'\n')
    receipt=dict(status='sealed',package=str(package),archive=str(archive),bytes=archive.stat().st_size,zip_sha256=sha(archive),seal_sha256=sealed,
      approved=False,camera_io=False,plaintext_password_included=False,camera_private_key_included=False,device_payload_bytes=sum(v['bytes'] for v in op['payloads'].values()),
      tests=regression['passed'],qemu_prior_evidence_reused_for_identical_payloads=True,real_boot_verified=False,existing_service_modified=False,
      old_package_and_locks_preserved=True,payloads_identical_to_01=True,previous_approval_reusable=False)
    save(HERE/'交付摘要-02.json',receipt);print(json.dumps(receipt,ensure_ascii=False,indent=2))
if __name__=='__main__':main()
