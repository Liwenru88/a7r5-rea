"""只在已验证、断网且无物理设备的QEMU中加载新库；不访问USB。"""
import hashlib
import json
from pathlib import Path
import shlex
import struct
import subprocess
import sys

from build import HERE, CLANG, LLD, save, digest


def cpio_entry(name,raw,mode,inode):
    name=name.encode()+b'\0'
    fields=[inode,mode,0,0,1,0,len(raw),0,0,0,0,len(name),0]
    header=b'070701'+b''.join(f'{v:08x}'.encode()for v in fields)
    value=header+name;value+=bytes(-len(value)%4);value+=raw;value+=bytes(-len(raw)%4)
    return value


def overlay_archive(source,target,files):
    raw=source.read_bytes();at=0
    while True:
        if raw[at:at+6] not in (b'070701',b'070702'):raise ValueError('不是已知newc归档')
        fields=[int(raw[at+6+8*i:at+14+8*i],16)for i in range(13)]
        size,namesize=fields[6],fields[11];name=raw[at+110:at+110+namesize].rstrip(b'\0')
        data=(at+110+namesize+3)&~3;end=(data+size+3)&~3
        if name==b'TRAILER!!!':break
        at=end
    suffix=bytearray()
    # 不替换原归档任何文件，只在其TRAILER前加入隔离测试目录。
    for index,(name,content,mode)in enumerate(files):suffix.extend(cpio_entry(name,content,mode,2000000+index))
    suffix.extend(cpio_entry('TRAILER!!!',b'',0,2099999))
    value=raw[:at]+bytes(suffix);value+=bytes(-len(value)%512)
    target.write_bytes(value)


def dtb_resize(raw,size):
    result=bytearray(raw);header=struct.unpack_from('>10I',raw)
    offset,names_at=header[2],header[3];stack=[];changed=0
    while offset<header[2]+header[9]:
        token=struct.unpack_from('>I',raw,offset)[0];offset+=4
        if token==1:
            end=raw.index(b'\0',offset);stack.append(raw[offset:end].decode());offset=(end+4)&~3
        elif token==2:stack.pop()
        elif token==3:
            count,nameoffset=struct.unpack_from('>II',raw,offset);offset+=8
            end=raw.index(b'\0',names_at+nameoffset);name=raw[names_at+nameoffset:end].decode()
            if '/'.join(stack)=='/chosen' and name=='linux,initrd-end':
                result[offset:offset+count]=(0x440000000+size).to_bytes(count,'big');changed+=1
            offset=(offset+count+3)&~3
        elif token==4:continue
        elif token==9:break
        else:raise ValueError('未知DTB token')
    if changed!=1:raise ValueError('DTB initrd-end字段不唯一')
    return bytes(result)


def verify(qemu_root,production,fixture,source,output):
    qemu_root=Path(qemu_root).resolve();output.mkdir(mode=0o700)
    sys.path.insert(0,str(qemu_root/'tools'))
    from native_vm import NativeVM
    from runtime_manifest import verified_inputs
    inputs=verified_inputs()
    sdk=qemu_root/'sdk/lib'
    loader=output/'loader'
    command=[str(CLANG),'--target=aarch64-linux-gnu','--ld-path='+str(LLD),'-nostdlib','-ffreestanding','-fno-stack-protector',
        '-O2','-fPIE','-pie','-Wl,-e,_start','-Wl,--dynamic-linker,/lib/ld-linux-aarch64.so.1','-Wl,-z,max-page-size=65536',
        str(HERE/'tests/guest-loader-start.S'),str(HERE/'tests/guest-loader.c'),str(sdk/'libc-2.25.so'),str(sdk/'libdl-2.25.so'),'-o',str(loader)]
    result=subprocess.run(command,capture_output=True,text=True,timeout=30)
    save(output/'loader-build.json',dict(argv=command,returncode=result.returncode,stderr=result.stderr))
    if result.returncode:raise ValueError('加载夹具构建失败')
    cfgs=[json.loads((p/'config.json').read_text())for p in (production,fixture)]
    files=[('simulation/trust-probe',b'',0o40700),('simulation/trust-probe/loader',loader.read_bytes(),0o100700),
        ('simulation/trust-probe/preload',bytes.fromhex(cfgs[0]['expected_preload_hex']),0o100600)]
    for label,package,cfg in zip(('production','fixture'),(production,fixture),cfgs):
        files += [('simulation/trust-probe/'+label+'.so',(package/'materials/libJit.so').read_bytes(),0o100600),
            ('simulation/trust-probe/'+label+'.ticket',(package/'materials/ticket.bin').read_bytes(),0o100600)]
    files += [('simulation/trust-'+cfgs[1]['run_id'],b'',0o40700),
        ('simulation/trust-'+cfgs[1]['run_id']+'/disk.img',source.read_bytes(),0o100600)]
    archive=output/'probe.cpio';overlay_archive(inputs['initrd'],archive,files)
    dtb=output/'probe.dtb';dtb.write_bytes(dtb_resize(inputs['dtb'].read_bytes(),archive.stat().st_size))
    class ProbeVM(NativeVM):
        def runtime_inputs(self):
            value=verified_inputs();value['initrd']=archive;value['dtb']=dtb;return value
    vm=ProbeVM('updater-trust-offline',capid=True,boot_services=True)
    before=digest(qemu_root/'runtime/manifest.json')
    report=dict(status='failed',camera_IO=False,physical_devices=False,guest_nic='none',vm_evidence=str(vm.out),cases=[])
    try:
        vm.start();print('QEMU_ROOT_READY',flush=True)
        vm.command('mkdir -p /tmp/jiritsu /tmp_wbshd; mount -t tmpfs tmpfs /tmp_wbshd; cp /simulation/trust-probe/preload /etc/ld.so.preload')
        # 生产库先试普通文件。仅此隔离VM内创建该同名文件，绝不在主机/dev写入。
        fixture_target='/simulation/trust-'+cfgs[1]['run_id']+'/disk.img'
        vm.command('test ! -e /dev/cnflasha1 && cp '+shlex.quote(fixture_target)+' /dev/cnflasha1')
        for label,package,cfg in zip(('production','fixture'),(production,fixture),cfgs):
            prefix='/tmp/jiritsu/a7r5-jit-'+cfg['run_id']
            vm.command('cp /simulation/trust-probe/'+label+'.ticket '+prefix+'.ticket; cp /simulation/trust-probe/'+label+'.so /tmp/jiritsu/libJit.so')
            raw=vm.command('/simulation/trust-probe/loader /tmp/jiritsu/libJit.so; cat '+prefix+'.state; cat '+prefix+'.output; true',timeout=150)
            (output/(label+'.txt')).write_bytes(raw)
            normalized=raw.replace(b'\r\n',b'\n').replace(b'\r',b'')
            if b'LOADER_RETURNED' not in normalized or b'WORKER_REAPED' not in normalized:raise ValueError('构造返回或工作进程未收敛')
            state=('A7R5-JIT-1 '+cfg['run_id']+' '+('FAILED 42 ' if label=='production' else 'DONE 0 ')).encode()
            if state not in normalized:raise ValueError(label+'状态不符')
            if label=='fixture':
                output_proof=('A7R5_TRUST_COMPLETE '+cfg['candidate_sha256']+' sectors=258 bytes=132096 reopened=1').encode()
                if output_proof not in normalized:raise ValueError('夹具未完成原生提交和重开回读')
                proof=vm.command('/bin/busybox md5sum '+fixture_target+' '+cfg['readback_path']+' /dev/cnflasha1; cat '+cfg['journal_path'],timeout=30)
                (output/'fixture-full-proof.txt').write_bytes(proof)
                candidate_md5=hashlib.md5((package/'materials/candidate.logical.img').read_bytes()).hexdigest().encode()
                original_md5=hashlib.md5(source.read_bytes()).hexdigest().encode()
                if proof.count(candidate_md5)!=2 or original_md5 not in proof:raise ValueError('完整目标／重开副本或生产拒绝前像不符')
            report['cases'].append(dict(label=label,payload_sha256=digest(package/'materials/libJit.so'),status='passed',
                result='普通文件被生产库拒绝，随后原像保持' if label=='production' else '实际AArch64库固定258扇区提交与重开完整回读通过'))
            print('QEMU_'+label.upper()+'_PASSED',flush=True)
        report['status']='passed'
    except BaseException as error:report['error']=type(error).__name__+': '+str(error)
    finally:
        report['cleanup']=vm.close();report['runtime_manifest_unchanged']=digest(qemu_root/'runtime/manifest.json')==before
        if report['cleanup']!={'method':'qmp-quit','exit_code':0} or not report['runtime_manifest_unchanged']:report['status']='failed'
        save(output/'result.json',report)
    return report
