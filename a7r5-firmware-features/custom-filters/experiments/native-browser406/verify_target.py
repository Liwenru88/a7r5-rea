"""锁定原AP注册器／确认分派与只读文件浏览模块联验；不是完整Qt或持久化验收。"""
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
OUT=ROOT/'.local/fixed-custom-filters/continuation29-browser'
sys.path[:0]=[str(FEATURE),str(ROOT/'a7r5-qemu/tools')]
from elftools.elf.elffile import ELFFile
from media_candidate import extract
from unicorn import arm64_const as r


def build():
    OUT.mkdir(parents=True,exist_ok=True)
    objects=[]
    for name in ('af_ap_browser.c',):
        target=OUT/(name+'.o')
        subprocess.run([shutil.which('clang'),'--target=aarch64-none-elf','-std=c11','-O2',
            '-fPIC','-ffreestanding','-fno-builtin','-fno-stack-protector','-Wall','-Wextra','-Werror',
            '-I'+str(NATIVE),'-c',str(NATIVE/name),'-o',str(target)],check=True,capture_output=True,text=True)
        objects.append(str(target))
    script=OUT/'browser.ld'
    script.write_text((NATIVE/'af_ap_ui_dynamic.ld').read_text().replace('ENTRY(af_ap_register)','ENTRY(af_ap_browser_bind)'))
    target=OUT/'browser.elf'
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
    rows,descriptors,parents,secondary=work+0x100,work+0x200,work+0x300,work+0x400
    # 四树完整原注册约1.4MiB，独立模拟分配器明确扩为2MiB；不改产品/客体。
    u.mem_map(m.heap_end,0x100000,3);m.heap_end+=0x100000
    trees=((rows,0x5915b80,0x1c91e94,0x5030590,0x5046300),
           (descriptors,0x59611f8,0x1c91c40,0x502a980,0x5030590),
           (parents,0x593fbd8,0x1c935e0,0x3e44de0,0x3e47f88),
           (secondary,0x59430d0,0x1c938a8,0x3e47f88,0x3e52e40))
    for tree,global_offset,constructor,begin,end in trees:
        m.initialize_tree(tree);m.map_ap(global_offset);u.mem_write(base+global_offset,struct.pack('<Q',tree))
        m.call(base+constructor,tree,base+begin,base+end)
    before_counts=[count(tree) for tree,_,_,_,_ in trees]
    assert before_counts==[5591,1473,1589,5591]
    source_parent=m.ap.read(0x3fe4980,7*128)
    m.map_ap(0x5858b08);creative_descriptor=bytes(u.mem_read(base+0x5858b08,0xc0))
    m.map_ap(0x5895280);parent_descriptor=bytes(u.mem_read(base+0x5895280,192))
    binding,list_address,output=work+0x600,work+0x10000,work+0x18000
    u.mem_write(binding,struct.pack('<IIQ',1,16,base))
    assert call('af_ap_browser_bind',binding)==0
    assert call('af_ap_browser_register')==0
    assert [count(tree) for tree,_,_,_,_ in trees]==[5659,1474,1590,5659]
    assert call('af_ap_browser_register')==-4
    assert call('af_ap_browser_enable',1)==0
    assert bytes(u.mem_read(base+0x5858b08,0xc0))==creative_descriptor
    key=work+0x700;registered=[]
    for menu in range(0x1620,0x1664):
        u.mem_write(key,struct.pack('<I',menu));assert m.call(base+0x1bd906c,rows,key)==1
        pointer=word(m.call(base+0x1bd90c4,rows,key))
        assert struct.unpack('<II',u.mem_read(pointer,8))==(menu,menu)
        assert m.call(base+0x1bd8ee8,menu)==menu
        registered.append({'menu':hex(menu),'row':hex(pointer),'secondary':hex(menu)})
    # 原parent/screen查询完整执行；仅资格服务和显式私有数据是边界。
    obj,vt=work+0x800,work+0x1000
    u.mem_write(obj,struct.pack('<Q',vt))
    for off,callback in ((0x208,work+0xa000),(0x210,work+0xa000),(0x1d8,work+0xa000),
                         (0x250,work+0xa008),(0x328,base+0x1bdb0b0),(0x790,base+0x1bd9f98)):
        u.mem_write(vt+off,struct.pack('<Q',callback))
    m.extra[work+0xa000]=lambda cpu:1
    m.extra[work+0xa008]=lambda cpu:0
    m.map_ap(0x591f9a8);u.mem_write(base+0x591f9a8,struct.pack('<Q',vt-16))
    logical,primary=work+0x500,work+0x580
    hierarchy=[(key,0x15e7 if key==0x1620 else 0x1620) for key in range(0x1620,0x1664)]+[(0x15ea,0x15e7)]
    for tree,global_offset,constructor,pairs in ((logical,0x5968078,0x1c927e4,hierarchy),
            (primary,0x592f4c8,0x1c938a8,[(key,key) for key,_ in hierarchy])):
        m.initialize_tree(tree);m.map_ap(global_offset);u.mem_write(base+global_offset,struct.pack('<Q',tree))
        encoded=b''.join(struct.pack('<II',*pair) for pair in pairs);u.mem_write(work+0x1a000,encoded)
        m.call(base+constructor,tree,work+0x1a000,work+0x1a000+len(encoded))
    data=bytearray(m.ap.read(0x3f52680,128));struct.pack_into('<II',data,0,0x15ea,0x15ea);struct.pack_into('<I',data,0x7c,0)
    u.mem_write(work+0x1b000,bytes(data));u.mem_write(work+0x1c000,struct.pack('<QQ',0x15ea,work+0x1b000))
    m.call(base+0x1c91e94,rows,work+0x1c000,work+0x1c010)
    current=m.call(base+0x28a87e8);m.map_ap(current-base)
    current_page=m.call(base+0x28a88ac);m.map_ap(current_page-base)
    meta_menu=m.call(base+0x28a87fc);m.map_ap(meta_menu-base)
    meta_page=m.call(base+0x28a88c0);m.map_ap(meta_page-base)
    u.mem_write(meta_menu,bytes(8));u.mem_write(meta_page,bytes(8))
    u.mem_write(current,struct.pack('<I',0x15ea));u.mem_write(current_page,struct.pack('<I',0x335))
    journals=[];notifications=[];locks=[]
    def journal(cpu):
        ident=cpu.reg_read(r.UC_ARM64_REG_X1);old=cpu.reg_read(r.UC_ARM64_REG_X2);new=cpu.reg_read(r.UC_ARM64_REG_X3)
        assert cpu.reg_read(r.UC_ARM64_REG_X4)==4 and cpu.reg_read(r.UC_ARM64_REG_X0)==0
        journals.append({'id':hex(ident),'old':struct.unpack('<I',u.mem_read(old,4))[0],'new':struct.unpack('<I',u.mem_read(new,4))[0]});return 0
    def notify(cpu):notifications.append(cpu.reg_read(r.UC_ARM64_REG_X0));return 0
    m.extra[base+0x3694f64]=journal;m.extra[base+0x252d80c]=notify
    m.extra[base+0x2e7d208]=lambda cpu:locks.append('enter') or 0
    m.extra[base+0x2e7cee4]=lambda cpu:locks.append('leave') or 0
    def highlight(menu):
        # 原D4控制器先更新3b7再调用预览分派；此窄实验显式提供该外层状态。
        u.mem_write(current,struct.pack('<I',menu));m.call(base+0x1bd924c,obj,menu)

    def make_list(generation,count):
        result=struct.pack('<QQQI4x',generation,3,44,count)
        for index in range(64):
            name=('file%02d.cube'%index).encode() if index<count else bytes()
            result+=struct.pack('<128sQQQqq',name,3,100+index,64,1,0)
        return result
    def text(pointer):return bytes(u.mem_read(pointer,128)).split(bytes([0]))[0].decode()
    original_690=m.call(base+0x28ae4b0);m.map_ap(original_690-base)
    original_value=bytes(u.mem_read(original_690,4))
    media_raw=make_list(11,64);u.mem_write(list_address,media_raw)
    assert call('af_ap_browser_publish',list_address)==0
    assert bytes(u.mem_read(list_address,len(media_raw)))==media_raw
    assert call('af_ap_browser_show')==0
    assert struct.unpack('<I',u.mem_read(current,4))[0]==0x1621 and struct.unpack('<I',u.mem_read(current_page,4))[0]==0x335
    assert notifications==[0x3b7,0x3bc] and locks==['enter','leave','enter','leave']
    first_token=call('af_ap_browser_name',0x1621)
    assert text(call('af_ap_browser_text',first_token))=='file00.cube'
    descriptor_key=work+0x760;u.mem_write(descriptor_key,struct.pack('<I',0x639))
    descriptor_ptr=word(m.call(base+0x1bd90c4,descriptors,descriptor_key))
    def check_page(page,files,total):
        assert call('af_ap_browser_page')==page and call('af_ap_browser_rows')==total
        assert struct.unpack('<I',u.mem_read(descriptor_ptr+0x54,4))[0]==total
        page_rows=word(descriptor_ptr+0x58)
        actual=[struct.unpack('<I',u.mem_read(page_rows+i*128,4))[0] for i in range(total)]
        expected=list(range(0x1621+page*17,0x1621+page*17+files))
        if page:expected.append(0x1661)
        if page<3:expected.append(0x1662)
        expected.append(0x1663);assert actual==expected
        return {'page':page,'files':files,'total_rows':total,'menus':list(map(hex,actual))}
    pages=[check_page(0,17,19)]
    # 原高亮并不选择/入队；只有原确认才返回同代index。
    for page in range(1,4):
        u.mem_write(current,struct.pack('<I',0x1662))
        assert call('af_ap_browser_take',11,output)==-2
        m.call(base+0x1bd9348,obj,0x1662)
        assert call('af_ap_browser_show')==0
        pages.append(check_page(page,17 if page<3 else 13,20 if page<3 else 15))
    u.mem_write(current,struct.pack('<I',0x1660))
    assert call('af_ap_browser_take',11,output)==-2
    m.call(base+0x1bd9348,obj,0x1660)
    assert call('af_ap_browser_result')==0
    assert call('af_ap_browser_back')==0
    assert struct.unpack('<I',u.mem_read(current,4))[0]==0x15ea and struct.unpack('<I',u.mem_read(current_page,4))[0]==0x335
    u.mem_write(output,bytes([0xa5])*16)
    assert call('af_ap_browser_take',10,output)==-5 and bytes(u.mem_read(output,16))==bytes([0xa5])*16
    assert call('af_ap_browser_take',11,output)==0
    assert struct.unpack('<QII',u.mem_read(output,16))==(11,63,0)
    assert call('af_ap_browser_take',11,output)==-2
    u.mem_write(list_address,make_list(12,2));assert call('af_ap_browser_publish',list_address)==0
    assert call('af_ap_browser_show')==0
    assert text(call('af_ap_browser_text',first_token))=='List changed'
    call('af_ap_browser_focus',first_token)
    u.mem_write(current,struct.pack('<I',0x1622))
    m.call(base+0x1bd9348,obj,0x1621);assert call('af_ap_browser_result')==-5
    highlight(0x1663);m.call(base+0x1bd9348,obj,0x1663)
    assert call('af_ap_browser_result')==-22 and call('af_ap_browser_take',12,output)==-2
    assert call('af_ap_browser_back')==0
    # 同一原setter的影子属性通路也执行，不以本地手写通知代替。
    u.mem_write(meta_menu,struct.pack('<Q',work+0x19000));u.mem_write(meta_page,struct.pack('<Q',work+0x19008))
    u.mem_write(list_address,make_list(13,0));assert call('af_ap_browser_publish',list_address)==0
    assert call('af_ap_browser_show')==0
    assert struct.unpack('<I',u.mem_read(work+0x19000,4))[0]==0x1663
    assert struct.unpack('<I',u.mem_read(work+0x19008,4))[0]==0x335
    assert call('af_ap_browser_cancel')==0 and call('af_ap_browser_back')==0
    assert struct.unpack('<I',u.mem_read(work+0x19000,4))[0]==0x15ea
    assert struct.unpack('<I',u.mem_read(work+0x19008,4))[0]==0x335
    # 不转动转盘，刚呈现的首文件也能直接由原确认分派选中。
    u.mem_write(list_address,make_list(14,2));assert call('af_ap_browser_publish',list_address)==0
    assert call('af_ap_browser_show')==0
    m.call(base+0x1bd9348,obj,0x1621)
    assert call('af_ap_browser_result')==0 and call('af_ap_browser_back')==0
    assert call('af_ap_browser_take',14,output)==0
    assert struct.unpack('<QII',u.mem_read(output,16))==(14,0,0)
    assert all(notifications[i:i+2]==[0x3b7,0x3bc] for i in range(0,len(notifications),2))
    assert len(locks)==len(notifications)*2
    assert bytes(u.mem_read(original_690,4))==original_value
    assert bytes(u.mem_read(base+0x5895280,192))==parent_descriptor
    assert bytes(u.mem_read(base+0x5858b08,0xc0))==creative_descriptor and m.redzones()
    return {'status':'PASS_ORIGINAL_AP_DISPATCH_ONLY','source_cpio_sha256':expected,
        'module_sha256':hashlib.sha256(module).hexdigest(),'module_bytes':len(module),
        'source_sha256':{name:hashlib.sha256(raw[name]).hexdigest() for name in files},
        'registry_counts_before':before_counts,'registry_counts_after':[count(tree) for tree,_,_,_,_ in trees],
        'new_rows':registered,'pages':pages,'original_highlight_entry':'0x1bd924c',
        'original_confirm_entry':'0x1bd9348','selection':{'generation':11,'index':63},
        'cancel_no_selection':True,'old_generation_no_output':True,'stale_token_rejected':True,'first_file_confirm_without_highlight_event':True,
        'confirmation_without_preview':True,'strict_current_menu_no_ROOT_fallback':True,
        'original_parent_wrapper':'0x1bdb214','original_screen_wrapper':'0x1bd6384',
        'screen_335_produced_by_original_row_query':True,
        'original_690_unchanged':True,'secondary_self_registration_and_original_resolver':68,'original_parent_and_creative_descriptor_unchanged':True,
        'allocation_redzones_unchanged':True,'callee_saved_registers_checked':True,
        'boundaries':['bounded allocator','private identity/parent data fixture, original tree execution','menu qualification','explicit64entry media snapshot','UI model current-menu/screen fixtures','transaction locks/journal envelope/notification transport'],
        'logical_D4_route':{'source':'0x21f41a8','menu_property':'0x3b7','target_screen_property':'0x3bc','original_setters':['0x21f3ed8','0x21f4130'],'journal_envelopes':journals,'notifications':list(map(hex,notifications)),'shadow_properties_verified':True,'physical_screen_manager_called':False},
        'not_proven':['full picker page rebuild/frame','same-ID delayed confirm epoch (not carried by original ABI)'],
        'actual_media_scan_verified':False,'qt_frame_verified':False,'new_sprite_labels_verified':False,
        'import_conversion_or_storage_success':False,'camera_io':False}

if __name__=='__main__':
    module=build();receipt=verify(module)
    (OUT/'original-browser-dispatch.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'status':receipt['status'],'registry_counts_after':receipt['registry_counts_after'],'pages':len(receipt['pages']),'selection':receipt['selection']},ensure_ascii=False))
