"""真实Mac OpenSSH/PTTY/SCP经Unix socket和QEMU串口，无主机TCP/NIC。"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import socket
import struct
import subprocess
import sys
import tempfile
import threading
import time

import build
import credentials
import package
import verify_reference
sys.path.insert(0,str(build.LAB))
import isolation_qemu
import qemu_verify
sys.path.insert(0,str(build.LAB.parent/'a7r5-qemu/tools'))
import vm_session
from native_vm import NativeVM
from runtime_manifest import verified_inputs


def main():
    out=Path(tempfile.mkdtemp(prefix='service-qemu-',dir=build.ROOT/'verification'))
    password=credentials.load(build.ROOT/'fixed-password-input')
    manifest=package.prepare(out/'candidate',qemu_only=True)
    candidate=json.loads((out/'candidate/build.json').read_text())
    vm_session.RUNS=out;vm=NativeVM('interactive-ssh-service',capid=True,boot_services=True)
    inputs={k:build.sha(v) for k,v in verified_inputs().items()}
    result=dict(status='failed',camera_io=False,host_tcp_connections=0,guest_nic='none',candidate=candidate)
    ram=candidate['ram_directory'];install=candidate['install_directory']
    relay_build=qemu_verify.build_target(build.ROOT/'tests/framed_relay.c',out/'framed-relay')
    result['relay_build']=relay_build
    short=Path(tempfile.mkdtemp(prefix='a7r5-svc-',dir='/tmp')).resolve()
    secret=short/'password';secret.write_text(password+'\n');secret.chmod(0o600)
    askpass=short/'askpass';askpass.write_text('#!/bin/sh\nexec /bin/cat "$A7R5_PASSWORD_FILE"\n');askpass.chmod(0o700)
    try:
        vm.start()
        vm.command('mount -t tmpfs -o mode=0755 tmpfs /etc; mount -t tmpfs -o mode=0755 tmpfs /var; mount -t tmpfs -o mode=1777 tmpfs /tmp_network; mkdir -p /etc/ssh /tmp/jiritsu /simulation /root /dev/pts; test -e /dev/ptmx || /bin/busybox mknod /dev/ptmx c 5 2')
        original={'/etc/passwd':verify_reference.original_passwd()}
        fixture=build.LAB/'analysis/network-20261020-v1'
        for path in ('/etc/nsswitch.conf','/etc/ssh/sshd_config'):
            original[path]=(fixture/'original'/path.lstrip('/')).read_bytes()
        for path,data in original.items():isolation_qemu.put(vm,path,data)
        isolation_qemu.put(vm,'/etc/ld.so.preload',b'\n'*512)
        for file,target in manifest['upload_map'].items():
            isolation_qemu.put(vm,target,(out/'candidate'/file).read_bytes())
        isolation_qemu.put(vm,'/simulation/framed-relay',(out/'framed-relay').read_bytes(),'700')
        # 在客体内执行真正的root_once，覆盖32KiB soft/hard限制与后台脱离边界。
        isolation_qemu.put(vm,'/etc/ld.so.preload',(out/'candidate/preload-arm.bin').read_bytes())
        prefix='/tmp/jiritsu/a7r5-'+candidate['run_id']
        launch=vm.command('/bin/sh -c "/bin/date -s 070421422017.26"; for n in 1 2 3 4 5 6 7 8 9 10; do case "$(cat '+prefix+'.state 2>/dev/null)" in *" DONE 0 "*) break;; esac; /bin/busybox sleep 1; done; cat '+prefix+'.state '+prefix+'.output '+ram+'/ready '+ram+'/host-public-key',timeout=20)
        (out/'launch.txt').write_bytes(launch)
        if ('A7R5_PRIVATE_LAUNCH '+candidate['run_id']+' READY').encode() not in launch:raise ValueError('常驻服务未READY')
        if ('A7R5-ROOT-1 '+candidate['run_id']+' DONE 0 ').encode() not in launch:raise ValueError('一次性执行器未DONE 0')
        public=re.search(rb'ecdsa-sha2-nistp256 ([A-Za-z0-9+/=]+)',launch)
        if not public:raise ValueError('缺少可信主机公钥')
        duplicate=vm.command(install+'/ssh-service.arm64 --launch; printf "DUPLICATE_EXIT:%s\\n" "$?"; cat '+ram+'/heartbeat')
        (out/'duplicate-active-launch.txt').write_bytes(duplicate)
        if b'DUPLICATE_EXIT:68' not in duplicate or b'A7R5_PRIVATE_ALIVE' not in duplicate:raise ValueError('重复启动未拒绝或现有实例已退出')
        result['stage_installer_and_active_duplicate_rejection_verified']=True
        hosts=short/'known_hosts';hosts.write_bytes(b'a7r5-qemu ecdsa-sha2-nistp256 '+public[1]+b'\n');hosts.chmod(0o600)

        @contextmanager
        def bridge():
            offset=vm.console.stat().st_size
            vm.process.stdin.write(b"/bin/busybox stty raw -echo; /simulation/framed-relay; /bin/busybox stty sane; printf '\\nA7R5_RELAY_EXIT\\n'\n");vm.process.stdin.flush()
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                raw=vm.console.read_bytes()[offset:]
                if b'A7R5_RELAY_READY\n' in raw:break
                time.sleep(.01)
            else:raise TimeoutError('中继未READY')
            cursor=[offset+raw.index(b'A7R5_RELAY_READY\n')+17]
            path=short/'bridge.sock';server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(str(path));server.listen(1);server.settimeout(12)
            errors=[];finished=threading.Event()
            def exact(n):
                data=b'';until=time.monotonic()+25
                while len(data)<n:
                    with vm.console.open('rb') as stream:stream.seek(cursor[0]);part=stream.read(n-len(data))
                    if part:data+=part;cursor[0]+=len(part)
                    elif time.monotonic()>until:raise TimeoutError('串口帧等待超时')
                    else:time.sleep(.005)
                return data
            def serve():
                try:
                    peer,_=server.accept();peer.settimeout(25)
                    def incoming():
                        try:
                            while True:
                                raw=peer.recv(4096)
                                vm.process.stdin.write(struct.pack('<I',len(raw))+raw);vm.process.stdin.flush()
                                if not raw:return
                        except Exception as exc:
                            if not finished.is_set():errors.append(type(exc).__name__)
                    upstream=threading.Thread(target=incoming,daemon=True);upstream.start()
                    while True:
                        count=struct.unpack('<I',exact(4))[0]
                        if count>4096:raise ValueError('串口帧失步')
                        if not count:break
                        peer.sendall(exact(count))
                    finished.set();peer.close();upstream.join(2)
                except Exception as exc:errors.append(type(exc).__name__+': '+str(exc))
                finally:finished.set()
            worker=threading.Thread(target=serve,daemon=True);worker.start()
            try:yield path
            finally:
                worker.join(30);server.close();path.unlink(missing_ok=True)
                if worker.is_alive() or errors:raise RuntimeError('本机中继未正常退出：'+repr(errors))
                deadline=time.monotonic()+5
                while time.monotonic()<deadline:
                    if b'\nA7R5_RELAY_EXIT' in vm.console.read_bytes()[cursor[0]:]:break
                    time.sleep(.01)
                else:raise TimeoutError('串口未归还控制台')

        def client(program,args,stdin=None):
            with bridge() as path:
                proxy=shlex.join([str(Path(sys.executable).absolute()),str(build.ROOT/'tests/stdio_unix_proxy.py'),str(path)])
                common=['-F','/dev/null','-o','ProxyCommand='+proxy,'-o','HostKeyAlias=a7r5-qemu','-o','UserKnownHostsFile='+str(hosts),'-o','GlobalKnownHostsFile=/dev/null','-o','StrictHostKeyChecking=yes','-o','IdentityAgent=none','-o','PubkeyAuthentication=no','-o','PreferredAuthentications=password','-o','NumberOfPasswordPrompts=1','-o','ConnectTimeout=10']
                environment=os.environ|dict(SSH_ASKPASS=str(askpass),SSH_ASKPASS_REQUIRE='force',DISPLAY='offline',A7R5_PASSWORD_FILE=str(secret))
                cmd=[program,*common,*args]
                completed=subprocess.run(cmd,input=stdin,capture_output=True,timeout=40,env=environment)
                tag='client-'+str(len(list(out.glob('client-*.json'))))
                (out/(tag+'.stdout')).write_bytes(completed.stdout)
                (out/(tag+'.stderr')).write_bytes(completed.stderr)
                (out/(tag+'.json')).write_text(json.dumps(dict(program=program,exit_code=completed.returncode)))
                if completed.returncode:
                    diagnostic=vm.command('cat '+ram+'/result '+ram+'/child-result '+ram+'/diagnostic; cat /proc/mounts; ls -l /dev/ptmx /dev/pts',timeout=10)
                    (out/(tag+'.guest.txt')).write_bytes(diagnostic)
                    raise ValueError('Mac客户端退出码'+str(completed.returncode)+'，见'+tag+'的输出和客体诊断')
                return completed

        terminal=client('/usr/bin/ssh',['-tt','-p','2222','root@a7r5-qemu'],b"[ -t 0 ] && [ -t 1 ] && printf 'A7R5_PTY_COMMAND_READY\\n'; /bin/busybox cat /proc/self/status; exit 0\n")
        (out/'terminal-stdout.txt').write_bytes(terminal.stdout);(out/'terminal-stderr.txt').write_bytes(terminal.stderr)
        if b'\nA7R5_PTY_COMMAND_READY\r\n' not in terminal.stdout or not re.search(rb'Uid:\s+0\s+0\s+0\s+0',terminal.stdout):raise ValueError('真实PTY/交互root命令未通过')
        result['mac_openssh_pty_verified']=True
        vm.command('mkdir /tmp_network/a7r5-transfer-'+candidate['run_id'])
        remote='/tmp_network/a7r5-transfer-'+candidate['run_id']+'/binary transfer.bin'
        data=bytes(range(256))*256;source=short/'binary source.bin';source.write_bytes(data);download=short/'download.bin'
        uploaded=client('/usr/bin/scp',['-q','-P','2222',str(source),'root@a7r5-qemu:'+remote])
        received=client('/usr/bin/scp',['-q','-P','2222','root@a7r5-qemu:'+remote,str(download)])
        if download.read_bytes()!=data:raise ValueError('Mac默认SCP双向字节或摘要不符')
        result['mac_default_scp_sftp_verified']=dict(bytes=len(data),sha256=hashlib.sha256(data).hexdigest(),space_in_filename=True)
        result['inherited_installer_file_limit_reset_verified']=True
        # 显式管理停止常驻服务，验证无TTL分支与完整亲缘清理。
        ended=vm.command(install+'/ssh-service.arm64 --stop; cat '+ram+'/child-result; /usr/bin/openssl dgst -sha256 /etc/passwd /etc/nsswitch.conf /etc/ssh/sshd_config',timeout=25)
        (out/'stopped.txt').write_bytes(ended);clean=ended.replace(b'\r',b'')
        if not re.search(rb'code=0 parent_unchanged=1 child_tree_reaped=1 child_terminal_seen=1 listener_absent=1',clean):raise ValueError('常驻停止清理未通过')
        for raw in original.values():
            if hashlib.sha256(raw).hexdigest().encode() not in clean:raise ValueError('父视图原件变化')
        # 不接受未知的预加载；此处511换行不会要求加载其他库。
        isolation_qemu.put(vm,'/etc/ld.so.preload',b'\n'*511)
        refused=vm.command('/bin/sh '+install+'/control.sh enable-autostart ENABLE_AUTOSTART_'+candidate['run_id']+'; printf "ENABLE_EXIT:%s\\n" "$?"; test ! -e '+install+'/enabled; printf "NO_MARKER:%s\\n" "$?"')
        (out/'unknown-preload-refused.txt').write_bytes(refused)
        if b'ENABLE_EXIT:1' not in refused or b'NO_MARKER:0' not in refused:raise ValueError('未知预加载没有拒绝或写入了标记')
        isolation_qemu.put(vm,'/etc/ld.so.preload',b'\n'*512)
        trigger=out/'trigger.c';trigger.write_text('extern int puts(const char *); int main(void){puts("A7R5_BOOT_TRIGGER_RETURNED");return 0;}\n')
        qemu_verify.build_target(trigger,out/'boot-trigger')
        isolation_qemu.put(vm,'/simulation/boot-trigger',(out/'boot-trigger').read_bytes(),'700')
        enabled=vm.command('/bin/sh '+install+'/control.sh enable-autostart ENABLE_AUTOSTART_'+candidate['run_id'])
        (out/'enable.txt').write_bytes(enabled)
        if b'A7R5_AUTOSTART_ENABLED_CANDIDATE' not in enabled:raise ValueError('自启启用未完成')
        boot=vm.command('/simulation/boot-trigger; for n in 1 2 3 4 5; do if [ ! -e '+ram+'/result ] && [ -f '+ram+'/ready ]; then break; fi; /bin/busybox sleep 1; done; cat '+ram+'/ready '+ram+'/host-public-key')
        (out/'boot-hook-trigger.txt').write_bytes(boot)
        new_public=re.search(rb'ecdsa-sha2-nistp256 ([A-Za-z0-9+/=]+)',boot)
        if b'A7R5_BOOT_TRIGGER_RETURNED' not in boot or not new_public or new_public[1]!=public[1]:raise ValueError('模拟自启或稳定主机公钥未通过')
        terminal2=client('/usr/bin/ssh',['-tt','-p','2222','root@a7r5-qemu'],b"[ -t 0 ] && printf 'SECOND_PTY_READY\\n'; exit 0\n")
        if b'\nSECOND_PTY_READY\r\n' not in terminal2.stdout:raise ValueError('模拟自启后PTY未通过')
        disabled=vm.command('/bin/sh '+install+'/control.sh disable-autostart; /bin/sh '+install+'/control.sh stop; cat '+ram+'/child-result; /simulation/boot-trigger; /usr/bin/openssl dgst -sha256 /etc/ld.so.preload')
        (out/'disabled-stopped.txt').write_bytes(disabled)
        if b'A7R5_AUTOSTART_DISABLED_PRELOAD_RESTORED' not in disabled or b'code=0 parent_unchanged=1 child_tree_reaped=1 child_terminal_seen=1 listener_absent=1' not in disabled or hashlib.sha256(b'\n'*512).hexdigest().encode() not in disabled:raise ValueError('禁用恢复/清理失败')
        final=vm.command('cat '+ram+'/result; test ! -e '+install+'/enabled; printf "NO_MARKER:%s\\n" "$?"')
        (out/'disabled-trigger-final.txt').write_bytes(final)
        if b'code=0 parent_unchanged=1' not in final or b'NO_MARKER:0' not in final:raise ValueError('禁用后仍触发服务')
        result.update(unknown_preload_rejected=True,boot_hook_simulated_trigger_verified=True,stable_host_key_across_restart=True,disable_restores_exact_baseline=True,real_camera_cold_boot_verified=False)
        result.update(status='passed',operator_stop_verified=True,parent_originals_unchanged=True)
    except BaseException as exc:
        result['error']=type(exc).__name__+': '+str(exc).replace(password,'[REDACTED]')
        raise
    finally:
        result['cleanup']=vm.close()
        result['runtime_inputs_unchanged']=inputs=={k:build.sha(v) for k,v in verified_inputs().items()}
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(dict(output=str(out),status=result['status'],error=result.get('error'),cleanup=result['cleanup']),ensure_ascii=False),flush=True)


if __name__=='__main__':main()
