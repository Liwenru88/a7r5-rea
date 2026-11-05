"""当前4.06的身份注册、显示模型和调参窗口；不安装至固件。"""
import struct

from .access_evidence import AP_SHA, WORK, STACK, STOP, arm64_cpu, run64, require_source
from .investigate import AP, PARAMETERS, instructions

STD_PATH = '/lib/libstdc++.so.6.0.22'
STD_SHA = '28f2d082aea5206c42ba15664f39e2eaf7febed8f6264305e7e16aa44c878389'
ROW_TABLE, ROW_BYTES = 0x5030590, 0x15d70
PARENT_TABLE, PARENT_BYTES = 0x3e44de0, 0x31a8
BUILTINS = (0,1,2,3,4,5,17,18,6,7,8,9)
NEW_FIRST, NEW_LAST = 0x15d9, 0x15e6
MENU_IDS = list(range(0x84c,0x85e)) + list(range(NEW_FIRST,NEW_LAST+1)) + [0x85e]
SELECTORS = list(BUILTINS) + list(range(10,16)) + list(range(19,33)) + [16]


def candidate_rows(ap):
    """隔离描述符夹具；新行五类索引使用原厂空哨兵，资格另行分流。"""
    raw = bytearray(ap.read(0x3f4a280,18*128))
    for i in range(14):
        row = bytearray(ap.read(0x3f4ab00,128))
        struct.pack_into('<2I',row,0,NEW_FIRST+i,NEW_FIRST+i)
        struct.pack_into('<I',row,8,0x0200abde+i)
        struct.pack_into('<I',row,0x34,19+i)
        struct.pack_into('<6HI',row,0x70,0x29,0x55,0x1086,0x12,0x4f,0,0)
        raw.extend(row)
    raw.extend(ap.read(0x3f4ab80,128))
    return bytes(raw)


class RegistryMachine:
    """注册树搜索、分配前的构造和平衡均用原代码；只替代有界分配器。"""
    def __init__(self, ap, std):
        from unicorn import UC_HOOK_CODE
        from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_PC, UC_ARM64_REG_LR
        self.ap, self.std = ap, std
        self.pages = set()
        self.cpu = arm64_cpu(ap,[])
        self.allocations = []
        self.allocation_sizes = {40,48}
        self.component_buckets = False
        self.heap = 0x91000010
        self.cpu.mem_map(0x91000000,0x100000)
        self.cpu.mem_map(0x91200000,0x20000)
        self.cpu.mem_map(0x91300000,0x2000)
        self.cpu.mem_map(0x100a6000,0x1000)
        self.cpu.mem_write(0x100a6000,std.read(0xa6000,0x1000))
        self.map_ap(0x1c91000,0x1c93000,0x1bd1000,0x1bd8000,0x1bd9000,
                    0x1bc7000,0x500f000,0x16d9000,0x16da000,0x16db000,0x16dc000,
                    0x591f000,0x5915000,0x593f000,0x5936000,0x3f4a000,0x3f4b000)
        names = {s.name:int(s['st_value']) for s in std.elf.get_section_by_name('.dynsym').iter_symbols()}
        if names['_ZSt29_Rb_tree_insert_and_rebalancebPSt18_Rb_tree_node_baseS0_RS_'] != 0xa6350:
            raise ValueError('同包树平衡入口前像变化')
        if names['_ZSt28_Rb_tree_rebalance_for_erasePSt18_Rb_tree_node_baseRS_'] != 0xa65e8:
            raise ValueError('同包树删除入口前像变化')
        self.extra = {}

        def boundary(cpu,at,size,data):
            if at == 0x16dc130:
                requested = cpu.reg_read(UC_ARM64_REG_X0)
                bucket = (self.component_buckets and cpu.reg_read(UC_ARM64_REG_LR)==0x1af0dac
                          and requested in (88,136,184))
                if (not bucket and (requested not in self.allocation_sizes or not 0<requested<=64)
                        or self.heap+requested+16 > 0x91100000):
                    raise ValueError('注册器分配超出隔离预算')
                node = self.heap
                self.heap += (max(64,requested)+47)&~15
                self.allocations.append((node,requested))
                cpu.mem_write(node-16,b'\xa5'*(requested+32))
                cpu.reg_write(UC_ARM64_REG_X0,node)
            elif at in (0x16d9f20,0x16d9c70,0x16da520,0x16dbc80,0x16dc870):
                # 跳转同包库代码，不以Python构造或平衡树。
                offsets={0x16d9f20:0xa6350,0x16d9c70:0xa6210,0x16da520:0xa6280,0x16dbc80:0xa6288,
                         0x16dc870:0xa65e8}
                cpu.reg_write(UC_ARM64_REG_PC,0x10000000+offsets[at])
                return
            elif at in self.extra:
                cpu.reg_write(UC_ARM64_REG_X0,self.extra[at](cpu))
            else:
                return
            cpu.reg_write(UC_ARM64_REG_PC,cpu.reg_read(UC_ARM64_REG_LR))

        self.cpu.hook_add(UC_HOOK_CODE,boundary)

    def map_ap(self,*pages):
        for page in pages:
            if page in self.pages: continue
            available = next(min(4096,s['p_vaddr']+s['p_filesz']-page)
                             for s in self.ap.segments if s['p_vaddr'] <= page < s['p_vaddr']+s['p_filesz'])
            self.cpu.mem_map(page,4096)
            self.cpu.mem_write(page,self.ap.read(page,available))
            for address,value in self.ap.relocations.items():
                if page <= address <= page+4088:
                    self.cpu.mem_write(address,struct.pack('<Q',value))
            self.pages.add(page)

    def call(self,address,*arguments,limit=10000):
        from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_LR
        # Unicorn寄存器常量不保证X0..X7可用算术递增，显式取得名称。
        from unicorn import arm64_const as regs
        for i,value in enumerate(arguments):
            self.cpu.reg_write(getattr(regs,'UC_ARM64_REG_X'+str(i)),value)
        self.cpu.reg_write(UC_ARM64_REG_LR,STOP)
        run64(self.cpu,address,limit)
        return self.cpu.reg_read(UC_ARM64_REG_X0)

    def initialize(self,address):
        self.cpu.mem_write(address,b'\0'*48)
        self.cpu.mem_write(address+0x10,struct.pack('<4Q',0,address+8,address+8,0))

    def append(self,constructor,registry,raw):
        table = 0x91200000
        if len(raw)>0x20000: raise ValueError('注册表夹具超限')
        self.cpu.mem_write(table,raw)
        self.call(constructor,registry,table,table+len(raw),limit=3000000)

    def count(self,registry):
        return struct.unpack('<Q',self.cpu.mem_read(registry+0x28,8))[0]

    def redzones(self):
        return all(bytes(self.cpu.mem_read(at-16,16))==b'\xa5'*16 and
                   bytes(self.cpu.mem_read(at+size,16))==b'\xa5'*16
                   for at,size in self.allocations)


def registry_and_names(ap,std):
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X19,UC_ARM64_REG_X20,UC_ARM64_REG_FP,UC_ARM64_REG_PC
    m = RegistryMachine(ap,std)
    u = m.cpu
    rows,parents = WORK+0x100,WORK+0x200
    m.initialize(rows);m.initialize(parents)
    m.append(0x1c91e94,rows,ap.read(ROW_TABLE,ROW_BYTES))
    if m.count(rows)!=5591: raise ValueError('原厂行注册数量不符')
    u.mem_write(WORK+0x80,struct.pack('<I',NEW_FIRST))
    if m.call(0x1bd906c,rows,WORK+0x80)!=0:
        raise ValueError('新增身份已被现有行注册占用')
    candidate = candidate_rows(ap)
    u.mem_write(0x91300000,candidate)
    additions = b''.join(struct.pack('<2Q',MENU_IDS[i],0x91300000+128*i) for i in range(18,32))
    m.append(0x1c91e94,rows,additions)
    m.append(0x1c91e94,rows,additions)
    if m.count(rows)!=5605: raise ValueError('追加或重复注册语义不符')
    m.append(0x1c935e0,parents,ap.read(PARENT_TABLE,PARENT_BYTES))
    if m.count(parents)!=1589: raise ValueError('原厂页面映射数量不符')
    checked=[]
    for i,key in enumerate(MENU_IDS):
        u.mem_write(WORK+0x80,struct.pack('<I',key))
        if m.call(0x1bd906c,rows,WORK+0x80)!=1:
            raise ValueError('候选身份未进入原厂注册树')
        holder = m.call(0x1bd90c4,rows,WORK+0x80)
        pointer = struct.unpack('<Q',u.mem_read(holder,8))[0]
        expected = 0x3f4a280+(i if i<18 else 18)*128 if i<18 or i==32 else 0x91300000+i*128
        if pointer!=expected: raise ValueError('身份指向了错误行记录')
        checked.append(dict(menu=hex(key),record=hex(pointer)))
    # 父项映射执行真实多重树查询；仅资格谓词固定允许。
    obj,vt = WORK+0x400,WORK+0x800
    u.mem_write(obj,struct.pack('<Q',vt))
    u.mem_write(vt+0x208,struct.pack('<Q',WORK+0xa000))
    u.mem_write(0x593fbd8,struct.pack('<Q',parents))
    m.extra[WORK+0xa000] = lambda cpu:1
    if m.call(0x1bd1dd4,obj,0x1e6)!=0x1f2:
        raise ValueError('逻辑菜单页到描述符身份不符')
    parent_mapping = dict(logical_menu_page='0x1e6',descriptor_key='0x1f2',ds_screen='0xd9')
    # 沿原厂名称分支运行；旧六槽保留当前包的名称助手。
    for offset,address in ((0x550,0x1bc7840),(0x560,0x1bc785c),(0x8c8,0x1bc78a4),
                           (0x790,0x1bd9f98),(0x328,WORK+0xa008),(0x8d0,WORK+0xa010)):
        u.mem_write(vt+offset,struct.pack('<Q',address))
    # 1bd8eb8构造的临时菜单对象使用原厂全局虚表，改为同一隔离对象表。
    u.mem_write(0x591f9a8,struct.pack('<Q',vt-16))
    u.mem_write(0x5915b80,struct.pack('<Q',rows))
    m.extra[WORK+0xa008] = lambda cpu:0x1e6
    m.extra[WORK+0xa010] = lambda cpu:0
    # 别名树尚未整体扩展，普通直接身份在此作为明确边界保持不变。
    m.extra[0x1bd8eb8] = lambda cpu:cpu.reg_read(UC_ARM64_REG_X0)
    names=[]
    for i,key in enumerate(MENU_IDS[:-1]):
        actual = m.call(0x1bd1b88,obj,key)&0xffffffff
        expected = ap.u32(0x3f4a280+i*128+8) if i<18 else 0x0200abde+i-18
        if actual!=expected: raise ValueError('原厂名称分派或资源身份不符')
        names.append(dict(menu=hex(key),resource=hex(actual),resource_installed=i<18))
    # 执行真实呈现器选中名称写入窗口；同一个文本组件承接32种选择。
    m.map_ap(0x2208000,0x1afe000,0x1bd5000)
    presenter,model,widget=WORK+0x6000,WORK+0x5000,WORK+0x5800
    u.mem_write(presenter+0x48,struct.pack('<Q',model))
    u.mem_write(model+0xb0,struct.pack('<2Q',2,widget))
    for row in names:
        u.mem_write(presenter+0x3a80,struct.pack('<I',int(row['menu'],16)))
        u.mem_write(widget-8,b'\xa5'*80)
        for register,value in ((UC_ARM64_REG_X19,presenter),(UC_ARM64_REG_X20,STACK+0x8030),
                               (UC_ARM64_REG_FP,STACK+0x8000)):
            u.reg_write(register,value)
        u.emu_start(0x2208e70,0x2208e94,count=5000)
        expected=bytearray(b'\xa5'*80)
        struct.pack_into('<I',expected,8+0x30,int(row['resource'],16))
        if u.reg_read(UC_ARM64_REG_PC)!=0x2208e94 or bytes(u.mem_read(widget-8,80))!=expected:
            raise ValueError('选中名称呈现窗口越界或资源身份不符')
    if not m.redzones(): raise ValueError('注册器写入超出节点大小')
    return dict(native_row_constructor='0x1c91e94',native_parent_constructor='0x1c935e0',
                native_rebalance='libstdc++ 0xa6350',native_increment='libstdc++ 0xa6210',
                original_rows=5591,extended_rows=5605,duplicate_insert_adds_zero=True,
                parent_entries=1589,parent_mapping=parent_mapping,lookups=checked,names=names,
                selected_name_presenter_cases=32,selected_name_window='0x2208e70..0x2208e90',
                selected_name_widget_redzones_unchanged=True,
                allocator_requests=len(m.allocations),node_redzones_unchanged=True,
                fixture_boundaries=['bounded allocator','parent eligibility','base getter','row alias identity',
                                    'presenter/widget references'],
                new_name_resources_installed=False,tail_navigation_fields_validated=False,
                firmware_registration_installed=False)


def parameter_callbacks(ap):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_PC,UC_ARM64_REG_LR
    results=[]
    low=(-9,-9,-9,0,-9,0,1,0);high=(9,9,9,9,9,9,5,9)
    for p,row in enumerate(PARAMETERS):
        cpu=arm64_cpu(ap,[0x2209000,0x220a000,0x28c5000,0x2dc6000,0x4a59000,
                         0x2e7d000,0x2e7c000,0x2542000,0x28a8000,0x1bd9000,
                         (row[3]+0x120)&~4095])
        # 执行原厂数组地址getter，随后仅映射所需隔离BSS页。
        cpu.reg_write(UC_ARM64_REG_LR,STOP)
        run64(cpu,row[2])
        array=cpu.reg_read(UC_ARM64_REG_X0)
        cpu.mem_map(array&~4095,0x2000)
        mutable={'selector':0,'events':[]}
        setter=row[3]+0x120
        def boundary(u,at,size,data):
            if at in (0x2e7d208,0x2e7cee4,0x2542a30,0x2542a40):
                result=0
            elif at==0x28a87e8:result=WORK+0x100
            elif at==0x1bd921c:result=mutable['selector']
            elif at==setter:
                v=u.reg_read(UC_ARM64_REG_X1)&0xffffffff
                mutable['events'].append(v if v<0x80000000 else v-0x100000000)
                result=0
            else:return
            u.reg_write(UC_ARM64_REG_X0,result)
            u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))
        cpu.hook_add(UC_HOOK_CODE,boundary)
        cases=[(s,0,3 if p==6 else 0) for s in BUILTINS]
        cases += [(0,d,v) for d in (0,1) for v in (low[p],high[p])]
        for selector,direction,value in cases:
            index=selector-1 if selector in (17,18) else selector
            cpu.mem_write(array-8,b'\xa5'*88)
            cpu.mem_write(array+index*4,struct.pack('<i',value))
            before=bytes(cpu.mem_read(array-8,88))
            mutable['selector']=selector;mutable['events']=[]
            cpu.reg_write(UC_ARM64_REG_X0,WORK+0x200)
            cpu.reg_write(UC_ARM64_REG_X1,direction)
            cpu.reg_write(UC_ARM64_REG_LR,STOP)
            run64(cpu,0x2209918+p*0x154)
            expected=value+(1 if direction==0 else -1)
            events=[] if expected<low[p] or expected>high[p] else [expected]
            if mutable['events']!=events or bytes(cpu.mem_read(array-8,88))!=before:
                raise ValueError('原厂调参回调步进、边界或数组读取不符')
        results.append(dict(parameter=row[0],callback=hex(0x2209918+p*0x154),
                            array_getter=hex(row[2]),setter_wrapper=hex(setter),
                            cases=len(cases),original_array_unchanged=True))
    return dict(parameters=results,fixture_boundaries=['transaction/lock','current menu lookup','setter wrapper'],
                native_ranges_executed=True,user_routes_must_precede_normalizer=True,
                cp_or_storage_called=False)


def collect(ap_raw,std_raw):
    require_source(ap_raw,AP_SHA,'AP')
    require_source(std_raw,STD_SHA,'libstdc++')
    if len(std_raw)!=1549496: raise ValueError('同包C++库长度不符')
    from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
    ap,std=AP(ap_raw),AP(std_raw)
    ad=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    windows={hex(a):instructions(ad,ap.read(a,n),a) for a,n in (
        (0x16f65ec,40),(0x16fbed4,44),(0x1bd1b88,64),(0x1bc7840,16),
        (0x2208e34,104),(0x23fcd48,120),(0x220a7ac,144))}
    return dict(schema='a7r5-ui-evidence/1',ap_sha256=AP_SHA,
                stdlib=dict(path=STD_PATH,bytes=len(std_raw),sha256=STD_SHA),
                registry=registry_and_names(ap,std),parameters=parameter_callbacks(ap),
                presenter=dict(main_constructor='0x1e1dff4',parameter_constructor='0x1e1e88c',
                               main_ds_screen='0xd9',parameter_ds_screen='0xda',
                               main_widget_count=34,parameter_widget_count=107,
                               snapshot_reader='0x23fcd48',snapshot_native_parameters=18,
                               ui_shape_counts_are_not_look_slot_capacity=True,
                               full_32_slot_render_verified=False),
                ap_windows=windows,camera_io=False,firmware_modified=False,
                installable_candidate_allowed=False)
