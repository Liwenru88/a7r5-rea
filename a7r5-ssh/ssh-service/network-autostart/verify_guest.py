"""断网QEMU，仅固定RAM夹具；模拟恢复生命周期，不启动sshd或联网程序。"""
from pathlib import Path
import hashlib
import json
import re
import shlex
import subprocess
import sys
from build import HERE,WORK,OLD,CLANG,LLD,sha

sys.path.insert(0,str(WORK/'a7r5-qemu/tools'))
from native_vm import NativeVM


def put(vm,path,raw):
    vm.command('umask 077; : > '+shlex.quote(path))
    for offset in range(0,len(raw),128):
        row=''.join('\\%03o'%b for b in raw[offset:offset+128])
        vm.command('printf '+shlex.quote(row)+' >> '+shlex.quote(path))
    vm.command('/bin/busybox chmod 700 '+shlex.quote(path))
    actual=vm.command('/bin/busybox md5sum '+shlex.quote(path))
    if hashlib.md5(raw).hexdigest().encode() not in actual:raise ValueError('夹具传输摘要不符')


def main():
    directory=HERE/'verification/guest';directory.mkdir(parents=True,exist_ok=True)
    op=json.loads((HERE/'operation.json').read_text());base='/simulation/network-autostart';etc=base+'/etc';ram=base+'/ram'
    auto=etc+'/network';old=etc+'/previous';stage=ram+'/stage';active=ram+'/active';trigger=base+'/wpa_supplicant'
    libc=WORK/'a7r5-ssh/vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.25.so'
    common=[CLANG,'--target=aarch64-linux-gnu','--ld-path='+LLD,'-nostdlib','-ffreestanding','-fno-builtin','-fno-stack-protector',
        '-O2','-Wall','-Wextra','-Werror','-Wno-unused-function','-Wl,--no-undefined','-Wl,-z,max-page-size=65536',
        '-I',str(directory),'-I',str(HERE/'sdk'),'-I',str(HERE/'src')]
    def build(name,source,static=False,shared=False):
        flags=['-fPIC','-shared','-fvisibility=hidden'] if shared else ['-Wl,-e,_start',str(HERE/'sdk/start.S')]+(['-static',str(HERE/'src/linux_crt.c')] if static else ['-fPIE','-pie','-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1'])
        subprocess.run(common+flags+[str(source)]+([] if static else [str(libc)])+['-o',str(directory/name)],capture_output=True,check=True,timeout=60)
    helper=directory/'helper.c';helper.write_text('#include "ns_abi.h"\nint main(int argc,char **argv){if(argc!=2||strcmp(argv[1],"--launch"))return 61;int fd=open("'+base+'/launches",O_WRONLY|O_CREAT|1024,0600);if(fd<0)return 62;int okay=write(fd,"LAUNCHED\\n",9)==9&&!close(fd);return okay?0:63;}\n')
    build('helper',helper,static=True)
    dummy=directory/'dummy.c';dummy.write_text('#include "ns_abi.h"\nint main(void){return write(1,"TRIGGER_RETURNED\\n",17)==17?0:1;}\n')
    build('wpa_supplicant',dummy)
    result=dict(status='failed',camera_io=False,physical_devices=False,guest_nic='none',sshd_started=False,
                actual_wpa_supplicant_executed=False,real_boot_verified=False,real_warmboot_verified=False,
                fixture_core_sources={n:sha(HERE/'src'/n) for n in ['common.h','network_hook.c','control.c','linux_crt.c']})
    vm=NativeVM('network-autostart-offline',capid=True,boot_services=True);result['vm_evidence']=str(vm.out)
    manifest=WORK/'a7r5-qemu/runtime/manifest.json';before=sha(manifest)
    try:
        vm.start();print('QEMU_ROOT_READY',flush=True)
        vm.command('mkdir '+base+'; mount -t tmpfs -o size=4m,mode=0755 tmpfs '+base+'; mkdir '+etc+' '+ram+' '+stage+' '+old+' '+active+'; chmod 700 '+stage+' '+active+'; chmod 1777 '+ram)
        raw=vm.command('/bin/busybox readlink /proc/self/ns/mnt');ns=re.findall(rb'\nmnt:\[[0-9]+\]\r?\n',raw)[-1].strip().decode()
        values=dict(NET_ID=op['net_id'],OLD_ID=op['old_id'],SERVICE_RUN=op['service_run'],NET_NAME='network',NET_DIR=auto,NET_TRIGGER=trigger,
            HELPER_DIR=old,HELPER_PATH=old+'/ssh-service.arm64',HELPER_SHA=sha(directory/'helper'),OLD_HOOK_SHA=hashlib.sha256(b'OLD_TEST_ONLY\n').hexdigest(),
            SERVICE_RAM=active,RAM_PARENT=ram,CLAIM_NAME='claim',CLAIM_PATH=ram+'/claim',PROC_CMDLINE='/proc/self/cmdline',PROC_EXE='/proc/self/exe',
            PROC_SELF_NS='/proc/self/ns/mnt',PROC_INIT_NS='/proc/1/ns/mnt',PROC_TCP='/proc/net/tcp',ETC_ROOT=etc,STAGE_DIR=stage,
            ACTIVE_NS=ns,SELF_EXE='/proc/self/exe',READY_SHA=hashlib.sha256(b'READY_TEST_ONLY\n').hexdigest(),PUBLIC_SHA=hashlib.sha256(b'PUBLIC_TEST_ONLY\n').hexdigest(),
            OLD_PRELOAD=old+'/boot.so\n',NEW_PRELOAD=auto+'/network.so\n',PRELOAD_NEW='new',PRELOAD_RESTORE='restore')
        def config():
            (directory/'net_config.h').write_text(''.join('#define '+k+' '+json.dumps(v)+'\n' for k,v in values.items())+'#define HELPER_BYTES '+str((directory/'helper').stat().st_size)+'\n')
        config();build('network.so',HERE/'src/network_hook.c',shared=True)
        values['HOOK_SHA']=sha(directory/'network.so');config();build('control.static',HERE/'src/control.c',static=True)
        # 原实现对网络程序不触发：同一目标和helper均有效，仅旧BOOT_TRIGGER仍是bootin。
        oldvalues=dict(AUTO_ID=op['old_id'],AUTO_DIR=old,BOOT_TRIGGER='/usr/bin/bootin.elf',PROC_CMDLINE='/proc/self/cmdline',PROC_EXE='/proc/self/exe',RAM_PARENT=ram,CLAIM_NAME='old-claim',HELPER_SHA=values['HELPER_SHA'])
        (directory/'auto_config.h').write_text(''.join('#define '+k+' '+json.dumps(v)+'\n' for k,v in oldvalues.items()))
        legacy_source=HERE/'reference/old-boot_hook.c'
        build('old-boot.so',legacy_source if legacy_source.exists() else OLD/'src/boot_hook.c',shared=True)
        for name,target in [('helper',old+'/ssh-service.arm64'),('network.so',stage+'/network.so'),('control.static',base+'/control.static'),('wpa_supplicant',trigger),('old-boot.so',base+'/old-boot.so')]:
            put(vm,target,(directory/name).read_bytes());print('QEMU_TRANSFERRED '+name,flush=True)
        vm.command("printf 'OLD_TEST_ONLY\\n' > "+old+"/boot.so; printf '"+op['old_id']+"\\n' > "+old+"/enabled; printf 'READY_TEST_ONLY\\n' > "+active+"/ready; printf 'PUBLIC_TEST_ONLY\\n' > "+active+"/host-public-key; printf '"+old+"/boot.so\\n' > "+etc+'/ld.so.preload')
        proof=vm.command('LD_PRELOAD='+base+'/old-boot.so '+trigger+'; sleep 1; test ! -e '+ram+'/old-claim; test ! -e '+base+'/launches')
        (directory/'old-network-trigger-missed.txt').write_bytes(proof);result['old_bootin_only_misses_network_reproduced']=True
        proof=vm.command(base+'/control.static install');(directory/'install.txt').write_bytes(proof)
        if ('A7R5_NET_INSTALLED1 '+op['net_id']).encode() not in proof:raise ValueError('没有安装成功回执')
        vm.command('LD_PRELOAD='+auto+'/network.so '+trigger+'; sleep 1; test ! -e '+base+'/launches')
        result['current_service_suppressed_no_second_launch']=True
        # 只删除夹具RAM内容以模拟恢复到安装前的RAM；不是机身/VM重启。
        vm.command('rm '+ram+'/claim/suppressed-active-service; rmdir '+ram+'/claim; rm '+active+'/ready '+active+'/host-public-key; rmdir '+active)
        proof=vm.command('LD_PRELOAD='+auto+'/network.so '+trigger+'; sleep 1; cat '+base+'/launches; cat '+ram+'/claim/launch-approved')
        (directory/'warm-fixture-launch.txt').write_bytes(proof)
        if b'\nLAUNCHED\n' not in proof.replace(b'\r',b''):raise ValueError('网络触发未启动固定夹具ELF')
        vm.command('LD_PRELOAD='+auto+'/network.so '+trigger+'; sleep 1; test "$(/bin/busybox wc -c < '+base+'/launches)" -eq 9')
        result.update(fixture_warm_restore_new_network_exec_launches=True,descriptor_execveat_verified=True,repeated_network_trigger_no_duplicate=True)
        vm.command('rm '+ram+'/claim/attempt '+ram+'/claim/launch-approved; rmdir '+ram+'/claim; mkdir '+active+'; printf "stale PID fixture\\n" > '+active+'/ready; LD_PRELOAD='+auto+'/network.so '+trigger+'; sleep 1; test "$(cat '+ram+'/claim/result)" = EXISTING_RAM_REFUSED; test "$(/bin/busybox wc -c < '+base+'/launches)" -eq 9')
        result['stale_restored_ram_refused_without_delete_or_launch']=True
        proof=vm.command(base+'/control.static rollback');(directory/'rollback.txt').write_bytes(proof)
        if ('A7R5_NET_ROLLED_BACK1 '+op['net_id']).encode() not in proof:raise ValueError('回滚未通过')
        put(vm,etc+'/ld.so.preload',(auto+'/network.so\n').encode())
        vm.command('printf broken > '+auto+'/network.so; printf broken > '+old+'/ssh-service.arm64')
        proof=vm.command('LD_PRELOAD=/definitely-missing '+base+'/control.static neutralize');(directory/'static-neutralize-broken.txt').write_bytes(proof)
        if ('A7R5_NET_NEUTRAL1 '+op['net_id']).encode() not in proof:raise ValueError('静态中和失败')
        vm.command('test "$(/bin/busybox wc -c < '+etc+'/ld.so.preload)" -eq 512')
        result['static_neutralization_works_with_broken_hook_and_helper']=True
        # 精确生产ELF：仅非目标程序加载及只读inspect拒绝；不建立生产目录。
        put(vm,base+'/production-network.so',(HERE/'materials/network.so').read_bytes())
        put(vm,base+'/production-control.static',(HERE/'materials/control.static').read_bytes())
        proof=vm.command('LD_PRELOAD='+base+'/production-network.so /bin/true; '+base+'/production-control.static inspect; rc=$?; printf "PRODUCTION_REFUSAL:%s\\n" "$rc"; test "$rc" -eq 2 -o "$rc" -eq 3')
        (directory/'production-elf-safe-refusal.txt').write_bytes(proof)
        result.update(exact_production_elf_loaded_non_target_and_static_refused=True,status='passed')
    except BaseException as exc:result['error']=type(exc).__name__+': '+str(exc)
    finally:
        result['cleanup']=vm.close();result['runtime_manifest_unchanged']=sha(manifest)==before
        if result['cleanup']!={'method':'qmp-quit','exit_code':0} or not result['runtime_manifest_unchanged']:result['status']='failed'
        (HERE/'verification/guest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
