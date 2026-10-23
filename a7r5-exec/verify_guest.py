"""仅在无网原生QEMU中验收新工具的两种精确载荷，不初始化USB。"""
import json
import sys
import time
from pathlib import Path
import core
WORK=core.HERE.parent
sys.path[:0]=[str(WORK/'a7r5-qemu/tools'),str(WORK/'a7r5-libjit')]
from native_vm import NativeVM
from verify_guest import put
from guest_loader import build as build_loader


def verify(jit,kit,output):
    output=core.safe(output);output.mkdir(parents=True,exist_ok=False)
    harness=build_loader(output/'guest-loader')
    vm=NativeVM('quick-exec-offline',capid=True,boot_services=True)
    before=core.sha(WORK/'a7r5-qemu/runtime/manifest.json')
    report=dict(status='failed',camera_io=False,guest_nic='none',physical_devices=False,vm_evidence=str(vm.out),cases=[])
    try:
        vm.start();print('GUEST_READY',flush=True)
        vm.command('mkdir -p /tmp/jiritsu')
        # 从保留源码构建，不再依赖已删除的研究运行目录。
        put(vm,'/simulation/quick-loader',harness.read_bytes());vm.command('chmod 700 /simulation/quick-loader')
        for engine,directory in [('libjit',jit),('kit',kit)]:
            op=core.load(directory);cfg=json.loads((directory/'config.json').read_text());rid=op['run_id']
            payload=(directory/'materials/payload.so').read_bytes()
            if engine=='libjit':
                prefix='/tmp/jiritsu/a7r5-jit-'+rid
                put(vm,prefix+'.ticket',(directory/'materials/ticket.bin').read_bytes())
                put(vm,'/tmp/jiritsu/libJit.so',payload)
                command='/simulation/quick-loader /tmp/jiritsu/libJit.so'
            else:
                prefix='/tmp/jiritsu/a7r5-'+rid
                put(vm,prefix+'.so',payload)
                put(vm,'/etc/ld.so.preload',(prefix+'.so\n').encode())
                command="/bin/sh -c '/bin/date -s 070421422017.26'"
            raw=vm.command(command,timeout=40)
            state=None
            for _ in range(60):
                data=vm.command('/bin/cat '+prefix+'.state; /bin/cat '+prefix+'.output; true',timeout=10)
                if ('A7R5-'+('JIT' if engine=='libjit' else 'ROOT')+'-1 '+rid+' DONE 0 uid=0 euid=0').encode() in data:
                    state=data;break
                time.sleep(.2)
            # 串口回显会把LF转换为CRLF；仅验收比较时规范化，原始回执照存。
            normalized=b'' if state is None else state.replace(b'\r\n',b'\n').replace(b'\r',b'')
            if state is None or cfg['expected_output_begin'].encode() not in normalized or cfg['expected_output_end'].encode() not in normalized:
                raise ValueError(engine+'客体固定任务未完成')
            (output/(engine+'.txt')).write_bytes(raw+state)
            if engine=='kit':
                neutral=vm.command('/bin/busybox md5sum /etc/ld.so.preload')
                import hashlib
                if hashlib.md5(b'\n'*512).hexdigest().encode() not in neutral:raise ValueError('kit预加载未中和')
            report['cases'].append(dict(engine=engine,run_id=rid,payload_sha256=core.sha(directory/'materials/payload.so'),status='passed'))
            print('GUEST_PASSED '+engine,flush=True)
        report['status']='passed'
    except BaseException as exc:report['error']=type(exc).__name__+': '+str(exc)
    finally:
        report['cleanup']=vm.close();report['runtime_manifest_unchanged']=core.sha(WORK/'a7r5-qemu/runtime/manifest.json')==before
        if report['cleanup']!={'method':'qmp-quit','exit_code':0} or not report['runtime_manifest_unchanged']:report['status']='failed'
        core.save(output/'result.json',report)
    print(json.dumps(report,ensure_ascii=False,indent=2));return 0 if report['status']=='passed' else 1


if __name__=='__main__':
    raise SystemExit(verify(Path(sys.argv[1]).absolute(),Path(sys.argv[2]).absolute(),Path(sys.argv[3]).absolute()))
