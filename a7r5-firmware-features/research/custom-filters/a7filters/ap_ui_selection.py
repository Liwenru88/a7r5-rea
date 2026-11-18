"""真实列表提交和界面刷新查询/快照消费；客体绘制与像素仍不在此验收。"""
import struct

from .access_evidence import WORK, STACK
from .ui_evidence import MENU_IDS, SELECTORS, PARENT_TABLE, PARENT_BYTES


class SelectionRefreshProbe:
    def __init__(self, machine, symbols, model, native_selector, output):
        from unicorn import arm64_const as regs
        self.m, self.u, self.s = machine, machine.cpu, symbols
        self.r, self.model, self.selector, self.output = regs, model, native_selector, output
        self.manager = WORK+0x7000
        self.view = 0x91400000
        self.data = self.view+0x7000
        self.u.mem_map(self.view,0x8000)
        self.u.mem_write(self.manager,b'\0'*0x400)
        self.scheduler_state = machine.ap.ptr(0x5952b80)
        self.kind = 'main'
        self.cycles = self.scheduled = self.consumed = 0
        self.processors = (0x23ff0ac,0x23ff0e0,0x23ff268,0x2405218,
                           0x23dd924,0x2405c9c,0x23dd818)
        # 无关界面字段的计算器是明确边界；八项快照调用及其上层函数不替换。
        for address in self.processors: machine.extra[address] = lambda cpu:0
        previous_clear=machine.extra.get(0x16d95f0)
        def clear_bits(cpu):
            dest = cpu.reg_read(regs.UC_ARM64_REG_X0)
            size = cpu.reg_read(regs.UC_ARM64_REG_X2)
            if size==0x400 and STACK<=dest<=STACK+0x10000-size:
                cpu.mem_write(dest,b'\0'*size);return dest
            if dest != 0x7ef88a8 or size != 0x998:
                if previous_clear is not None:return previous_clear(cpu)
                raise ValueError('刷新窗口清零边界超出已验证界面脏位区')
            for page in (0x7ef8000,0x7ef9000): self.ensure_page(page)
            cpu.mem_write(dest,b'\0'*size)
            return dest
        machine.extra[0x16d95f0] = clear_bits
        self.set_view('main')
        self.ensure_page(self.scheduler_state)

    def ensure_page(self, address):
        page = address&~4095
        if page in self.m.pages: return
        seg = next(s for s in self.m.ap.segments
                   if s['p_vaddr']<=page<s['p_vaddr']+s['p_memsz'])
        if page < seg['p_vaddr']+seg['p_filesz']: self.m.map_ap(page)
        else: self.u.mem_map(page,4096);self.m.pages.add(page)

    def set_view(self, kind):
        self.kind = kind
        self.u.mem_write(self.view,b'\0'*0x8000)
        table = {'main':0x58ca670,'parameter':0x58ca720,'other':0x58ca6c8}[kind]
        self.u.mem_write(self.view,struct.pack('<Q',table))
        self.u.mem_write(self.manager+0x338,struct.pack('<Q',self.view))
        if kind == 'other': return
        model_offset, field = (0x48,0xd8) if kind=='main' else (0x90,0x218)
        self.u.mem_write(self.view+model_offset,struct.pack('<Q',self.data))
        self.u.mem_write(self.data+field,struct.pack('<Q',self.output))

    def query(self):
        return self.m.call(0x1e97a24,self.manager)

    def empty_selection(self, menu, selector):
        u,m=self.u,self.m
        u.mem_write(self.model,struct.pack('<I',menu))
        before=bytes(u.mem_read(self.selector,4))
        catalog=bytes(u.mem_read(self.s['af_ap_catalog'],6888))
        for entry,args in ((0x1c6f208,(selector,)),(0x25966cc,(0,selector)),
                           (0x1c956c8,(menu,))):
            m.call(entry,*args)
            self.cycle(False)
            if bytes(u.mem_read(self.selector,4))!=before or bytes(u.mem_read(self.s['af_ap_catalog'],6888))!=catalog:
                raise ValueError('空槽提交修改原厂模型或目录')

    def cycle(self, expected=True):
        """执行真实调度窗口；帧驱动只在其请求后调用原厂快照消费者。"""
        r,u = self.r,self.u
        self.cycles += 1
        u.mem_write(self.scheduler_state,struct.pack('<I',2))
        u.reg_write(r.UC_ARM64_REG_X19,self.manager)
        u.reg_write(r.UC_ARM64_REG_SP,STACK+0x8000)
        u.emu_start(0x1ec7388,0x1ec73a4,count=20000)
        if u.reg_read(r.UC_ARM64_REG_PC)!=0x1ec73a4 or u.reg_read(r.UC_ARM64_REG_SP)!=STACK+0x8000:
            raise ValueError('原厂刷新查询/请求窗口未正常返回')
        scheduled = struct.unpack('<I',u.mem_read(self.scheduler_state,4))[0] == 1
        if scheduled != expected: raise ValueError('用户修改的界面刷新判定不符')
        self.scheduled += scheduled
        if not scheduled: return
        if self.kind == 'other': raise ValueError('非目标呈现器被刷新')
        self.m.call(0x1e1e1d8 if self.kind=='main' else 0x1e1ea74,self.view)
        self.consumed += 1
        if self.query()!=0: raise ValueError('快照消费后刷新请求未清除')

    def selections(self, object_address, vtable, metadata):
        """两条原厂上层分派一直执行到实际写入入口，不替换菜单转选择器。"""
        m,u,r = self.m,self.u,self.r
        parents,descriptors = WORK+0x1100,WORK+0x1140
        m.initialize(parents);m.initialize(descriptors)
        m.append(0x1c935e0,parents,m.ap.read(PARENT_TABLE,PARENT_BYTES))
        m.append(0x1c91e94,descriptors,struct.pack('<2Q',0x1f2,0x5858b08))
        m.map_ap(0x593f000,0x5961000)
        u.mem_write(0x593fbd8,struct.pack('<Q',parents))
        u.mem_write(0x59611f8,struct.pack('<Q',descriptors))
        u.mem_write(vtable+0x208,struct.pack('<Q',WORK+0xa030))
        u.mem_write(vtable+0x250,struct.pack('<Q',WORK+0xa038))
        m.extra[WORK+0xa030] = lambda cpu:1
        m.extra[WORK+0xa038] = lambda cpu:0
        events = []
        envelopes = []
        def transaction(cpu):
            p = cpu.reg_read(r.UC_ARM64_REG_X0)
            cpu.mem_write(p,struct.pack('<2Q',WORK+0x120,WORK+0x128))
            return 0
        def notified(cpu, address):
            events.append((address,cpu.reg_read(r.UC_ARM64_REG_X0)))
            return 0
        boundaries = {0x17f7d44:transaction,0x17f7d68:lambda cpu:0,
                      0x2542a30:transaction,0x2542a40:lambda cpu:0,
                      0x3694f64:lambda cpu:0}
        for address in (0x3694fe8,0x3701c38,0x3701e08,0x36950d4,0x2e781b0):
            def envelope(cpu,at=address):
                if cpu.reg_read(r.UC_ARM64_REG_X0)!=0x3ced:
                    raise ValueError('预览外层消息身份改变')
                envelopes.append(at);return 0
            boundaries[address] = envelope
        for address in (0x252d80c,0x252ca34):
            boundaries[address] = lambda cpu,at=address:notified(cpu,at)
        old = {at:m.extra.get(at) for at in boundaries}
        m.extra.update(boundaries)
        metadata_before = bytes(u.mem_read(metadata,40))
        u.mem_write(metadata,b'\0'*40)
        catalog_before = bytes(u.mem_read(self.s['af_ap_catalog'],6888))
        original_cases = user_cases = 0
        routes = (0x1bd924c,0x1bd9348)
        for entry in routes:
            for row in list(range(12))+[32]:
                u.mem_write(self.model,struct.pack('<I',MENU_IDS[row]))
                u.mem_write(self.selector,b'\0'*4);events.clear();envelopes.clear()
                m.call(entry,object_address,MENU_IDS[row],limit=30000)
                if struct.unpack('<I',u.mem_read(self.selector,4))[0]!=SELECTORS[row]:
                    raise ValueError('原厂列表提交未按原选择器委派')
                if events!=[(0x252d80c,0x690),(0x252ca34,0x690)]:
                    raise ValueError('原厂列表提交属性通知改变')
                if len(envelopes)!=(5 if entry==0x1bd9348 else 0):
                    raise ValueError('原厂预览外层消息委派改变')
                original_cases += 1
            for row in range(12,32):
                menu = MENU_IDS[row]
                u.mem_write(self.model,struct.pack('<I',menu))
                u.mem_write(self.selector,struct.pack('<I',18));events.clear();envelopes.clear()
                m.call(entry,object_address,menu,limit=30000)
                if struct.unpack('<I',u.mem_read(self.selector,4))[0]!=18 or events or envelopes:
                    raise ValueError('用户列表提交泄漏到原厂0x690或属性通知')
                if bytes(u.mem_read(self.s['af_ap_catalog'],6888))!=catalog_before:
                    raise ValueError('用户选择修改预设或保存状态')
                if self.query()!=1 or self.query()!=1:
                    raise ValueError('列表请求未产生刷新或被查询提前消费')
                self.cycle()
                user_cases += 1
        # 不相关页面保持静默，请求等目标页面出现后仍可消费。
        menu=MENU_IDS[18];u.mem_write(self.model,struct.pack('<I',menu))
        m.call(0x1c6f208,19)
        self.set_view('other');self.cycle(False)
        self.set_view('parameter');self.cycle()
        # 切换身份丢弃旧请求，不刷新到另一个预设。
        m.call(0x1c6f208,19);u.mem_write(self.model,struct.pack('<I',MENU_IDS[31]))
        self.cycle(False)
        # 错配和无效选择均不产生刷新，也不写原模型。
        for selector in (19,33,0xffffffff):
            events.clear();m.call(0x1c6f208,selector)
            self.cycle(False)
            if events or struct.unpack('<I',u.mem_read(self.selector,4))[0]!=18:
                raise ValueError('错配或越界选择泄漏到原模型')
        # 两个叶子均拒绝非法扩展值，包含禁用研究后的直接调用。
        leaf_cases=0
        for enabled in (1,0):
            if m.call(self.s['af_ap_research_enable'],enabled)!=0:
                raise ValueError('研究开关切换失败')
            for selector in (19,32,33,0xffffffff):
                u.mem_write(self.model,struct.pack('<I',MENU_IDS[0]))
                for entry,args in ((0x1c6f208,(selector,)),(0x25966cc,(0,selector))):
                    events.clear();envelopes.clear()
                    m.call(entry,*args);self.cycle(False)
                    if events or envelopes or struct.unpack('<I',u.mem_read(self.selector,4))[0]!=18:
                        raise ValueError('叶子扩展值或禁用状态泄漏原模型')
                    leaf_cases+=1
        m.call(self.s['af_ap_research_enable'],1)
        # 原厂限制布局下，旧六槽继续原路径，新增槽始终不能写0x690。
        restriction=m.call(0x28bfdcc)
        u.mem_write(restriction,struct.pack('<I',1))
        for entry in routes:
            for row in (12,17,18,31):
                u.mem_write(self.model,struct.pack('<I',MENU_IDS[row]))
                u.mem_write(self.selector,struct.pack('<I',18));events.clear();envelopes.clear()
                m.call(entry,object_address,MENU_IDS[row],limit=30000)
                expected=SELECTORS[row] if row<18 else 18
                if struct.unpack('<I',u.mem_read(self.selector,4))[0]!=expected:
                    raise ValueError('限制布局未保持旧槽委派或未阻断扩展值')
                if len(events)!=(2 if row<18 else 0) or len(envelopes)!=(5 if row<18 and entry==routes[1] else 0):
                    raise ValueError('限制布局通知边界错误')
                self.cycle(False)
        u.mem_write(restriction,b'\0'*4)
        # 已有影子副本也不得被用户选择改写；原厂委派必须仍更新两个副本。
        shadow=WORK+0x1200;shadow_cases=0
        u.mem_write(metadata+8,struct.pack('<Q',shadow))
        for entry in routes:
            for row in (7,31):
                u.mem_write(self.model,struct.pack('<I',MENU_IDS[row]))
                u.mem_write(self.selector,struct.pack('<I',17));u.mem_write(shadow,struct.pack('<I',17))
                events.clear();envelopes.clear()
                m.call(entry,object_address,MENU_IDS[row],limit=30000)
                expected=18 if row==7 else 17
                if any(struct.unpack('<I',u.mem_read(p,4))[0]!=expected for p in (self.selector,shadow)):
                    raise ValueError('选择模型影子副本隔离或委派错误')
                if len(events)!=(2 if row==7 else 0) or (row==31 and envelopes):
                    raise ValueError('影子副本路径通知不符')
                self.cycle(row==31);shadow_cases+=1
        u.mem_write(metadata+8,b'\0'*8)
        self.set_view('main')
        # 原厂已有脏位仍可通过原始查询，不依赖我们的待刷新标记。
        mask=self.view+0x58;index,bit=divmod(0x3b7,64)
        self.ensure_page(0x7ef88a8)
        u.mem_write(mask+index*8,struct.pack('<Q',1<<bit))
        u.mem_write(mask+0x998,struct.pack('<I',index))
        u.mem_write(mask+0xe64,struct.pack('<I',1))
        u.mem_write(0x7ef88a8+index*8,struct.pack('<Q',1<<bit))
        if self.query()!=1:raise ValueError('原厂已有刷新请求被吞掉')
        u.mem_write(0x7ef88a8+index*8,b'\0'*8)
        self.set_view('main')
        navigation=self.navigation(vtable)
        u.mem_write(metadata,metadata_before)
        for at,fn in old.items():
            if fn is None: del m.extra[at]
            else:m.extra[at]=fn
        return dict(native_submit_entries=[hex(x) for x in routes],
                    user_submit_cases=user_cases,builtin_and_special_delegations=original_cases,
                    extension_selectors_written_to_690=0,user_property_notifications=0,
                    user_preview_envelopes=0,
                    unrelated_view_ignored=True,stale_request_discarded=True,
                    repeated_query_preserves_pending=True,native_dirty_request_preserved=True,
                    invalid_leaf_cases=leaf_cases,restricted_layout_cases=8,shadow_copy_cases=shadow_cases,
                    empty_selection_cases=3,
                    navigation_and_names=navigation,
                    fixture_boundaries=['parent map native tree and one real descriptor registration',
                        'menu eligibility and transaction/journal/message envelopes',
                        'active presenter references and empty native subscriptions',
                        'unrelated UI field processors','bounded UI dirty-bit memset',
                        'frame driver invokes original snapshot consumer only after native schedule request'],
                    full_frame_loop_executed=False,presenter_draw_executed=False)

    def navigation(self, vtable):
        """原厂索引查询及有界导航循环；屏幕准入仍是明确夹具。"""
        m,u,r=self.m,self.u,self.r
        for offset,address in ((0x278,0x1bca844),(0x2b0,0x1bd0a34),
                               (0x2e0,0x1bcf3fc),(0x258,WORK+0xa040),(0x750,0x1bd1ef8)):
            u.mem_write(vtable+offset,struct.pack('<Q',address))
        m.extra[WORK+0xa040]=lambda cpu:0
        page=m.call(0x28a8720);self.ensure_page(page)
        u.mem_write(page,struct.pack('<I',0x1e6))
        dest,screen=WORK+0x1240,WORK+0x1244
        cases=0
        for special in (False,True):
            menus=MENU_IDS if special else MENU_IDS[:-1]
            u.mem_write(self.selector,struct.pack('<I',16 if special else 0))
            for index,menu in enumerate(menus):
                u.mem_write(self.model,struct.pack('<I',menu))
                for direction in (-1,1):
                    u.mem_write(dest-8,b'\xa5'*24)
                    m.call(0x1bd7234,direction&0xffffffff,dest,screen,1,limit=100000)
                    if struct.unpack('<I',u.mem_read(dest,4))[0]!=menus[(index+direction)%len(menus)]:
                        raise ValueError('原厂导航遗漏用户槽或环绕边界错误')
                    if bytes(u.mem_read(dest-8,8))!=b'\xa5'*8 or bytes(u.mem_read(dest+8,8))!=b'\xa5'*8:
                        raise ValueError('原厂导航输出越界')
                    cases+=1
        # 同一原厂名称组件承接全部32槽，保留其余字节。
        widget=WORK+0x7800
        u.mem_write(self.data+0xb0,struct.pack('<2Q',2,widget))
        for row,menu in enumerate(MENU_IDS[:-1]):
            u.mem_write(self.view+0x3a80,struct.pack('<I',menu))
            u.mem_write(widget-8,b'\xa5'*80)
            u.reg_write(r.UC_ARM64_REG_X19,self.view)
            u.reg_write(r.UC_ARM64_REG_X20,STACK+0x8030)
            u.reg_write(r.UC_ARM64_REG_FP,STACK+0x8000)
            u.reg_write(r.UC_ARM64_REG_SP,STACK+0x8000)
            u.emu_start(0x2208e70,0x2208e94,count=10000)
            resource=m.ap.u32(0x3f4a280+row*128+8) if row<18 else 0x0200abde+row-18
            expected=bytearray(b'\xa5'*80);struct.pack_into('<I',expected,8+0x30,resource)
            if u.reg_read(r.UC_ARM64_REG_PC)!=0x2208e94 or bytes(u.mem_read(widget-8,80))!=expected:
                raise ValueError('挂钩后原厂名称窗口写入错误或越界')
        self.set_view('main')
        return dict(native_navigation_entry='0x1bd7234',directions_and_wrap_cases=cases,
                    list_sizes=[32,33],selected_name_presenter_cases=32,
                    native_index_and_enum_executed=True,screen_admission_fixture=True,
                    current_page_and_menu_are_model_fixtures=True,
                    uxc_loader_and_pixels_verified=False)
