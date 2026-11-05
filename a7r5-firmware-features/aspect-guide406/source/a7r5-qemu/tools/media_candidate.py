"""独立研究候选：仅增加固定模拟材料，不切换默认清单。"""
import hashlib
import json
from pathlib import Path
import re
import struct
import subprocess
import tempfile

from cpio_inputs import entries
from native_vm import NativeVM, dtb_properties
from runtime_manifest import LAB, digest, verified_inputs
from virtual_fat import make_fixture

ADDITIONS = ('simulation/media-config.so', 'simulation/fsys-file-test', 'simulation/media-template.fat',
             'simulation/media-regs', 'simulation/media-readmem')


def extract(source, wanted):
    result={}
    with source.open('rb') as stream:
        while True:
            h=stream.read(110)
            if len(h)!=110 or h[:6]!=b'070701':raise ValueError('归档头不符')
            v=[int(h[6+i*8:14+i*8],16) for i in range(13)]
            name=stream.read(v[11])[:-1].decode().removeprefix('./');stream.read((-110-v[11])%4)
            data=stream.read(v[6]);stream.read((-v[6])%4)
            if len(data)!=v[6]:raise ValueError('归档截断')
            if name in wanted:result[name]=data
            if name=='TRAILER!!!':break
    if result.keys()!=set(wanted):raise ValueError('缺少原厂链接库')
    return result


def entry(name,data,mode=0o100755):
    name=name.encode()+b'\0';v=[0,mode,0,0,1,0,len(data),0,0,0,0,len(name),0]
    return b'070701'+b''.join(f'{x:08x}'.encode() for x in v)+name+bytes((-110-len(name))%4)+data+bytes((-len(data))%4)


def add_files(source, target, additions):
    with source.open('rb') as reader,target.open('xb') as writer:
        while True:
            h=reader.read(110)
            if len(h)!=110 or h[:6]!=b'070701':raise ValueError('归档头不符')
            v=[int(h[6+i*8:14+i*8],16) for i in range(13)]
            name=reader.read(v[11]);pad=reader.read((-110-v[11])%4)
            data=reader.read(v[6]);tail=reader.read((-v[6])%4)
            if name[:-1]==b'TRAILER!!!':
                for key,value in additions.items():writer.write(entry(key,value))
                writer.write(h+name+pad+data+tail);break
            writer.write(h+name+pad+data+tail)
        writer.write(bytes((-writer.tell())%512))


def compare(base,candidate):
    before,after=entries(base),entries(candidate)
    if set(after)-set(before)!=set(ADDITIONS):raise ValueError('候选新增路径不符')
    if any(after.get(name)!=record for name,record in before.items()):raise ValueError('原归档条目发生变化')
    return {'original_entries':len(before),'all_original_entries_identical':True,'added':list(ADDITIONS)}


def patch_property(raw,path,key,value):
    """只调整一个 DTB 属性，保留其他节点、属性及保留表。"""
    raw=bytearray(raw);v=list(struct.unpack_from('>10I',raw));off=v[2];end=off+v[9];names=raw[v[3]:v[3]+v[8]];stack=[]
    while off<end:
        token=struct.unpack_from('>I',raw,off)[0];off+=4
        if token==1:
            stop=raw.index(0,off,end);stack.append(raw[off:stop].decode());off=(stop+4)&~3
        elif token==2:stack.pop()
        elif token==3:
            count,nameoff=struct.unpack_from('>II',raw,off);name=bytes(names[nameoff:names.index(0,nameoff)]).decode()
            if ('/'.join(stack),name)==(path,key):
                oldlen=(count+3)&~3;replacement=value+bytes((-len(value))%4);delta=len(replacement)-oldlen
                struct.pack_into('>I',raw,off,len(value));raw[off+8:off+8+oldlen]=replacement
                v[1]+=delta;v[3]+=delta;v[9]+=delta;struct.pack_into('>10I',raw,0,*v)
                return bytes(raw)
            off+=8+((count+3)&~3)
        elif token==4:continue
        elif token==9:break
        else:raise ValueError('DTB token 不符')
    raise ValueError('DTB 属性不存在')


def build():
    inputs=verified_inputs();out=Path(tempfile.mkdtemp(prefix='media-',dir=LAB/'build'))
    libs=['libInfraFsys.so','libInfraMediaCommon.so','libMWF.so','libbackup.so','libosal_uipc.so','libosal_utm.so']
    library_data=extract(inputs['initrd'],['usr/lib/'+n for n in libs])
    for name,data in library_data.items():(out/Path(name).name).write_bytes(data)
    clang='/opt/homebrew/opt/llvm/bin/clang';lld='/opt/homebrew/opt/lld/bin/ld.lld'
    common=[clang,'--target=aarch64-linux-gnu','--ld-path='+lld,'-nostdlib','-O2','-mno-outline-atomics','-Wl,--no-undefined']
    glibc=[str(LAB/'sdk/lib'/n) for n in ('libc-2.25.so','libdl-2.25.so','libpthread-2.25.so','ld-2.25.so')]
    config=out/'media-config.so';test=out/'fsys-file-test'
    commands=[common+['-shared','-fPIC',str(LAB/'source/guest/file-media-config.c'),str(LAB/'source/guest/virtual-media-rm.c'),*glibc,'-o',str(config)]]
    # 独立测试没有 SDK 头文件；只移除标准 include，并注入明确的 AArch64 ABI 声明。
    original=(LAB/'source/guest/fsys-file-test.c').read_text()
    (out/'fsys-test.c').write_text(re.sub(r'^#include[^\n]*\n','',original,flags=re.M))
    commands.append(common+['-include',str(LAB/'source/guest/media-test-abi.h'),'-Wl,-e,_start',
        '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',str(out/'fsys-test.c'),'-Wl,--no-as-needed',
        *[str(out/n) for n in libs],'-Wl,--allow-shlib-undefined',*glibc,'-o',str(test)])
    for name in ('regs','readmem'):
        commands.append(common+['-Wl,-e,_start','-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',
            str(LAB/f'source/guest/menu-{name}.c'),*glibc,'-o',str(out/f'media-{name}')])
    for command in commands:subprocess.run(command,check=True)
    additions=dict(zip(ADDITIONS,(config.read_bytes(),test.read_bytes(),make_fixture(photos=True),
                                  (out/'media-regs').read_bytes(),(out/'media-readmem').read_bytes())))
    candidate=out/'media.cpio';add_files(inputs['initrd'],candidate,additions)
    comparison=compare(inputs['initrd'],candidate)
    raw=inputs['dtb'].read_bytes();props=dtb_properties(raw)
    cmdline=props[('/chosen','bootargs')].rstrip(b'\0')
    # 该区域在现有预留区之外，位于 initrd 地址之前，仅供固定 4 MiB 导出。
    extra=b'memrsv=0x00400000@0x41e600000:uc memrsv=0x00004000@0x41ea00000:uc'
    for match in re.finditer(rb'memrsv=(0x[0-9a-fA-F]+)@(0x[0-9a-fA-F]+)',cmdline):
        size,start=(int(x,16) for x in match.groups())
        if start<0x41ea04000 and start+size>0x41e600000:raise ValueError('导出区域与既有预留区重叠')
    cmdline=re.sub(rb'ramdisk_size=\d+',b'ramdisk_size='+str((candidate.stat().st_size+1023)//1024).encode(),cmdline)
    raw=patch_property(raw,'/chosen','bootargs',cmdline+b' '+extra+b' a7r5.media_test=1\0')
    raw=patch_property(raw,'/chosen','linux,initrd-end',(0x440000000+candidate.stat().st_size).to_bytes(len(props[('/chosen','linux,initrd-end')]),'big'))
    dtb=out/'media.dtb';dtb.write_bytes(raw)
    record={'schema':1,'base_initrd_sha256':digest(inputs['initrd']),'base_dtb_sha256':digest(inputs['dtb']),
        'candidate':{name:{'bytes':p.stat().st_size,'sha256':digest(p)} for name,p in [('media.cpio',candidate),('media.dtb',dtb)]},
        'comparison':comparison,'commands':commands,'sources':{n:digest(LAB/'source/guest'/n) for n in ('file-media-config.c','virtual-media-rm.c','cp-request-capture.inc','dataflow-pin-service.inc','dataflow-pin-definitions.inc','fsys-file-test.c','media-test-abi.h','menu-regs.c','menu-readmem.c')},
        'original_link_libraries':{n:hashlib.sha256(d).hexdigest() for n,d in library_data.items()}}
    (out/'receipt.json').write_text(json.dumps(record,indent=2)+'\n')
    return out


class MediaVM(NativeVM):
    def __init__(self,candidate):
        super().__init__('media',capid=True,boot_services=True);self.candidate=Path(candidate).absolute()

    def prime_native_menu(self):
        """研究按键独立运行，阻塞时保留串口用于只读取样；绝不追加后续按键。"""
        from menu_live import key_command
        if getattr(self,'native_primed',False):raise RuntimeError('拒绝重复执行研究初始化')
        self.wait_native_screen(0x2d6)
        steps=[];record=self.out/'native-initialization.json'
        try:
            for index,(key,expected) in enumerate((('MENU',0x355),('MENU',0x2d6),('MENU',0x1e9),('ENTER',0),('MENU',0x2d6))):
                before=self.last_native_screen();status=f'/tmp/media-prime-{index}.status'
                NativeVM.command(self,f'({key_command(key)}; key_rc=$?; echo "$key_rc" > {status}) > /tmp/media-prime-{index}.log 2>&1 & echo MEDIA_PRIME_STARTED',timeout=30)
                steps.append({'key':key,'before':before,'expected':expected,'state':'submitted'})
                self.wait_native_screen(expected)
                # 只有状态文件证明注入程序已结束后才可发下一键；等待有界。
                data=NativeVM.command(self,f'for attempt in 1 2 3; do [ -f {status} ] && break; sleep 1; done; if [ -f {status} ]; then echo MEDIA_PRIME_RC=$(cat {status}); else echo MEDIA_PRIME_PENDING; fi',timeout=15)
                if not re.search(rb'^MEDIA_PRIME_RC=0\r?$',data,re.M):raise RuntimeError('研究初始化按键未正常结束，停止后续按键')
                steps[-1].update(after=self.last_native_screen(),state='completed')
                record.write_text(json.dumps({'status':'in-progress','steps':steps},indent=2)+'\n')
        except Exception as error:
            record.write_text(json.dumps({'status':'stopped','steps':steps,'error':str(error)},indent=2)+'\n')
            raise
        self.native_primed=True
        record.write_text(json.dumps({'status':'ready','steps':steps,'settings_persistence':'guest RAM only'},indent=2)+'\n')

    def runtime_inputs(self):
        inputs=verified_inputs();root=self.candidate
        if root.parent!=LAB/'build' or root.is_symlink():raise ValueError('候选目录越界')
        if (root/'receipt.json').is_symlink():raise ValueError('候选收据含符号链接')
        receipt=json.loads((root/'receipt.json').read_text())
        if receipt['base_initrd_sha256']!=digest(inputs['initrd']) or receipt['base_dtb_sha256']!=digest(inputs['dtb']):
            raise ValueError('候选基线已经变化')
        for name in ('media.cpio','media.dtb'):
            p=root/name;r=receipt['candidate'][name]
            if p.is_symlink() or p.stat().st_size!=r['bytes'] or digest(p)!=r['sha256']:raise ValueError('候选摘要不符')
        compare(inputs['initrd'],root/'media.cpio')
        inputs.update(initrd=root/'media.cpio',dtb=root/'media.dtb')
        return inputs


if __name__=='__main__':print(build())
