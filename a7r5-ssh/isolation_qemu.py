#!/usr/bin/env python3
"""仅QEMU RAM验证命名空间，不启动SSH，不修改模拟器源材料。"""
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys
import tempfile

import isolation as ns
import lab


def put(vm,path,raw,mode='600'):
    quoted=shlex.quote(path);vm.command('umask 077; : > '+quoted)
    # 沿用已有目标终端验证过的短行长度，避免BusyBox行编辑器截断引号。
    for offset in range(0,len(raw),48):
        octal=''.join('\\%03o'%value for value in raw[offset:offset+48])
        vm.command('printf '+shlex.quote(octal)+' >> '+quoted)
    vm.command('/bin/busybox chmod '+mode+' '+quoted)


def main():
    sys.path.insert(0,str(lab.ROOT.parent/'a7r5-qemu/tools'))
    import vm_session
    from native_vm import NativeVM
    from runtime_manifest import verified_inputs
    inputs=verified_inputs();before={k:lab.digest(v) for k,v in inputs.items()}
    output=Path(tempfile.mkdtemp(prefix='namespace-qemu-',dir=lab.ROOT/'verification'))
    operation=ns.prepare(output/'target-material')
    abi_source=output/'abi-check.c'
    abi_source.write_text('''#include "ns_abi.h"
extern int symlink(const char *,const char *);
int main(int argc,char **argv){(void)argc;(void)argv;struct stat s;
int d=open("/tmp_network",O_RDONLY|O_DIRECTORY|O_NOFOLLOW);if(d<0||fstat(d,&s)||!S_ISDIR(s.st_mode)||s.st_uid)return 1;close(d);
int f=open("/tmp_network/abi-proof-file",O_WRONLY|O_CREAT|O_EXCL|O_NOFOLLOW,0600);if(f<0)return 2;close(f);
if(symlink("/tmp_network/abi-proof-file","/tmp_network/abi-proof-link")||lstat("/tmp_network/abi-proof-link",&s)||S_ISREG(s.st_mode))return 3;
int link=open("/tmp_network/abi-proof-link",O_RDONLY|O_NOFOLLOW);int e=errno;if(link>=0){close(link);return 4;}if(e!=40)return 5;
return write(1,"A7R5_ABI_DIRECTORY_STAT_NOFOLLOW_OK\\n",35)==35?0:6;}
''')
    abi_build=ns.compile_target(abi_source,output/'abi-check',lab.ROOT/'src')
    vm_session.RUNS=output
    vm=NativeVM('namespace',capid=True,boot_services=True)
    receipt=dict(camera_io=False,real_sshd_started=False,host_network=False,guest_nic='none',
                 source_sha256=lab.sources(),input_sha256=before,run_id=operation['run_id'],
                 status='failed',qemu_scope='RAM夹具，账户字段未变；不是实机STOP或Wi-Fi证明')
    p=ns.paths(operation['run_id'])
    try:
        vm.start()
        vm.command('mount -t tmpfs -o mode=0755 tmpfs /etc; mount -t tmpfs -o mode=0755 tmpfs /var; mount -t tmpfs -o mode=1777 tmpfs /tmp_network; mkdir -p /tmp/jiritsu')
        # 为全新RAM视图提供固定非登录账户夹具；启动器仅原字节复制，不修改字段。
        fixture=b'root:*:0:0:root:/root:/bin/false\nsshd:*:77:77:sshd:/var/run/sshd:/bin/false\n'
        put(vm,'/etc/passwd',fixture)
        put(vm,'/tmp/jiritsu/abi-check',(output/'abi-check').read_bytes(),'700')
        abi=vm.command('/tmp/jiritsu/abi-check')
        if b'A7R5_ABI_DIRECTORY_STAT_NOFOLLOW_OK' not in abi:raise ValueError('AArch64目录/stat/NOFOLLOW行为不符')
        receipt['abi_regression']=dict(passed=True,build=abi_build)
        (output/'abi-result.txt').write_bytes(abi)
        put(vm,p['helper'],(output/'target-material/ns-probe.arm64').read_bytes(),'700')
        put(vm,p['payload'],(output/'target-material/isolation.arm64.so').read_bytes())
        initial=vm.command('cat /proc/self/mountinfo; ls -ldn /tmp_network /var; /usr/bin/openssl dgst -sha256 /etc/passwd '+p['helper']+' '+p['payload'])
        (output/'initial.txt').write_bytes(initial)
        (output/'namespace-links.txt').write_bytes(vm.command('ls -ln /proc/self/ns; :'))
        if lab.digest(output/'target-material/ns-probe.arm64').encode() not in initial:
            raise ValueError('串口上传的启动器摘要不符，拒绝执行')
        if lab.digest(output/'target-material/isolation.arm64.so').encode() not in initial:
            raise ValueError('串口上传的固定执行器摘要不符，拒绝执行')
        put(vm,'/etc/ld.so.preload',(p['payload']+'\n').encode())
        vm.command("/bin/sh -c '/bin/date -s 070421422017.26'")
        poll_script=('n=0; finished=0; while [ "$n" -lt 30 ]; do if [ -r '+p['state']+' ]; then '
            's=$(/bin/busybox cat '+p['state']+'); case "$s" in *" DONE "*|*" FAILED "*|*" TIMEOUT "*) '
            'finished=1; break;; esac; fi; /bin/busybox sleep 1; n=$((n+1)); done; '
            '/bin/busybox cat '+p['state']+' '+p['output']+'; [ "$finished" = 1 ]')
        launched=vm.command(poll_script,timeout=40)
        (output/'launch.txt').write_bytes(launched)
        if ('A7R5-ROOT-1 '+operation['run_id']+' DONE 0 uid=0 euid=0 bytes=').encode() not in launched:
            raise RuntimeError('固定执行器未取得DONE0')
        neutral=vm.command('/usr/bin/openssl dgst -sha256 /etc/ld.so.preload')
        if hashlib.sha256(b'\n'*512).hexdigest().encode() not in neutral:
            raise ValueError('预加载中和未通过')
        receipt['fixed_root_payload_done_zero']=True;receipt['preload_neutral_verified']=True
        if b'outcome=READY' in launched:
            receipt['isolation_ready']=True
            ready=vm.command('cat '+p['ready']+'; cat '+p['heartbeat'])
            (output/'ready.txt').write_bytes(ready)
            # 不模拟或发送相机STOP；验证完整75秒生命周期与原视图不变。
            result=vm.command('sleep 80; cat '+p['result']+'; printf "TRACE_BEGIN\\n"; cat '+p['trace']+'; printf "TRACE_END\\n"; /usr/bin/openssl dgst -sha256 /etc/passwd; test ! -e /var/a7r5-ns-proof-'+operation['run_id'],timeout=95)
        elif b'outcome=NEGATIVE_CLEAN' in launched:
            receipt['isolation_ready']=False
            result=vm.command('cat '+p['result']+'; printf "TRACE_BEGIN\\n"; cat '+p['trace']+'; printf "TRACE_END\\n"; /usr/bin/openssl dgst -sha256 /etc/passwd')
        else:raise RuntimeError('启动器没有完整READY或已清理负结果')
        (output/'final.txt').write_bytes(result)
        clean=result.replace(b'\r',b'')
        begin=clean.index(('A7R5_NS_RESULT '+operation['run_id']+'\n').encode())
        end=clean.index(('END '+operation['run_id']+'\n').encode(),begin)+len('END '+operation['run_id']+'\n')
        parsed=ns.fields(clean[begin:end],operation['run_id'],'terminal')
        trace=clean[clean.index(b'TRACE_BEGIN\n',end)+len(b'TRACE_BEGIN\n'):clean.index(b'TRACE_END\n',end)]
        # 串口将换行转换为CRLF；去CR后按原始Linux文本摘要验收。
        if len(trace)!=parsed['trace_bytes'] or hashlib.sha256(trace).hexdigest()!=parsed['trace_sha256']:
            raise ValueError('客体RAM轨迹长度或摘要不符')
        if hashlib.sha256(fixture).hexdigest().encode() not in clean[end:]:raise ValueError('父视图账户摘要变化')
        receipt.update(status='passed',guest_result=parsed,trace_verified=True,parent_fixture_unchanged=True,
                       capability_result='available' if parsed['code']==0 else 'negative_clean',
                       real_device_stop_tested=False,real_device_wifi_tested=False)
    except BaseException as exc:
        receipt['error']=type(exc).__name__+': '+str(exc)
        try:
            (output/'guest-diagnostic.txt').write_bytes(vm.command('ls -ldn /var /tmp_network '+p['ram']+'; cat '+p['result']+'; :',timeout=5))
        except Exception as diagnostic_error:receipt['diagnostic_error']=str(diagnostic_error)
        raise
    finally:
        receipt['cleanup']=vm.close()
        receipt['runtime_inputs_unchanged']={k:lab.digest(v) for k,v in verified_inputs().items()}==before
        receipt['console_sha256']=lab.digest(vm.console)
        lab.save(output/'result.json',receipt)
        print(json.dumps(dict(output=str(output),status=receipt['status'],
                              capability_result=receipt.get('capability_result'),error=receipt.get('error'),
                              cleanup=receipt['cleanup']),ensure_ascii=False,indent=2))


if __name__=='__main__':main()
