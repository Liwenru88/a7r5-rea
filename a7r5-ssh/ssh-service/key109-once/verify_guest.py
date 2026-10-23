"""无网卡沙箱QEMU中验证同一ELF组合；所有客体写入仅在RAM。"""
import hashlib
import json
from pathlib import Path
import re
import shlex
import sys

SOURCE=Path(__file__).resolve().parent
PACKAGE=SOURCE if (SOURCE/'config.json').exists() else SOURCE/'packages/key109-once-20261021-01'
WORK=next(parent for parent in SOURCE.parents if (parent/'a7r5-qemu/runtime/manifest.json').is_file())
sys.path[:0]=[str(PACKAGE),str(WORK/'a7r5-qemu/tools')]
import policy
from native_vm import NativeVM


def put(vm,path,data):
    vm.command('umask 077; : > '+shlex.quote(path))
    for index in range(0,len(data),48):
        encoded=''.join('\\%03o'%b for b in data[index:index+48])
        vm.command('printf '+shlex.quote(encoded)+' >> '+shlex.quote(path))


def main():
    config=json.loads((PACKAGE/'config.json').read_text())
    prefix='/tmp/jiritsu/a7r5-'+config['run_id']
    target='/tmp/jiritsu/a7r5-ssh-service-'+policy.TARGET
    result=dict(status='failed',camera_io=False,network_interface=False,ssh_started=False,
                guest_writes_ram_only=True, run_id=config['run_id'], simulated_metadata=True)
    vm=NativeVM('key109-metadata',capid=True,boot_services=True)
    result['vm_evidence']=str(vm.out)
    inputs={name:hashlib.sha256((WORK/'a7r5-qemu'/name).read_bytes()).hexdigest()
            for name in ('runtime/manifest.json',)}
    try:
        vm.start()
        # 原镜像从未挂载写入；/etc挂载仅在本次客体内存。
        vm.command('mount -t tmpfs -o mode=0755 tmpfs /etc; mkdir -p '+target+'; chmod 755 '+target)
        vm.command("printf 'SYNTHETIC_KEY_METADATA_ONLY\\n' > "+target+'/host_ecdsa; chmod 644 '+target+'/host_ecdsa')
        before=vm.command('/bin/busybox md5sum '+target+'/host_ecdsa')
        (PACKAGE/'verification/guest-key-before.txt').write_bytes(before)
        for suffix,name in [('.probe','probe.arm64'),('.so','root.arm64.so')]:
            data=(PACKAGE/'materials'/name).read_bytes()
            put(vm,prefix+suffix,data)
            got=vm.command('/usr/bin/openssl dgst -sha256 '+prefix+suffix)
            if hashlib.sha256(data).hexdigest().encode() not in got:
                raise ValueError('客体材料传输摘要不符')
        put(vm,'/etc/ld.so.preload',(prefix+'.so\n').encode())
        vm.command("/bin/sh -c '/bin/date -s 070421422017.26'")
        observed=vm.command('sleep 1; cat '+prefix+'.state; cat '+prefix+'.output')
        (PACKAGE/'verification/guest-transcript.txt').write_bytes(observed)
        clean=observed.replace(b'\r',b'')
        start=clean.index(f'KEY109_BEGIN1 run={policy.TARGET}\n'.encode())
        endmark=f'KEY109_END1 run={policy.TARGET} samples=2 key_content_read=0 key_writes=0 ssh_started=0\n'.encode()
        end=clean.index(endmark,start)+len(endmark)
        raw=clean[start:end]
        parsed=policy.parse_output(raw)
        if parsed['metadata']['private']['reject_mask'] != 8:
            raise ValueError('合成644权限未产生旧109拒绝位8')
        match=re.search(rb'A7R5-ROOT-1 '+config['run_id'].encode()+rb' DONE 0 uid=0 euid=0 bytes=(\d+)\n',clean)
        if not match or int(match[1]) != len(raw):
            raise ValueError('目标架构root终态不符')
        after=vm.command('/bin/busybox md5sum '+target+'/host_ecdsa; /bin/busybox md5sum /etc/ld.so.preload')
        (PACKAGE/'verification/guest-key-and-neutral-after.txt').write_bytes(after)
        if hashlib.md5(b'SYNTHETIC_KEY_METADATA_ONLY\n').hexdigest().encode() not in before or hashlib.md5(b'SYNTHETIC_KEY_METADATA_ONLY\n').hexdigest().encode() not in after:
            raise ValueError('合成密钥字节发生变化')
        if hashlib.md5(policy.NEUTRAL).hexdigest().encode() not in after:
            raise ValueError('客体预加载未中和')
        (PACKAGE/'verification/guest-probe-output.bin').write_bytes(raw)
        result.update(status='passed', parsed=parsed, root_done_zero=True, exact_output_size=True,
                      target_preload_neutral=True, synthetic_key_bytes_unchanged=True,
                      payload_sha256={name:hashlib.sha256((PACKAGE/'materials'/name).read_bytes()).hexdigest()
                                      for name in ('probe.arm64','root.arm64.so')})
    except BaseException as exc:
        result['error']=type(exc).__name__+': '+str(exc)
    finally:
        result['cleanup']=vm.close()
        result['runtime_manifest_unchanged']=all(hashlib.sha256((WORK/'a7r5-qemu'/name).read_bytes()).hexdigest()==digest for name,digest in inputs.items())
        if not result['runtime_manifest_unchanged'] or result['cleanup']['method']!='qmp-quit': result['status']='failed'
        (PACKAGE/'verification/guest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0 if result['status']=='passed' else 1


if __name__=='__main__': raise SystemExit(main())
