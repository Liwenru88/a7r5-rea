"""离线封装候选，保留旧包/锁；不生成实机批准、不访问设备。"""
import hashlib,json,re,shutil,subprocess,sys
from pathlib import Path
import build_candidate as build
import source_gate

ROOT=build.ROOT


def prepare(directory,evidence,*,password_hash=None,qemu_only=False,host_public=None):
    old=build.SERVICE/'ram-key-fix/packages/ram-key-install-20261021-01/materials'
    # 仅复用已验证的密码哈希；不读取明文、不在构建日志输出哈希。
    if password_hash is None:
        matched=re.search(r'^#define PASSWORD_HASH (".*")$',(old/'config.h').read_text(),re.M)
        if not matched:raise ValueError('旧认证材料缺失')
        password_hash=json.loads(matched[1])
    result=build.build(directory,password_hash,seconds=600,qemu_only=qemu_only)
    directory=Path(directory).absolute();run=result['run_id'];install=result['install_directory']
    for name in ['sftp-server.arm64','sftp-COPYRIGHT','sftp-provenance.json']:shutil.copyfile(ROOT/'vendor'/name,directory/name)
    shutil.copyfile(ROOT/'candidate_once.py',directory/'candidate_once.py')
    shutil.copyfile(ROOT/'source_gate.py',directory/'source_gate.py')
    shutil.copytree(ROOT/'key-source-audit-20261021-02',directory/'key-source-audit-20261021-02',ignore=shutil.ignore_patterns('ATTEMPT_LOCK','__pycache__'))
    key= (build.SERVICE/'manual-restart/packages/restart-20261021-01/reference/host-public-key').read_text().split()
    if host_public is not None:
        if not qemu_only:raise ValueError('实机材料禁止替换可信公钥')
        key=host_public.split()
    if len(key)<2 or key[0]!='ecdsa-sha2-nistp256':raise ValueError('历史可信公钥缺失')
    (directory/'known_hosts').write_text('a7r5-original-'+run+' '+' '.join(key[:2])+'\n')
    version='34c44c5d2974d822eb8c43953317c8ccecaa51b72ffad8693d1cd3261a4fa79b'
    preamble='''#!/bin/sh
# 仅相机候选阶段使用；不编辑预加载、账户、旧服务或自启。
set -eu
PATH=/bin:/sbin:/usr/bin:/usr/sbin
LC_ALL=C
export PATH LC_ALL
umask 077
die(){ printf 'A7R5_ORIGINAL_STAGE_REFUSED %s\\n' "$1" >&2; exit 1; }
hash(){ [ -f "$1" ] && [ ! -L "$1" ] || return 1; sum=$(/usr/bin/openssl dgst -sha256 "$1") || return 1; printf '%s' "${sum##* }"; }
'''
    prepare=preamble+f'''[ "$(hash /version.txt)" = '{version}' ] || die version
'''+source_gate.script(qemu_only)+f'''
[ -d /tmp/jiritsu ] && [ ! -L /tmp/jiritsu ] || die shared_directory
[ ! -e '{install}' ] && [ ! -L '{install}' ] || die existing_candidate
/bin/busybox mkdir '{install}'
printf 'A7R5_STAGE_EMPTY {run}\\n'
'''
    checks=''.join('[ "$(hash '+install+'/'+name+')" = '+build.digest(directory/name)+' ] || die '+name+'\n' for name in ['ssh-original.arm64','session.arm64','sftp-server.arm64','anchor.arm64'])
    start=preamble+checks+source_gate.script(qemu_only)+f"exec '{install}/ssh-original.arm64' --launch-from-proof\n"
    (directory/'start.sh').write_text(start)
    executable=''.join('/bin/busybox chmod 700 '+install+'/'+name+'\n[ -x '+install+'/'+name+' ] || die executable_'+name+'\n' for name in ['ssh-original.arm64','session.arm64','sftp-server.arm64','anchor.arm64'])
    verify=preamble+checks+executable+f'''[ "$(hash {install}/start.sh)" = '{hashlib.sha256(start.encode()).hexdigest()}' ] || die start_script
[ ! -e '{install}/host_ecdsa.pub' ] && [ ! -L '{install}/host_ecdsa.pub' ] || die existing_public_key
set -C
printf '%s\\n' '{' '.join(key[:2])}' > '{install}/host_ecdsa.pub'
set +C
[ "$(hash {install}/host_ecdsa.pub)" = '{hashlib.sha256((' '.join(key[:2])+chr(10)).encode()).hexdigest()}' ] || die public_key_copy
printf 'A7R5_STAGE_VERIFIED {run}\\n'
'''
    task=f"set -eu\nsum=$(/usr/bin/openssl dgst -sha256 '{install}/anchor.arm64')\n[ \"${{sum##* }}\" = '{build.digest(directory/'anchor.arm64')}' ]\nexec '{install}/anchor.arm64'\n"
    for name,text in [('stage-prepare.sh',prepare),('stage-verify.sh',verify),('anchor-task.sh',task)]:
        (directory/name).write_text(text)
        subprocess.run(['/bin/sh','-n'],input=text,text=True,capture_output=True,check=True)
    subprocess.run(['/bin/sh','-n'],input=start,text=True,capture_output=True,check=True)
    # 保存可重建源码及ABI材料，目录关系与工程保持一致。
    source=directory/'rebuild/a7r5-ssh/ssh-service/original-view';source.mkdir(parents=True)
    for name in ['launcher.c','session.c','anchor.c','proof.h','build_candidate.py','package_materials.py','source_gate.py']:
        shutil.copyfile(ROOT/name,source/name)
    audit=source/'key-source-audit-20261021-02';audit.mkdir()
    shutil.copyfile(ROOT/'key-source-audit-20261021-02/result.json',audit/'result.json')
    compat=ROOT/'packages/original-view-20261021-03'
    shutil.copytree(compat/'compat-proof',directory/'compat-proof')
    shutil.copyfile(compat/'anchor_once.py',directory/'anchor_once.py')
    for name in ['private_account.h','private_hostkey.h','credentials.py']:
        shutil.copyfile(build.SERVICE/name,source.parent/name)
    abi=directory/'rebuild/a7r5-ssh/src';abi.mkdir()
    for name in ['ns_abi.h','ns_sha256.h','start.S']:shutil.copyfile(build.LAB/'src'/name,abi/name)
    sdk=directory/'rebuild/a7r5-ssh/vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib';sdk.mkdir(parents=True)
    original_lib=build.LAB/'vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.25.so'
    shutil.copyfile(original_lib,sdk/'libc-2.25.so')
    verification=directory/'verification';verification.mkdir()
    for name in ['result.json','original-session.txt','stopped.txt','ram-key-copy.txt']:
        if (evidence/name).is_file():shutil.copyfile(evidence/name,verification/name)
    for path in sorted(evidence.glob('client-*.json')):
        shutil.copyfile(path,verification/path.name)
        for suffix in ['.stdout','.stderr']:
            f=path.with_suffix(suffix)
            if f.is_file():shutil.copyfile(f,verification/f.name)
    shutil.copyfile(ROOT/'verify_qemu.py',verification/'verify_qemu.py')
    shutil.copytree(ROOT/'tests',verification/'tests',ignore=shutil.ignore_patterns('__pycache__'))
    for name in ['README.md','实施与恢复清单.md']:shutil.copyfile(ROOT/name,directory/name)
    (directory/'source-binding.json').write_text(json.dumps(source_gate.binding(),ensure_ascii=False,indent=2)+'\n')
    for action in ['stage','start','stop']:
        body='#!/bin/zsh\nset -eu\nROOT="${0:A:h}"\nTASK_PY="${A7R5_PYTHON:-'+str(build.LAB.parent/'.venv/bin/python')+'}"\n"$TASK_PY" -B "$ROOT/candidate_once.py" check --package "$ROOT"\nprintf "本阶段需另行确认；输入本阶段 ACCEPT 短语："\nread -r accepted\n'
        extra=''
        if action=='start':body+='printf "输入已通过屏幕门槛的锚点会话完整路径："\nread -r anchor\n';extra=' --anchor-run "$anchor"'
        body+='exec "$TASK_PY" -B "$ROOT/candidate_once.py" '+action+' --package "$ROOT" --device-io --accept "$accepted"'+extra+'\n'
        (directory/('run-'+action+'-once.command')).write_text(body)
    (directory/'run-anchor-once.command').write_text('#!/bin/zsh\nset -eu\nROOT="${0:A:h}"\nTASK_PY="${A7R5_PYTHON:-'+str(build.LAB.parent/'.venv/bin/python')+'}"\n"$TASK_PY" -B "$ROOT/candidate_once.py" check --package "$ROOT"\nprintf "本次锚点须另行确认；输入锚点ACCEPT短语："\nread -r accepted\nexec "$TASK_PY" -B "$ROOT/anchor_once.py" "$accepted"\n')
    manifest=dict(schema='a7r5-original-view-1',run_id=run,install_directory=install,ram_directory=result['ram_directory'],
        qemu_only=qemu_only,ip='10.10.10.177',port=2223,old_port=2222,seconds=600,autostart=False,live_approved=False,
        uploads=['ssh-original.arm64','session.arm64','sftp-server.arm64','anchor.arm64','start.sh'],
        evidence_scope='QEMU/本机，未实机验证',files={})
    for f in directory.rglob('*'):
        if f.is_file():f.chmod(0o600);manifest['files'][str(f.relative_to(directory))]=build.digest(f)
    for f in directory.glob('*.command'):f.chmod(0o700)
    (directory/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2)+'\n');(directory/'manifest.json').chmod(0o600)
    return manifest


if __name__=='__main__':
    if len(sys.argv)!=3:raise SystemExit('用法：package_materials.py 新目录 QEMU验收目录')
    print(json.dumps(prepare(Path(sys.argv[1]),Path(sys.argv[2])),ensure_ascii=False,indent=2))
