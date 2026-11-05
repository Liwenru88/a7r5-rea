"""从只读4.06源归档构建全新隔离客体；不修改任何原输入。"""
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import argparse

ROOT = Path(__file__).resolve().parents[5]
LAB = ROOT/'a7r5-qemu'
FEATURE = ROOT/'a7r5-firmware-features/custom-filters'
OUT = ROOT/'.local/fixed-custom-filters/continuation28-menu/guest'
BASE = OUT
RESTORE = None
RECORD_PARSER = Path(__file__).absolute().with_name('record_export.py')
REPOSITORY = ROOT/'.local/fixed-custom-filters/continuation28-menu/service-comment-v3/libaf_repository_media.so'
sys.path[:0] = [str(LAB/'tools'),str(FEATURE)]
from media_candidate import extract,patch_property,entry
from cpio_inputs import entries
from native_vm import dtb_properties
from a7filters.investigate import AP
from a7filters.ap_ui_hooks import HOOKS
from a7filters.ui_resources import append_name_fixture
from a7filters.ui_icons import append_icons_fixture

def digest(path):
    with path.open('rb') as stream:return hashlib.file_digest(stream,'sha256').hexdigest()

def build():
    if RECORD_PARSER.is_symlink() or RECORD_PARSER.resolve()!=RECORD_PARSER or not RECORD_PARSER.is_file():
        raise ValueError('固定记录解析器路径不符')
    parser_identity={'path':str(RECORD_PARSER),'sha256':digest(RECORD_PARSER)}
    OUT.mkdir(exist_ok=False)
    shutil.copyfile(Path(__file__),OUT/'build-source.py')
    source = LAB/'build/aspect-guide406-20261026-01/source-02/source.cpio'
    old = LAB/'build/aspect-guide406-20261026-01/guest-11'
    if digest(source)!='c01948220e1cced7f4e1d6a6dd28221c587050214d32cc405291cc00d2f1ed80':raise ValueError('源CPIO不符')
    if digest(old/'menu.cpio')!='15089fc1b0a65dc7a198a2b11d9a56f6f55c746400e5cdc0122a9b878a768a53':raise ValueError('辅助客体不符')
    before = entries(source)
    users = sorted(n for n in before if n.startswith('usr/share/app/string_') and n.endswith(('_horizontal.uxc','_vertical.uxc')))
    if len(users)!=68:raise ValueError('名称资源集合不符')
    # 资源低13位为组内索引；新增ID只属于00组，01/02组完整保持。
    images=sorted(n for n in before if n.startswith('usr/share/app/image_00_') and n.endswith('_IPSX.uxc'))
    if len(images)!=2:raise ValueError('原00组图标资源集合不符')
    fonts=['tmp/images/MYingHeiC-GB18030-SJ_wIcon.ltt','tmp/images/MYingHeiC-Big5-SJ_wIcon.ltt','tmp/images/Sony_DI_Icons.ttf']
    raw = extract(source,['usr/lib/appFw.so','usr/lib/libObj.so','usr/lib/libbackup.so',*users,*images,*fonts]);ap = AP(raw['usr/lib/appFw.so'])
    if hashlib.sha256(ap.raw).hexdigest()!='d15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9':raise ValueError('AP不符')
    if hashlib.sha256(raw['usr/lib/libObj.so']).hexdigest()!='0d0be8f1e48b3c74330f9afab698ac352b3c2a922f7231ffc836591529a9fdf9':raise ValueError('同包Obj不符')
    module = ROOT/'.local/fixed-custom-filters/rename30/module-v3/dynamic/ap-ui.elf'
    module_receipt=json.loads((module.parents[1]/'verification.json').read_text())
    if module_receipt['status']!='PASS' or digest(module)!=module_receipt['dynamic_module_sha256']:
        raise ValueError('动态模块不符')
    for name,wanted in module_receipt['source_fingerprints'].items():
        if digest(ROOT/name)!=wanted:raise ValueError('模块编译后源码已变化：'+name)
    shutil.copyfile(module,OUT/'af-ui-dynamic.so')
    repository=REPOSITORY
    repository_receipt=json.loads(repository.with_name('service-media-build.json').read_text())
    if repository_receipt['status']!='PASS' or repository_receipt['capabilities'] not in (11,27,59) or digest(repository)!=repository_receipt['sha256']:
        raise ValueError('持久化服务来源或ABI不符')
    for name,wanted in repository_receipt['source_sha256'].items():
        if digest(ROOT/name)!=wanted:raise ValueError('服务编译后源码已变化：'+name)
    names = sorted(n for n in entries(old/'menu.cpio') if n.startswith('simulation/'))
    helpers = extract(old/'menu.cpio',names)
    helpers['simulation/libaf_repository.so']=repository.read_bytes()
    exporter=ROOT/'.local/fixed-custom-filters/continuation29-exporter'
    exporter_receipt=json.loads((exporter/'final-freeze.json').read_text())
    if exporter_receipt['status']!='PASS' or not exporter_receipt['target_glibc225_os_executed']:raise ValueError('导出助手未通过旧ABI执行')
    for name,wanted in exporter_receipt['source_and_artifact_sha256'].items():
        if digest(ROOT/name)!=wanted:raise ValueError('导出助手冻结来源变化：'+name)
    helpers['simulation/af-export-records']=(exporter/'af-export-records').read_bytes()
    lut_fixtures={}
    for i in range(1,19):
        name=f'simulation/ui406-lut-{i:02d}_测试.cube'
        contents=(f'TITLE "UI406 identity fixture {i:02d}"\nLUT_3D_SIZE 2\nDOMAIN_MIN 0 0 0\nDOMAIN_MAX 1 1 1\n'+
                  ''.join(f'{r} {g} {b}\n' for b in range(2) for g in range(2) for r in range(2))).encode()
        helpers[name]=contents;lut_fixtures[name]={'bytes':len(contents),'sha256':hashlib.sha256(contents).hexdigest(),'test_fixture':True}

    restore_receipt=None
    if RESTORE is not None:
        source_restore=RESTORE.resolve()
        if not source_restore.is_dir() or not source_restore.is_relative_to(BASE):raise ValueError('恢复输入必须来自本实验原记录导出')
        records=json.loads((source_restore/'records.json').read_text())
        expected={'STORE.ID','C07_A.rec','C07_B.rec','C20_A.rec','C20_B.rec'}
        log=Path(records['source_log']).resolve()
        if records['status']!='PASS' or not log.is_relative_to(BASE) or digest(log)!=records['source_log_sha256']:raise ValueError('实际GUI导出日志来源不符')
        import importlib.util
        if digest(RECORD_PARSER)!=parser_identity['sha256']:raise ValueError('构建期间记录解析器变化')
        spec=importlib.util.spec_from_file_location('ui406_strict_store_export',RECORD_PARSER)
        parser=importlib.util.module_from_spec(spec);spec.loader.exec_module(parser)
        decoded,report=parser.verify(log.read_text(errors='strict'))
        if set(decoded)!=expected or records['files']!=report:raise ValueError('记录与严格导出解码不一致')
        rows={}
        for name,data in decoded.items():
            rows[name]={'present':data is not None}
            if data is not None:
                if (source_restore/name).read_bytes()!=data:raise ValueError('记录不等于实际导出的原始字节')
                rows[name].update(bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        restore_receipt={'records':rows}
        for name,row in restore_receipt['records'].items():
            if not row['present']:continue
            item=source_restore/name
            if item.is_symlink() or item.stat().st_size!=row['bytes'] or digest(item)!=row['sha256']:raise ValueError('实际记录导出变化：'+name)
            helpers['simulation/ui406-restore-'+name]=item.read_bytes()
        restore_receipt={'source':str(source_restore),'manifest_sha256':digest(source_restore/'records.json'),
                         'records':restore_receipt['records'],'catalog_memory_seed':False}

    font_receipts={}
    for name in fonts:
        helper='simulation/'+Path(name).name;helpers[helper]=raw[name]
        font_receipts[name]={'helper':helper,'bytes':len(raw[name]),'sha256':hashlib.sha256(raw[name]).hexdigest()}
    resource_receipts = {};replacements = {}
    for name in users:replacements[name],resource_receipts[name]=append_name_fixture(raw[name])
    for name in images:replacements[name],resource_receipts[name]=append_icons_fixture(raw[name])
    native = LAB/'source/guest'
    for name in ('a7r5-gui.inc','aspect-guide406.inc','menu-observe-native.c'):
        shutil.copyfile(old/name,OUT/name)
    source_c = (OUT/'menu-observe-native.c').read_text()
    anchor = '        if (getenv("A7R5_ASPECT_GUIDE406_UNLOCK")) aspect406_install(symbol);'
    if source_c.count(anchor)!=1:raise ValueError('初始化锚点不唯一')
    source_c=source_c.replace(anchor,'        if (getenv("A7R5_UI406_ATTACH")) ui406_install(symbol);\n'+anchor)
    source_c=source_c.replace('#include "aspect-guide406.inc"','#include "ui406-loader.inc"\n#include "aspect-guide406.inc"')
    source_c=source_c.replace('#include "ui406-loader.inc"','#include "ui406-loader.inc"\n#include "locale-ui406.inc"')
    locale_anchor='        if (getenv("A7R5_UI406_ATTACH")) ui406_install(symbol);'
    if source_c.count(locale_anchor)!=1:raise ValueError('语言准备锚点不唯一')
    source_c=source_c.replace(locale_anchor,locale_anchor+'\n        if (getenv("A7R5_UI406_CHINESE")) locale28_install(symbol);')
    thread_anchor='    if (!ui_thread_id) ui_thread_id = (unsigned int)syscall(178);   /* remember the UI thread */'
    if source_c.count(thread_anchor)!=1:raise ValueError('原首CreateScreen线程锚点不唯一')
    source_c=source_c.replace(thread_anchor,thread_anchor+'\n    if (getenv("A7R5_UI406_CHINESE")) locale28_apply_model();')
    source_c='static void locale28_apply_model(void);\n'+source_c

    (OUT/'menu-observe-native.c').write_text(source_c)
    gui = (OUT/'a7r5-gui.inc').read_text()
    if gui.count('    aspect406_observe();')!=1:raise ValueError('绘制观察锚点不唯一')
    locale_actual='    ui_thread_id = (unsigned int)syscall(178);'
    if gui.count(locale_actual)!=1:raise ValueError('真实CreateScreen wrapper线程锚点不唯一')
    gui=gui.replace(locale_actual,locale_actual+'\n    if (getenv("A7R5_UI406_CHINESE")) locale28_apply_model();')
    (OUT/'a7r5-gui.inc').write_text(gui.replace('    aspect406_observe();','    aspect406_observe();\n    ui406_observe();\n    if (getenv("A7R5_UI406_CHINESE")) locale28_observe();'))
    shutil.copyfile(Path(__file__).with_name('ui406-loader.inc'),OUT/'ui406-loader.inc')
    for name in ('locale-ui406.inc','locale28-backup.h'):shutil.copyfile(Path(__file__).with_name(name),OUT/name)
    if hashlib.sha256(raw['usr/lib/libbackup.so']).hexdigest()!='6a3c5f6067620c00d790cbe520844acdbb721fa5d0e7433b00a227f922ab9d0d':raise ValueError('同包语言Backup来源不符')

    def array(value):return ','.join('0x'+value[i:i+2] for i in range(0,64,2))
    header = '#define UI406_MODULE_BYTES '+str(module.stat().st_size)+'UL\n'
    header += 'static const unsigned char ui406_ap_sha[32]={'+array(hashlib.sha256(ap.raw).hexdigest())+'};\n'
    header += 'static const unsigned char ui406_module_sha[32]={'+array(digest(module))+'};\n'
    header += 'static const unsigned char ui406_obj_sha[32]={'+array(hashlib.sha256(raw['usr/lib/libObj.so']).hexdigest())+'};\n'
    header += '#define UI406_REPOSITORY_BYTES '+str(repository.stat().st_size)+'UL\n'
    header += 'static const unsigned char ui406_repository_sha[32]={'+array(digest(repository))+'};\n'
    for i,name in enumerate(fonts):
        header += '#define UI406_FONT_'+str(i)+'_BYTES '+str(len(raw[name]))+'UL\n'
        header += 'static const unsigned char ui406_font_'+str(i)+'_sha[32]={'+array(hashlib.sha256(raw[name]).hexdigest())+'};\n'
    header += 'struct ui406_hook { unsigned int offset,before;const char *name;int link,protection;unsigned int after;unsigned long address,target; };\n'
    header += '#define UI406_HOOK_COUNT '+str(len(HOOKS))+'\n'
    header += 'static struct ui406_hook ui406_hooks[UI406_HOOK_COUNT]={\n'
    for at,name,link,_ in HOOKS:header += '{'+f'0x{at:x},0x{ap.u32(at):x},"{name}",{int(link)},0,0,0,0'+'},\n'
    header+='};\n'
    source_checks=(FEATURE/'native/af_ap_ui.c').read_text().split('static const AfApCheck checks[] = {',1)[1].split('};',1)[0]
    import re
    checks=re.findall(r'\{(0x[0-9a-f]+),(0x[0-9a-f]+)\}',source_checks)
    if len(checks)!=132:raise ValueError('绑定前像数量不符')
    header+='#define UI406_CHECK_COUNT '+str(len(checks))+'\nstatic const unsigned int ui406_checks[UI406_CHECK_COUNT][2]={\n'
    for a,b in checks:
        if ap.u32(int(a,16))!=int(b,16):raise ValueError('绑定前像不符')
        header+='{'+a+','+b+'},\n'
    (OUT/'ui406-hooks.h').write_text(header+'};\n')
    glibc = [LAB/'sdk/lib'/n for n in ('libc-2.25.so','libdl-2.25.so','libpthread-2.25.so','ld-2.25.so')]
    wanted = json.loads((LAB/'build/aspect-guide406-20261026-01/source-02/source-manifest.json').read_text())['files']
    for p in glibc:
        if digest(p)!=wanted['lib/'+p.name]['sha256']:raise ValueError('SDK来源不符')
    command=['/opt/homebrew/opt/llvm/bin/clang','--target=aarch64-linux-gnu',
        '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld','-nostdlib','-O2','-mno-outline-atomics','-fno-stack-protector',
        '-Wl,--no-undefined','-I'+str(OUT),'-I'+str(native),'-I'+str(FEATURE/'native'),
        '-shared','-fPIC','-Wl,-soname,menu-observe-a7r5-baseline.so',str(OUT/'menu-observe-native.c')]
    command += [str(native/n) for n in ('capid-service.c','sa-address-service.c','hdmi-format-service.c',
        'dmm-service.c','gpe-raster.c','gpe-sprite.c','sony-lz77.c','headless-osd-a7r5.c','a7r5-services.c')]
    command += [str(FEATURE/'native/af_sha256.c'),*[str(p) for p in glibc],'-o',str(OUT/'menu-observe-a7r5-baseline.so')]
    result=subprocess.run(command,capture_output=True,text=True)
    (OUT/'compiler.log').write_text(result.stdout+result.stderr)
    if result.returncode:raise RuntimeError('编译失败，现场保留')
    helpers['simulation/menu-observe-a7r5-baseline.so']=(OUT/'menu-observe-a7r5-baseline.so').read_bytes()
    helpers['simulation/af-ui-dynamic.so']=module.read_bytes()
    target=OUT/'menu.cpio'
    with source.open('rb') as reader,target.open('xb') as writer:
        while True:
            h=reader.read(110)
            if len(h)!=110 or h[:6]!=b'070701':raise ValueError('归档头不符')
            v=[int(h[6+i*8:14+i*8],16) for i in range(13)]
            encoded=reader.read(v[11]);pad=reader.read((-110-v[11])%4)
            data=reader.read(v[6]);tail=reader.read((-v[6])%4);name=encoded[:-1].decode().removeprefix('./')
            if name=='TRAILER!!!':
                for added,contents in helpers.items():writer.write(entry(added,contents))
                writer.write(h+encoded+pad+data+tail);break
            if name in replacements:
                data=replacements[name];v[6]=len(data);h=b'070701'+b''.join(f'{x:08x}'.encode() for x in v);tail=bytes((-len(data))%4)
            writer.write(h+encoded+pad+data+tail)
        writer.write(bytes((-writer.tell())%512))
    after=entries(target)
    changed=[n for n in before if before[n]!=after.get(n)]
    if set(changed)!=set(users+images) or set(after)-set(before)!=set(helpers):raise ValueError('归档出现额外改动')
    for n in changed:
        if before[n]['metadata']!=after[n]['metadata']:raise ValueError('原元数据改变')
    manifest=json.loads((old/'manifest.json').read_text())
    dtb=(old/'virt.dtb').read_bytes();props=dtb_properties(dtb)
    import re
    args=re.sub(rb'ramdisk_size=\d+',b'ramdisk_size='+str((target.stat().st_size+1023)//1024).encode(),props[('/chosen','bootargs')])
    dtb=patch_property(dtb,'/chosen','bootargs',args)
    dtb=patch_property(dtb,'/chosen','linux,initrd-end',(0x440000000+target.stat().st_size).to_bytes(8,'big'))
    (OUT/'virt.dtb').write_bytes(dtb)
    files={}
    for key,record in manifest['files'].items():
        p=target if key=='initrd' else OUT/'virt.dtb' if key=='dtb' else LAB/record['path']
        if key not in ('initrd','dtb') and digest(p)!=record['sha256']:raise ValueError('外部输入改变')
        files[key]={'path':str(p),'bytes':p.stat().st_size,'sha256':digest(p)}
    receipt={'schema':'a7r5-ui406-guest/1','firmware':'research-4.06','AP_sha256':hashlib.sha256(ap.raw).hexdigest(),
        'files':files,'source_cpio_sha256':digest(source),'original_entries':len(before),'changed_original_resources':changed,
        'all_other_original_entries_identical':True,'added':sorted(helpers),'resource_receipts':resource_receipts,
        'font_restoration':font_receipts,'repository_restore':restore_receipt,'media_RAM_fixture_files':lut_fixtures,
        'record_parser':parser_identity,
        'record_exporter':{'sha256':digest(exporter/'af-export-records'),'freeze_receipt':str(exporter/'final-freeze.json')},
        'repository_service':{'file':str(repository),'sha256':digest(repository),'bytes':repository.stat().st_size,
                              'receipt':str(repository.with_name('service-media-build.json')),'capabilities':repository_receipt['capabilities']},
        'compiler':{'argv':command,'exit_code':result.returncode},'sources':{str(p):digest(p) for p in
            [Path(__file__),RECORD_PARSER,Path(__file__).with_name('ui406-loader.inc'),Path(__file__).with_name('locale-ui406.inc'),Path(__file__).with_name('locale28-backup.h'),*glibc,FEATURE/'native/af_sha256.c']},
        'camera_io':False,'DAT_read':False,'DAT_write':False,'installable_firmware':False}
    (OUT/'manifest.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({'manifest':str(OUT/'manifest.json'),'changed_resources':len(changed),'added':len(helpers),
                      'CPIO_sha256':digest(target)},indent=2))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',type=Path,default=BASE)
    parser.add_argument('--restore',type=Path)
    parser.add_argument('--repository',type=Path,default=REPOSITORY)
    args=parser.parse_args();OUT=args.output.absolute();RESTORE=args.restore;REPOSITORY=args.repository.absolute()
    if OUT!=BASE and (OUT.parent!=BASE or not OUT.name.startswith('candidate-')):raise ValueError('独占输出路径越界')
    build()
