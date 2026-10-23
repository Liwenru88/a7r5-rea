"""无NIC QEMU：真实主机操作器读写RAM、停止与有限寿命失败夹具。"""
from pathlib import Path
import hashlib
import json
import re
import shlex
import sys
import tempfile
import time
import build
sys.path[:0]=[str(build.HERE),str(build.PROJECT/'a7r5-exec/runtime'),str(build.PROJECT/'a7r5-qemu/tools')]
from operation import Operation
from transport import FileResultError
from verify_qemu import put
from native_vm import NativeVM
from runtime_manifest import verified_inputs
import vm_session


class GuestChannel:
    vm=None
    def __init__(self,driver,operation,log):
        self.operation=operation
    def read(self,path,limit):
        if path not in self.operation.reads:
            raise PermissionError('非白名单读取')
        target=shlex.quote(path)
        raw=self.vm.command('/simulation/readhex '+target,timeout=40)
        match=re.search(rb'\r?\nQREAD:([0-9a-f]*)\r?\nEND_QREAD\r?\n',raw)
        if not match:
            if b'\nQREAD_UNAVAILABLE\r\n' in raw:
                raise FileResultError(0x10000006)
            raise ValueError('QEMU读取夹具格式错误')
        data=bytes.fromhex(match[1].decode())
        if len(data)>limit:
            raise ValueError('QEMU内容超过固定读取长度')
        return data
    def put(self,path,data):
        if self.operation.writes.get(path)!=data:
            raise PermissionError('非白名单写入')
        put(self.vm,path,data)
        if path=='/tmp/jiritsu/libJit.so':
            self.vm.command('/simulation/dlopen /tmp/jiritsu/libJit.so')


def main(wait_lock=False):
    out=Path(tempfile.mkdtemp(prefix='flow-',dir=build.HERE/'verification'))
    vm_session.RUNS=out
    vm=NativeVM('libjit-ssh-flow',capid=True,boot_services=True)
    before={k:build.sha(v) for k,v in verified_inputs().items()}
    result=dict(status='failed',camera_io=False,host_tcp_connections=0,guest_nic='none',cases=[],vm=str(vm.out))
    try:
        if wait_lock:
            # 在同一进程排队取得原共享锁，再把同一已持有FD交给NativeVM；不删锁、不绕过互斥。
            import app_paths,fcntl
            owned=app_paths.open_vm_lock()
            print(json.dumps(dict(stage='waiting_shared_qemu_lock')),flush=True)
            fcntl.flock(owned,fcntl.LOCK_EX)
            original=app_paths.open_vm_lock
            app_paths.open_vm_lock=lambda:owned
            try:
                vm.start()
            finally:
                app_paths.open_vm_lock=original
            print(json.dumps(dict(stage='shared_qemu_lock_acquired')),flush=True)
        else:vm.start()
        GuestChannel.vm=vm
        vm.command('mount -t tmpfs -o mode=0755 tmpfs /etc; mount -t tmpfs -o mode=0755 tmpfs /var; mount -t tmpfs -o mode=1777 tmpfs /tmp_network; mkdir -p /etc/ssh /tmp/jiritsu /simulation /root /dev/pts; test -e /dev/ptmx || /bin/busybox mknod /dev/ptmx c 5 2')
        reference=build.SERVICE/'recovery-code85/packages/code85-recovery-20261021-02/reference'
        for path,name in [('/etc/passwd','passwd.bin'),('/etc/nsswitch.conf','nsswitch.bin'),('/etc/ssh/sshd_config','sshd-config.bin')]:
            put(vm,path,(reference/name).read_bytes())
        put(vm,'/etc/ld.so.preload',b'\n'*512)
        loader=out/'dlopen.c'
        loader.write_text('extern void *dlopen(const char *,int); extern void (*signal(int,void (*)(int)))(int); int main(int n,char **v){signal(17,(void (*)(int))1);return n!=2||!dlopen(v[1],2);}')
        build.compile_target(loader,out/'dlopen',out,extra_libraries=[build.PROJECT/'a7r5-qemu/sdk/lib/libdl-2.25.so'])
        put(vm,'/simulation/dlopen',(out/'dlopen').read_bytes(),'700')
        hexreader=out/'readhex.c'
        hexreader.write_text('''#include "ns_abi.h"
int main(int n,char **v){if(n!=2)return 64;struct stat st;if(lstat(v[1],&st)||!S_ISREG(st.st_mode)){write(1,"\\nQREAD_UNAVAILABLE\\n",19);return 0;}int f=open(v[1],O_RDONLY|O_NOFOLLOW|O_CLOEXEC);
if(f<0){write(1,"\\nQREAD_UNAVAILABLE\\n",19);return 0;}
if(fstat(f,&st)||!S_ISREG(st.st_mode))return 3;
char in[256],out[512];const char hex[]="0123456789abcdef";
write(1,"\\nQREAD:",7);for(;;){ssize_t k=read(f,in,sizeof(in));if(k<0)return 1;if(!k)break;
for(int i=0;i<k;i++){out[i*2]=hex[((unsigned char)in[i])>>4];out[i*2+1]=hex[((unsigned char)in[i])&15];}
if(write(1,out,(size_t)k*2)!=k*2)return 2;}close(f);write(1,"\\nEND_QREAD\\n",11);return 0;}''')
        build.compile_target(hexreader,out/'readhex',out)
        put(vm,'/simulation/readhex',(out/'readhex').read_bytes(),'700')
        flagprobe=out/'flags.c'
        flagprobe.write_text('''#include "ns_abi.h"
int main(void){struct stat st;if(lstat("/simulation/flag-link",&st))return 1;const long flags[]={32768,131072};for(int i=0;i<2;i++){
errno=0;int f=(int)syscall(56L,-100,"/simulation/flag-link",flags[i],0);int e=errno;
char row[128];int n=snprintf(row,sizeof(row),"RAW_NOFOLLOW flag=%ld fd=%d errno=%d\\n",flags[i],f,e);write(1,row,(size_t)n);if(f>=0){if(fstat(f,&st))return 2;close(f);}}return 0;}''')
        build.compile_target(flagprobe,out/'flags',out)
        put(vm,'/simulation/flags',(out/'flags').read_bytes(),'700')
        (out/'raw-open-flags.txt').write_bytes(vm.command('printf flag > /simulation/flag-target; /bin/busybox ln -s /simulation/flag-target /simulation/flag-link; /simulation/flags'))
        password_hash=build.credentials.make_hash('12345678')
        for case,seconds in [('actual-operation-flow',0),('explicit-ttl',2),('unknown-preload',0),('global-claim-conflict',0),('ticket-symlink',0)]:
            package=out/case;package.mkdir(mode=0o700)
            material=build.build(package/'materials',password_hash,seconds=seconds,qemu_only=True)
            cfg=json.loads((build.PROJECT/'a7r5-exec/runtime/profile.json').read_text())
            # 夹具与操作器使用真实版本和加载库，不替换这些协议对照。
            (package/'config.json').write_text(json.dumps(cfg))
            if case=='actual-operation-flow':
                for action in ['load-once','start-once','stop-once','collect-once']:
                    target=package/'.state'/action/'session';target.mkdir(parents=True)
                    op=Operation(package,action,GuestChannel)
                    report={}
                    op(None,target,lambda *a,**kw:None,report)
                    assert op.safe_to_stop and report['protocol_gate_passed']
                    (target.parent/'assessment.json').write_text(json.dumps(report,indent=2))
                    if action=='load-once':
                        vm.command('test ! -e '+material['ram_directory']+'/ready; test ! -e /tmp/jiritsu/libJit.so')
                    if action=='start-once':
                        # 记录仍存活的私有子树，停止后从原始控制台验证消失。
                        raw=vm.command('cat '+material['ram_directory']+'/ready')
                        child=int(re.search(rb' child=(\d+)',raw)[1])
                        (out/'child-fd.txt').write_bytes(vm.command('cat /proc/'+str(child)+'/task/'+str(child)+'/children'))
                    if action=='stop-once':
                        vm.command('test ! -e /proc/'+str(child)+'; test ! -e /tmp_network/a7r5-libjit-ssh.active')
                result['actual_operation_load_start_stop_collect']=True
            else:
                for destination,name in material['uploads'].items():put(vm,destination,(package/'materials'/name).read_bytes())
                if case=='unknown-preload':
                    # 空格同样未知，但不会让动态加载器尝试打开一个不存在的库。
                    put(vm,'/etc/ld.so.preload',b' \n')
                if case=='global-claim-conflict':vm.command('mkdir -m 700 /tmp_network/a7r5-libjit-ssh.active')
                if case=='ticket-symlink':
                    put(vm,material['prefix']+'.ticket-real',(package/'materials/ticket.bin').read_bytes())
                    vm.command('/bin/busybox ln -s '+material['prefix']+'.ticket-real '+material['prefix']+'.ticket')
                else:put(vm,material['prefix']+'.ticket',(package/'materials/ticket.bin').read_bytes())
                put(vm,'/tmp/jiritsu/libJit.so',(package/'materials/libJit.so').read_bytes())
                raw=vm.command('/simulation/dlopen /tmp/jiritsu/libJit.so; sleep 7; cat '+material['ram_directory']+'/result; :',timeout=15)
                (out/(case+'.txt')).write_bytes(raw)
                if case=='explicit-ttl':
                    assert b'code=0 parent_unchanged=1 child_tree_reaped=1 child_terminal_seen=1 listener_absent=1' in raw
                else:
                    vm.command('test ! -e '+material['ram_directory']+'/ready')
                    if case=='global-claim-conflict':
                        assert b'code=94' in raw
                        vm.command('test -d /tmp_network/a7r5-libjit-ssh.active; rmdir /tmp_network/a7r5-libjit-ssh.active')
                    elif case=='ticket-symlink':
                        vm.command('test -f /tmp/jiritsu/libJit.so; test ! -e '+material['prefix']+'.claim; rm /tmp/jiritsu/libJit.so')
                    else:put(vm,'/etc/ld.so.preload',b'\n'*512)
            result['cases'].append(dict(case=case,passed=True))
            print(json.dumps(dict(case=case,status='passed')),flush=True)
        result['status']='passed'
    except BaseException as exc:
        result['error']=type(exc).__name__+': '+str(exc)
        import traceback
        (out/'failure.txt').write_text(traceback.format_exc())
    finally:
        result['cleanup']=vm.close()
        result['runtime_inputs_unchanged']=before=={k:build.sha(v) for k,v in verified_inputs().items()}
        if result['cleanup']!={'method':'qmp-quit','exit_code':0} or not result['runtime_inputs_unchanged']:
            result['status']='failed'
        (out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
        print(json.dumps(dict(output=str(out),**result),ensure_ascii=False),flush=True)
    return 0 if result['status']=='passed' else 1


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description='无NIC QEMU实际操作器与失败夹具')
    parser.add_argument('--wait-lock',action='store_true',help='遵守原共享锁，在同一进程排队等待')
    args=parser.parse_args()
    raise SystemExit(main(args.wait_lock))
