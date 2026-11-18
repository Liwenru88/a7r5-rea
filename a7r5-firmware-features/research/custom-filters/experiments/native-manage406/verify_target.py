"""锁定原AP注册器／确认分派与管理模块联验；不是完整Qt或持久化验收。"""
from pathlib import Path
import hashlib
import importlib.util
import io
import json
import shutil
import struct
import subprocess
import sys

FEATURE=Path(__file__).resolve().parents[2]
ROOT=FEATURE.parents[1]
NATIVE=FEATURE/'native'
OUT=ROOT/'.local/fixed-custom-filters/continuation28-menu/original-main-catalog-v9'
sys.path[:0]=[str(FEATURE),str(ROOT/'a7r5-qemu/tools')]
from elftools.elf.elffile import ELFFile
from media_candidate import extract
from unicorn import arm64_const as r


def build():
    OUT.mkdir(parents=True,exist_ok=True)
    objects=[]
    for name in ('af_slots.c','af_ap_manage.c'):
        target=OUT/(name+'.o')
        subprocess.run([shutil.which('clang'),'--target=aarch64-none-elf','-std=c11','-O2',
            '-fPIC','-ffreestanding','-fno-builtin','-fno-stack-protector','-Wall','-Wextra','-Werror',
            '-I'+str(NATIVE),'-c',str(NATIVE/name),'-o',str(target)],check=True,capture_output=True,text=True)
        objects.append(str(target))
    script=OUT/'manage.ld'
    script.write_text((NATIVE/'af_ap_ui_dynamic.ld').read_text().replace('ENTRY(af_ap_register)','ENTRY(af_ap_manage_init)'))
    target=OUT/'manage.elf'
    subprocess.run([shutil.which('ld.lld') or '/opt/homebrew/opt/lld/bin/ld.lld','-shared','-Bsymbolic',
        '--no-undefined','-z','max-page-size=4096','-T',str(script),*objects,'-o',str(target)],
        check=True,capture_output=True,text=True)
    return target.read_bytes()


def verify(module):
    source=ROOT/'a7r5-qemu/build/aspect-guide406-20261026-01/source-02/source.cpio'
    expected='c01948220e1cced7f4e1d6a6dd28221c587050214d32cc405291cc00d2f1ed80'
    assert not source.is_symlink()
    with source.open('rb') as stream:assert hashlib.file_digest(stream,'sha256').hexdigest()==expected
    files=['usr/lib/appFw.so','usr/lib/libstdc++.so.6.0.22','usr/lib/libObj.so']
    raw=extract(source,files)
    spec=importlib.util.spec_from_file_location('manage_native_runtime',FEATURE/'experiments/native-ui406/runtime.py')
    runtime=importlib.util.module_from_spec(spec);spec.loader.exec_module(runtime)
    m=runtime.ShiftedRegistry(*(raw[name] for name in files),0x7000000000)
    u,base,work=m.u,m.base,m.work
    module_base=0x7100000000
    elf=ELFFile(io.BytesIO(module));pages=set()
    for segment in elf.iter_segments():
        if segment['p_type']!='PT_LOAD':continue
        start=module_base+segment['p_vaddr'];end=start+segment['p_memsz']
        for page in range(start&~4095,(end+4095)&~4095,4096):
            assert page not in pages;u.mem_map(page,4096,3);pages.add(page)
        u.mem_write(start,segment.data())
    symbols={s.name:module_base+s['st_value'] for s in elf.get_section_by_name('.symtab').iter_symbols()
             if s.name and s['st_shndx']!='SHN_UNDEF'}
    for section in elf.iter_sections():
        if section['sh_type']=='SHT_RELA':
            for rel in section.iter_relocations():
                assert rel['r_info_type']==1027
                u.mem_write(module_base+rel['r_offset'],struct.pack('<Q',module_base+rel['r_addend']))
    for segment in elf.iter_segments():
        if segment['p_type']!='PT_LOAD':continue
        start=module_base+segment['p_vaddr'];end=start+segment['p_memsz']
        u.mem_protect(start&~4095,((end+4095)&~4095)-(start&~4095),1|(2 if segment['p_flags']&2 else 4))
    def call(name,*args):return m.call(symbols[name],*args)
    def word(address):return struct.unpack('<Q',u.mem_read(address,8))[0]
    def count(tree):return word(tree+0x28)
    rows,descriptors,parents,secondary,reverse=work+0x100,work+0x200,work+0x300,work+0x400,work+0x500
    # 加入原5591项二级身份树，显式扩大已声明分配器预算至2MiB。
    u.mem_map(m.heap_end,0x100000,3);m.heap_end+=0x100000
    trees=((rows,0x5915b80,0x1c91e94,0x5030590,0x5046300),
           (descriptors,0x59611f8,0x1c91c40,0x502a980,0x5030590),
           (parents,0x593fbd8,0x1c935e0,0x3e44de0,0x3e47f88),
           (secondary,0x59430d0,0x1c938a8,0x3e47f88,0x3e52e40),
           (reverse,0x5959e80,0x1c933ec,0x3e41c38,0x3e44de0))
    for tree,global_offset,constructor,begin,end in trees:
        m.initialize_tree(tree);m.map_ap(global_offset);u.mem_write(base+global_offset,struct.pack('<Q',tree))
        m.call(base+constructor,tree,base+begin,base+end)
    before_counts=[count(tree) for tree,_,_,_,_ in trees]
    assert before_counts==[5591,1473,1589,5591,1589]
    source_parent=m.ap.read(0x3fe4980,7*128)
    for offset in range(0x5049000,0x5061000,4096):m.map_ap(offset)
    source_main=bytes(u.mem_read(base+0x5049d80,0x17088))
    m.map_ap(0x594a7b0)
    m.map_ap(0x5858b08);creative_descriptor=bytes(u.mem_read(base+0x5858b08,0xc0))
    catalog,manager=work+0x10000,work+0x14000
    binding,preset=work+0x600,work+0x15600
    call('af_catalog_init',catalog);call('af_ap_manage_init',manager)
    u.mem_write(preset,struct.pack('<BB8b32s32s',0,0,0,0,0,0,0,0,3,0,bytes(32),bytes(32)))
    assert call('af_install',catalog,7,preset,0)==0
    assert call('af_edit',catalog,7,0,3)==0
    catalog_before=bytes(u.mem_read(catalog,6888))
    u.mem_write(binding,struct.pack('<IIQQQ',1,32,base,manager,catalog))
    assert call('af_ap_manage_menu_bind',binding)==0
    assert call('af_ap_manage_menu_register')==0
    assert [count(tree) for tree,_,_,_,_ in trees]==[5596,1474,1590,5596,1590]
    assert call('af_ap_manage_menu_register')==-4
    assert call('af_ap_manage_menu_enable',1)==0
    m.map_ap(0x5895280)
    parent_pointer=word(base+0x5895280+0x58)
    assert parent_pointer==base+0x3fe4980 and bytes(u.mem_read(parent_pointer,7*128))==source_parent
    main_pointer=word(base+0x594a7b0)
    main=bytes(u.mem_read(main_pointer,0x17088))
    group=0x5053628-0x5049d80
    changed=set(range(group+8,group+12))|set(range(group+0x10+7*24,group+0x10+8*24))
    assert all(a==b for i,(a,b) in enumerate(zip(source_main,main)) if i not in changed)
    assert struct.unpack_from('<I',main,group+8)[0]==8
    assert struct.unpack_from('<I',main,group+0x10+7*24)[0]==0x637
    management_descriptor=word(main_pointer+group+0x18+7*24)
    assert word(main_pointer+group+0x20+7*24)==0
    assert m.call(base+0x1bd2020,0,0x637)==0x15e7
    assert bytes(u.mem_read(base+0x5858b08,0xc0))==creative_descriptor
    key=work+0x700
    registered=[]
    for menu in range(0x15e7,0x15ec):
        u.mem_write(key,struct.pack('<I',menu));assert m.call(base+0x1bd906c,rows,key)==1
        pointer=word(m.call(base+0x1bd90c4,rows,key))
        assert struct.unpack('<II',u.mem_read(pointer,8))==(menu,menu)
        assert call('af_ap_manage_menu_name',menu)==0x7fcb0001+menu-0x15e7
        registered.append({'menu':hex(menu),'row':hex(pointer)})
        if menu==0x15e7:
            assert list(struct.unpack('<20H',u.mem_read(pointer+0x44,40)))==[int(i==16) for i in range(20)]
            assert struct.unpack('<I',u.mem_read(pointer+0x30,4))[0]==0
    # 明确的外部边界：菜单资格与逻辑页回调。树查询／确认／高亮分派不替换。
    obj,vt=work+0x800,work+0x1000
    u.mem_write(obj,struct.pack('<Q',vt))
    for offset,callback in ((0x208,work+0xa000),(0x250,work+0xa008),(0x328,work+0xa010)):
        u.mem_write(vt+offset,struct.pack('<Q',callback))
    m.extra[work+0xa000]=lambda cpu:1
    m.extra[work+0xa008]=lambda cpu:0
    m.extra[work+0xa010]=lambda cpu:0x15e7
    m.map_ap(0x591f9a8);u.mem_write(base+0x591f9a8,struct.pack('<Q',vt-16))
    # 真实主菜单单项消费：原产品型号缓存23/列16来自本批同源客体只读观测。
    # mode2沿原产品资格和私有描述符+70；没有替代原注册树或反向查询。
    u.mem_write(vt+0x748,struct.pack('<Q',base+0x1bd2020))
    m.map_ap(0x598e7a8);u.mem_write(base+0x598e7a8,struct.pack('<I',23))
    out,counter,total=work+0x900,work+0x960,work+0x964
    u.mem_write(counter,bytes(8))
    assert m.call(base+0x1bcb384,obj,main_pointer+group+0x10+7*24,2,out,counter,total)==1
    assert struct.unpack('<II',u.mem_read(out,8))==(0x15e7,1)
    assert struct.unpack('<II',u.mem_read(counter,8))==(1,1)

    for menu in range(0x15e7,0x15ec):assert m.call(base+0x1bd8ee8,menu)==menu
    assert m.call(base+0x1bd8ee8,0x15d9)==0x2b36
    current=m.call(base+0x28a87e8);m.map_ap(current-base)
    u.mem_write(current,struct.pack('<I',0x15e8))
    assert call('af_ap_manage_menu_context',7)==0
    # 只证明确认入队；此能力声明为显式queue-only服务，绝不返回耐久成功。
    service=work+0x740
    u.mem_write(service,struct.pack('<IIQQII',1,32,work,work+0xa018,9,0))
    m.extra[work+0xa018]=lambda cpu:-21
    assert call('af_ap_manage_service_bind',service)==0
    for menu in range(0x15e8,0x15ec):
        m.call(base+0x1bd924c,obj,menu)
        assert bytes(u.mem_read(catalog,6888))==catalog_before
        # queued ticket在job开头；焦点变化必须保持无请求。
        assert word(manager+8)==0
    m.call(base+0x1bd924c,obj,0x15e8)
    m.call(base+0x1bd9348,obj,0x15e8)
    assert call('af_ap_manage_menu_result')==0 and word(manager+8)==1
    assert bytes(u.mem_read(catalog,6888))==catalog_before
    assert call('af_ap_manage_menu_enable',0)==-4
    assert call('af_ap_manage_cancel',manager,1)==0
    # 真实D4允许未发生+80预览就确认；不能要求不存在的高亮回调。
    assert call('af_ap_manage_menu_context',8)==0
    u.mem_write(current,struct.pack('<I',0x15eb))
    m.call(base+0x1bd9348,obj,0x15eb)
    assert call('af_ap_manage_menu_result')==0 and word(manager+8)==2
    assert bytes(u.mem_read(catalog,6888))==catalog_before
    assert call('af_ap_manage_cancel',manager,2)==0
    u.mem_write(current,struct.pack('<I',0x15e7))
    m.call(base+0x1bd9348,obj,0x15e8)
    assert call('af_ap_manage_menu_result')==-5 and word(manager+8)==2


    assert call('af_ap_manage_menu_enable',0)==0
    assert word(base+0x594a7b0)==base+0x5049d80
    assert word(base+0x5895280+0x58)==base+0x3fe4980
    assert struct.unpack('<I',u.mem_read(base+0x5895280+0x54,4))[0]==7
    assert m.redzones()
    return {'status':'PASS_ORIGINAL_AP_DISPATCH_ONLY','source_cpio_sha256':expected,
        'module_sha256':hashlib.sha256(module).hexdigest(),'module_bytes':len(module),
        'source_sha256':{name:hashlib.sha256(raw[name]).hexdigest() for name in files},
        'registry_counts_before':before_counts,'registry_counts_after':[count(tree) for tree,_,_,_,_ in trees],
        'new_rows':registered,'parent_original_seven_byte_exact':True,'main_catalog_original_bytes_preserved_except_new_entry':True,
        'main_catalog_section':'0x15','main_catalog_group_count':8,'reverse_descriptor_to_logical':'0x637→0x15e7','original_main_item_consumer_1bcb384_mode2':True,'creative_look_descriptor_unchanged':True,
        'creative_32_module_loaded':False,
        'original_highlight_entry':'0x1bd924c','highlight_no_job':4,
        'original_confirm_entry':'0x1bd9348','confirmed_save_queue_ticket':1,'confirm_create_without_preview_ticket':2,
        'catalog_bytes_unchanged_until_backend':True,'queued_cancel_and_parent_restore':True,
        'allocation_redzones_unchanged':True,'callee_saved_registers_checked':True,
        'secondary_new_management_self_maps':5,'secondary_creative_slots_still_skipped':True,
        'boundaries':['bounded allocator','menu qualification callbacks','logical-page callback','queue-only service capability, no storage completion',
                      'current-menu and C07 directory memory fixtures'],
        'qt_frame_verified':False,'new_sprite_labels_verified':False,'storage_or_cp_verified':False}


if __name__=='__main__':
    module=build();receipt=verify(module)
    (OUT/'original-menu-dispatch.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps(receipt,ensure_ascii=False))
