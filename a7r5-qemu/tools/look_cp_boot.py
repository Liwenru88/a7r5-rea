"""从 CP 原入口观察固定候选，导出真实页表和矩阵；不伪造启动完成。"""
import argparse
import fcntl
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile
import time

from app_paths import open_vm_lock
from cp_boot_state import export_boot_state
from cp_native_probe import (research_binary,qmp_command,prepare_tomco,prepare_backup,CP_SHA)
from look_materials import load,sha,regular
from look_matrix_embed import BASE,TABLE_VA,HELPER_VA,payload
from media_candidate import extract
from native_vm import NativeVM,sandbox_profile
from runtime_manifest import LAB,verified_inputs,verified_libraries,digest


def translate(va,l1,read_l2):
    """ARM短描述符页表，只支持本原厂加载器实际产生的节和小页。"""
    if len(l1)!=0x4000 or not 0<=va<1<<32:raise ValueError('页表长度或虚拟地址不符')
    first=struct.unpack_from('<I',l1,(va>>20)*4)[0]
    if first&3==2 and not first&(1<<18):return (first&0xfff00000)+(va&0xfffff),dict(L1=first)
    if first&3==1:
        second_table=read_l2(first&0xfffffc00)
        if len(second_table)!=1024:raise ValueError('二级页表长度不符')
        second=struct.unpack_from('<I',second_table,((va>>12)&255)*4)[0]
        if second&2:return (second&0xfffff000)+(va&0xfff),dict(L1=first,L2=second)
    raise ValueError('目标虚拟地址没有本工具支持的有效映射')


def inspect_dump(vm,address,size,name):
    if type(address) is not int or type(size) is not int or address<0 or not 0<size<=0x4000 or address+size>0x8000000:
        raise ValueError('只读导出范围超出低地址 RAM')
    if Path(name).name!=name:raise ValueError('导出文件名越界')
    path=vm.out/name
    if path.exists() or path.is_symlink():raise ValueError('拒绝覆盖启动导出')
    qmp_command(vm,dict(execute='pmemsave',arguments=dict(val=address,size=size,filename=str(path))))
    raw=regular(path,0x4000)
    if len(raw)!=size:raise ValueError('启动导出长度不符')
    return raw


def observe(materials,cp_qemu,*,observe_ms=2000):
    if type(observe_ms) is not int or not 50<=observe_ms<=2000:raise ValueError('启动观察仅50～2000毫秒')
    inputs=verified_inputs();binary,model=research_binary(cp_qemu)
    files,record=load(materials) if materials is not None else ({}, {})
    vm=NativeVM('look-cp-boot');started=None
    result=dict(status='failed',full_CP_boot_verified=False,CP_service_ready_proven=False,
        ISP_pixels_verified=False,DAT_packaging_allowed=False,camera_io=False,
        observer_source_sha256=digest(Path(__file__)),
        model_binary_sha256=model['binary_sha256'],default_runtime_modified=False,
        materials=str(Path(materials).absolute()) if materials is not None else 'pinned stock CP')
    print(vm.out,flush=True)
    try:
        vm.lock=open_vm_lock();fcntl.flock(vm.lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
        vm.control=Path(tempfile.mkdtemp(prefix='a7r5-cp-layout-',dir='/private/tmp'))
        names=['cp/tomco.txt','seed-backup.bin']+([] if files else ['cp/cpapp-b.bin'])
        seed=extract(inputs['initrd'],names)
        cp=files['cpapp-b.bin'] if files else seed['cp/cpapp-b.bin']
        if not files and sha(cp)!=CP_SHA:raise ValueError('原厂基线 CP 身份不符')
        result['CP_sha256']=sha(cp)
        for name,raw in (('cpapp-b.bin',cp),('tomco.txt',prepare_tomco(seed['cp/tomco.txt'],True)),
                         ('backup.bin',prepare_backup(seed['seed-backup.bin']))):
            (vm.out/name).write_bytes(raw)
        result['simulation_configuration']='pinned TOMCO with explicit wdt_on=0; no watchdog model'
        profile=vm.out/'native.sb'
        profile.write_text(sandbox_profile(binary,vm.out/'cpapp-b.bin',vm.out/'tomco.txt',
            vm.out/'backup.bin',vm.out,vm.control,libraries=verified_libraries()))
        args=['/usr/bin/sandbox-exec','-f',str(profile),str(binary),'-machine','a7r5-cp-boot',
            '-cpu','cortex-a35,aarch64=off,has_el2=off,has_el3=off','-smp','4','-accel','tcg','-m','128M',
            '-nodefaults','-display','none','-monitor','none','-serial','stdio','-nic','none','-no-reboot',
            '-audiodev','none,id=silent','-S','-qmp',f'unix:{vm.control}/qmp.sock,server=on,wait=off',
            '-d','in_asm,int,guest_errors,unimp','-dfilter','0x108000+0x1b00000',
            '-D',str(vm.out/'instruction-trace.log')]
        for name,address in (('cpapp-b.bin',0x108000),('tomco.txt',0x100000),('backup.bin',0x4000000)):
            args+=['-device',f'loader,file={vm.out/name},addr={address:#x},force-raw=on']
        for cpu in range(4):args+=['-device',f'loader,addr=0x108000,cpu-num={cpu}']
        (vm.out/'native-command.json').write_text(json.dumps(args,indent=2)+'\n')
        vm.log=vm.console.open('wb')
        vm.process=subprocess.Popen(args,stdin=subprocess.DEVNULL,stdout=vm.log,stderr=subprocess.STDOUT,
            env=dict(PATH='/usr/bin:/bin',HOME=str(vm.control),TMPDIR=str(vm.control),LC_ALL='C'),start_new_session=True)
        (vm.out/'native-owner.json').write_text(json.dumps(dict(pid=vm.process.pid,control=str(vm.control)))+'\n')
        deadline=time.monotonic()+5
        while not (vm.control/'qmp.sock').exists():
            if vm.process.poll() is not None or time.monotonic()>deadline:raise RuntimeError('完整CP观察QMP未就绪')
            time.sleep(.01)
        qmp_command(vm,dict(execute='cont'));started=time.monotonic();reason='observation_window'
        trace=vm.out/'instruction-trace.log'
        while time.monotonic()-started<observe_ms/1000:
            if vm.process.poll() is not None:raise RuntimeError('完整CP观察提前退出')
            if trace.exists():
                with trace.open('rb') as stream:
                    stream.seek(max(0,trace.stat().st_size-65536));tail=stream.read()
                if b'[Data Abort]' in tail:reason='data_abort';break
                if trace.stat().st_size>16*1024*1024:reason='trace_budget';break
            time.sleep(.005)
        qmp_command(vm,dict(execute='stop'))
        elapsed=round((time.monotonic()-started)*1000,2)
        export_boot_state(vm,qmp_command,4)
        text=trace.read_text(errors='replace')
        first=re.search(r'with DFSR (0x[0-9a-f]+) DFAR (0x[0-9a-f]+)',text)
        prefix=inspect_dump(vm,0x108000,4096,'boot-prefix.bin')
        root=struct.unpack_from('<I',prefix,0xf1c)[0]
        mapping=dict(status='not_available',root=root)
        if root and root%0x4000==0 and root+0x4000<=0x8000000:
            l1=inspect_dump(vm,root,0x4000,'mmu-l1.bin');l2={}
            def table(address):
                if address not in l2:l2[address]=inspect_dump(vm,address,1024,f'mmu-l2-{address:08x}.bin')
                return l2[address]
            try:
                physical,descriptors=translate(TABLE_VA,l1,table)
                loaded=inspect_dump(vm,physical,2304,'matrix-after-boot.bin')
                mapping=dict(status='mapped',root=root,virtual=TABLE_VA,physical=physical,descriptors=descriptors,
                    sha256=sha(loaded),matches_embedded_payload=bool(files and loaded==payload(files['matrix-delta.bin'])))
            except ValueError as error:mapping=dict(status='not_mapped',root=root,error=str(error))
        runtime=regular(vm.out/'cp-runtime-01500000.bin',0x500000)
        word=lambda va:struct.unpack_from('<I',runtime,va-0x1500000)[0]
        result.update(status='boot_observed_not_accepted',stop_reason=reason,observation_ms=elapsed,
            first_data_abort=dict(DFSR=first[1],DFAR=first[2]) if first else None,
            configuration_group=word(0x195e9dc),cross_domain_callback=word(0x193eb08),
            bootstrap_shadow_matches_header=prefix[0xda0:0xf1c]==cp[0x20000:0x2017c],
            bootstrap_shadow_BSS=struct.unpack_from('<3I',prefix,0xda0+0x148),
            matrix_mapping=mapping,instruction_trace_sha256=digest(trace),
            original_entry_used=True,semihosting_enabled=False,guest_runtime_writes_from_host=False)
    except Exception as error:
        result['error']=str(error);raise
    finally:
        result['exit']=vm.close()
        (vm.out/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    return vm.out


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--materials',type=Path)
    p.add_argument('--cp-qemu',type=Path,required=True);p.add_argument('--observe-ms',type=int,default=2000)
    a=p.parse_args();observe(a.materials,a.cp_qemu,observe_ms=a.observe_ms)
