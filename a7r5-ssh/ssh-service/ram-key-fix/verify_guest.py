"""断网沙箱QEMU只验证密钥复制函数；不调用SSH启动器或sshd。"""
import hashlib
import json
from pathlib import Path
import re
import shlex
import subprocess
import sys

SOURCE=Path(__file__).resolve().parent
PACKAGE=SOURCE if (SOURCE/'config.json').exists() else SOURCE/'packages/ram-key-install-20261021-01'
WORK=next(p for p in SOURCE.parents if (p/'a7r5-qemu/runtime/manifest.json').is_file())
sys.path[:0]=[str(PACKAGE),str(WORK/'a7r5-qemu/tools')]
import policy
from native_vm import NativeVM


def put(vm,path,raw):
    vm.command('umask 077; : > '+shlex.quote(path))
    for offset in range(0,len(raw),48):
        row=''.join('\\%03o'%b for b in raw[offset:offset+48])
        vm.command('printf '+shlex.quote(row)+' >> '+shlex.quote(path))
    vm.command('/bin/busybox chmod 700 '+shlex.quote(path))


def main():
    verify=PACKAGE/'verification';verify.mkdir(exist_ok=True)
    run=json.loads((PACKAGE/'config.json').read_text())['run_id']
    include=verify/'probe-include';include.mkdir(exist_ok=True)
    (include/'probe_config.h').write_text('#define PROBE_RUN '+json.dumps(run)+'\n')
    source=PACKAGE/'rebuild-sources/ssh-service/ram-key-fix/key_copy_probe.c'
    output=verify/'key-copy-only.arm64'
    libc=WORK/'a7r5-ssh/vendor/engine/sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev/nflasha7_unpacked/lib/libc-2.25.so'
    command=['/opt/homebrew/opt/llvm/bin/clang','--target=aarch64-linux-gnu','--ld-path=/opt/homebrew/opt/lld/bin/ld.lld',
             '-nostdlib','-ffreestanding','-fno-builtin','-fno-stack-protector','-fPIE','-pie','-O2','-Wall','-Wextra','-Werror','-Wno-unused-function',
             '-Wl,--no-undefined','-Wl,-e,_start','-Wl,-z,max-page-size=65536','-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1',
             '-I',str(include),str(WORK/'a7r5-ssh/src/start.S'),str(source),str(libc),'-o',str(output)]
    built=subprocess.run(command,capture_output=True,text=True,timeout=60)
    (verify/'guest-probe-build.json').write_text(json.dumps(dict(command=command,exit_code=built.returncode,stderr=built.stderr),indent=2)+'\n')
    if built.returncode:raise RuntimeError('离线密钥专用探针编译失败')
    result=dict(status='failed',run_id=run,camera_io=False,ssh_started=False,sshd_config_test_executed=False,
                login_attempted=False,autostart_enabled=False,guest_nic='none',synthetic_key_only=True)
    vm=NativeVM('ram-key-copy-only',capid=True,boot_services=True);result['vm_evidence']=str(vm.out)
    manifest=WORK/'a7r5-qemu/runtime/manifest.json';before=hashlib.sha256(manifest.read_bytes()).hexdigest()
    try:
        vm.start()
        vm.command('mkdir /simulation/key-copy-source /simulation/key-copy-target; chmod 755 /simulation/key-copy-source; mount -t tmpfs -o size=1m,mode=0700 tmpfs /simulation/key-copy-target')
        vm.command("printf 'SYNTHETIC_KEY_COPY_ONLY\\n' > /simulation/key-copy-source/host_ecdsa; chmod 755 /simulation/key-copy-source/host_ecdsa")
        put(vm,'/simulation/key-copy-only',output.read_bytes())
        first=vm.command('/simulation/key-copy-only')
        (verify/'guest-copy-success.txt').write_bytes(first)
        clean=first.replace(b'\r',b'')
        match=re.search(rb'\n(A7R5_RAM_HOSTKEY1 [^\n]+\n)',clean)
        if not match:raise ValueError('没有完整元数据回执')
        result['parsed']=policy.hostkey_receipt(match[1],run)
        refused=vm.command('/simulation/key-copy-only; key_copy_rc=$?; printf "COPY_COLLISION_EXIT:%s\\n" "$key_copy_rc"; test "$key_copy_rc" -eq 1')
        (verify/'guest-collision-refused.txt').write_bytes(refused)
        if b' stage=5 errno=17 verified=0 ' not in refused or b'COPY_COLLISION_EXIT:1' not in refused:
            raise ValueError('已有目标没有拒绝')
        verified=vm.command('/bin/busybox md5sum /simulation/key-copy-source/host_ecdsa /simulation/key-copy-target/host_ecdsa; /bin/busybox ls -l /simulation/key-copy-source/host_ecdsa /simulation/key-copy-target/host_ecdsa')
        (verify/'guest-source-target-proof.txt').write_bytes(verified)
        expected=hashlib.md5(b'SYNTHETIC_KEY_COPY_ONLY\n').hexdigest().encode()
        if verified.count(expected)!=2:raise ValueError('源或副本字节不符')
        result.update(status='passed',source_0755_to_ram_0600=True,existing_destination_refused=True,
                      source_and_destination_bytes_verified=True,source_permissions_unchanged=True,
                      copy_function_header_sha256=hashlib.sha256((WORK/'a7r5-ssh/ssh-service/private_hostkey.h').read_bytes()).hexdigest())
    except BaseException as exc:result['error']=type(exc).__name__+': '+str(exc)
    finally:
        result['cleanup']=vm.close()
        result['runtime_manifest_unchanged']=hashlib.sha256(manifest.read_bytes()).hexdigest()==before
        if result['cleanup']!={'method':'qmp-quit','exit_code':0} or not result['runtime_manifest_unchanged']:result['status']='failed'
        (verify/'guest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':raise SystemExit(main())
