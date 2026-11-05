"""锁定原AP注册器／确认分派与目标槽选择模块联验；不是完整Qt或持久化验收。"""
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
OUT=ROOT/'.local/fixed-custom-filters/overwrite30/original-targets-v2'
sys.path[:0]=[str(FEATURE),str(ROOT/'a7r5-qemu/tools')]
from elftools.elf.elffile import ELFFile
from media_candidate import extract
from unicorn import arm64_const as r


def build():
    OUT.mkdir(parents=True,exist_ok=False)
    objects=[]
    for name in ('af_slots.c','af_ap_targets.c'):
        target=OUT/(name+'.o')
        subprocess.run([shutil.which('clang'),'--target=aarch64-none-elf','-std=c11','-O2',
            '-fPIC','-ffreestanding','-fno-builtin','-fno-stack-protector','-Wall','-Wextra','-Werror',
            '-I'+str(NATIVE),'-c',str(NATIVE/name),'-o',str(target)],check=True,capture_output=True,text=True)
        objects.append(str(target))
    script=OUT/'targets.ld'
    script.write_text((NATIVE/'af_ap_ui_dynamic.ld').read_text().replace('ENTRY(af_ap_register)','ENTRY(af_ap_targets_bind)'))
    target=OUT/'targets.elf'
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
    binding,catalog,preset=work+0x600,work+0x10000,work+0x18000
    choices=[];callback_result=[0]
    def chosen(cpu):
        assert cpu.reg_read(r.UC_ARM64_REG_X0)==work
        address=cpu.reg_read(r.UC_ARM64_REG_X1)
        choice=struct.unpack('<IIQ4I',u.mem_read(address,32));assert choice[:2]==(2,512);choices.append(choice)
        packet=bytes(u.mem_read(address,512));assert len(packet)==512
        return callback_result[0]
    m.extra[work+0xa018]=chosen
    call('af_catalog_init',catalog)
    u.mem_write(preset,struct.pack('<BB8b32s32s',0,0,0,0,0,0,0,0,3,0,bytes(32),bytes(32)))
    assert call('af_install',catalog,7,preset,0)==0 and call('af_install',catalog,8,preset,0)==0
    before=bytes(u.mem_read(catalog,6888))
    u.mem_write(binding,struct.pack('<IIQQQQ',2,40,base,catalog,work,work+0xa018))
    assert call('af_ap_targets_bind',binding)==0
    assert call('af_ap_targets_register')==0
    assert [count(tree) for tree,_,_,_,_ in trees]==[5613,1474,1590,5613]
    assert call('af_ap_targets_enable',1)==0
    key=work+0x700;registered=[]
    for menu in range(0x15ec,0x1602):
        u.mem_write(key,struct.pack('<I',menu));assert m.call(base+0x1bd906c,rows,key)==1
        pointer=word(m.call(base+0x1bd90c4,rows,key))
        assert struct.unpack('<II',u.mem_read(pointer,8))==(menu,menu)
        assert m.call(base+0x1bd8ee8,menu)==menu
        assert bytes(u.mem_read(pointer+0x44,40))==struct.pack('<20H',*([1]*20))
        registered.append({'menu':hex(menu),'row':hex(pointer)})
    descriptor_key=work+0x760;u.mem_write(descriptor_key,struct.pack('<I',0x638))
    descriptor_ptr=word(m.call(base+0x1bd90c4,descriptors,descriptor_key))
    assert struct.unpack('<I',u.mem_read(descriptor_ptr+0x54,4))[0]==21
    # 这些是descriptor源行数，不足以独立证明实际呈现器21行容量。
    d4=[]
    for index in range(1473):
        ident,pointer=struct.unpack('<QQ',m.ap.read(0x502a980+index*16,16))
        if m.ap.u32(pointer+0x20)==0xd4 and m.ap.u32(pointer+0x54)>=21:
            d4.append({'descriptor':hex(ident),'rows':m.ap.u32(pointer+0x54)})
    assert d4
    obj,vt=work+0x800,work+0x1000;u.mem_write(obj,struct.pack('<Q',vt))
    for off,callback in ((0x208,work+0xa000),(0x210,work+0xa000),(0x1d8,work+0xa000),
                         (0x250,work+0xa008),(0x328,base+0x1bdb0b0),(0x790,base+0x1bd9f98)):
        u.mem_write(vt+off,struct.pack('<Q',callback))
    m.extra[work+0xa000]=lambda cpu:1;m.extra[work+0xa008]=lambda cpu:0
    m.map_ap(0x591f9a8);u.mem_write(base+0x591f9a8,struct.pack('<Q',vt-16))
    # 独立窗口把同样的私有层级/身份作为数据夹具交给原父树/主别名树，
    # 然后完整执行原parent wrapper与screen wrapper；不伪造335返回。
    logical,primary=work+0x500,work+0x580
    hierarchy=[(key,0x15e7 if key==0x15ec else 0x15ec) for key in range(0x15ec,0x1602)]+[(0x15e9,0x15e7),(0x15eb,0x15e7)]
    for tree,global_offset,constructor,pairs in ((logical,0x5968078,0x1c927e4,hierarchy),
            (primary,0x592f4c8,0x1c938a8,[(key,key) for key,_ in hierarchy])):
        m.initialize_tree(tree);m.map_ap(global_offset);u.mem_write(base+global_offset,struct.pack('<Q',tree))
        encoded=b''.join(struct.pack('<II',*pair) for pair in pairs);u.mem_write(work+0x1a000,encoded)
        m.call(base+constructor,tree,work+0x1a000,work+0x1a000+len(encoded))
    management_pairs=[]
    for index,key_value in enumerate((0x15e9,0x15eb)):
        address=work+0x1b000+index*128;data=bytearray(m.ap.read(0x3f52680,128))
        struct.pack_into('<II',data,0,key_value,key_value);struct.pack_into('<I',data,0x7c,0);u.mem_write(address,bytes(data))
        management_pairs.append((key_value,address))
    encoded=b''.join(struct.pack('<QQ',*pair) for pair in management_pairs);u.mem_write(work+0x1c000,encoded)
    m.call(base+0x1c91e94,rows,work+0x1c000,work+0x1c000+len(encoded))
    current=m.call(base+0x28a87e8);m.map_ap(current-base)
    current_page=m.call(base+0x28a88ac);m.map_ap(current_page-base)
    for getter in (0x28a87fc,0x28a88c0):
        address=m.call(base+getter);m.map_ap(address-base);u.mem_write(address,bytes(8))
    journals=[];notifications=[];locks=[]
    def journal(cpu):
        assert cpu.reg_read(r.UC_ARM64_REG_X0)==0 and cpu.reg_read(r.UC_ARM64_REG_X4)==4
        journals.append(cpu.reg_read(r.UC_ARM64_REG_X1));return 0
    m.extra[base+0x3694f64]=journal
    m.extra[base+0x252d80c]=lambda cpu:notifications.append(cpu.reg_read(r.UC_ARM64_REG_X0)) or 0
    m.extra[base+0x2e7d208]=lambda cpu:locks.append('enter') or 0
    m.extra[base+0x2e7cee4]=lambda cpu:locks.append('leave') or 0
    def context(menu):u.mem_write(current,struct.pack('<I',menu));u.mem_write(current_page,struct.pack('<I',0x335))
    def apply(menu,permit=False):
        u.mem_write(current,struct.pack('<I',menu))
        if permit:assert call('af_ap_targets_intent',menu)==0
        m.call(base+0x1bd9348,obj,menu)
    def target(slot):return 0x15ed+slot-1
    original_690=m.call(base+0x28ae4b0);m.map_ap(original_690-base);original_value=bytes(u.mem_read(original_690,4))
    context(0x15e9);assert call('af_ap_targets_begin',2,7,1)==0
    assert call('af_ap_targets_show')==0
    assert struct.unpack('<I',u.mem_read(current,4))[0]==target(9)
    assert struct.unpack('<I',u.mem_read(current_page,4))[0]==0x335
    # 真实原泛用枚举器遍历21行；可见资格仅为该窗口的显式边界，禁选由模块确认保证。
    u.mem_write(vt+0x10,struct.pack('<Q',work+0xa020));u.mem_write(vt+0x1a8,struct.pack('<Q',work+0xa028))
    m.extra[work+0xa020]=lambda cpu:descriptor_ptr;m.extra[work+0xa028]=lambda cpu:1
    output=work+0x19000;u.mem_write(output-8,bytes([0xa5])*100)
    assert m.call(base+0x1bcf3fc,obj,0x15ec,output,21)==21
    assert list(struct.unpack('<21I',u.mem_read(output,84)))==list(range(0x15ed,0x1602))
    assert bytes(u.mem_read(output-8,8))==bytes([0xa5])*8 and bytes(u.mem_read(output+84,8))==bytes([0xa5])*8
    apply(target(1),True);apply(target(8));assert call('af_ap_targets_result')==-3 and not choices
    old_token=call('af_ap_targets_name',target(20))
    apply(target(20),True);assert choices==[(2,512,1,2,7,20,0)]
    assert call('af_ap_targets_result')==0 and call('af_ap_targets_back')==0
    assert struct.unpack('<I',u.mem_read(current,4))[0]==0x15e9
    assert bytes(u.mem_read(catalog,6888))==before
    assert call('af_ap_targets_begin',2,7,2)==0 and call('af_ap_targets_show')==0
    call('af_ap_targets_focus',old_token);u.mem_write(current,struct.pack('<I',target(19)))
    assert call('af_ap_targets_intent',target(20))==-5
    m.call(base+0x1bd9348,obj,target(20));assert len(choices)==1
    apply(0x1601,True);assert call('af_ap_targets_result')==-23 and call('af_ap_targets_back')==0
    context(0x15eb);assert call('af_ap_targets_begin',4,0,3)==0 and call('af_ap_targets_show')==0
    apply(target(9),True);assert choices[-1]==(2,512,3,4,0,9,0)
    assert call('af_ap_targets_back')==0
    # 同一ROOT换为两行确认表，真实原枚举与原current匹配返回默认Cancel。
    context(0x15e9);assert call('af_ap_targets_begin',2,7,4)==0 and call('af_ap_targets_show')==0
    apply(target(8),True);assert call('af_ap_targets_result')==-24 and len(choices)==2
    assert struct.unpack('<I',u.mem_read(descriptor_ptr+0x54,4))[0]==2
    assert m.call(base+0x1bcf3fc,obj,0x15ec,output,2)==2
    assert list(struct.unpack('<2I',u.mem_read(output,8)))==[0x1601,target(8)]
    for off,fn in ((0x2b8,0x1bc5038),(0x20,0x1bc8578)):u.mem_write(vt+off,struct.pack('<Q',base+fn))
    default=m.call(base+0x1bc50ec,obj,0x15ec);assert default==0x1601
    context(default);assert call('af_ap_targets_presented')==0
    apply(target(8),True);assert choices[-1]==(2,512,4,2,7,8,1)
    assert call('af_ap_targets_result')==0 and call('af_ap_targets_back')==0
    assert bytes(u.mem_read(catalog,6888))==before
    context(0x15e9);assert call('af_ap_targets_begin',2,7,5)==0 and call('af_ap_targets_show')==0
    assert call('af_edit',catalog,7,0,4)==0
    apply(target(20),True);assert call('af_ap_targets_result')==-5 and len(choices)==3
    assert call('af_ap_targets_cancel')==0 and call('af_ap_targets_back')==0
    context(0x15eb);assert call('af_ap_targets_begin',4,0,6)==0 and call('af_ap_targets_show')==0
    callback_result[0]=-6;apply(target(8),True);assert call('af_ap_targets_result')==-24
    context(0x1601);assert call('af_ap_targets_presented')==0
    apply(target(8),True);assert call('af_ap_targets_result')==-6 and len(choices)==4
    assert choices[-1]==(2,512,6,4,0,8,1) and call('af_ap_targets_back')==0
    context(0x15eb);assert call('af_ap_targets_begin',4,0,7)==0 and call('af_ap_targets_show')==0
    apply(target(8),True);context(0x1601);assert call('af_ap_targets_presented')==0
    apply(0x1601,True);assert call('af_ap_targets_result')==-23 and len(choices)==4
    assert call('af_ap_targets_back')==0
    assert all(notifications[i:i+2]==[0x3b7,0x3bc] for i in range(0,len(notifications),2))
    assert journals==notifications and len(locks)==len(notifications)*2
    assert bytes(u.mem_read(original_690,4))==original_value
    assert bytes(u.mem_read(base+0x5895280,192))==parent_descriptor
    assert bytes(u.mem_read(base+0x5858b08,192))==creative_descriptor and m.redzones()
    return {'status':'PASS_ORIGINAL_AP_TARGET_DISPATCH_ONLY','source_cpio_sha256':expected,
        'module_sha256':hashlib.sha256(module).hexdigest(),'module_bytes':len(module),
        'source_sha256':{name:hashlib.sha256(raw[name]).hexdigest() for name in files},
        'registry_counts_before':before_counts,'registry_counts_after':[count(tree) for tree,_,_,_,_ in trees],
        'new_rows':registered,'original_D4_larger_lists':d4,'target_rows':21,
        'original_enum':'0x1bcf3fc','original_highlight':'0x1bd924c','original_apply':'0x1bd9348; explicit ENTER intent is separately provided in this window',
        'chosen_callbacks':choices,'legacy_six_refused':True,'occupied_requires_second_confirmation':True,'confirmation_rows':2,'original_current_default_cancel':True,'choice_version':2,'choice_bytes':512,'cancel_no_callback':True,
        'stale_generation_token_refused':True,'source_changed_refused':True,'first_empty_direct_confirm':True,
        'callback_failure_not_saved':True,'COPY_source_preserved':True,'selection_did_not_change_catalog':True,
        'empty_target_without_preview':True,'strict_current_menu_no_ROOT_fallback':True,
        'original_parent_wrapper':'0x1bdb214','original_screen_wrapper':'0x1bd6384',
        'screen_335_produced_by_original_row_query':True,
        'original_UI_navigation_properties':['0x3b7','0x3bc'],'notifications':list(map(hex,notifications)),
        'original_690_unchanged':True,'original_parent_and_creative_descriptor_unchanged':True,
        'allocation_redzones_unchanged':True,'callee_saved_registers_checked':True,
        'boundaries':['bounded2MiBallocator','catalog/source and current UI model inputs','private identity/parent data fixture, original tree execution','menu/enum qualification','chosen receiver returns explicit status, no queue','transaction locks/journal and notification transport'],
        'not_proven':['actual D4 21-row presenter capacity','full picker page rebuild/frame','same-ID delayed input epoch (not carried by original ABI); confirmation defaults Cancel'],
        'GUI_verified':False,'actual_persistence_verified':False,'camera_io':False}
if __name__=='__main__':
    module=build();receipt=verify(module)
    (OUT/'original-targets-dispatch.json').write_text(json.dumps(receipt,indent=2,ensure_ascii=False)+'\n')
    print(json.dumps({'status':receipt['status'],'registry_counts_after':receipt['registry_counts_after'],'choices':receipt['chosen_callbacks'],'rows':receipt['target_rows']},ensure_ascii=False))
