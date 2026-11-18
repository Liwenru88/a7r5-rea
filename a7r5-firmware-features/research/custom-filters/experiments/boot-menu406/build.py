"""构建自然启动的软件客体；冻结输入，不运行CP或连接设备。"""
from pathlib import Path
import argparse
import hashlib
import io
import json
import re
import subprocess
import struct
import sys

ROOT = Path(__file__).resolve().parents[4]
LAB = ROOT / 'a7r5-qemu'
BASE = ROOT / '.local/incident409-20261101'
sys.path[:0] = [str(LAB / 'tools')]
from media_candidate import entry, patch_property
from native_vm import dtb_properties
from cpio_inputs import entries
from elftools.elf.elffile import ELFFile


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--loader', type=Path, default=ROOT / '.local/fixed-custom-filters/loader-recovery-library')
    parser.add_argument('--software-peer', action='store_true')
    parser.add_argument('--software-storage', action='store_true')
    parser.add_argument('--chinese', action='store_true')
    parser.add_argument('--restore-records', type=Path)
    parser.add_argument('--prepared-record', type=Path)
    args = parser.parse_args()
    assert not args.software_storage or args.software_peer
    assert not args.restore_records or args.software_storage
    assert not args.prepared_record or args.software_storage
    out = args.output.absolute()
    assert out.is_relative_to(ROOT / '.local/fixed-custom-filters') and not out.exists()
    previous = LAB / 'build/aspect-guide406-20261026-01/guest-11'
    source = previous / 'menu.cpio'
    assert sha(source) == '15089fc1b0a65dc7a198a2b11d9a56f6f55c746400e5cdc0122a9b878a768a53'
    loader = args.loader.absolute()
    report = json.loads((loader / 'verification.json').read_text())
    ap = BASE / 'candidate409/components/usr/lib/appFw.so'
    assert sha(ap) == report['ap_candidate_sha256']
    out.mkdir(parents=True)
    replacements = {'usr/lib/appFw.so': ap.read_bytes(),
                    'usr/lib/libaf_bootstrap406.so': (loader / 'libaf_bootstrap406.so').read_bytes()}
    assert hashlib.sha256(replacements['usr/lib/libaf_bootstrap406.so']).hexdigest() == report['bootstrap']['sha256']
    if args.software_storage:
        loader_source = ROOT / 'a7r5-firmware-features/custom-filters/experiments/packaging406/loader/af_bootstrap406.c'
        code = loader_source.read_text()
        anchor = 'static int native_media_select(void *context,uint32_t slot){'
        assert code.count(anchor) == 1
        code = code.replace(anchor, '#include "qemu-storage.inc"\n' + anchor)
        anchor = 'int af_bootstrap406_bind_native_media(unsigned slot){'
        assert code.count(anchor) == 1
        code = code.replace(anchor, anchor + '\n return af_qemu_media_bind(slot); /* 实验库专用目录端口，产品库没有此分支。 */')
        (out/'bootstrap-qemu.c').write_text(code)
        (out/'qemu-storage.inc').write_bytes(Path(__file__).with_name('qemu-storage.inc').read_bytes())
        command = json.loads((loader/'compile.json').read_text())['argv']
        command = [str(out/'bootstrap-qemu.c') if v==str(loader_source) else v for v in command]
        command[1:1] = ['-I'+str(out)]
        command[-1] = str(out/'libaf_bootstrap-qemu.so')
        result = subprocess.run(command,capture_output=True,text=True)
        (out/'bootstrap-qemu-compile.json').write_text(json.dumps(dict(argv=command,exit_code=result.returncode,stderr=result.stderr),indent=2))
        assert result.returncode==0,result.stderr
        replacements['usr/lib/libaf_bootstrap406.so'] = (out/'libaf_bootstrap-qemu.so').read_bytes()
        # 普通RAM块设备上的16MiB FAT16；不是机身分区镜像或物理SD。
        fat=bytearray(16*1024*1024);fat[:3]=b'\xeb\x3c\x90';fat[3:11]=b'A7QEMU  '
        struct.pack_into('<HBHBHHBHHHII',fat,11,512,1,1,2,512,len(fat)//512,0xf8,128,32,64,0,0)
        struct.pack_into('<BBBI',fat,36,0x80,0,0x29,0xAF510001);fat[43:54]=b'AF QEMU    ';fat[54:62]=b'FAT16   ';fat[510:512]=b'\x55\xaa'
        for offset in (512,129*512):struct.pack_into('<HH',fat,offset,0xfff8,0xffff)
        replacements['simulation/af-body.fat']=bytes(fat)
        cube=b'LUT_3D_SIZE 2\n'+''.join(f'{r} {g} {b}\n' for b in range(2) for g in range(2) for r in range(2)).encode()
        replacements['simulation/sd0-01_照片基准.cube']=cube
        # AFD1纯参数文件也由生产导入器严格解码；不是预置槽位或成功回执。
        name='电脑参数示例'.encode();document=bytearray(256+len(name));document[:8]=b'AFD1\x01\x00\x00\x01'
        struct.pack_into('<I',document,16,len(name));struct.pack_into('<I',document,236,1)
        preset=bytes([0,0])+struct.pack('8b',1,2,0,0,0,4,3,1)+bytes(64)
        document[88:162]=preset;document[162:236]=preset;document[256:]=name
        replacements['simulation/sd0-02_电脑参数.a7filter']=bytes(document)
        replacements['simulation/sd1-03_第二卡.cube']=cube
        if args.prepared_record:
            from store_records import validate
            p=args.prepared_record.absolute()
            assert p.is_relative_to(ROOT/'.local/fixed-custom-filters') and p.is_file() and not p.is_symlink()
            data=p.read_bytes();info=validate(p.name,data)
            assert info['saved']['kind']==1 and info['converter'] in (2,3)
            # 复用实际导出的完整AFD1原字节，去掉仓库记录头即为独立配方文件。
            replacements['simulation/sd0-04_完整配方.a7filter']=data[32:]
        native = ROOT/'a7r5-firmware-features/custom-filters/native'
        export_source=Path(__file__).with_name('store-export.c')
        export_command=['/opt/homebrew/opt/llvm/bin/clang','--target=aarch64-linux-gnu','--ld-path=/opt/homebrew/opt/lld/bin/ld.lld',
            '-nostdlib','-O2','-mno-outline-atomics','-DAF_TARGET_GLIBC225','-I'+str(native),'-Wl,-e,_start',
            '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1',str(export_source),
            *[str(native/n) for n in ('af_document.c','af_record.c','af_slots.c','af_sha256.c')],
            str(LAB/'sdk/lib/libc-2.25.so'),str(LAB/'sdk/lib/ld-2.25.so'),'-o',str(out/'af-store-export')]
        compiled=subprocess.run(export_command,capture_output=True,text=True)
        (out/'export-compile.json').write_text(json.dumps(dict(argv=export_command,exit_code=compiled.returncode,stderr=compiled.stderr),indent=2))
        assert compiled.returncode==0,compiled.stderr
        replacements['simulation/af-store-export']=(out/'af-store-export').read_bytes()
        if args.restore_records:
            from store_records import validate
            restore=args.restore_records.absolute();assert restore.is_relative_to(ROOT/'.local/fixed-custom-filters')
            records=json.loads((restore/'records.json').read_text());assert records['status']=='PASS_READONLY_STORE_EXPORT'
            for name,expected in records['files'].items():
                assert re.fullmatch(r'STORE\.ID|C(?:0[1-9]|1[0-9]|20)_[AB]\.rec',name)
                p=restore/name;assert p.is_file() and not p.is_symlink()
                data=p.read_bytes();assert validate(name,data)==expected
                replacements['simulation/restore-'+name]=data
    if args.chinese:
        from media_candidate import extract
        fonts=['tmp/images/MYingHeiC-GB18030-SJ_wIcon.ltt','tmp/images/MYingHeiC-Big5-SJ_wIcon.ltt','tmp/images/Sony_DI_Icons.ttf']
        for name,data in extract(source,fonts).items():replacements['simulation/'+Path(name).name]=data
    if args.software_peer:
        native = ROOT / 'a7r5-firmware-features/custom-filters/native'
        old_source = previous / 'menu-observe-native.c'
        observer = old_source.read_text()
        if args.chinese:
            (out/'chinese-ui.inc').write_bytes(Path(__file__).with_name('chinese-ui.inc').read_bytes())
            observer='static void qemu_chinese_apply(void);\n'+observer
            observer=observer.replace('#include "a7r5-gui.inc"','#include "chinese-ui.inc"\n#include "a7r5-gui.inc"')
            anchor='    if (symbol && same_name(name, "Application_System_Init")) {'
            assert observer.count(anchor)==1
            observer=observer.replace(anchor,anchor+'\n        qemu_chinese_prepare(symbol);')
            anchor='    if (!ui_thread_id) ui_thread_id = (unsigned int)syscall(178);   /* remember the UI thread */'
            assert observer.count(anchor)==1
            observer=observer.replace(anchor,anchor+'\n    qemu_chinese_apply();')
            gui=(previous/'a7r5-gui.inc').read_text();anchor='    ui_thread_id = (unsigned int)syscall(178);'
            assert gui.count(anchor)==1
            (out/'a7r5-gui.inc').write_text(gui.replace(anchor,anchor+'\n    qemu_chinese_apply();'))
        anchor = 'int osal_rcv_msg_tmo(unsigned int id, void **message, long timeout) {'
        assert observer.count(anchor) == 1
        observer = observer.replace(anchor, '#include "software-peer.inc"\n' + anchor + '\n    if(af_qemu_peer_enabled() && af_qemu_peer_take(id,message))return 0;')
        for anchor, body in [
            ('int osal_valloc_msg_wait(unsigned int id, void **message, unsigned int size, unsigned int count) {',
             '\n    if(af_qemu_peer_enabled() && id==0x90030001u && size==128 && count==0)return af_qemu_peer_allocate(message,size,count);'),
            ('int osal_snd_msg(unsigned int id, void *message) {',
             '\n    if(af_qemu_peer_enabled() && id==0x90030001u && message==af_qemu_peer_message)return af_qemu_peer_send(message);'),
            ('int osal_free_msg(unsigned int id, void *message) {',
             '\n    if(af_qemu_peer_enabled() && af_qemu_peer_free(message))return 0;')]:
            assert observer.count(anchor) == 1
            observer = observer.replace(anchor, anchor + body)
        (out / 'observer.c').write_text(observer)
        peer = Path(__file__).with_name('software-peer.inc')
        (out / 'software-peer.inc').write_bytes(peer.read_bytes())
        argv = json.loads((previous / 'build-receipt.json').read_text())['commands'][0]
        argv = [str(out / 'observer.c') if v == str(old_source) else v for v in argv]
        argv[-1] = str(out / 'menu-observe-peer.so')
        argv[1:1] = ['-I'+str(out), '-I'+str(native), '-DAF_RECIPE_BRIDGE406', '-DAF_FACTORY_RESTORE406', '-DAF_SNAPSHOT_OVERLAY406']
        argv += [str(native / n) for n in ('af_handshake.c', 'af_apply_wire.c', 'af_slots.c', 'af_recipe_transport.c','af_joint_asset.c','af_joint.c','af_sha256.c')]
        compiled = subprocess.run(argv, capture_output=True, text=True)
        (out / 'peer-compile.json').write_text(json.dumps(dict(argv=argv, exit_code=compiled.returncode, stderr=compiled.stderr), indent=2))
        assert compiled.returncode == 0, compiled.stderr
        replacements['simulation/menu-observe-a7r5-baseline.so'] = (out / 'menu-observe-peer.so').read_bytes()
    for field, name in [('ui', 'libaf_ui406.so'), ('requests', 'libaf_requests406.so'), ('repository', 'libaf_repository_media.so')]:
        p = Path(report[field]['path'])
        assert sha(p) == report[field]['sha256']
        replacements['usr/lib/' + name] = p.read_bytes()
    for row in report['assets']:
        if '/share/app/' not in row['path']:
            continue
        p = loader / ('components' + row['path'])
        assert sha(p) == row['sha256']
        replacements[row['path'].lstrip('/')] = p.read_bytes()
    elf = ELFFile(io.BytesIO(replacements['usr/lib/libaf_bootstrap406.so']))
    symbols = {s.name: s for s in elf.get_section_by_name('.symtab').iter_symbols()}
    selected = ['last_status', 'ctor_attempted', 'observer_installed', 'natural_registration',
                'attempted', 'registered', 'installed', 'prepared', 'admission_ready', 'ui', 'requests',
                'startup_phase', 'startup_result', 'hook_changed', 'startup_changed', 'native_media_result', 'reference_import_result']
    table = ',\n'.join('{"%s",%d,%d}' % (n, symbols[n]['st_value'], symbols[n]['st_size']) for n in selected)
    header = (loader / 'af_bootstrap_manifest.h').read_text()
    checks = re.search(r'boot_checks\[\]=\{(.*?)\};', header).group(1)
    code = r'''
typedef unsigned long size_t;
extern int printf(const char *,...),snprintf(char *,size_t,const char *,...),sscanf(const char *,const char *,...);
extern void *fopen(const char *,const char *);
extern char *fgets(char *,int,void *),*strstr(const char *,const char *);
extern int fclose(void *),open(const char *,int,...),close(int);
extern long read(int,void *,size_t),lseek(int,long,int);
extern unsigned long strtoul(const char *,char **,int);
extern int __libc_start_main(int (*)(int,char **),int,char **,void (*)(void),void (*)(void),void (*)(void),void *);
__asm__(".global _start\n.type _start,%function\n_start:\nmov x0,sp\nbl entry\nbrk #0\n");
static const struct {const char *name;unsigned long offset,bytes;} items[]={TABLE};
static const struct {unsigned int at,before;} checks[]={CHECK_TABLE};
static int run(int argc,char **argv){
 if(argc!=2)return 2;
 char *end;unsigned long pid=strtoul(argv[1],&end,10);if(*end || !pid)return 2;
 char path[96],line[512];snprintf(path,sizeof(path),"/proc/%lu/maps",pid);
 void *f=fopen(path,"r");if(!f)return 3;
 unsigned long base=0,apbase=0;int single_rx=0;
 while(fgets(line,sizeof(line),f)){
  unsigned long lo,hi,off;char mode[5];
  if(sscanf(line,"%lx-%lx %4s %lx",&lo,&hi,mode,&off)!=4)continue;
  if(strstr(line,"/usr/lib/libaf_bootstrap406.so") && off==0)base=lo;
  if(strstr(line,"/usr/lib/appFw.so")){
   if(off==0)apbase=lo;
   if(apbase && lo<=apbase+0x16d9740 && apbase+0x3554ed8<=hi && mode[0]=='r' && mode[1]=='-' && mode[2]=='x')single_rx=1;
   printf("AF_AP_MAP %s",line);
  }
 }
 if(fclose(f) || !base)return 4;
 snprintf(path,sizeof(path),"/proc/%lu/mem",pid);int fd=open(path,0);if(fd<0)return 5;
 printf("AF_LOADER_BASE=%lx\n",base);
 printf("AF_AP_BASE=%lx AF_SINGLE_RX=%d\n",apbase,single_rx);
 unsigned bad=0;
 for(unsigned i=0;i<sizeof(checks)/sizeof(checks[0]);++i){
  unsigned int actual=0;
  if(!apbase || lseek(fd,apbase+checks[i].at,0)!=(long)(apbase+checks[i].at) || read(fd,&actual,4)!=4)return 9;
  if(actual!=checks[i].before){++bad;printf("AF_CHECK_BAD offset=%x expected=%x actual=%x\n",checks[i].at,checks[i].before,actual);}
 }
 printf("AF_CHECK_MISMATCHES=%u\n",bad);
 for(unsigned i=0;i<sizeof(items)/sizeof(items[0]);++i){
  unsigned char bytes[128];size_t count=items[i].bytes;if(count>sizeof(bytes))return 6;
  if(lseek(fd,base+items[i].offset,0)!=(long)(base+items[i].offset) || read(fd,bytes,count)!=(long)count)return 7;
  printf("AF_STATE %s ",items[i].name);for(size_t j=0;j<count;++j)printf("%02x",bytes[j]);printf("\n");
 }
 return close(fd)?8:0;
}
__attribute__((noreturn)) void entry(unsigned long *s){__libc_start_main(run,(int)s[0],(char **)(s+1),0,0,0,s);__builtin_trap();}
'''.replace('CHECK_TABLE', checks).replace('TABLE', table)
    c = out / 'state.c'
    c.write_text(code)
    command = ['/opt/homebrew/opt/llvm/bin/clang', '--target=aarch64-linux-gnu',
               '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld', '-nostdlib', '-O2', '-mno-outline-atomics',
               '-Wl,-e,_start', '-Wl,--dynamic-linker=/lib/ld-linux-aarch64.so.1', str(c),
               str(LAB / 'sdk/lib/libc-2.25.so'), str(LAB / 'sdk/lib/ld-2.25.so'), '-o', str(out / 'af-state')]
    result = subprocess.run(command, capture_output=True, text=True)
    (out / 'compile.json').write_text(json.dumps(dict(argv=command, exit_code=result.returncode, stderr=result.stderr), indent=2))
    assert result.returncode == 0, result.stderr
    replacements['simulation/af-state'] = (out / 'af-state').read_bytes()
    before = entries(source)
    added = set(replacements) - set(before)
    target = out / 'menu.cpio'
    with source.open('rb') as reader, target.open('xb') as writer:
        while True:
            h = reader.read(110)
            assert h[:6] == b'070701' and len(h) == 110
            values = [int(h[6 + 8*i:14 + 8*i], 16) for i in range(13)]
            encoded = reader.read(values[11]); pad = reader.read((-110-values[11]) % 4)
            data = reader.read(values[6]); tail = reader.read((-values[6]) % 4)
            name = encoded[:-1].decode().removeprefix('./')
            if name == 'TRAILER!!!':
                for n in sorted(added):
                    writer.write(entry(n, replacements[n]))
                writer.write(h + encoded + pad + data + tail)
                break
            if name in replacements:
                data = replacements[name]; values[6] = len(data)
                h = b'070701' + b''.join(f'{v:08x}'.encode() for v in values)
                tail = bytes((-len(data)) % 4)
            writer.write(h + encoded + pad + data + tail)
        writer.write(bytes((-writer.tell()) % 512))
    after = entries(target)
    changed = {n for n in before if before[n] != after.get(n)}
    assert changed == set(replacements) - added and set(after) - set(before) == added
    dtb = (previous / 'virt.dtb').read_bytes(); props = dtb_properties(dtb)
    bootargs = re.sub(rb'ramdisk_size=\d+', b'ramdisk_size=' + str((target.stat().st_size+1023)//1024).encode(), props[('/chosen', 'bootargs')])
    dtb = patch_property(dtb, '/chosen', 'bootargs', bootargs)
    dtb = patch_property(dtb, '/chosen', 'linux,initrd-end', (0x440000000+target.stat().st_size).to_bytes(8, 'big'))
    (out / 'virt.dtb').write_bytes(dtb)
    original = json.loads((previous / 'manifest.json').read_text())
    files = {}
    for key, row in original['files'].items():
        p = target if key == 'initrd' else out / 'virt.dtb' if key == 'dtb' else LAB / row['path']
        if key not in ('initrd', 'dtb'):
            assert sha(p) == row['sha256']
        files[key] = dict(path=str(p), bytes=p.stat().st_size, sha256=sha(p))
    manifest = dict(schema='af-boot-menu406/1', files=files, AP_sha256=sha(ap),
                    loader_sha256=hashlib.sha256(replacements['usr/lib/libaf_bootstrap406.so']).hexdigest(),
                    product_loader_sha256=report['bootstrap']['sha256'], changed_original=sorted(changed), added=sorted(added),
                    original_source_sha256=sha(source), unrelated_original_entries_identical=True,
                    CP_hardware_emulated=False, actual_CP_peer=False, camera_io=False,
                    software_protocol_peer=args.software_peer,
                    software_storage=args.software_storage, chinese=args.chinese,
                    restore_records=bool(args.restore_records),
                    prepared_record_sha256=sha(args.prepared_record) if args.prepared_record else None,
                    software_adapters='复用既有QEMU菜单环境的UIPC/Backup/GPE软件服务，非机身硬件',
                    state_observer_read_only=True)
    (out / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2)+'\n')
    print(out / 'manifest.json')


if __name__ == '__main__':
    main()
