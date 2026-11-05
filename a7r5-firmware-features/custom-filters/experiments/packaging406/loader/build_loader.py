"""从固定当前预检回执生成真实Linux启动DSO和70项资源候选；不运行目标文件。"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
FEATURE=ROOT/'a7r5-firmware-features/custom-filters';NATIVE=FEATURE/'native'
sys.path[:0]=[str(FEATURE/'experiments/packaging406'),str(HERE.parent),str(FEATURE)]
from candidate_preflight import Image,dynamic,sha,require,read_cpio,source_declarations,hooks_from_source,AP_SHA,recipe_pairing
from aspect_merge import validate_plan
from a7filters.ui_resources import append_name_fixture
from a7filters.ui_icons import append_icons_fixture

def digest(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def array(raw):return '{'+','.join(str(b) for b in raw)+'}'
def quoted(s):return json.dumps(str(s),ensure_ascii=True)

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight',required=True,type=Path);parser.add_argument('--software',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path);args=parser.parse_args()
    args.preflight=args.preflight.resolve();args.software=args.software.resolve()
    out=args.output.resolve();require(out.is_relative_to(ROOT/'.local/fixed-custom-filters') and not out.exists(),'只接受全新隔离输出')
    out.mkdir();report=json.loads(args.preflight.read_text());software=json.loads(args.software.read_text())
    markers=report['bootstrap']['includes_aspect_changes']
    require(report['status']=='PASS_STATIC_BINDING_AND_COMPOSITE_PLAN_ONLY' and type(markers) is bool,
            '需要明确范围的4.06预检回执')
    if markers:
        validate_plan(report['bootstrap']['file_patch_plan'],report['bootstrap'].get('aspect_merge'))
    recipe_enabled=recipe_pairing(report,software)
    watched=[*HERE.glob('*.[ch]'),Path(__file__),HERE/'manifest_types.h',NATIVE/'af_sha256.c',NATIVE/'af_sha256.h',NATIVE/'af_ap_requests_binding.h',args.preflight,args.software]
    watched+=[NATIVE/'af_ap_ui.c',FEATURE/'a7filters/ap_ui_hooks.py',NATIVE/'af_ap_lifecycle.c',NATIVE/'af_ap_lifecycle.h',
              NATIVE/'af_storage406.c',NATIVE/'af_storage406.h',NATIVE/'af_repository.h',NATIVE/'af_target_posix.h',
              NATIVE/'af_imaging406.h',NATIVE/'af_repository_service.h',NATIVE/'af_recipe_transport.h',
              NATIVE/'af_ap_ui.h',NATIVE/'af_apply.h']
    watched += [NATIVE/name for name in ('af_fsys406.c','af_fsys406.h','af_media_snapshot406.c','af_media_snapshot406.h','af_media.h','af_ap_media.h','af_ap_cards.h')]
    before={str(p.relative_to(ROOT)):digest(p) for p in watched}
    ui=Path(report['ui_input']['path']);requests=ROOT/report['module']['path'];repo=args.software.parent/'libaf_repository_media.so'
    require(digest(ui)==report['ui_input']['sha256']==software['artifacts']['dynamic/ap-ui.elf']['sha256'],'当前UI不符')
    require(digest(requests)==report['module']['sha256'],'动态请求模块不符')
    require(digest(repo)==software['artifacts']['libaf_repository_media.so']['sha256'],'当前仓库不符')
    # 原70项资源集合从只读newc名称读取；内容仍由固定CPIO全文摘要门控。
    cpio=ROOT/'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio';names=[]
    with cpio.open('rb') as f:
        while True:
            h=f.read(110);require(len(h)==110 and h[:6]==b'070701','CPIO头不符')
            v=[int(h[6+i*8:14+i*8],16) for i in range(13)];name=f.read(v[11])[:-1].decode().removeprefix('./');f.read((-110-v[11])%4)
            if re.fullmatch(r'usr/share/app/string_[a-z]+_(horizontal|vertical)\.uxc',name) or re.fullmatch(r'usr/share/app/image_00_(23|32)_IPSX\.uxc',name):names.append(name)
            f.seek(v[6]+(-v[6])%4,1)
            if name=='TRAILER!!!':break
    require(len(names)==70 and len(set(names))==70,'68+2资源集合不符')
    raw=read_cpio(cpio,set(names)|{'usr/lib/libObj.so','usr/lib/libInfraFsys.so','usr/lib/appFw.so'})
    require(sha(raw['usr/lib/appFw.so'])==AP_SHA,'启动入口AP来源不符')
    ap_image=Image(raw['usr/lib/appFw.so'])
    require(sha(raw['usr/lib/libObj.so'])=='0d0be8f1e48b3c74330f9afab698ac352b3c2a922f7231ffc836591529a9fdf9','Obj来源不符')
    fsys=raw['usr/lib/libInfraFsys.so'];require(len(fsys)==708568 and sha(fsys)=='1986525ba65519a00ee5f41fbf40d2651bfcccb518bbb1e7e8e7fc0a58db7c5b','Fsys来源不符')
    assets=[dict(path='/usr/lib/libObj.so',bytes=len(raw['usr/lib/libObj.so']),sha256=sha(raw['usr/lib/libObj.so']))]
    for name in sorted(names):
        replacement,_=(append_name_fixture(raw[name]) if '/string_' in name else append_icons_fixture(raw[name]))
        target=out/'components'/name;target.parent.mkdir(parents=True,exist_ok=True);target.write_bytes(replacement)
        assets.append(dict(path='/'+name,bytes=len(replacement),sha256=sha(replacement),source_sha256=sha(raw[name])))
    lines=['#include "manifest_types.h"']
    def bootfile(name,path,n,h):
        lines.append('static const BootFile '+name+'={'+quoted(path)+','+str(n)+','+array(bytes.fromhex(h))+'};')
    bootfile('boot_ap','/usr/lib/appFw.so',97368304,report['bootstrap']['memory_only_candidate_ap_sha256'])
    bootfile('boot_repository','/usr/lib/libaf_repository_media.so',repo.stat().st_size,digest(repo))
    bootfile('boot_fsys','/usr/lib/libInfraFsys.so',len(fsys),sha(fsys))
    fsys_image=Image(fsys)
    loads=[s for s in fsys_image.elf.iter_segments() if s['p_type']=='PT_LOAD']
    require([(s['p_vaddr'],s['p_memsz'],s['p_flags']) for s in loads]==
            [(0,0xa77e7,5),(0xb7ac8,0xa8c20,6)],'Fsys完整虚拟范围/LOAD权限不符')
    require(max(s['p_vaddr']+s['p_memsz'] for s in loads)==0x1606e8,'Fsys虚拟跨度不符')
    require('#define AF_FSYS406_LIBRARY_SPAN 0x1606e8u' in (NATIVE/'af_fsys406.h').read_text(),
            'Fsys绑定跨度与原ELF不符')
    fsys_entries=[('Fsys_Open',0x35e90),('Fsys_Read',0x36120),('Fsys_Close',0x36004),
                  ('Fsys_FindFirst',0x371d4),('Fsys_FindNext',0x37390)]
    symbols={s.name:s for s in fsys_image.elf.get_section_by_name('.dynsym').iter_symbols()}
    require(all(name in symbols and int(symbols[name]['st_value'])==at and symbols[name]['st_info']['type']=='STT_FUNC'
                for name,at in fsys_entries),'Fsys原导出不符')
    lines.append('static const BootSymbol boot_fsys_exports[]={'+','.join('{'+quoted(name)+','+str(at)+'}' for name,at in fsys_entries)+'};')
    lines.append('static const BootCheck boot_fsys_checks[]={'+','.join('{%d,%d}'%(at+4*i,int.from_bytes(fsys_image.read(at+4*i,4),'little'))
                 for name,at in fsys_entries for i in range(4))+'};')
    lines.append('static const uint8_t boot_original_sha[32]='+array(bytes.fromhex(AP_SHA))+';')
    patches=report['bootstrap']['file_patch_plan'];entries=[]
    for i,p in enumerate(patches):
        b=bytes.fromhex(p['before']);a=bytes.fromhex(p['after']);require(len(a)==len(b),'逆补丁长度不符')
        lines+=['static const uint8_t patch_before_%d[]='%i+array(b)+';','static const uint8_t patch_after_%d[]='%i+array(a)+';']
        entries.append('{%d,%d,patch_before_%d,patch_after_%d}'%(p['offset'],len(a),i,i))
    lines.append('static const BootPatch boot_patches[]={'+','.join(entries)+'};')
    start,end=report['bootstrap']['reserved_file_range'];shim=next(bytes.fromhex(p['after']) for p in patches if p['offset']==start)
    lines+=['#define BOOT_SHIM_START %du'%start,'#define BOOT_SHIM_BYTES %du'%len(shim),'static const uint8_t boot_shim[]='+array(shim)+';']
    ctor_start,ctor_end=report['bootstrap']['ctor_file_range']
    ctor=next(bytes.fromhex(p['after']) for p in patches if p['offset']==ctor_start)
    require(len(ctor)==ctor_end-ctor_start,'构造shim长度不符')
    lines+=['#define BOOT_CTOR_START %du'%ctor_start,'#define BOOT_CTOR_BYTES %du'%len(ctor),
            '#define BOOT_CTOR_POINTER 0x5020388u','static const uint8_t boot_ctor_shim[]='+array(ctor)+';']
    lines.append('static const BootFile boot_assets[]={'+','.join('{'+quoted(a['path'])+','+str(a['bytes'])+','+array(bytes.fromhex(a['sha256']))+'}' for a in assets)+'};')
    for name,path,target,entry in [('ui',ui,'/usr/lib/libaf_ui406.so','af_ap_register'),('requests',requests,'/usr/lib/libaf_requests406.so','af_ap_hs_gate')]:
        data=path.read_bytes();m=dynamic(data,entry);image=m['image']
        if name=='ui':require('af_ap_after_original_registration' in m['symbols'],'缺少post-original接口')
        if recipe_enabled:
            required=(('af_stock_refresh','af_ap_refresh') if name=='ui' else
                      ('af_ap_runtime_gate','af_ap_hs_gate','af_ap_runtime_preset_capabilities','af_ap_runtime_preset_status'))
            require(all(n in m['symbols'] for n in required),'缺少真实启动观察或通信入口')
        segs=[s for s in image.elf.iter_segments() if s['p_type']=='PT_LOAD']
        lines.append('static const BootSegment '+name+'_segments[]={'+','.join('{%d,%d,%d,%d,%d}'%(s['p_vaddr'],s['p_offset'],s['p_filesz'],s['p_memsz'],s['p_flags']) for s in segs)+'};')
        lines.append('static const BootReloc '+name+'_relocs[]={'+','.join('{%d,%d}'%r for r in m['relocations'])+'};')
        symbols=[s for s in image.elf.get_section_by_name('.symtab').iter_symbols() if s.name.startswith('af_') and s['st_info']['type'] in ('STT_FUNC','STT_OBJECT') and s['st_shndx'] not in ('SHN_UNDEF','SHN_ABS')]
        lines.append('static const BootSymbol '+name+'_symbols[]={'+','.join('{'+quoted(s.name)+','+str(s['st_value'])+'}' for s in symbols)+'};')
        span=(max(s['p_vaddr']+s['p_memsz'] for s in segs)+4095)&~4095
        lines.append('static const BootModule boot_'+name+'={{'+quoted(target)+','+str(len(data))+','+array(bytes.fromhex(sha(data)))+'},'+str(span)+','+name+'_segments,'+str(len(segs))+','+name+'_relocs,'+str(len(m['relocations']))+','+name+'_symbols,'+str(len(symbols))+'};')
    checks=source_declarations(NATIVE/'af_ap_ui.c');hooks=hooks_from_source(FEATURE/'a7filters/ap_ui_hooks.py')
    # 自然登记只由early观察一次；发布阶段不重新安装已完成的构造器BL。
    hooks=[h for h in hooks if h[0]!=0x16f6610]
    lines.append('static const BootCheck boot_checks[]={'+','.join('{%d,%d}'%p for p in checks)+'};')
    lines.append('static const BootHook boot_hooks[]={'+','.join('{%d,%d,%s,%d}'%(at,dict(checks)[at],quoted(n),int(link)) for at,n,link,_ in hooks)+'};')
    if recipe_enabled:
        startup_hooks=((0x3554d38,0x97861836,'af_ap_runtime_gate',False),
                       (0x3554d90,0x39400260,'af_ap_hs_gate',False),
                       (0x1ec738c,0x97ff41a6,'startup_refresh',True))
        for at,before_word,_,_ in startup_hooks:
            require(int.from_bytes(ap_image.read(at,4),'little')==before_word,'启动通信/观察入口前像不符')
        # 启动任务创建、manager构造、主loop到唯一refresh的原窗口全部来自同一固定AP。
        windows=((0x3554d24,28),(0x3554d90,20),(0x1ec7388,16),
                 (0x17feb84,24),(0x17ff040,68),(0x1801fd8,24),(0x1ec670c,24),(0x1ec7a50,40),
                 (0x28a87e8,12))
        startup_checks=[(at+i,int.from_bytes(ap_image.read(at+i,4),'little'))
                        for at,size in windows for i in range(0,size,4)]
        lines+=['#ifdef AF_RECIPE_BRIDGE406',
                '#define BOOT_STARTUP_REQUIRED (AF_APPLY_ALL|AF_AP_IMAGING_REQUIRED|AF_AP_IMAGING_FULL_RECIPE|AF_AP_IMAGING_USER20|AF_AP_IMAGING_SECTOR_MATRIX)',
                'static const BootCheck boot_startup_checks[]={'+','.join('{%d,%d}'%p for p in startup_checks)+'};',
                'static const BootHook boot_startup_hooks[]={'+','.join('{%d,%d,%s,%d}'%(at,b,quoted(n),int(link)) for at,b,n,link in startup_hooks)+'};',
                '#endif']
    exit_names=['af_ap_hs_original_return','af_ap_hs_owned_return','af_ap_receive_return','af_ap_receive_loop']
    lines.append('static const char *const boot_exit_names[]={'+','.join(quoted(n) for n in exit_names)+'};')
    lines.append('static const uint32_t boot_exit_targets[]={0x3554d94u,0x3554ec8u,0x3554d3cu,0x3554d24u};')
    header=out/'af_bootstrap_manifest.h';header.write_text('\n'.join(lines)+'\n')
    target=out/'libaf_bootstrap406.so';argv=['/opt/homebrew/opt/llvm/bin/clang','--target=aarch64-linux-gnu',
        '--ld-path=/opt/homebrew/opt/lld/bin/ld.lld','-nostdlib','-shared','-fPIC','-ffreestanding','-fno-builtin',
        '-fno-stack-protector','-mno-outline-atomics','-O2','-std=c11','-Wall','-Wextra','-Werror','-DAF_TARGET_GLIBC225',
        *(['-DAF_RECIPE_BRIDGE406'] if recipe_enabled else []),
        '-I'+str(out),'-I'+str(HERE),'-I'+str(HERE.parent/'native'),'-I'+str(NATIVE),
        '-Wl,--no-undefined','-Wl,-soname,libaf_bootstrap406.so',str(HERE/'af_bootstrap406.c'),str(NATIVE/'af_ap_lifecycle.c'),
        str(NATIVE/'af_storage406.c'),str(NATIVE/'af_fsys406.c'),str(NATIVE/'af_media_snapshot406.c'),str(NATIVE/'af_sha256.c'),
        *[str(ROOT/'a7r5-qemu/sdk/lib'/n) for n in ['libdl-2.25.so','libc-2.25.so','ld-2.25.so']],'-o',str(target)]
    r=subprocess.run(argv,capture_output=True,text=True,cwd=ROOT)
    (out/'compile.json').write_text(json.dumps(dict(argv=argv,exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr),ensure_ascii=False,indent=2)+'\n')
    require(r.returncode==0,r.stderr)
    require(before=={str(p.relative_to(ROOT)):digest(p) for p in watched},'编译期间源码变化')
    result=dict(status='PASS_BOOTSTRAP_LINK_ONLY_NOT_EXECUTED',source_sha256=before,source_unchanged=True,
        recipe_bridge_enabled=recipe_enabled,includes_aspect_changes=markers,
        bootstrap=dict(path=str(target.relative_to(ROOT)),bytes=target.stat().st_size,sha256=digest(target)),
        ap_candidate_sha256=report['bootstrap']['memory_only_candidate_ap_sha256'],header_sha256=digest(header),assets=assets,
        ui=dict(path=str(ui),sha256=digest(ui)),requests=dict(path=str(requests),sha256=digest(requests)),
        repository=dict(path=str(repo),sha256=digest(repo)),CP_gates_installed=False,storage_namespace_selected=False,
        startup_source_bound=recipe_enabled,startup_protocol_required=0x1f1fff if recipe_enabled else 0,
        startup_preinstalls_disabled_ui=recipe_enabled,startup_late_RX_mutation=False,
        runtime_startup_source_bound=recipe_enabled,runtime_passthrough_hooks_armed=recipe_enabled,
        runtime_UI_requires_verified_peer=True,
        startup_hook_sites=[hex(h[0]) for h in startup_hooks] if recipe_enabled else [],
        target_executed=False,hardware_simulation=False,camera_io=False,installable_firmware=False)
    (out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:result[k] for k in ['status','bootstrap','ap_candidate_sha256']},ensure_ascii=False,indent=2))
if __name__=='__main__':main()
