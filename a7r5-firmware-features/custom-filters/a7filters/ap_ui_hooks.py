"""只在匿名AP地址空间安装真实分支；不导出AP，不把模型结果称为原厂画面。"""
import hashlib
import io
import struct

from .access_evidence import AP_SHA, WORK, STACK, STOP, require_source, arm64_cpu
from .investigate import AP, PARAMETERS
from .ui_evidence import (RegistryMachine, STD_SHA, MENU_IDS, SELECTORS, ROW_TABLE,
                          ROW_BYTES, NEW_FIRST, candidate_rows)

HOOKS = [
    (0x16f6610,'af_ap_register',True,None),
    (0x1bd8eb8,'af_ap_alias',False,'af_stock_alias'),
    (0x1bd1ef8,'af_ap_alias_object',False,'af_stock_alias_object'),
    (0x1bd1b88,'af_ap_name',False,'af_stock_name'),
    (0x1bcfffc,'af_ap_visible',False,'af_stock_visible'),
    (0x23fcd48,'af_ap_display',False,'af_stock_display'),
    (0x2209580,'af_ap_inhibited',False,'af_stock_inhibited'),
    (0x220933c,'af_ap_direct',False,'af_stock_direct'),
    (0x1c6f208,'af_ap_select',False,'af_stock_select'),
    (0x25966cc,'af_ap_preview',False,'af_stock_preview'),
    (0x1c956c8,'af_ap_preview_menu',False,'af_stock_preview_menu'),
    (0x1e97a24,'af_ap_refresh',False,'af_stock_refresh'),
    (0x220a7ac,'af_ap_parameter_init',False,'af_stock_parameter_init'),
    (0x220ac74,'af_ap_base_cycle',False,'af_stock_base_cycle'),
    (0x220a898,'af_ap_init_index',True,None),
    (0x220a8c4,'af_ap_init_bases',True,None),
] + [(0x2209918+p*0x154,'af_ap_step_'+str(p),False,'af_stock_step_'+str(p)) for p in range(8)] + [
    (0x1bd18e8,'af_ap_icon',False,'af_stock_icon'),
    (0x1bd19e8,'af_ap_icon_alternate',False,'af_stock_icon_alternate'),
    (0x1bdb0b0,'af_ap_parent',False,'af_stock_parent'),
    (0x220b620,'af_ap_parameter_value',False,'af_stock_parameter_value'),
    (0x220b51c,'af_ap_parameter_disabled',False,'af_stock_parameter_disabled'),
    (0x220b708,'af_ap_parameter_default',False,'af_stock_parameter_default'),
    (0x220b89c,'af_ap_parameter_layout',False,'af_stock_parameter_layout'),
    (0x2209464,'af_ap_base_available',False,'af_stock_base_available'),
    (0x220c87c,'af_ap_base_label',True,None),
    (0x220c8dc,'af_ap_base_icon',True,None),
    (0x2208e8c,'af_ap_names_title',True,None),
    (0x220c8a0,'af_ap_names_title',True,None),
    (0x1885b38,'af_ap_names_sprite',True,None),
    (0x263d558,'af_ap_reset',False,'af_stock_reset'),
    (0x21f3608,'af_ap_confirm',False,'af_stock_confirm'),
    (0x21f3a4c,'af_ap_confirm_close',True,None),
    (0x21f99a4,'af_ap_names_title',True,None),
    (0x219750c,'af_ap_rename_done_0',True,None),
    (0x2199cc4,'af_ap_rename_done_1',True,None),
    (0x219c1ac,'af_ap_rename_done_2',True,None),
    (0x219e694,'af_ap_rename_done_3',True,None),
    (0x2197b5c,'af_ap_rename_leave_0',False,'af_stock_rename_leave_0'),
    (0x219a2ec,'af_ap_rename_leave_1',False,'af_stock_rename_leave_1'),
    (0x219c814,'af_ap_rename_leave_2',False,'af_stock_rename_leave_2'),
    (0x219ed00,'af_ap_rename_leave_3',False,'af_stock_rename_leave_3'),
    (0x2198040,'af_ap_rename_init_0',False,'af_stock_rename_init_0'),
    (0x219a808,'af_ap_rename_init_1',False,'af_stock_rename_init_1'),
    (0x219ccc0,'af_ap_rename_init_2',False,'af_stock_rename_init_2'),
    (0x219f21c,'af_ap_rename_init_3',False,'af_stock_rename_init_3'),
    (0x2199510,'af_ap_rename_title',True,None),
    (0x219b9e0,'af_ap_rename_title',True,None),
    (0x219e07c,'af_ap_rename_title',True,None),
    (0x21a0520,'af_ap_rename_title',True,None),
]
CALL_TARGETS = {0x16f6610:0x1c91e94,0x220a898:0x2dc6160,0x220a8c4:0x28c54cc,0x220c87c:0x1bd54d8,0x220c8dc:0x220b838,
                0x2208e8c:0x1bd5508,0x220c8a0:0x1bd5508,0x1885b38:0x16db4f0,0x21f3a4c:0x21edb2c,0x21f99a4:0x1bd5508, 0x219750c:0x219712c,0x2199cc4:0x21998ec,0x219c1ac:0x219bdbc,0x219e694:0x219e29c, 0x2199510:0x1bd54d8,0x219b9e0:0x1bd54d8,0x219e07c:0x1bd54d8,0x21a0520:0x1bd54d8}


def branch(source,target,link=False):
    delta=target-source
    if source&3 or target&3 or not -(1<<27)<=delta<(1<<27):
        raise ValueError('分支目标不对齐或超出AArch64直接分支范围')
    return struct.pack('<I',(0x94000000 if link else 0x14000000)|((delta//4)&0x3ffffff))


def load_module(raw):
    from elftools.elf.elffile import ELFFile
    elf=ELFFile(io.BytesIO(raw))
    if elf['e_machine']!='EM_AARCH64' or elf['e_type']!='ET_EXEC' or not elf.little_endian:
        raise ValueError('AP研究模块必须是AArch64小端测试ELF')
    table=elf.get_section_by_name('.symtab')
    if table is None:raise ValueError('AP研究模块缺少符号表')
    symbols={s.name:int(s['st_value']) for s in table.iter_symbols() if s.name and s['st_shndx']!='SHN_UNDEF'}
    required={h[1] for h in HOOKS}|{h[3] for h in HOOKS if h[3]}|{
        'af_ap_research_enable','af_ap_catalog','af_ap_rows','af_install','af_read','af_ap_native_seed'}
    if any(n not in symbols or not 0x9000000<=symbols[n]<0x9040000 for n in required):
        raise ValueError('AP研究模块缺少符号或地址越界')
    if any(s.name and s['st_shndx']=='SHN_UNDEF' for s in table.iter_symbols()):
        raise ValueError('AP研究模块仍有未定义符号')
    segments=[s for s in elf.iter_segments() if s['p_type']=='PT_LOAD']
    used=set()
    for s in segments:
        start,end=int(s['p_vaddr']),int(s['p_vaddr']+s['p_memsz'])
        pages=set(range(start&~4095,(end+4095)&~4095,4096))
        if (not 0x9000000<=start<=end<=0x9040000 or s['p_flags'] not in (5,6)
                or used&pages or s['p_filesz']>s['p_memsz']):
            raise ValueError('AP研究模块段预算、权限或重叠不符')
        used|=pages
    if elf['e_entry']!=symbols['af_ap_register']:raise ValueError('AP研究模块初始化入口不符')
    return symbols,segments


def collect(ap_raw,std_raw,module_raw,gcc_raw=None):
    require_source(ap_raw,AP_SHA,'AP')
    require_source(std_raw,STD_SHA,'libstdc++')
    from .ui_hash_runtime import GCC_SHA
    require_source(gcc_raw or b'',GCC_SHA,'libgcc_s')
    symbols,segments=load_module(module_raw)
    from unicorn import UC_HOOK_MEM_UNMAPPED, UC_HOOK_CODE
    from unicorn import arm64_const as regs
    ap,std=AP(ap_raw),AP(std_raw)
    m=RegistryMachine(ap,std);u=m.cpu
    from .ui_hash_runtime import NativeHashRuntime
    hash_runtime=NativeHashRuntime(m,gcc_raw)
    # 只按已锁定AP的段按需装入页；未覆盖的地址仍失败，不以空白页吞掉错误。
    def missing(cpu,access,address,size,value,data):
        page=address&~4095
        seg=next((s for s in ap.segments if s['p_vaddr']<=page<s['p_vaddr']+s['p_memsz']),None)
        if seg is None:return False
        if page in m.pages:return False
        if page<seg['p_vaddr']+seg['p_filesz']:m.map_ap(page)
        else:cpu.mem_map(page,4096);m.pages.add(page)
        return True
    u.hook_add(UC_HOOK_MEM_UNMAPPED,missing)
    for s in segments:
        start,end=int(s['p_vaddr']),int(s['p_vaddr']+s['p_memsz'])
        u.mem_map(start&~4095,((end+4095)&~4095)-(start&~4095))
        u.mem_write(start,s.data())
    # 旧基址0夹具只覆盖原34个入口；名称模块须另在非零AP和同包Obj绑定后执行。
    legacy_hooks=[h for h in HOOKS if not h[1].startswith('af_ap_names_')]
    changes=[]
    for address,name,link,trampoline in legacy_hooks:
        m.map_ap(address&~4095)
        before=ap.read(address,4)
        if trampoline:
            at=symbols[trampoline]
            if bytes(u.mem_read(at,4))!=before or bytes(u.mem_read(at+4,4))!=branch(at+4,address+4):
                raise ValueError('原指令返回跳板与4.06前像不符: '+name)
        elif address not in CALL_TARGETS or before!=branch(address,CALL_TARGETS[address],True):
            raise ValueError('原厂BL调用前像不符')
        after=branch(address,symbols[name],link)
        u.mem_write(address,after)
        changes.append(dict(address=hex(address),before=before.hex(),after=after.hex(),symbol=name))
    hits={h[0]:0 for h in legacy_hooks}
    normalizations={'count':0}
    notifications={'count':0}
    def observe(cpu,at,length,data):
        # 只计数，不修改PC、寄存器、内存或返回值。
        if at in hits:hits[at]+=1
        if at==0x2dc6160:normalizations['count']+=1
        if at in (0x252d80c,0x252ca34,0x24a453c):notifications['count']+=1
    u.hook_add(UC_HOOK_CODE,observe)
    rows,aliases=WORK+0x100,WORK+0x200
    m.initialize(rows);m.initialize(aliases)
    m.map_ap(0x5858000,0x1bcf000,0x1bd0000,0x1c5f000)
    u.mem_write(0x5915b80,struct.pack('<Q',rows))
    # 真正从原厂全局初始化的BL开始，返回原来的下一条指令时结束窗口。
    for i,v in enumerate((rows,ROW_TABLE,ROW_TABLE+ROW_BYTES)):
        u.reg_write(getattr(regs,'UC_ARM64_REG_X'+str(i)),v)
    u.reg_write(regs.UC_ARM64_REG_SP,STACK+0x8000)
    u.emu_start(0x16f6610,0x16f6614,count=3000000)
    if u.reg_read(regs.UC_ARM64_REG_PC)!=0x16f6614 or u.reg_read(regs.UC_ARM64_REG_SP)!=STACK+0x8000:
        raise ValueError('AP初始化挂钩未正常返回原位置')
    if m.count(rows)!=5605:raise ValueError('AP初始化未完成5591+14行注册')
    if bytes(u.mem_read(symbols['af_ap_rows'],33*128))!=candidate_rows(ap):
        raise ValueError('AP真实C构造的行记录与独立解释不符')
    desc=bytes(u.mem_read(0x5858b08,0xa0))
    if m.call(symbols['af_ap_research_enable'],2)&0xffffffff!=0xffffffff:
        raise ValueError('非法研究开关未拒绝')
    if bytes(u.mem_read(0x5858b08,0xa0))!=desc:raise ValueError('非法开关修改描述符')
    if m.call(symbols['af_ap_research_enable'],1)!=0:raise ValueError('离线研究启用失败')
    if struct.unpack('<I',u.mem_read(0x5858b08+0x54,4))[0]!=33:
        raise ValueError('研究列表未发布33行')
    # 原厂别名原指令仍执行；此处仅建立直接身份的树夹具，不声称完整别名表启动。
    m.map_ap(0x592f000)
    u.mem_write(0x592f4c8,struct.pack('<Q',aliases))
    m.append(0x1c935e0,aliases,b''.join(struct.pack('<2I',k,k) for k in MENU_IDS[:18]+[0x85e]))
    obj,vt=WORK+0x400,WORK+0x800
    u.mem_write(obj,struct.pack('<Q',vt))
    # 资格状态是明确边界；descriptor与行查询运行真实原厂代码。
    points={0x10:WORK+0xa000,0x1a8:0x1bcfffc,0x790:0x1bd9f98,
            0x798:0x1bd9ffc,0x700:WORK+0xa010,0x550:0x1bc7840,
            0x560:0x1bc785c,0x8c8:0x1bc78a4,0x328:WORK+0xa018,
            0x8d0:WORK+0xa020,0x210:WORK+0xa028}
    for offset,address in points.items():u.mem_write(vt+offset,struct.pack('<Q',address))
    u.mem_write(0x591f9a8,struct.pack('<Q',vt-16))
    qualification={'value':1,'menus':[]}
    m.extra[WORK+0xa000]=lambda cpu:0x5858b08
    def qualify(cpu):
        qualification['menus'].append(cpu.reg_read(regs.UC_ARM64_REG_X1))
        return qualification['value']
    m.extra[WORK+0xa010]=qualify
    m.extra[WORK+0xa018]=lambda cpu:0x1e6
    m.extra[WORK+0xa020]=lambda cpu:0
    m.extra[WORK+0xa028]=lambda cpu:1
    m.extra[0x1be12d0]=lambda cpu:1
    m.extra[0x2e7d208]=lambda cpu:0
    m.extra[0x2e7cee4]=lambda cpu:0
    m.extra[0x16d9770]=lambda cpu:copy_boundary(cpu)
    def copy_boundary(cpu):
        dest,src,size=[cpu.reg_read(r) for r in (regs.UC_ARM64_REG_X0,regs.UC_ARM64_REG_X1,regs.UC_ARM64_REG_X2)]
        if size!=128:raise ValueError('资格临时行拷贝超预算')
        cpu.mem_write(dest,bytes(cpu.mem_read(src,size)));return dest
    output=WORK+0x2800
    def model_page(address):
        page=address&~4095
        if page not in m.pages:
            if not any(s['p_vaddr']+s['p_filesz']<=page<s['p_vaddr']+s['p_memsz'] for s in ap.segments):
                raise ValueError('测试模型不是AP BSS')
            u.mem_map(page,4096);m.pages.add(page)
    m.map_ap(0x28ae000)
    native_selector=m.call(0x28ae4b0);model_page(native_selector)
    for state,special,expected in ((1,0,MENU_IDS[:-1]),(1,16,MENU_IDS),(0,16,[])):
        u.mem_write(native_selector,struct.pack('<I',special))
        qualification['value']=state;qualification['menus']=[]
        u.mem_write(output-8,b'\xa5'*(33*4+16))
        count=m.call(0x1bcf3fc,obj,0x1e6,output,33,limit=100000)
        if count!=len(expected) or list(struct.unpack('<'+'I'*count,u.mem_read(output,count*4)))!=expected:
            raise ValueError('真实原厂33行枚举或资格过滤不符')
        if any(k>=NEW_FIRST for k in qualification['menus']):raise ValueError('新身份进入原厂资格缓存')
        if bytes(u.mem_read(output-8,8))!=b'\xa5'*8 or bytes(u.mem_read(output+132,8))!=b'\xa5'*8:
            raise ValueError('列表枚举越过保护区')
    qualification['value']=1
    # 行尾是函数/数据表索引，而非连续导航身份；执行原厂五个解析器。
    tail_getters=(0x1c5febc,0x1c5fee0,0x1c5ff04,0x1c5ff2c,0x1c5ff50)
    tail_records=[]
    for index in range(33):
        raw=bytes(u.mem_read(symbols['af_ap_rows']+index*128,128))
        indices=struct.unpack_from('<5H',raw,0x70)
        pointers=[m.call(g,v) for g,v in zip(tail_getters,indices)]
        if 18<=index<32 and pointers!=[0]*5:raise ValueError('新增行误继承原厂槽回调')
        if index<18 or index==32:
            source=index if index<18 else 18
            expected=ap.ptr(0x5060e08+(0x75c+source)*8)
            if pointers!=[0,0,expected,0,0]:raise ValueError('原厂行尾索引解释不符')
        tail_records.append(dict(menu=hex(MENU_IDS[index]),indices=list(indices),
                                 resolved=[hex(p) for p in pointers]))
    permission_model=m.call(0x28ae4c4);model_page(permission_model)
    offsets=list(range(0x15,0x1b))+[0x26,0x27]+list(range(0x1b,0x26))
    for index,offset in enumerate(offsets):
        pointer=ap.ptr(0x5060e08+(0x75c+index)*8)
        for flag in (0,1):
            fixture=bytearray(40);fixture[offset]=flag
            u.mem_write(permission_model,bytes(fixture))
            if m.call(pointer)!=flag or bytes(u.mem_read(permission_model,40))!=fixture:
                raise ValueError('原厂行尾资格函数读错外观标记或修改模型')
    for menu in MENU_IDS:
        actual=m.call(0x1bd8eb8,menu)&0xffffffff
        if actual!=menu:raise ValueError('真实分支别名身份不符')
    if m.call(0x1bd8eb8,0x15d8)&0xffffffff!=0x15d8:raise ValueError('原厂哨兵被改写')
    for row,menu in enumerate(MENU_IDS[:-1]):
        expected=ap.u32(0x3f4a280+row*128+8) if row<18 else 0x0200abde+row-18
        if m.call(0x1bd1b88,obj,menu)&0xffffffff!=expected:raise ValueError('真实名称分支错误')
    # 安装的是明确的内存夹具，不声称机内持久化已读取。
    preset,out,snapshot=WORK+0x1800,WORK+0x3000,WORK+0x4000
    catalog=symbols['af_ap_catalog'];originals={}
    m.map_ap(0x28c5000)
    base_array=m.call(0x28c54cc);model_page(base_array);model_page(base_array+71)
    arrays=[m.call(a) for a in (0x28c5544,0x28c556c,0x28c5594,0x28c55bc,
                               0x28c55e4,0x28c560c,0x28c5634,0x28c565c)]
    for address in arrays:model_page(address);model_page(address+71)
    for slot in range(1,21):
        base=(17,18,0,1,2,3,4,5,6,7,8,9)[(slot-1)%12]
        raw=struct.pack('<BB8b64x',base,0,slot%8,-2,3,1,2,3,3,4)
        u.mem_write(preset,raw)
        if slot<=6:
            u.mem_write(base_array+(slot+9)*4,struct.pack('<I',10 if base==17 else 11 if base==18 else base))
            for p,address in enumerate(arrays):
                u.mem_write(address+(slot+9)*4,struct.pack('<i',struct.unpack_from('<b',raw,2+p)[0]))
            if m.call(symbols['af_ap_native_seed'],slot)!=0:raise ValueError('原六槽原生模型迁移失败')
            if m.call(symbols['af_ap_native_seed'],slot)&0xffffffff!=0xfffffffd:
                raise ValueError('再次迁移误覆盖用户槽')
        elif slot<20 and m.call(symbols['af_install'],catalog,slot,preset,0)!=0:
            raise ValueError('研究目录夹具安装失败')
        originals[slot]=raw
    # 原厂受限标记窗口：真正执行BL getter、24字节索引及+0x14读取。
    metadata=m.call(0x28c5558);model_page(metadata);model_page(metadata+431)
    for index in range(18):
        for flag in (0,1):
            u.mem_write(metadata+index*24+0x14,bytes([flag]))
            u.reg_write(regs.UC_ARM64_REG_X20,index)
            u.emu_start(0x2209638,0x2209648,count=100)
            if u.reg_read(regs.UC_ARM64_REG_PC)!=0x2209648 or u.reg_read(regs.UC_ARM64_REG_X21)!=flag:
                raise ValueError('原厂参数+0x14受限标记窗口不符')
    # 原厂模式表和当前身份getter均执行真实指令；只设定其输入模型字节。
    m.map_ap(0x17ff000,0x598e000,0x3725000,0x28a8000)
    model=0x7eff000+0xa98+0x18000+0xfb8
    if (model&~4095) not in m.pages:u.mem_map(model&~4095,4096);m.pages.add(model&~4095)
    def display(selector,mode=0):
        u.mem_write(snapshot,b'\0'*0x1010)
        u.mem_write(snapshot,struct.pack('<I',mode))
        u.mem_write(snapshot+0x20,struct.pack('<I',selector))
        u.mem_write(out-8,b'\xa5'*176)
        m.call(0x23fcd48,0,out,0,snapshot)
        if bytes(u.mem_read(out-8,8))!=b'\xa5'*8 or bytes(u.mem_read(out+0x98,16))!=b'\xa5'*16:
            raise ValueError('显示快照越过保护区')
    controller,event=WORK+0x6000,WORK+0x5200
    u.mem_write(controller,b'\0'*0x1000)
    from .ui_components import ComponentProbe
    engine=ComponentProbe(m,controller,model_page)
    component_result=engine.verify()
    focus_map=list(ap.read(0x4283740,17))
    components=[next(0xf+i for i,option in enumerate(focus_map)
                     if option==p+1 and engine.state(0xf+i) is not None) for p in range(8)]
    for i,option in enumerate(focus_map):
        engine.set_focus(0xf+i)
        if m.call(0x220929c,controller)!=option:raise ValueError('真实焦点到参数映射错误')
    def direct(value,message=0xd):
        u.mem_write(event,b'\0'*64)
        u.mem_write(event+0xc,struct.pack('<I',message))
        u.mem_write(event+0x30,bytes([value&255]))
        if m.call(0x220933c,controller,event)!=1:raise ValueError('参数消息未按原厂返回已处理')
    low=(-9,-9,-9,0,-9,0,1,0);high=(9,9,9,9,9,9,5,9)
    direct_accepted=direct_rejected=0
    u.mem_write(native_selector,b'\0'*4)
    u.mem_write(model,struct.pack('<I',MENU_IDS[31]))
    display(0);engine.set_focus(components[0])
    empty_before=bytes(u.mem_read(catalog,6888))
    if m.call(0x2209580,controller)!=1:raise ValueError('未安装用户槽未阻断输入')
    m.call(0x220ae78,controller);direct(1)
    if bytes(u.mem_read(catalog,6888))!=empty_before:raise ValueError('未安装用户槽被输入隐式创建')
    if any(struct.unpack('<i',u.mem_read(out+0x34+p*12,4))[0]!=-1 for p in range(8)):
        raise ValueError('未安装用户槽暴露无效参数')
    from .ap_ui_selection import SelectionRefreshProbe
    refresh=SelectionRefreshProbe(m,symbols,model,native_selector,out)
    refresh.empty_selection(MENU_IDS[31],32)
    u.mem_write(preset,originals[20])
    if m.call(symbols['af_install'],catalog,20,preset,0)!=0:raise ValueError('末槽研究夹具安装失败')
    selection=refresh.selections(obj,vt,permission_model)
    from .ap_ui_initialization import InitializationProbe
    initialization=InitializationProbe(m,symbols,controller,model,native_selector,base_array,refresh,engine)
    initialization_result=initialization.collect()
    native_arrays_before=[bytes(u.mem_read(address,72)) for address in arrays]
    normalizations_before=normalizations['count']
    notifications_before=notifications['count']
    focus_notices_before=engine.focus_notices
    u.mem_write(native_selector,b'\0'*4)
    for row in range(12,32):
        slot=row-11;menu=MENU_IDS[row]
        refresh.set_view('main' if row%2==0 else 'parameter')
        u.mem_write(model,struct.pack('<I',menu))
        # 原厂成像选择保持安全基底0；显示以当前菜单身份选择用户工作快照。
        display(0)
        expected=struct.unpack_from('<8b',originals[slot],2)
        for p in range(8):
            fields=struct.unpack('<iiB',u.mem_read(out+0x34+12*p,9))
            if fields!=(p,expected[p],0):raise ValueError('用户槽八项显示或受限语义不符')
            engine.set_focus(components[p])
            if m.call(0x2209580,controller)!=0:raise ValueError('用户参数被错误标记为受限')
            before=bytes(u.mem_read(catalog,6888))
            if m.call(0x220ae78,controller)!=1:raise ValueError('原厂上层增加事件未返回')
            refresh.cycle()
            if struct.unpack('<i',u.mem_read(out+0x38+12*p,4))[0]!=min(expected[p]+1,(9,9,9,9,9,9,5,9)[p]):
                raise ValueError('真实AP回调后显示未使用工作值')
            if m.call(0x220af84,controller)!=1:raise ValueError('原厂上层减少事件未返回')
            refresh.cycle()
            if bytes(u.mem_read(catalog,6888))!=before:raise ValueError('回调往返改变保存状态或其他槽')
            for value in (low[p],high[p],expected[p]):
                direct(value);direct_accepted+=1;refresh.cycle()
                if struct.unpack('<i',u.mem_read(out+0x38+12*p,4))[0]!=value:
                    raise ValueError('参数对话框未按焦点写入对应槽或符号值错误')
            if bytes(u.mem_read(catalog,6888))!=before:raise ValueError('直接赋值恢复后修改其他状态')
            for value in (low[p]-1,high[p]+1):
                direct(value);direct_rejected+=1
                refresh.cycle(False)
                if bytes(u.mem_read(catalog,6888))!=before:raise ValueError('非法直接赋值修改目录')
        if m.call(symbols['af_read'],catalog,slot,1,preset)!=0 or bytes(u.mem_read(preset,74))!=originals[slot]:
            raise ValueError('实际AP挂钩修改了用户保存值')
    if normalizations['count']!=normalizations_before or native_arrays_before!=[
            bytes(u.mem_read(address,72)) for address in arrays]:
        raise ValueError('用户路径进入原厂归一化或改写18项数组')
    if bytes(u.mem_read(native_selector,4))!=b'\0'*4:
        raise ValueError('用户参数输入改写了原厂0x690选择模型')
    if notifications['count']-notifications_before!=engine.focus_notices-focus_notices_before:
        raise ValueError('用户调参借用原厂全局属性广播刷新')
    focus_ui_notifications=engine.focus_notices-focus_notices_before
    # 不支持布局的新选择值必须隐藏且拒绝调节，不落入正规化或负索引。
    u.mem_write(model,struct.pack('<I',MENU_IDS[31]))
    before=bytes(u.mem_read(catalog,6888))
    for mode in (1,2,0xffffffff):
        display(0,mode)
        if any(struct.unpack('<i',u.mem_read(out+0x34+p*12,4))[0]!=-1 for p in range(8)):
            raise ValueError('未知布局未隐藏用户参数')
        if m.call(0x2209580,controller)!=1:raise ValueError('未知布局错误开放调参')
        m.call(0x220ae78,controller);direct(1)
    if bytes(u.mem_read(catalog,6888))!=before:raise ValueError('未知布局修改目录')
    # 显示之后原厂实时限制变化，也必须拒绝，不能仅依赖上次显示快照。
    live_restriction=m.call(0x28bfdcc);model_page(live_restriction)
    display(0)
    for value in (1,2):
        u.mem_write(live_restriction,struct.pack('<I',value))
        if m.call(0x2209580,controller)!=1:raise ValueError('实时限制变化后仍开放用户调参')
        m.call(0x220ae78,controller);direct(1)
        if bytes(u.mem_read(catalog,6888))!=before:raise ValueError('实时限制变化后修改用户目录')
    u.mem_write(live_restriction,b'\0'*4)
    # 新列表切换而尚未更新显示时，旧快照不能授权另一个用户槽调参。
    u.mem_write(model,struct.pack('<I',MENU_IDS[18]))
    display(0)
    u.mem_write(model,struct.pack('<I',MENU_IDS[31]))
    if m.call(0x2209580,controller)!=1:raise ValueError('陈旧选择快照授权了另一槽')
    m.call(0x220ae78,controller);direct(1)
    if bytes(u.mem_read(catalog,6888))!=before:raise ValueError('陈旧选择快照修改目录')
    display(0)
    # 基底现在是合法焦点；八项数值赋值消息不能误写基底或任意参数。
    engine.set_focus(0xf)
    if m.call(0x2209580,controller)!=0:raise ValueError('纯参数用户基底未开放')
    direct(1)
    if bytes(u.mem_read(catalog,6888))!=before:raise ValueError('数值赋值消息误写基底焦点')
    for component in (0,0xffffffff):
        engine.set_focus(component)
        if m.call(0x2209580,controller)!=1:raise ValueError('非法或非参数焦点开放编辑')
        m.call(0x220ae78,controller);direct(1)
        if bytes(u.mem_read(catalog,6888))!=before:raise ValueError('非法焦点修改目录')
    # 非赋值消息携带组件身份，原1af3ca0会切换焦点；不能只返回0冒充事件消费。
    direct(0,components[0])
    if m.call(0x1af11f0,engine.object)!=components[0] or bytes(u.mem_read(catalog,6888))!=before:
        raise ValueError('非赋值消息未沿原厂组件焦点设置路径执行')
    # 实际挂钩后的原厂回调仍执行原代码；仅在原有setter/锁边界记录调用。
    native_events=[]
    selectors=dict(zip(MENU_IDS,SELECTORS))
    m.extra[0x1bd921c]=lambda cpu:selectors[struct.unpack('<I',cpu.mem_read(model,4))[0]]
    m.extra[0x2542a30]=lambda cpu:0;m.extra[0x2542a40]=lambda cpu:0
    def setter_boundary(cpu):
        value=cpu.reg_read(regs.UC_ARM64_REG_X1)&0xffffffff
        native_events.append(value if value<0x80000000 else value-0x100000000)
        return 0
    for p,parameter in enumerate(PARAMETERS):
        m.extra[parameter[3]+0x120]=setter_boundary
        native_metadata=m.call(parameter[2]+0x14)
        model_page(native_metadata);model_page(native_metadata+431)
        engine.set_focus(components[p])
        cases=[(row,0,3 if p==6 else 0) for row in range(12)]
        cases += [(0,d,v) for d in (0,1) for v in (low[p],high[p])]
        for row,direction,value in cases:
            u.mem_write(model,struct.pack('<I',MENU_IDS[row]))
            index=SELECTORS[row]-1 if SELECTORS[row]>=17 else SELECTORS[row]
            u.mem_write(arrays[p]+index*4,struct.pack('<i',value))
            u.mem_write(native_metadata+index*24+0x14,b'\0')
            original=bytes(u.mem_read(arrays[p],72));native_events.clear()
            m.call(0x220ae78 if direction==0 else 0x220af84,controller)
            expected=value+(1 if direction==0 else -1)
            if native_events!=([] if expected<low[p] or expected>high[p] else [expected]):
                raise ValueError('实际AP挂钩改变原厂回调行为')
            if bytes(u.mem_read(arrays[p],72))!=original:raise ValueError('原厂回调意外写数组')
        # 原厂标记1仍阻断上层事件，不因用户分流而放开。
        u.mem_write(model,struct.pack('<I',MENU_IDS[0]))
        u.mem_write(native_metadata+0x14,b'\x01');native_events.clear()
        m.call(0x220ae78,controller)
        if native_events:raise ValueError('原厂受限标记未阻断事件')
        direct(-3 if p in (0,1,2,4) else 3)
        expected=253 if p in (0,1,2,4) else 3
        if native_events!=[expected]:raise ValueError('原厂直接赋值委派与字节编码不符')
    if bytes(u.mem_read(catalog,6888))!=before:raise ValueError('原厂回调写入用户目录')
    # 原厂12种选择的全部字段与无挂钩的原指令逐字节对比。
    stock=arm64_cpu(ap,[0x23fc000,0x2dc6000,0x4a59000,0x17ff000,0x598e000,0x3725000])
    from .access_evidence import run64
    for row in range(12):
        u.mem_write(model,struct.pack('<I',MENU_IDS[row]))
        selector=SELECTORS[row]
        fixture=bytearray(0x1010);struct.pack_into('<I',fixture,0x20,selector)
        native_index=selector-1 if selector>=17 else selector
        for p in range(8):
            struct.pack_into('<i',fixture,0x50+p*0x1f8+native_index*4,p-3)
            fixture[0xac+p*0x1f8+native_index*24]=p%2
        for cpu in (u,stock):
            cpu.mem_write(snapshot,bytes(fixture));cpu.mem_write(out,b'\xa5'*160)
            for i,v in enumerate((0,out,0,snapshot)):cpu.reg_write(getattr(regs,'UC_ARM64_REG_X'+str(i)),v)
            cpu.reg_write(regs.UC_ARM64_REG_LR,STOP)
            run64(cpu,0x23fcd48)
        if bytes(u.mem_read(out,160))!=bytes(stock.mem_read(out,160)):raise ValueError('原厂显示委派改变结果')
    if not m.redzones():raise ValueError('注册节点越界')
    if m.call(symbols['af_ap_research_enable'],0)!=0 or bytes(u.mem_read(0x5858b08,0xa0))!=desc:
        raise ValueError('禁用研究未恢复原描述符')
    if m.call(0x1bcfffc,obj,NEW_FIRST)!=0:raise ValueError('禁用后新增身份未拒绝')
    for change in changes:
        u.mem_write(int(change['address'],16),bytes.fromhex(change['before']))
    if any(bytes(u.mem_read(a,4))!=ap.read(a,4) for a,_,_,_ in legacy_hooks):raise ValueError('AP分支无法精确回退')
    component_result['cleanup']=engine.finish()
    return dict(schema='a7r5-ap-ui-hooks/1',status='OFFLINE_REAL_BRANCHES_EXECUTED',
                ap_sha256=AP_SHA,module_sha256=hashlib.sha256(module_raw).hexdigest(),
                module_bytes=len(module_raw),patches=changes,branch_entry_hits={hex(k):v for k,v in hits.items()},
                excluded_name_hooks=[hex(h[0]) for h in HOOKS if h not in legacy_hooks],
                dynamic_name_binding_and_rendering_verified=False,
                original_init_call_executed=True,registry_rows=5605,native_list_rows=33,
                tail_records=tail_records,tail_resolver_calls=165,native_look_permission_cases=38,
                native_parameter_metadata_cases=36,native_six_seeded_and_no_overwrite=True,
                navigation_states=3,alias_queries=34,name_queries=32,user_display_slots=20,
                user_callback_steps=320,user_inhibit_queries=160,builtin_display_parity=12,
                native_focus_map_cases=17,native_upper_key_events=320,
                parameter_input_components=components,
                user_focus_ui_notifications=focus_ui_notifications,focus_ui_models='0x1942..0x1945',
                direct_values_accepted=direct_accepted,direct_values_rejected=direct_rejected,
                non_value_message_delegated=True,builtin_inhibit_preserved=8,builtin_direct_delegations=8,
                native_component_focus_message_executed=True,
                display_uses_current_menu_with_safe_native_selector=True,
                native_selector_model_unchanged_during_user_edits=True,empty_user_input_rejected=True,
                user_edit_property_broadcasts=0,user_parameter_broadcasts=0,
                patched_builtin_callback_cases=128,user_path_native_normalizer_calls=0,
                stale_selection_rejected=True,disabled_new_identity_rejected=True,
                live_restriction_changes_rejected=2,
                unsupported_layouts_rejected=3,descriptor_and_branches_restored=True,
                allocator_redzones_valid=True,entry_pc_redirection_used=False,
                selection_isolation=selection,
                parameter_initialization=initialization_result,
                native_components=component_result,
                native_hash_runtime=hash_runtime.report(),
                refresh_query_cycles=refresh.cycles,refresh_scheduled=refresh.scheduled,
                native_presenter_snapshot_consumptions=refresh.consumed,
                fixture_boundaries=['AP load base 0','same-package bounded allocator/PLT',
                    'eligibility state/temporary row memcpy/transaction boundary','direct identity alias-tree fixtures',
                    'explicit research enable','installed in-memory presets','mode snapshot and model inputs',
                    'builtin callback selector/setter/transaction boundaries','component allocator/zero/free and exit registration',
                    'photo mode model inputs'],
                full_global_initialization_verified=False,refresh_notification_connected=False,
                native_ui_refresh_query_connected=True,full_refresh_draw_verified=False,
                photo_mode_semantics_verified=False,uxc_loader_verified=False,
                full_native_screen_verified=False,cp_or_storage_called=False,
                camera_io=False,input_dat_modified=False,installable_candidate_allowed=False)
