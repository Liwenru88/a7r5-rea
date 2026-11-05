"""从固定菜单候选派生独立研究客体；构建及逐条回读均留收据。"""
import argparse
import importlib.util
import json
from pathlib import Path
import re
import subprocess
import environment as env
from cpio_inputs import entries
from media_candidate import patch_property, extract, add_files
from native_vm import dtb_properties


def build(source, output, release411=False, menu_event_fix=False, unified_look=False, pending_notify=False):
    if unified_look and not menu_event_fix:raise ValueError('统一入口必须包含 E4 修复前像')
    source=Path(source).absolute();output=Path(output).absolute()
    if output.parent!=env.LAB/'build' or output.exists():raise ValueError('须使用独立新build目录')
    record=json.loads(source.read_text());files=env.verified(record)
    if record['AP_sha256']!=env.AP_SHA or record['CP_sha256']!=env.CP_SHA:raise ValueError('来源身份不符')
    output.mkdir(mode=0o700)
    service_source=Path(__file__).with_name('native12-services.inc').absolute()
    (output/'native12-services.inc').write_bytes(service_source.read_bytes())
    (output/'e4-trace.inc').write_bytes(Path(__file__).with_name('e4-trace.inc').read_bytes())
    (output/'e4-services.inc').write_bytes(Path(__file__).with_name('e4-services.inc').read_bytes())
    pin_sources={env.LAB/'source/guest'/name:sha for name,sha in {
        'virtual-media-rm.c':'5f841b73480ebd512ae2fc527ab05fb6dd27eab2b28c0f4a0e3a87919eb42c1d',
        'dataflow-pin-service.inc':'f9c545d4db4c1575fc1bc08e55db4ff4697f1b2d03a5a95782742c3dd8aeda20',
        'dataflow-pin-definitions.inc':'ac79c31a22feeaf775da6b4c223b2571ce1895b42f1edef9c9feb83cb122e290'}.items()}
    for path,sha in pin_sources.items():
        if env.digest(path)!=sha:raise ValueError('受限端口服务来源变化')
    media=(env.LAB/'source/guest/virtual-media-rm.c').read_text()
    first=media.index('#include "dataflow-pin-definitions.inc"')
    end=media.index('#include "dataflow-pin-service.inc"',first)+len('#include "dataflow-pin-service.inc"')
    adapter='''/* 仅复用端口控制模型；不接入媒体存储或图像生产者。 */
extern void _exit(int) __attribute__((noreturn));
extern int printf(const char *, ...);
extern int fflush(void *);
extern int memcmp(const void *, const void *, unsigned long);
extern void *memcpy(void *, const void *, unsigned long);
static unsigned pin_connections;
static __thread unsigned pin_draining;
static __thread int pin_transport_error;
static void *n12_pin_next(const char *name) {
    void *p=real_dlsym((void *)-1,name);if(!p)_exit(126);return p;
}
#define next n12_pin_next
'''+media[first:end]+'''
#undef next
static int native12_dataflow_send(unsigned id,void *message,int *handled) {
    *handled=0;
    if(!n12_mailbox||!getenv("A7R5_N12_E4_SERVICES")||!message||!real_msg_size||!real_get_source)return 0;
    unsigned n=real_msg_size(message);const unsigned char *p=message;
    if(!dataflow_node(id)||n<28||p[24]!=0||p[25]!=0x10)return 0;
    *handled=1;
    return dataflow_dispatch(id,message,n,real_get_source(message));
}
'''
    (output/'dataflow-adapter.inc').write_text(adapter)
    (output/'builder.py').write_bytes(Path(__file__).read_bytes())
    font_spec=importlib.util.spec_from_file_location('derived_font',env.ROOT/'a7r5-firmware-features/native24-combined/dependencies/native12-combined/menu_font.py')
    font=importlib.util.module_from_spec(font_spec);font_spec.loader.exec_module(font)
    icon_names={'usr/share/app/image_00_23_IPSX.uxc','usr/share/app/image_00_32_IPSX.uxc'} if unified_look else set()
    original_files=extract(files['initrd'],{'usr/lib/appFw.so','usr/lib/libObj.so','cp/cpapp-b.bin'}|icon_names)
    if font.sha(original_files['usr/lib/libObj.so'])!=font.LIBOBJ_SHA:raise ValueError('原厂字体库身份不符')
    patched,font_receipt=font.build(original_files['usr/lib/appFw.so'],output/'font')
    if font_receipt['target_sha256']!=env.FONT_AP_SHA:raise ValueError('字体修订构建结果不符')
    actual_ap_sha=env.FONT_AP_SHA
    if menu_event_fix:
        event_spec=importlib.util.spec_from_file_location('derived_e4_event',env.ROOT/'a7r5-firmware-features/native24-combined/dependencies/native12-combined/e4_menu_compat.py')
        event=importlib.util.module_from_spec(event_spec);event_spec.loader.exec_module(event)
        patched,event_receipt=event.build(patched.read_bytes(),output/'e4-menu')
        actual_ap_sha=event_receipt['target_sha256']
        if actual_ap_sha!=env.E4_AP_SHA:raise ValueError('E4菜单修订构建结果不符')
        record['e4_menu_patch']=env.fact(output/'e4-menu/e4-menu-patch.json')
        record['component_override']='AP derived from 4.11; consumes private value-refresh event; not repackaged in DAT'
    if unified_look:
        unified_spec=importlib.util.spec_from_file_location('derived_unified_look',env.ROOT/'a7r5-firmware-features/native24-combined/dependencies/native12-combined/unified_look.py')
        unified=importlib.util.module_from_spec(unified_spec);unified_spec.loader.exec_module(unified)
        patched,unified_receipt=unified.build(patched.read_bytes(),output/'unified-look')
        actual_ap_sha=unified_receipt['target_sha256']
        if actual_ap_sha!=env.UNIFIED_AP_SHA:raise ValueError('统一入口构建摘要不符')
        record['unified_look_patch']=env.fact(output/'unified-look/unified-look-patch.json')
        record['component_override']='AP derived from E4-fixed 4.11; native Creative Look unified list; not repackaged in DAT'
    from cp_service import build as build_cp
    receiver=build_cp(output/'cp-receiver')
    cp=output/'cpapp-b.bin';cp.write_bytes(original_files['cp/cpapp-b.bin'])
    binpath=env.ROOT/'a7r5-firmware-features/native24-combined/dependencies/native12-combined/upstream/filters/FUJ_12_v45/R5NATIVE.BIN'
    if env.digest(binpath)!=env.BIN_SHA:raise ValueError('十二配置 BIN 身份不符')
    (output/'R5NATIVE.BIN').write_bytes(binpath.read_bytes())
    base=env.LAB/'build/aspect-guide406-20261026-01/guest-11'
    receipt=json.loads((base/'build-receipt.json').read_text())
    frequency_source=Path(__file__).with_name('hold-frequency.c').absolute()
    (output/'hold-frequency.c').write_bytes(frequency_source.read_bytes())
    frequency_command=[str(output/'hold-frequency.c') if x.endswith('/source/guest/seed-power-on.c') else
                       str(output/'hold-frequency') if x==str(base/'seed-power-on') else x for x in receipt['commands'][1]]
    frequency_compiled=subprocess.run(frequency_command,capture_output=True,text=True)
    (output/'frequency-compiler.log').write_text(frequency_compiled.stdout+frequency_compiled.stderr)
    if frequency_compiled.returncode:raise RuntimeError('原厂频率锁工具编译失败')
    original=(base/'menu-observe-native.c').read_text()
    original='static void native12_install(unsigned long);\nstatic void native12_observe(void);\nstatic void native12_trace_send(unsigned,void *);\nstatic int native12_native_send(unsigned,void *,int *);\nstatic int native12_dataflow_send(unsigned,void *,int *);\n'+original
    original=original.replace('static void record(const char *prefix, const char *name) {','static void record(const char *prefix, const char *name) {\n    native12_observe();')
    original=original.replace('#include "native-menu-reentry.inc"','#include "native-menu-reentry.inc"\n#include "native12-services.inc"')
    original=original.replace('int osal_snd_msg(unsigned int id, void *message) {',
        'int osal_snd_msg(unsigned int id, void *message) {\n    native12_trace_send(id,message);\n    int n12_handled=0,n12_rc=native12_dataflow_send(id,message,&n12_handled);if(n12_handled)return n12_rc;\n    n12_rc=native12_native_send(id,message,&n12_handled);if(n12_handled)return n12_rc;')
    anchor='        record("A7R5_ORIGINAL_APP_INIT ",'
    if original.count(anchor)!=1:raise ValueError('模拟器安装锚点不唯一')
    original=original.replace(anchor,'        native12_install(appfw_base);\n'+anchor)
    (output/'menu-observe-native.c').write_text(original)
    command=receipt['commands'][0]
    command=[str(output/'menu-observe-native.c') if x==str(base/'menu-observe-native.c') else
             str(output/'menu-observe-a7r5-baseline.so') if x==str(base/'menu-observe-a7r5-baseline.so') else x for x in command]
    command[1:1]=['-I',str(Path(__file__).parent.absolute())]
    compiled=subprocess.run(command,capture_output=True,text=True)
    (output/'compiler.log').write_text(compiled.stdout+compiled.stderr)
    if compiled.returncode:raise RuntimeError('服务库编译失败')
    spec=importlib.util.spec_from_file_location('loading_cpio',env.LAB/'tools/build-guest.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    candidate=output/'menu.cpio';intermediate=output/'replaced.cpio'
    replacements={'simulation/menu-observe-a7r5-baseline.so':(output/'menu-observe-a7r5-baseline.so').read_bytes(),'usr/lib/appFw.so':patched.read_bytes()}
    if unified_look:
        icon_spec=importlib.util.spec_from_file_location('derived_unified_icons',env.ROOT/'a7r5-firmware-features/native24-combined/dependencies/native12-combined/unified_icons.py')
        icons=importlib.util.module_from_spec(icon_spec);icon_spec.loader.exec_module(icons)
        receipts={}
        for name in sorted(icon_names):
            if icons.hashlib.sha256(original_files[name]).hexdigest()!=icons.SOURCES[name]:raise ValueError('原图标资源完整前像不符')
            changed,proof=icons.append_icons(original_files[name]);replacements[name]=changed;receipts[name]=proof
            (output/Path(name).name).write_bytes(changed)
        env.save(output/'unified-icons.json',receipts);record['unified_icons']=env.fact(output/'unified-icons.json')
    if release411:
        release=env.ROOT/'a7r5-firmware-features/native24-combined/dependencies/native12-combined/releases/4.11'
        if env.digest(release/'BODYDATA.DAT')!=env.DAT411_SHA:raise ValueError('4.11包身份不符')
        delivered=json.loads((release/'verification.json').read_text())
        if (delivered['sha256'],delivered['partitions']['AP']['component_sha256'],delivered['partitions']['CP']['component_sha256'])!=(env.DAT411_SHA,env.FONT_AP_SHA,env.CP_SHA):
            raise ValueError('4.11组件身份不符')
        replacements['simulation/firmware-version.dat4']=b'\x11\x04'
        record['DAT_sha256']=env.DAT411_SHA
        identity=record['adaptations']['firmware_identity'];identity['source'].update(minor=11,dat_sha256=env.DAT411_SHA);identity['dat4_hex']='1104'
        record['package_source']=dict(version='4.11',path=str(release/'BODYDATA.DAT'),sha256=env.DAT411_SHA)
    module.replace_cpio(files['initrd'],intermediate,replacements)
    from virtual_fat import make_fixture
    additions={'simulation/native12-lut.fat':make_fixture(),'simulation/R5NATIVE.BIN':binpath.read_bytes(),
               'simulation/hold-frequency':(output/'hold-frequency').read_bytes()}
    add_files(intermediate,candidate,additions)
    before,after=entries(files['initrd']),entries(candidate)
    changed=[k for k in before if before[k]!=after[k]]
    if set(after)-set(before)!=set(additions) or set(changed)!=set(replacements):raise ValueError('归档变更超出范围')
    for name in replacements:
        if before[name]['metadata']!=after[name]['metadata']:raise ValueError('归档元数据变化')
    raw=files['dtb'].read_bytes();props=dtb_properties(raw)
    bootargs=re.sub(rb'ramdisk_size=\d+',b'ramdisk_size='+str((candidate.stat().st_size+1023)//1024).encode(),props[('/chosen','bootargs')])
    if b'0x41ec00000' in bootargs:raise ValueError('传输保留区已存在')
    bootargs=bootargs.rstrip(b'\0')+b' memrsv=0x00010000@0x41ec00000:uc\0'
    raw=patch_property(raw,'/chosen','bootargs',bootargs)
    raw=patch_property(raw,'/chosen','linux,initrd-end',(0x440000000+candidate.stat().st_size).to_bytes(8,'big'))
    (output/'virt.dtb').write_bytes(raw)
    record.update(parent_manifest=env.fact(source),service_changes=changed,service_source=env.fact(output/'native12-services.inc'))
    record['native_e4_services']='virtual touch/output configuration and imaging locks; original E4 body preserved'
    if pending_notify:record['pending_notify_model']='one validated ON request retained without reply or 0x2040; native waiter is not completed'
    record['native_frequency_lock']='original UPM LOCK_MODE DEBUG via OSAL; VM lifetime only; no DFS completion emulation'
    record['native_dataflow_service']='existing bounded pin topology and original SDK state machine; no image producer'
    if not menu_event_fix:record['native_ui_trace']='original private dispatcher entry/return; guest log only; no input injection'
    env.save(output/'dataflow-source.json',dict(sources=[env.fact(p) for p in pin_sources],adapter=env.fact(output/'dataflow-adapter.inc')))
    record['readonly_AP_state_bytes']=1264
    record.update(AP_sha256=actual_ap_sha,base_AP_sha256=env.AP_SHA,font_patch=env.fact(output/'font/font-patch.json'),
        loading_inputs={k:env.fact(v) for k,v in {'cp':cp,'receiver':receiver,'bin':output/'R5NATIVE.BIN'}.items()},
        loading_adaptations={'SD':'POSIX read-only virtual A drive','internal_storage':'guest RAM-backed vfat /dev/nflasha30',
                            'CP':'real CP receiver on separate ARM QEMU; OSAL and 1MiB heap services',
                            'transport':'reserved guest RAM request via QMP pmemsave / bounded guest tmpfs reply; no network'},added_entries=list(additions))
    files.update(initrd=candidate,dtb=output/'virt.dtb')
    record['files']={k:env.fact(v) for k,v in files.items()}
    env.save(output/'manifest.json',record)
    used_sources={p:env.fact(Path(p)) for p in command if Path(p).suffix=='.c' and Path(p).is_file()}
    includes={p.name:env.fact(p) for p in base.glob('*.inc')}
    env.save(output/'service-build.json',dict(command=command,base_source=env.fact(base/'menu-observe-native.c'),output_source=env.fact(output/'menu-observe-native.c'),
             library=env.fact(output/'menu-observe-a7r5-baseline.so'),used_sources=used_sources,base_includes=includes,service_include=env.fact(output/'native12-services.inc'),e4_trace=env.fact(output/'e4-trace.inc'),e4_services=env.fact(output/'e4-services.inc'),frequency_command=frequency_command,frequency_source=env.fact(output/'hold-frequency.c'),frequency_binary=env.fact(output/'hold-frequency')))
    return output/'manifest.json'


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--release411',action='store_true')
    p.add_argument('--menu-event-fix',action='store_true')
    p.add_argument('--unified-look',action='store_true')
    p.add_argument('--pending-notify',action='store_true')
    a=p.parse_args();print(build(a.source,a.output,a.release411,a.menu_event_fix,a.unified_look,a.pending_notify))
