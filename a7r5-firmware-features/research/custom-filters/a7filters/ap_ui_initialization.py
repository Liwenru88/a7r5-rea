"""调参控制器完整初始化入口与基底切换隔离；不替代组件引擎或客体绘制。"""
import struct

from .access_evidence import WORK
from .ui_evidence import MENU_IDS, SELECTORS


class InitializationProbe:
    def __init__(self,machine,symbols,controller,model,selector,base_array,refresh,engine):
        from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ, UC_HOOK_MEM_WRITE, UC_MEM_READ
        from unicorn import arm64_const as r
        self.m,self.u,self.s,self.r=machine,machine.cpu,symbols,r
        self.controller,self.model,self.selector=controller,model,selector
        self.base,self.refresh,self.engine=base_array,refresh,engine
        self.events=[];self.reads=[];self.writes=[];self.normalizers=0;self.active=False
        self.last={}
        def memory(cpu,access,address,size,value,data):
            if self.active and base_array-4<=address<base_array+72:
                (self.reads if access==UC_MEM_READ else self.writes).append(dict(address=hex(address),bytes=size))
        def code(cpu,address,size,data):
            if self.active and address==0x2dc6160:self.normalizers+=1
            if self.active and address in (0x1af3cdc,0x1af1d48,0x1af3290):
                self.events.append(dict(address=hex(address),args=[cpu.reg_read(getattr(r,'UC_ARM64_REG_X'+str(i))) for i in range(3)]))
        self.memory_hook=self.u.hook_add(UC_HOOK_MEM_READ|UC_HOOK_MEM_WRITE,memory)
        self.code_hook=self.u.hook_add(UC_HOOK_CODE,code)
        self.old={}
        def boundary(address,fn):
            self.old[address]=machine.extra.get(address);machine.extra[address]=fn
        self.boundary=boundary
        def event(cpu,address):
            args=[cpu.reg_read(getattr(r,'UC_ARM64_REG_X'+str(i))) for i in range(3)]
            self.events.append(dict(address=hex(address),args=args));return 0
        for address in (0x24f0964,0x35b858c,0x3694f64,0x252d80c,0x252ca34):
            boundary(address,lambda cpu,at=address:event(cpu,at))
        for address in (0x2e7d208,0x2e7cee4,0x2542a30,0x2542a40):
            boundary(address,lambda cpu:0)
        context,table=WORK+0x5400,WORK+0x5480
        self.u.mem_write(controller+0x180,struct.pack('<Q',context))
        self.u.mem_write(context,struct.pack('<Q',table))
        self.u.mem_write(table+0x30,struct.pack('<Q',WORK+0xa050))
        boundary(WORK+0xa050,lambda cpu:0)
        self.label=machine.call(0x28c5684);self.label_meta=machine.call(0x28c5698)
        self.option=machine.call(0x28cc888)
        self.restriction=machine.call(0x28bfdcc)
        for p in (self.label,self.label_meta,self.label_meta+39,self.option,self.restriction,base_array-4):
            refresh.ensure_page(p)
        self.metadata_before=bytes(self.u.mem_read(self.label_meta,40))
        self.u.mem_write(self.label_meta,b'\0'*40)

    def execute(self,menu,entry=0x220a7ac,direction=None):
        m,u=self.m,self.u
        u.mem_write(self.model,struct.pack('<I',menu))
        u.mem_write(self.label,struct.pack('<I',0xdeadbeef))
        self.events.clear();self.reads.clear();self.writes.clear();self.normalizers=0
        catalog=bytes(u.mem_read(self.s['af_ap_catalog'],6888))
        original=bytes(u.mem_read(self.base-4,76));scalar=bytes(u.mem_read(self.selector,4))
        self.active=True
        try:m.call(entry,self.controller,*(() if direction is None else (direction,)),limit=100000)
        finally:self.active=False
        self.last=dict(menu=hex(menu),entry=hex(entry),base_reads=self.reads[:],
                       base_writes=self.writes[:],normalizers=self.normalizers,
                       label=hex(struct.unpack('<I',u.mem_read(self.label,4))[0]),events=self.events[:])
        if bytes(u.mem_read(self.s['af_ap_catalog'],6888))!=catalog:
            raise ValueError('初始化或非基底焦点的切换修改用户预设')
        if bytes(u.mem_read(self.base-4,76))!=original or bytes(u.mem_read(self.selector,4))!=scalar:
            raise ValueError('初始化/基底回调改写原厂基底数组或0x690')
        return self.last

    def collect(self):
        m,u=self.m,self.u
        # 独立核对原厂0..11内部编号到菜单的映射，不能把内部10/11当作用户槽。
        internal_to_menu=list(range(0x84c,0x852))+list(range(0x854,0x858))+[0x852,0x853]
        for internal,menu in enumerate(internal_to_menu):
            if m.call(0x220a3b8,self.controller,internal)!=menu:
                raise ValueError('原厂基底编号与菜单映射改变')
            expected=17 if internal==10 else 18 if internal==11 else internal
            if m.call(0x2dc6028,internal)!=expected:
                raise ValueError('原厂内部基底到外观选择值映射不符')
        # 用实际种子入口验证12种内部基底及非法编号；临时目录和输入字节均精确恢复。
        catalog=self.s['af_ap_catalog'];saved=bytes(u.mem_read(catalog,6888))
        native_base=bytes(u.mem_read(self.base+40,4))
        for internal in range(12):
            m.call(self.s['af_catalog_init'],catalog)
            u.mem_write(self.base+40,struct.pack('<I',internal))
            if m.call(self.s['af_ap_native_seed'],1)!=0:
                raise ValueError('合法原厂内部基底未迁入用户槽')
            m.call(self.s['af_read'],catalog,1,0,WORK+0x1800)
            expected=17 if internal==10 else 18 if internal==11 else internal
            if bytes(u.mem_read(WORK+0x1800,1))[0]!=expected:
                raise ValueError('原厂基底种子未转换独立选择值')
        before=bytes(u.mem_read(catalog,6888))
        for internal in (12,17,18,0xffffffff):
            u.mem_write(self.base+40,struct.pack('<I',internal))
            if m.call(self.s['af_ap_native_seed'],1)&0xffffffff!=0xffffffff or bytes(u.mem_read(catalog,6888))!=before:
                raise ValueError('非法原厂基底未拒绝或污染目录')
        u.mem_write(self.base+40,native_base)
        m.call(self.s['af_catalog_init'],catalog)
        self.execute(MENU_IDS[18])
        if self.events or self.reads or self.normalizers:raise ValueError('空用户槽仍执行原厂初始化')
        u.mem_write(catalog,saved)
        u.mem_write(self.base-4,struct.pack('<I',0xdadadada))
        u.mem_write(self.restriction,b'\0'*4)
        u.mem_write(self.option,struct.pack('<I',3))
        count=0;navigation=None
        for row in list(range(18,32))+list(range(12,18)):
            slot=row-11;menu=MENU_IDS[row]
            if m.call(self.s['af_read'],self.s['af_ap_catalog'],slot,0,WORK+0x1800)!=0:
                raise ValueError('初始化研究槽未安装')
            base=bytes(u.mem_read(WORK+0x1800,1))[0]
            internal=10 if base==17 else 11 if base==18 else base
            result=self.execute(menu)
            if result['base_reads'] or result['base_writes'] or result['normalizers']:
                raise ValueError('用户初始化进入原厂基底数组或正规化器')
            if int(result['label'],16)!=internal_to_menu[internal]:
                raise ValueError('用户初始化未按独立工作基底显示名称')
            notices=[e['args'][0] for e in self.events if e['address']==hex(0x252d80c)]
            if notices!=[0x1945,0x1700] or any(e['address']==hex(0x252ca34) for e in self.events):
                raise ValueError('初始化UI基底属性通知与原流程不符')
            if m.count(self.engine.object+8)!=9 or any(self.engine.state(k) is not None for k in range(0x1a,0x21)):
                raise ValueError('原初始化未隐藏限制布局组件')
            if count==0:navigation=self.engine.navigation()
            self.refresh.cycle()
            for direction in (0,1):
                result=self.execute(menu,0x220ac74,direction)
                if self.events or self.reads or self.writes or self.normalizers:
                    raise ValueError('用户基底回调进入原厂读写链')
            count+=1
        # 让原调用者查询以真实机器码重入挂钩，确认私有上下文不会被覆盖或提前清除。
        address=WORK+0xa100
        stub=struct.pack('<8I2Q',0xa9bf7bfd,0x580000e0,0x58000110,0xd63f0200,
                         0xa8c17bfd,0x52800000,0xd65f03c0,0xd503201f,self.controller,0x220a7ac)
        u.mem_write(address,stub)
        u.mem_write(WORK+0x5480+0x30,struct.pack('<Q',address))
        result=self.execute(MENU_IDS[18])
        u.mem_write(WORK+0x5480+0x30,struct.pack('<Q',WORK+0xa050))
        if self.reads or self.normalizers or sum(e['address']==hex(0x1af3cdc) for e in self.events)!=1:
            raise ValueError('重入初始化污染私有上下文或重复执行界面配置')
        self.refresh.cycle()
        # 原厂初始值按内部编号放入18项数组，验证12外观仍执行真实初始化。
        for row in range(12):
            selector=SELECTORS[row];index=selector-1 if selector>=17 else selector
            internal=internal_to_menu.index(MENU_IDS[row])
            u.mem_write(self.base+index*4,struct.pack('<I',internal))
            result=self.execute(MENU_IDS[row])
            if len(result['base_reads'])!=1 or result['normalizers']!=1 or result['label']!=hex(MENU_IDS[row]):
                raise ValueError('原厂完整初始化委派改变')
        # 禁用新身份与实时限制均不得落入原初始化；旧六槽限制布局仍走原路径。
        rejected=0
        m.call(self.s['af_ap_research_enable'],0)
        result=self.execute(MENU_IDS[18])
        if self.events or self.reads or self.normalizers:raise ValueError('禁用的新身份仍初始化')
        rejected+=1
        m.call(self.s['af_ap_research_enable'],1)
        u.mem_write(self.restriction,struct.pack('<I',1))
        result=self.execute(MENU_IDS[31])
        if self.events or self.reads or self.normalizers:raise ValueError('限制布局的新身份仍初始化')
        rejected+=1
        result=self.execute(MENU_IDS[12])
        if len(self.reads)!=1 or self.normalizers!=1:raise ValueError('旧六槽限制布局委派丢失')
        u.mem_write(self.restriction,b'\0'*4)
        # 原厂基底回调保留原循环/显示写入；成像包装器和有界向量是明确边界。
        vector=WORK+0x12c0
        values=[0,1,2,3,4,5,10,11,6,7,8,9]
        u.mem_write(vector,struct.pack('<12I',*values))
        def base_vector(cpu):
            destination=cpu.reg_read(self.r.UC_ARM64_REG_X8)
            cpu.mem_write(destination,struct.pack('<3Q',vector,vector+48,vector+48));return destination
        self.boundary(0x220ab50,base_vector)
        self.boundary(0x16d9870,lambda cpu:0)
        for address in (0x263d3ec,0x263bdb0):
            def base_setter(cpu,at=address):
                self.events.append(dict(address=hex(at),args=[cpu.reg_read(self.r.UC_ARM64_REG_X0),
                    cpu.reg_read(self.r.UC_ARM64_REG_X1)]));return 0
            self.boundary(address,base_setter)
        selector_before=bytes(u.mem_read(self.selector,4))
        u.mem_write(self.selector,b'\0'*4)
        # 原厂此回调0向前、1向后，与八项数值步进的方向解释不同。
        for direction,expected in ((0,9),(1,1)):
            result=self.execute(MENU_IDS[0],0x220ac74,direction)
            setters=[(e['address'],e['args'][1]) for e in self.events
                     if e['address'] in (hex(0x263d3ec),hex(0x263bdb0))]
            if setters!=[(hex(0x263d3ec),expected),(hex(0x263bdb0),expected)] or result['label']!=hex(internal_to_menu[expected]):
                raise ValueError('原厂基底切换回调未保留方向/环绕或名称')
        u.mem_write(self.selector,selector_before)
        u.mem_write(self.label_meta,self.metadata_before)
        for at,fn in self.old.items():
            if fn is None:del m.extra[at]
            else:m.extra[at]=fn
        u.hook_del(self.memory_hook);u.hook_del(self.code_hook)
        return dict(native_initializer='0x220a7ac',native_base_cycle='0x220ac74',
                    user_initializer_cases=count,user_base_cycles_blocked_at_nonbase_focus=count*2,
                    builtin_full_initializer_cases=12,blocked_initializers=rejected,
                    internal_base_mapping_cases=24,legacy_restricted_initializer_preserved=True,
                    native_seed_mapping_cases=12,native_seed_invalid_rejected=4,
                    empty_initializer_rejected=True,reentrant_initializer_isolated=True,
                    builtin_base_cycle_delegations=2,
                    user_native_array_reads=0,user_native_array_writes=0,
                    user_native_normalizer_calls=0,ui_base_property='0x1700',
                    user_base_editing_exercised=False,component_engine_executed=False,
                    native_focus_disable_hide_executed=True,
                    component_full_table_executed=True,global_focus_callbacks_registered=True,
                    native_component_navigation=navigation,
                    full_native_screen_verified=False,
                    fixture_boundaries=['caller screen query','component allocator/zero/free and chosen mode',
                        'property group reset','lock/journal/notification/logger',
                        'model inputs and native array sentinels','bounded base vector/free and image setter envelopes',
                        'native reentrant caller-query fixture'])
