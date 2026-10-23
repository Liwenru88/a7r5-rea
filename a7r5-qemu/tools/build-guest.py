"""本机 LLVM 交叉编译 AArch64 菜单载荷，只替换客体中的一个模拟库。"""
import hashlib,json,os,re,struct,subprocess,sys
from pathlib import Path
LAB=Path(__file__).resolve().parents[1]
NATIVE=LAB;SRC=LAB/'build/guest-source';ASSETS=LAB/'runtime'
SOURCE=LAB/'source/guest'
sys.path.insert(0,str(LAB/'tools'))
from native_vm import dtb_properties,digest


def replace_cpio(source,target,replacements):
    changed=[]
    with source.open('rb') as reader,target.open('xb') as writer:
        while True:
            header=reader.read(110)
            if len(header)!=110 or header[:6]!=b'070701':raise ValueError('newc header 不符')
            fields=[int(header[6+i*8:14+i*8],16) for i in range(13)]
            name=reader.read(fields[11]);pad=reader.read((-110-fields[11])%4)
            data=reader.read(fields[6]);tail=reader.read((-fields[6])%4)
            path=name[:-1].decode().removeprefix('./')
            if path in replacements:
                data=replacements[path];fields[6]=len(data)
                header=b'070701'+b''.join(f'{x:08x}'.encode() for x in fields)
                tail=bytes((-len(data))%4);changed.append(path)
            writer.write(header+name+pad+data+tail)
            if path=='TRAILER!!!':break
        writer.write(bytes((-writer.tell())%512))
    if set(changed)!=set(replacements):raise ValueError('客体文件匹配不全')
    return changed


def main():
    SRC.mkdir(parents=True,exist_ok=True)
    import fcntl
    from app_paths import open_vm_lock
    lock=open_vm_lock()
    fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    from runtime_manifest import verified_inputs,update_manifest
    accepted=verified_inputs()
    basegui=(SOURCE/'a7r5-gui.inc').read_text()
    gui='static unsigned int a7r5_native_pending,a7r5_native_seen_menu,a7r5_native_key_down;\nstatic void a7r5_native_reentry_poll(void);\n'+basegui
    needle='    record("A7R5_MENU_INIT_RETURN ","original rep_menu_controller init completed");'
    assert needle in gui;gui=gui.replace(needle,'    __atomic_store_n(&a7r5_native_seen_menu,1,__ATOMIC_RELEASE);\n'+needle)
    needle='    return r;\n}\nstatic void a7r5_open_screen'
    assert needle in gui;gui=gui.replace(needle,'    a7r5_native_reentry_poll();\n    return r;\n}\nstatic void a7r5_open_screen')
    marker='    record("A7R5_GUI_PROBES ",'
    assert marker in gui
    gui=gui.replace(marker,'    a7r5_native_install_boot_exit(base);\n'+marker)
    (SRC/'a7r5-gui.inc').write_text(gui)
    observer=(SOURCE/'menu-observe-a7r5-baseline.c').read_text()
    observer='static void a7r5_native_install_boot_exit(unsigned long);\nstatic int a7r5_native_key_received(unsigned int,void *);\nstatic void a7r5_native_reentry_poll(void);\n'+observer
    observer=observer.replace('#include "a7r5-gui.inc"','#include "a7r5-gui.inc"\n#include "native-menu-reentry.inc"')
    needle='    int result = real_rcv_msg_tmo(id, message, timeout);'
    assert observer.count(needle)==1
    observer=observer.replace(needle,'''    int result;
    for (;;) {
        result=real_rcv_msg_tmo(id,message,timeout);
        if (result || !message || !*message || !a7r5_native_key_received(id,*message))break;
        real_free_msg(id,*message);*message=0;
    }''')
    (SRC/'menu-observe-native.c').write_text(observer)
    llvm=Path('/opt/homebrew/opt/llvm/bin')
    compiler=llvm/'clang';linker=Path('/opt/homebrew/opt/lld/bin/ld.lld')
    if not compiler.is_file() or not linker.is_file():raise RuntimeError('缺少本机 LLVM clang/lld，请安装 llvm 和 lld')
    so=LAB/'build/menu-observe.so'
    command=[str(compiler),'--target=aarch64-linux-gnu','--ld-path='+str(linker),'-nostdlib','-O2',
        '-mno-outline-atomics','-Wl,--no-undefined','-I',str(SRC),'-I',str(SOURCE),
        '-shared','-fPIC','-Wl,-soname,menu-observe-a7r5-baseline.so',str(SRC/'menu-observe-native.c')]
    command += [str(SOURCE/s) for s in ['capid-service.c','sa-address-service.c','hdmi-format-service.c','dmm-service.c',
                 'gpe-raster.c','gpe-sprite.c','sony-lz77.c','headless-osd-a7r5.c','a7r5-services.c']]
    command += [str(LAB/'sdk/lib'/s) for s in ['libc-2.25.so','libdl-2.25.so','libpthread-2.25.so','ld-2.25.so']]
    command += ['-o',str(so)]
    subprocess.run(command,check=True)
    import struct
    elf=so.read_bytes()
    if elf[:6]!=b'\x7fELF\x02\x01' or struct.unpack_from('<H',elf,18)[0]!=183:raise ValueError('载荷不是 AArch64 ELF')
    original=accepted['initrd']
    import tempfile
    work=Path(tempfile.mkdtemp(prefix='guest-',dir=LAB/'build'))
    output=work/'menu.cpio'
    changed=replace_cpio(original,output,{'simulation/menu-observe-a7r5-baseline.so':so.read_bytes()})
    from cpio_inputs import only_observer_changed
    comparison=only_observer_changed(original,output)
    raw=bytearray(accepted['dtb'].read_bytes());props=dtb_properties(raw)
    old=props[('/chosen','linux,initrd-end')];new=(0x440000000+output.stat().st_size).to_bytes(len(old),'big')
    assert raw.count(old)==1;raw=raw.replace(old,new)
    bootargs=props[('/chosen','bootargs')];newargs=re.sub(rb'ramdisk_size=\d+',('ramdisk_size='+str((output.stat().st_size+1023)//1024)).encode(),bootargs)
    assert len(bootargs)==len(newargs) and raw.count(bootargs)==1;raw=raw.replace(bootargs,newargs)
    # 内容寻址产物先全部落盘，再原子切换清单；中断不破坏上次可运行输入。
    target=ASSETS/('menu-'+digest(output)[:16]+'.cpio')
    if target.exists():
        assert digest(target)==digest(output);output.unlink()
    else:output.replace(target)
    dtb=ASSETS/('virt-'+__import__('hashlib').sha256(raw).hexdigest()[:16]+'.dtb')
    if dtb.exists():assert dtb.read_bytes()==raw
    else:dtb.write_bytes(raw)
    update_manifest({'initrd':target,'dtb':dtb})
    result={'compiler':subprocess.check_output([str(compiler),'--version'],text=True).splitlines()[0],
        'command':command,'elf_machine':'AArch64','base_initrd_sha256':digest(original),
        'initrd':str(target.relative_to(LAB)),'initrd_sha256':digest(target),
        'observer_sha256':digest(so),'changed_guest_files':changed,'dtb_sha256':digest(dtb),
        'cpio_comparison':comparison}
    (LAB/'build/guest-build-receipt.json').write_text(json.dumps(result,indent=2)+'\n')
    work.rmdir()
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
