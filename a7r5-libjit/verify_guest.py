"""断网无物理设备 QEMU：实际 AArch64 加载、立即 dlclose 和任务失败路径。"""
from pathlib import Path
import hashlib
import json
import shlex
import subprocess
import sys
from build import HERE,WORK,CLANG,LLD,compile_payload,sha,save
from guest_loader import build as build_loader

sys.path.insert(0,str(WORK/'a7r5-qemu/tools'))
from native_vm import NativeVM

def put(vm,path,raw):
    vm.command('umask 077; : > '+shlex.quote(path))
    # 原厂BusyBox未包含base64，串口行缓冲也不能容纳大块八进制文本。
    for offset in range(0,len(raw),128):
        row=''.join('\\%03o'%b for b in raw[offset:offset+128])
        vm.command('printf '+shlex.quote(row)+' >> '+shlex.quote(path))
    proof=vm.command('/bin/busybox md5sum '+shlex.quote(path))
    if hashlib.md5(raw).hexdigest().encode() not in proof:raise ValueError('QEMU传输摘要不符')

def main():
    directory=HERE/'verification'/('guest' if len(sys.argv)<3 else sys.argv[2])
    directory.mkdir(parents=True,exist_ok=False)
    package=Path(sys.argv[1]).absolute()
    config=json.loads((package/'config.json').read_text())
    manifest_package=json.loads((package/'operation.json').read_text())
    if sha(package/'materials/libJit.so')!=manifest_package['payload']['sha256']:raise ValueError('先核对完整包再启动虚拟器')
    loader=build_loader(directory/'guest-loader')
    vm=NativeVM('libjit-offline',capid=True,boot_services=True)
    manifest=WORK/'a7r5-qemu/runtime/manifest.json';before=sha(manifest)
    result=dict(status='failed',camera_io=False,physical_devices=False,guest_nic='none',vm_evidence=str(vm.out),cases=[])
    try:
        vm.start();print('GUEST_ROOT_READY',flush=True)
        vm.command('mkdir -p /simulation/libjit /tmp/jiritsu; ulimit -n 4096')
        put(vm,'/simulation/libjit/loader',loader.read_bytes());vm.command('chmod 700 /simulation/libjit/loader')
        print('LOADER_TRANSFERRED',flush=True)
        # 精确生产库与本次固定脚本；只在模拟器RAM写入同名路径。
        run=config['run_id'];prefix='/tmp/jiritsu/a7r5-jit-'+run
        put(vm,prefix+'.ticket',(package/'materials/ticket.bin').read_bytes())
        put(vm,'/tmp/jiritsu/libJit.so',(package/'materials/libJit.so').read_bytes())
        proof=vm.command('/simulation/libjit/loader /tmp/jiritsu/libJit.so; cat '+prefix+'.state; cat '+prefix+'.output; test ! -e /tmp/jiritsu/libJit.so; test ! -e '+prefix+'.ticket',timeout=35)
        (directory/'production.txt').write_bytes(proof)
        expected=('A7R5-JIT-1 '+run+' DONE 0 uid=0 euid=0').encode()
        if expected not in proof or b'LOADER_RETURNED' not in proof or b'WORKER_REAPED' not in proof or b'A7R5_LIBJIT_INFO_END' not in proof:raise ValueError('精确生产库未完成固定任务')
        result['exact_production_payload_passed']=True;print('EXACT_PRODUCTION_PASSED',flush=True)
        cases=[('nonzero','echo output; echo error >&2; exit 42','DONE 42',None),
               ('timeout','/bin/sleep 20','TIMEOUT 93',None),
               ('overflow','while :; do echo abcdefghijklmnopqrstuvwxyz; done','FAILED 95',None),
               ('background','/bin/sleep 2 & echo parent-exit','FAILED 94',None),
               ('foreign-output','echo SHOULD_NOT_RUN','FAILED 86','output'),
               ('claim','echo SHOULD_NOT_RUN','FAILED 99','claim'),
               ('state-publication','echo SHOULD_NOT_RUN','NO_TERMINAL','state.new'),
               ('bad-ticket','echo SHOULD_NOT_RUN','NO_TERMINAL','ticket')]
        for i,(name,script,expected,fault) in enumerate(cases):
            root='/simulation/libjit/case-'+str(i);rid=f'{i+1:032x}';pref=root+'/a7r5-jit-'+rid
            proof=compile_payload(directory/name,rid,script,1,root)
            vm.command('mkdir '+root)
            ticket=('A7R5_LIBJIT '+rid+'\n').encode()
            put(vm,pref+'.ticket',b'foreign\n' if fault=='ticket' else ticket)
            if fault and fault!='ticket':put(vm,pref+'.'+fault,b'FOREIGN_EVIDENCE\n')
            put(vm,root+'/libJit.so',(directory/name/'libJit.so').read_bytes())
            out=vm.command('/simulation/libjit/loader '+root+'/libJit.so; /bin/busybox cat '+pref+'.state 2>/dev/null; /bin/busybox cat '+pref+'.output 2>/dev/null; true',timeout=20)
            (directory/(name+'.txt')).write_bytes(out)
            if expected=='NO_TERMINAL':
                if ('A7R5-JIT-1 '+rid+' DONE').encode() in out or b'SHOULD_NOT_RUN\n' in out:raise ValueError('无效票据/发布失败仍执行了任务')
            elif ('A7R5-JIT-1 '+rid+' '+expected).encode() not in out:raise ValueError('机内失败路径不符：'+name)
            if fault and fault!='ticket':
                keep=vm.command('cat '+pref+'.'+fault)
                if b'FOREIGN_EVIDENCE' not in keep:raise ValueError('覆盖了已有夹具证据')
            if name=='background':vm.command('sleep 3')
            result['cases'].append(dict(name=name,status='passed',expected=expected,payload_sha256=proof['sha256']))
            print('GUEST_CASE_PASSED '+name,flush=True)
        result['status']='passed'
    except BaseException as exc:result['error']=type(exc).__name__+': '+str(exc)
    finally:
        result['cleanup']=vm.close();result['runtime_manifest_unchanged']=sha(manifest)==before
        if result['cleanup']!={'method':'qmp-quit','exit_code':0} or not result['runtime_manifest_unchanged']:result['status']='failed'
        save(directory/'result.json',result)
    print(json.dumps(result,ensure_ascii=False,indent=2));return 0 if result['status']=='passed' else 1

if __name__=='__main__':raise SystemExit(main())
