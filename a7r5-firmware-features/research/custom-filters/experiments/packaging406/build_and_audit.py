"""离线交叉链接/静态合成核对；输出只有本任务新模块与JSON，无固件容器。"""
from pathlib import Path
import argparse
import hashlib
import importlib.util
import json
import os
import struct
import subprocess
import sys
from candidate_preflight import *
from aspect_merge import compose_plan, validate_plan

HERE=Path(__file__).resolve().parent
ROOT=next(p for p in HERE.parents if (p/'a7r5-firmware-features/custom-filters/native').is_dir())
FEATURE=ROOT/'a7r5-firmware-features/custom-filters';NATIVE=FEATURE/'native'

def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--ui',required=True,type=Path)
    parser.add_argument('--ui-receipt',required=True,type=Path)
    parser.add_argument('--recipe-bridge',action='store_true',help='成对编译完整配方发送及回执；不安装gate')
    parser.add_argument('--include-photo-markers',action='store_true',help='显式合并同源照片标记扩展；不声明取景叠加通过')
    args=parser.parse_args();out=args.output.resolve()
    require(out.is_relative_to(ROOT/'.local/fixed-custom-filters') and not out.exists(),'输出只允许任务隔离区全新目录')
    out.mkdir();commands=[]
    sources=['af_slots.c','af_apply_wire.c','af_handshake.c','af_hs_ap406.c','af_hs_ap406.S',
             'af_runtime.c','af_runtime_ap406.c','af_factory406.c','af_imaging406.c']
    if args.recipe_bridge:sources+=['af_recipe_transport.c','af_sha256.c','af_joint_asset.c','af_joint.c']
    local_native=['af_ap_requests_binding.c','af_ap_requests_binding.h','af_ap_requests_binding.S',
                  'af_ap_requests_dynamic.ld','af_ap_bootstrap406.S','af_ap_ctor406.S','af_ap_ctor406.ld']
    tests=[FEATURE/'tests'/n for n in ('test_request_bindings.py','test_candidate_preflight.py')]
    own=[NATIVE/n for n in local_native]+list(HERE.glob('*.py'))+tests
    watched=own+[NATIVE/n for n in sources]+list(NATIVE.glob('*.h'))+[NATIVE/'af_ap_ui.c',FEATURE/'a7filters/ap_ui_hooks.py',FEATURE/'tests/native_memory.c']
    before={str(p.relative_to(ROOT)):digest(p) for p in watched}
    def run(argv):
        r=subprocess.run(list(map(str,argv)),cwd=ROOT,env=dict(os.environ),capture_output=True,text=True)
        commands.append(dict(argv=list(map(str,argv)),exit_code=r.returncode,stdout=r.stdout,stderr=r.stderr))
        (out/'commands.json').write_text(json.dumps(commands,ensure_ascii=False,indent=2)+'\n')
        require(r.returncode==0,r.stderr+r.stdout)
    objects=[]
    for i,p in enumerate([*[NATIVE/n for n in sources],NATIVE/'af_ap_requests_binding.c',
                         NATIVE/'af_ap_requests_binding.S',FEATURE/'tests/native_memory.c']):
        obj=out/f'{i:02d}-{p.name}.o';objects.append(obj)
        run(['clang','--target=aarch64-none-elf','-O2','-fPIC','-ffreestanding','-fno-builtin',
             '-fno-stack-protector','-mno-outline-atomics','-Wall','-Wextra','-Werror',
             '-DAF_RUNTIME406=1','-DAF_CP_PRESET406=1','-DAF_FACTORY_RESTORE406=1','-DAF_SNAPSHOT_OVERLAY406=1',
             *(['-DAF_RECIPE_BRIDGE406=1'] if args.recipe_bridge else []),
             '-I'+str(NATIVE),'-c',p,'-o',obj])
    module=out/'ap-requests-dynamic.elf'
    run(['/opt/homebrew/opt/lld/bin/ld.lld','-shared','-Bsymbolic','--no-undefined','--build-id=none',
         '-z','max-page-size=4096','-T',NATIVE/'af_ap_requests_dynamic.ld',*objects,'-o',module])
    shim=out/'ap-bootstrap.elf'
    run(['clang','--target=aarch64-none-elf','-c',NATIVE/'af_ap_bootstrap406.S','-o',out/'bootstrap.o'])
    run(['clang','--target=aarch64-none-elf','-c',NATIVE/'af_ap_ctor406.S','-o',out/'ctor.o'])
    run(['/opt/homebrew/opt/lld/bin/ld.lld','--build-id=none','-T',NATIVE/'af_ap_ctor406.ld',
         out/'bootstrap.o',out/'ctor.o','-o',shim])
    run([ROOT/'.venv/bin/python','-B','-m','pytest','-q','-p','no:cacheprovider',*tests])
    source=ROOT/'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio'
    raw=read_cpio(source,{'usr/lib/appFw.so'})['usr/lib/appFw.so'];require(sha(raw)==AP_SHA,'AP来源不符')
    ap=Image(raw);checks=source_declarations(NATIVE/'af_ap_ui.c')
    require(len(checks)==132,'132前像数量改变')
    require(all(ap.read(a,4)==struct.pack('<I',w) for a,w in checks),'UI源前像失配')
    # 复用文件候选的纯内存构建，不调用其CLI、DAT工具或模拟验证。
    aspect_path=ROOT/'a7r5-firmware-features/aspect-guide406-update/ap_patch.py'
    spec=importlib.util.spec_from_file_location('aspect_package_preflight',aspect_path)
    aspect=importlib.util.module_from_spec(spec);spec.loader.exec_module(aspect)
    aspect_raw,aspect_receipt=aspect.build(raw)
    # 此尾部已由原文件候选证明位于同一RX页；再对shim实际大小独立做全section/reloc/符号排除。
    shim_image=Image(shim.read_bytes());text=shim_image.elf.get_section_by_name('.text')
    start,end=int(text['sh_addr']),int(text['sh_addr']+text['sh_size'])
    require(start==aspect.END and end<=0x5010000,'启动垫片超出原末页')
    symbols={s.name:int(s['st_value']) for s in shim_image.elf.get_section_by_name('.symtab').iter_symbols() if s.name}
    ctor_start,ctor_end=symbols['af_ctor_bootstrap_start'],symbols['af_ctor_bootstrap_end']
    require(symbols['af_bootstrap_start']==start and symbols['af_bootstrap_end']==ctor_start and
            ctor_start-start==396 and ctor_end-ctor_start==400 and ctor_end==end,'双启动垫片固定范围不符')
    require(raw[start:end]==bytes(end-start),'启动尾部已占用')
    for s in ap.elf.iter_segments():
        if s['p_type']=='PT_LOAD' and s['p_offset']:
            require(s['p_offset']>=end and s['p_vaddr']>=end,'启动尾部与LOAD重叠')
    for s in ap.elf.iter_sections():
        if s['sh_size'] and s['sh_type']!='SHT_NOBITS':
            require(s['sh_offset']>=end or s['sh_offset']+s['sh_size']<=start,'启动尾部与section重叠')
        if s['sh_type']=='SHT_RELA':
            require(all(not(start<=r['r_offset']<end or start<=r['r_addend']<end) for r in s.iter_relocations()),'启动尾部已有重定位')
        if s['sh_type'] in ('SHT_SYMTAB','SHT_DYNSYM'):
            for sym in s.iter_symbols():
                a,n=int(sym['st_value']),int(sym['st_size'])
                require(not(start<=a<end) and (not n or a+n<=start or a>=end),'启动尾部已有符号')
    require(ap.read(0x16da8f0,16)==bytes.fromhex('901502d0116a45f910422b9120021fd6'),'dlopen PLT前像不符')
    require(ap.read(0x16dac90,16)==bytes.fromhex('901502d0115246f91082329120021fd6'),'dlsym PLT前像不符')
    phfields=[int(ap.elf['e_phoff'])+32,int(ap.elf['e_phoff'])+40]
    # 默认只作冲突对照；显式合并时统一两份计划的RX长度字段。
    file_patches=[]
    file_patches+=[dict(offset=start,before=raw[start:ctor_start].hex(),after=shim_image.read(start,ctor_start-start).hex(),reason='PIC bootstrap in verified RX tail'),
        dict(offset=ap.offset(0x17feac0,4),before=ap.read(0x17feac0,4).hex(),after=branch(0x17feac0,start).hex(),reason='Application_System_Init entry')]
    ctor_pointer=0x5020388;ctor_pointer_file=ap.offset(ctor_pointer,8);rela=0x10c58
    init=ap.elf.get_section_by_name('.init_array')
    require(init is not None and int(init['sh_addr'])+104*8==ctor_pointer and
            int(init['sh_size'])==370*8 and struct.unpack('<Q',ap.read(ctor_pointer,8))[0]==0x16fbfc0 and
            struct.unpack_from('<QQq',raw,rela)==(ctor_pointer,1027,0x16fbfc0),'原构造器及RELATIVE身份不符')
    file_patches += [dict(offset=ctor_start,before=raw[ctor_start:ctor_end].hex(),after=shim_image.read(ctor_start,ctor_end-ctor_start).hex(),reason='constructor observer bootstrap'),
        dict(offset=ctor_pointer_file,before=raw[ctor_pointer_file:ctor_pointer_file+8].hex(),after=struct.pack('<Q',ctor_start).hex(),reason='init_array[104] pointer'),
        dict(offset=rela+16,before=raw[rela+16:rela+24].hex(),after=struct.pack('<Q',ctor_start).hex(),reason='existing init_array[104] RELATIVE addend')]
    file_patches +=[dict(offset=at,before=raw[at:at+8].hex(),after=struct.pack('<Q',end).hex(),reason='combined RX extent') for at in phfields]
    marker_metadata=None
    if args.include_photo_markers:
        file_patches,marker_metadata=compose_plan(raw,file_patches)
        validate_plan(file_patches,marker_metadata)
        for name in marker_metadata['source_sha256']:
            before[name]=digest(ROOT/name)
            watched.append(ROOT/name)
    staged_ap=compose(raw,AP_SHA,file_patches)
    # 仅输出补丁JSON，不输出AP；DSO入口尚未安装时此shim禁止交付给更新器。
    ui=args.ui.resolve();integration=json.loads(args.ui_receipt.read_text())
    require(integration['status']=='PASS_SOFTWARE_BUILD_AND_HOST_CONTRACTS' and
            integration.get('source_unchanged',True),'UI构建回执状态不符')
    recipe_pairing(dict(recipe_bridge_enabled=args.recipe_bridge),integration)
    require(digest(ui)==integration['artifacts']['dynamic/ap-ui.elf']['sha256'],'固定UI产物来源不符')
    for name in [str((NATIVE/n).relative_to(ROOT)) for n in ('af_ap_ui.c','af_ap_ui.S','af_ap_ui.h')]:
        require(integration['source_sha256'][name]==digest(ROOT/name),'UI源码较输入回执变化')
    hooks=hooks_from_source(FEATURE/'a7filters/ap_ui_hooks.py');layouts=[]
    dyn=dynamic(module.read_bytes(),'af_ap_hs_gate')
    binding_checks=[]
    at=dyn['symbols']['af_ap_requests_checks']
    for i in range(16):
        values=struct.unpack('<5I',dyn['image'].read(at+20*i,20));offset=values[0]
        require(ap.read(offset,16)==struct.pack('<4I',*values[1:]),'绑定PLT/返回原16B失配')
        binding_checks.append(dict(offset=offset,preimage=ap.read(offset,16).hex()))
    for base in (0x4000000000,0x7000000000):
        plan=runtime_plan(raw,ui.read_bytes(),base,base+0xa000000,base+0x8f00000,hooks)
        combined=compose(raw,AP_SHA,[*aspect_receipt['patches'],*plan['patches']])
        relocated,exits=exit_plan(module.read_bytes(),base,base+0xa080000)
        # 只构造接收/解析两个入口的最终分支计划；没有向CP或AP文件应用。
        requests=[]
        for a,name in [(0x3554d90,'af_ap_hs_gate'),(0x3554d38,'af_ap_runtime_gate')]:
            requests.append(dict(offset=ap.offset(a,4),before=ap.read(a,4).hex(),
                after=branch(base+a,base+0xa080000+dyn['symbols'][name]).hex(),name=name))
        compose(raw,AP_SHA,[*aspect_receipt['patches'],*plan['patches'],*requests])
        # 实际文件组合计划也必须与后续UI／通信挂点互不覆盖。
        compose(raw,AP_SHA,[*file_patches,*plan['patches'],*requests])
        layouts.append(dict(ap_base=base,ui_base=base+0xa000000,request_base=base+0xa080000,
            ui_plan=plan,request_inbound=requests,request_exit_patches=exits,
            memory_only_combined_sha256=sha(combined),memory_only_requests_sha256=sha(relocated)))
    after={str(p.relative_to(ROOT)):digest(p) for p in watched}
    require(before==after,'构建期间源码变化')
    result=dict(status='PASS_STATIC_BINDING_AND_COMPOSITE_PLAN_ONLY',source_sha256=before,source_unchanged=True,
        source_cpio_sha256=CPIO_SHA,source_ap_sha256=AP_SHA,ui_source_checks=len(checks),ui_hooks=len(hooks),
        ui_input=dict(path=str(ui),sha256=digest(ui),receipt=str(args.ui_receipt.resolve()),receipt_sha256=digest(args.ui_receipt)),
        aspect=dict(source_sha256=AP_SHA,target_sha256=sha(aspect_raw),patch_count=len(aspect_receipt['patches']),
                    reserved_file_range=[aspect.START,aspect.END],no_new_pages=True),
        bootstrap=dict(path=str(shim.relative_to(ROOT)),sha256=digest(shim),reserved_file_range=[start,end],
            bytes=end-start,ctor_file_range=[ctor_start,ctor_end],rx_end=end,
            init_array=dict(index=104,pointer_va=ctor_pointer,pointer_file_offset=ctor_pointer_file,
                            original_target=0x16fbfc0,rela_file_offset=rela),
            no_new_pages=True,dlopen=0x16da8f0,dlsym=0x16dac90,application_init=0x17feac0,
            payload_path='/usr/lib/libaf_bootstrap406.so',payload_symbol='af_bootstrap406',
            memory_only_candidate_ap_sha256=sha(staged_ap),file_patch_plan=file_patches,
            includes_aspect_changes=args.include_photo_markers,aspect_merge=marker_metadata,
            entry_implemented=True,installed=False),
        module=dict(path=str(module.relative_to(ROOT)),bytes=module.stat().st_size,sha256=digest(module),
                    type='ET_DYN',segments=dyn['segments'],relative_relocations=len(dyn['relocations']),
                    imports=11,full_state_single_branch_exits=4,ap_absolute_imports=0,
                    binding_source_windows=binding_checks,
                    release_preset_exported='af_ap_runtime_release_preset' in dyn['symbols']),
        layouts=layouts,commands=commands,installable_firmware=False,firmware_written=False,
        bootstrap_installed=False,storage_namespace_selected=False,hardware_simulation=False,camera_io=False,
        recipe_bridge_enabled=args.recipe_bridge,
        blockers=['启动器和原登记观察已实现；产品准入生产者未闭合，publish默认拒绝',
                  '机内父目录与双卡Fsys提供者已接线；实际介质/容量/掉电和旧六迁移未验',
                  '同版完整颜色模型、CP同次身份/最终消费及EVF/JPG/最后引用仍未闭合',
                  '新增DSO与70资源可组合为未签名USR；安装DAT及真实设备验收未获准入'])
    (out/'verification.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps({k:v for k,v in result.items() if k in ('status','module','ui_hooks','ui_source_checks','installable_firmware')},ensure_ascii=False,indent=2))

if __name__=='__main__':main()
