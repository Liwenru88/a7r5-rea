"""只构建离线产物；不读取设备，不调用SSH。"""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import uuid

HERE=Path(__file__).resolve().parent
WORK=next(p for p in HERE.parents if (p/'a7r5-qemu/runtime/manifest.json').is_file())
OLD=HERE.parent/'autostart/packages/autostart-20261021-02'
LIVE=HERE.parent/'manual-restart/packages/restart-20261021-01/result'
CLANG='/opt/homebrew/opt/llvm/bin/clang'
LLD='/opt/homebrew/opt/lld/bin/ld.lld'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    if (HERE/'packages').exists():raise ValueError('封包后不重建工作材料，请使用包内rebuild.py比对')
    materials=HERE/'materials';materials.mkdir(exist_ok=True)
    sdk=HERE/'sdk';sdk.mkdir(exist_ok=True)
    for name in ('ns_abi.h','ns_sha256.h','start.S'):
        source=WORK/'a7r5-ssh/src'/name
        if not (sdk/name).exists():shutil.copyfile(source,sdk/name)
    for name in ('credentials.py','native_validation.py'):
        if not (HERE/name).exists():shutil.copyfile(OLD/name,HERE/name)
    crt=HERE/'src/linux_crt.c'
    if not crt.exists():shutil.copyfile(OLD/'src/linux_crt.c',crt)
    legacy=json.loads((OLD/'operation.json').read_text())
    receipt=json.loads((LIVE/'final-acceptance.json').read_text())
    if not receipt['root_pty_verified'] or not receipt['screen_normal'] or not receipt['original_autostart_pointer_preserved']:
        raise ValueError('当前人工启动的验收证据不符')
    config=HERE/'operation.json'
    if config.exists():op=json.loads(config.read_text())
    else:
        aid=uuid.uuid4().hex
        op=dict(schema='a7r5-network-autostart-v1',net_id=aid,old_id=legacy['auto_id'],service_run=legacy['service_run'],
                net_dir='/etc/a7r5-netstart-'+aid,stage_dir='/tmp_network/a7r5-netstage-'+aid,
                helper_dir=legacy['auto_dir'],service_ram=legacy['ram_root'],private_source=legacy['private_source'],
                active_namespace='mnt:[4026533196]',target_ip='10.10.10.177',port=2222,
                trigger='/usr/bin/wpa_supplicant',package_name='network-autostart-20261021-01',
                real_boot_verified=False,real_network_trigger_verified=False,live_approved=False)
    if sha(OLD/'materials/ssh-service.arm64')!=legacy['payloads']['ssh-service.arm64']['sha256']:raise ValueError('已验证启动器材料改变')
    ready=(LIVE/'session/ready.bin').read_bytes();public=(LIVE/'session/host-public-key.bin').read_bytes()
    for name,raw in [('expected-ready.bin',ready),('trusted-host-public-key',public),('preload.previous', (op['helper_dir']+'/boot.so\n').encode())]:
        (materials/name).write_bytes(raw)
    values=dict(NET_ID=op['net_id'],NET_NAME=Path(op['net_dir']).name,NET_DIR=op['net_dir'],NET_TRIGGER=op['trigger'],
                HELPER_DIR=op['helper_dir'],HELPER_PATH=op['helper_dir']+'/ssh-service.arm64',
                HELPER_SHA=legacy['payloads']['ssh-service.arm64']['sha256'],OLD_HOOK_SHA=legacy['payloads']['boot.so']['sha256'],
                OLD_ID=op['old_id'],SERVICE_RUN=op['service_run'],SERVICE_RAM=op['service_ram'],RAM_PARENT='/tmp_network',
                CLAIM_NAME='a7r5-netstart-'+op['net_id']+'.claim',CLAIM_PATH='/tmp_network/a7r5-netstart-'+op['net_id']+'.claim',
                PROC_CMDLINE='/proc/self/cmdline',PROC_EXE='/proc/self/exe',PROC_SELF_NS='/proc/self/ns/mnt',
                PROC_INIT_NS='/proc/1/ns/mnt',PROC_TCP='/proc/net/tcp',ETC_ROOT='/etc',STAGE_DIR=op['stage_dir'],
                ACTIVE_NS=op['active_namespace'],SELF_EXE='/proc/self/exe',
                READY_SHA=hashlib.sha256(ready).hexdigest(),PUBLIC_SHA=hashlib.sha256(public).hexdigest(),
                OLD_PRELOAD=op['helper_dir']+'/boot.so\n',NEW_PRELOAD=op['net_dir']+'/network.so\n',
                PRELOAD_NEW='.a7r5-net-preload-new-'+op['net_id'],PRELOAD_RESTORE='.a7r5-net-preload-restore-'+op['net_id'])
    def header():
        (materials/'net_config.h').write_text(''.join('#define '+k+' '+json.dumps(v)+'\n' for k,v in values.items())+
            '#define HELPER_BYTES '+str(legacy['payloads']['ssh-service.arm64']['bytes'])+'\n')
    libc=WORK/'a7r5-ssh/vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.25.so'
    if sha(libc)!='f9104526eb7e5d2ea533c1a209bb0b83e69367f569e4c966895c8e106e6382c9':raise ValueError('libc摘要改变')
    common=[CLANG,'--target=aarch64-linux-gnu','--ld-path='+LLD,'-nostdlib','-ffreestanding','-fno-builtin','-fno-stack-protector',
            '-O2','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wl,--no-undefined','-Wl,-z,max-page-size=65536',
            '-I',str(materials),'-I',str(sdk),'-I',str(HERE/'src')]
    commands=[]
    header()
    command=common+['-fPIC','-shared','-fvisibility=hidden',str(HERE/'src/network_hook.c'),str(libc),'-o',str(materials/'network.so')]
    subprocess.run(command,capture_output=True,check=True,timeout=60);commands.append(command)
    values['HOOK_SHA']=sha(materials/'network.so');header()
    command=common+['-static','-Wl,-e,_start',str(sdk/'start.S'),str(crt),str(HERE/'src/control.c'),'-o',str(materials/'control.static')]
    subprocess.run(command,capture_output=True,check=True,timeout=60);commands.append(command)
    original=WORK/'a7r5-ssh/analysis/network-20261020-v1/original/etc'
    op.update(payloads={n:dict(bytes=(materials/n).stat().st_size,sha256=sha(materials/n)) for n in ('network.so','control.static')},
              helper_sha256=values['HELPER_SHA'],public_sha256=values['PUBLIC_SHA'],ready_sha256=values['READY_SHA'],
              original_hashes={'/proc/1/root/etc/passwd':'4a691edcd492167bb3d538e4e15c24dd5fbc45785afcf2beddb3fbd39e097398',
                  '/proc/1/root/etc/nsswitch.conf':sha(original/'nsswitch.conf'),'/proc/1/root/etc/ssh/sshd_config':sha(original/'ssh/sshd_config')})
    config.write_text(json.dumps(op,ensure_ascii=False,indent=2)+'\n')
    verification=HERE/'verification';verification.mkdir(exist_ok=True)
    (verification/'build.json').write_text(json.dumps(dict(commands=commands,camera_io=False,payloads=op['payloads']),indent=2)+'\n')
    print(json.dumps(op['payloads'],indent=2))


if __name__=='__main__':main()
