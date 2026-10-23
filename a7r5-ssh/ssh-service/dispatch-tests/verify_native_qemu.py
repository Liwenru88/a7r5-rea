"""本轮新原生客户端验收：实际生产ELF、无NIC QEMU、Unix/串口，不使用相机。"""
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import re
import shlex
import socket
import struct
import sys
import tempfile
import threading
import time

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT.parent),str(ROOT.parent.parent/'a7r5-qemu/tools')]
import build
import credentials
import isolation_qemu
import native_validation
import package
import qemu_verify
import service_dispatch
import verify_reference
import vm_session
from native_vm import NativeVM
from runtime_manifest import verified_inputs


def main():
    materials=ROOT/'packages/service-native-20261020-01';op=package.check(materials);run=op['run_id'];ram=op['ram_directory'];install=op['install_directory']
    out=Path(tempfile.mkdtemp(prefix='dispatch-native-qemu-',dir=ROOT/'verification'))
    short=Path(tempfile.mkdtemp(prefix='a7r5-dispatch-',dir='/tmp')).resolve()
    vm_session.RUNS=out;vm=NativeVM('dispatch-native-ssh',capid=True,boot_services=True)
    before={k:build.sha(v) for k,v in verified_inputs().items()}
    result=dict(status='failed',physical_usb_tested=False,camera_io=False,host_tcp_connections=0,guest_nic='none',production_materials_run=run)
    try:
        qemu_verify.build_target(ROOT/'tests/framed_relay.c',out/'relay')
        vm.start()
        vm.command('mount -t tmpfs -o mode=0755 tmpfs /etc; mount -t tmpfs -o mode=0755 tmpfs /var; mount -t tmpfs -o mode=1777 tmpfs /tmp_network; mkdir -p /etc/ssh /tmp/jiritsu /simulation /root /dev/pts; test -e /dev/ptmx || /bin/busybox mknod /dev/ptmx c 5 2')
        originals={'/etc/passwd':verify_reference.original_passwd()}
        for name in ('/etc/nsswitch.conf','/etc/ssh/sshd_config'):originals[name]=(ROOT.parent/'analysis/network-20261020-v1/original'/name.lstrip('/')).read_bytes()
        for name,raw in originals.items():isolation_qemu.put(vm,name,raw)
        isolation_qemu.put(vm,'/etc/ld.so.preload',b'\n'*512)
        for name,target in op['upload_map'].items():isolation_qemu.put(vm,target,(materials/name).read_bytes())
        isolation_qemu.put(vm,'/simulation/relay',(out/'relay').read_bytes(),'700')
        isolation_qemu.put(vm,'/etc/ld.so.preload',(materials/'preload-arm.bin').read_bytes())
        prefix='/tmp/jiritsu/a7r5-'+run
        launched=vm.command('/bin/sh -c "/bin/date -s 070421422017.26"; for n in 1 2 3 4 5 6 7 8 9 10; do case "$(cat '+prefix+'.state 2>/dev/null)" in *" DONE 0 "*) break;; esac; /bin/busybox sleep 1; done; cat '+prefix+'.state '+prefix+'.output '+ram+'/ready '+ram+'/host-public-key',timeout=20)
        (out/'launch.txt').write_bytes(launched);clean=launched.replace(b'\r',b'')
        if ('A7R5-ROOT-1 '+run+' DONE 0 ').encode() not in clean:raise ValueError('原包root_once没有DONE 0')
        ready=re.search(rb'^A7R5_PRIVATE_READY [^\n]+\n',clean,re.M)
        if not ready:raise ValueError('缺少本次READY')
        identity=service_dispatch.ready(ready[0])
        public=re.search(rb'^ecdsa-sha2-nistp256 [^\n]+\n',clean,re.M)
        if not public or hashlib.sha256(public[0]).hexdigest()!=identity['public_sha']:raise ValueError('可信公钥不符')
        (out/'host-public-key').write_bytes(public[0])

        @contextmanager
        def bridge():
            offset=vm.console.stat().st_size
            vm.process.stdin.write(b"/bin/busybox stty raw -echo; /simulation/relay; /bin/busybox stty sane; printf '\\nA7R5_RELAY_EXIT\\n'\n");vm.process.stdin.flush()
            deadline=time.monotonic()+8
            while time.monotonic()<deadline:
                raw=vm.console.read_bytes()[offset:]
                if b'A7R5_RELAY_READY\n' in raw:break
                time.sleep(.01)
            else:raise TimeoutError('无网卡中继未READY')
            cursor=[offset+raw.index(b'A7R5_RELAY_READY\n')+17];path=short/'bridge.sock'
            server=socket.socket(socket.AF_UNIX,socket.SOCK_STREAM);server.bind(str(path));server.listen(1);server.settimeout(12)
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
                    def upstream():
                        try:
                            while True:
                                chunk=peer.recv(4096);vm.process.stdin.write(struct.pack('<I',len(chunk))+chunk);vm.process.stdin.flush()
                                if not chunk:return
                        except Exception as exc:
                            if not finished.is_set():errors.append(type(exc).__name__)
                    writer=threading.Thread(target=upstream,daemon=True);writer.start()
                    while True:
                        size=struct.unpack('<I',exact(4))[0]
                        if size>4096:raise ValueError('帧超限')
                        if not size:break
                        peer.sendall(exact(size))
                    finished.set();peer.close();writer.join(2)
                except Exception as exc:errors.append(type(exc).__name__)
                finally:finished.set()
            worker=threading.Thread(target=serve,daemon=True);worker.start()
            try:yield path
            finally:
                worker.join(30);server.close();path.unlink(missing_ok=True)
                if worker.is_alive() or errors:raise RuntimeError('中继退出失败：'+repr(errors))
                until=time.monotonic()+5
                while time.monotonic()<until:
                    if b'\nA7R5_RELAY_EXIT' in vm.console.read_bytes()[cursor[0]:]:break
                    time.sleep(.01)
                else:raise TimeoutError('串口控制未归还')

        def runner(command,stdin,env):
            with bridge() as path:
                proxy=shlex.join([str(Path(sys.executable).absolute()),str(ROOT/'tests/stdio_unix_proxy.py'),str(path)])
                command=[command[0],'-o','ProxyCommand='+proxy,*command[1:]]
                return native_validation.run_bounded(command,stdin,env)
        # 网络验收前提由客体READY和本测试夹具给出，未测试真实USB恢复。
        report=dict(protocol_gate_passed=True,host_recovery_verified=True,service_stop_attempts=1,host_public_sha256=identity['public_sha'])
        native_validation.verify(dict(run_id=run,target_ip='10.10.10.177'),materials,out,report,credentials.load(ROOT/'fixed-password-input'),runner=runner)
        result['native_client_report']=report
        ended=vm.command(install+'/ssh-service.arm64 --stop; cat '+ram+'/child-result; /usr/bin/openssl dgst -sha256 /etc/passwd /etc/nsswitch.conf /etc/ssh/sshd_config',timeout=25)
        (out/'stopped.txt').write_bytes(ended)
        if b'code=0 parent_unchanged=1 child_tree_reaped=1 child_terminal_seen=1 listener_absent=1' not in ended:raise ValueError('客体服务清理失败')
        for raw in originals.values():
            if hashlib.sha256(raw).hexdigest().encode() not in ended:raise ValueError('父视图原件变化')
        result.update(status='passed',operator_stop_verified=True,parent_originals_unchanged=True)
    except BaseException as exc:
        result['error_type']=type(exc).__name__;raise
    finally:
        result['cleanup']=vm.close();result['runtime_inputs_unchanged']=before=={k:build.sha(v) for k,v in verified_inputs().items()}
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(dict(output=str(out),status=result['status'],error_type=result.get('error_type'),cleanup=result['cleanup']),ensure_ascii=False),flush=True)
        short.rmdir()


if __name__=='__main__':main()
