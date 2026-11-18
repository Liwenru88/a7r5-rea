"""执行原回调注册、全表组件构造、焦点及状态；通用内存/通知后端有界替代。"""
import hashlib
import struct

from .access_evidence import WORK


class ComponentProbe:
    def __init__(self,machine,controller,ensure_page):
        self.m,self.u=machine,machine.cpu
        self.object=controller+0x1a0
        self.ensure_page=ensure_page
        self.focus_notices=0
        self.freed=[]
        self.first_allocation=len(machine.allocations)
        self.owned=set()
        self.allocating_start=self.first_allocation
        self.m.allocation_sizes.update((16,32,56))
        self.m.component_buckets=True
        from unicorn import arm64_const as r
        self.r=r
        def journal(cpu):return 0
        def notice(cpu):
            model=cpu.reg_read(r.UC_ARM64_REG_X0)
            if not 0x1942<=model<=0x1945:
                raise ValueError('原焦点引擎通知了非焦点模型')
            self.focus_notices+=1;return 0
        def release(cpu):
            address=cpu.reg_read(r.UC_ARM64_REG_X0)
            if address not in self.allocations() or address in self.freed:
                raise ValueError('组件释放未知或已释放节点')
            self.freed.append(address);return 0
        def zero(cpu):
            destination,value,size=[cpu.reg_read(getattr(r,'UC_ARM64_REG_X'+str(i))) for i in range(3)]
            capacity=self.allocations().get(destination)
            inline={self.object+x for x in (0x68,0xa0,0xd8)}|{0x74da1f0,0x74da228}
            if value or destination in self.freed or not (
                    capacity is not None and 0<size<=capacity or destination in inline and size==8):
                raise ValueError('组件清零超出已登记内存')
            cpu.mem_write(destination,b'\0'*size);return destination
        machine.extra[0x3694f64]=journal
        machine.extra[0x252d80c]=notice
        machine.extra[0x16d9870]=release
        machine.extra[0x16d95f0]=zero
        self.models=[]
        for get in (0x28ca3a8,0x28ca3d0,0x28ca3f8,0x28ca420):
            value=machine.call(get);meta=machine.call(get+0x14)
            for at in (value,meta,meta+39):ensure_page(at)
            self.u.mem_write(value,b'\0'*4);self.u.mem_write(meta,b'\0'*40)
            self.models.append(value)
        # 原全局构造器复制原回调记录，再执行两份真实散列表构造；只接住退出登记。
        for destination in (0x74da1c0,0x74da1f8):ensure_page(destination);ensure_page(destination+55)
        self.exit_callbacks=[]
        def at_exit(cpu):
            entry=tuple(cpu.reg_read(getattr(r,'UC_ARM64_REG_X'+str(i))) for i in range(3))
            self.exit_callbacks.append(entry);return 0
        previous_copy=machine.extra.get(0x16d9770)
        def copy(cpu):
            dest,source,size=[cpu.reg_read(getattr(r,'UC_ARM64_REG_X'+str(i))) for i in range(3)]
            if (source,size) not in ((0x5991f98,168),(0x5992040,192)):
                if previous_copy is None:raise ValueError('组件回调复制来源不符')
                return previous_copy(cpu)
            if not 0x90100000<=dest<dest+size<=0x90110000:raise ValueError('组件回调复制目的越界')
            machine.map_ap(*range(source&~4095,((source+size+4095)&~4095),4096))
            cpu.mem_write(dest,bytes(cpu.mem_read(source,size)));return dest
        machine.extra[0x16dc7f0]=at_exit;machine.extra[0x16d9770]=copy
        machine.call(0x16f5ae8,limit=300000)
        self.owned.update(a for a,n in machine.allocations[self.first_allocation:])
        self.allocating_start=None
        if len(self.exit_callbacks)!=2 or [row[1] for row in self.exit_callbacks]!=[0x74da1c0,0x74da1f8]:
            raise ValueError('原焦点全局注册未登记两份回调容器')
        for destination,start,count in ((0x74da1c0,0x5991f98,7),(0x74da1f8,0x5992040,8)):
            expected={machine.ap.ptr(start+i*24):tuple(machine.ap.ptr(start+i*24+j*8) for j in range(3))
                      for i in range(count)}
            node=struct.unpack('<Q',self.u.mem_read(destination+0x10,8))[0];actual={}
            while node:
                row=struct.unpack('<3Q',self.u.mem_read(node+8,24))
                if row[0] in actual or len(actual)>=count:raise ValueError('原回调注册链重复或超出记录数')
                actual[row[0]]=row;node=struct.unpack('<Q',self.u.mem_read(node,8))[0]
            if actual!=expected:raise ValueError('原全局注册未保持全部回调记录')
        self.records=[]
        table=0x3c467e0
        for i in range(107):
            row=struct.unpack('<8I',machine.ap.read(table+i*32,32));kind=row[0]
            if (5<=kind<=68 and (0x80100101288038d1>>(kind-5))&1) or kind==0x8a:
                self.records.append(row)
        if [row[1] for row in self.records]!=[15,*range(18,33)]:
            raise ValueError('原调参输入组件身份集合改变')
        self.table_sha256=hashlib.sha256(machine.ap.read(table,107*32)).hexdigest()
        self.construct()

    def construct(self):
        # 原构造器遍历全部107项，类型筛选、树/附属表与分组构造均由原代码执行。
        m,u=self.m,self.u
        self.component_start=len(m.allocations)
        self.allocating_start=self.component_start
        m.call(0x1af57c0,self.object,0x3c467e0,107,limit=300000)
        self.component_allocations={a for a,n in m.allocations[self.component_start:]}
        self.owned.update(self.component_allocations)
        self.allocating_start=None
        m.call(0x1af3d78,self.object,3)
        if self.container_counts()!=[16]*6 or not m.redzones():raise ValueError('原组件六容器构造失败或越界')

    def allocations(self):
        owned={a:n for a,n in self.m.allocations if a in self.owned}
        if self.allocating_start is not None:owned.update(self.m.allocations[self.allocating_start:])
        return owned

    def container_counts(self):
        trees=[self.m.count(self.object+x) for x in (8,0xe0,0x110)]
        hashes=[struct.unpack('<Q',self.u.mem_read(self.object+x+0x18,8))[0] for x in (0x38,0x70,0xa8)]
        return trees+hashes

    def set_focus(self,component):
        self.m.call(0x1af3cdc,self.object,component)
        if self.m.call(0x1af11f0,self.object)&0xffffffff!=component:
            raise ValueError('原组件焦点回调读写不一致')

    def state(self,component):
        self.u.mem_write(WORK+0x1700,struct.pack('<I',component))
        node=self.m.call(0x1af1cf4,self.object+8,WORK+0x1700)
        if node==self.object+16:return None
        if struct.unpack('<I',self.u.mem_read(node+0x20,4))[0]!=component:
            raise ValueError('原组件树查找到错误身份')
        return dict(node=hex(node),disabled=bytes(self.u.mem_read(node+0x34,1))[0])

    def verify(self):
        m,u=self.m,self.u
        for mode in range(4):
            m.call(0x1af3d78,self.object,mode)
            self.set_focus(0x12+mode)
            if struct.unpack('<I',u.mem_read(self.models[mode],4))[0]!=0x12+mode:
                raise ValueError('原焦点模式未路由对应UI属性')
        m.call(0x1af3d78,self.object,3)
        before=self.state(0xf)
        m.call(0x1af1d48,self.object,0xf,1)
        if self.state(0xf)['disabled']!=1:raise ValueError('原组件禁用标记未写入')
        m.call(0x1af1d48,self.object,0xf,0)
        if self.state(0xf)!=before:raise ValueError('原组件重新启用未恢复')
        count=m.count(self.object+8)
        freed_before=len(self.freed)
        m.call(0x1af3290,self.object,0x1a)
        if self.state(0x1a) is not None or self.container_counts()!=[count-1]*6 or len(self.freed)!=freed_before+6:
            raise ValueError('原隐藏处理未移除/释放对应组件')
        m.call(0x1af3290,self.object,0x1a)
        if self.container_counts()!=[count-1]*6 or len(self.freed)!=freed_before+6:raise ValueError('重复隐藏重复释放组件')
        try:m.call(0x16d9870,self.freed[-1])
        except ValueError as error:
            if '已释放节点' not in str(error):raise
        else:raise ValueError('组件释放后端未拒绝重复释放')
        if len(self.freed)!=freed_before+6:raise ValueError('拒绝重复释放仍改变记录')
        # 输入引擎查找不存在的编号不会创建节点；轮盘组件另由图形/事件引擎承接。
        if self.state(0x10) is not None:raise ValueError('轮盘组件被错误伪造为矩形输入节点')
        # 验证即使显式放行65字节，分配后端的64字节硬限制仍生效。
        heap=m.heap;m.allocation_sizes.add(65)
        try:m.call(0x16dc130,65)
        except ValueError as error:
            if '超出隔离预算' not in str(error):raise
        else:raise ValueError('组件分配器放宽了64字节硬限制')
        finally:m.allocation_sizes.remove(65)
        if m.heap!=heap:raise ValueError('拒绝分配改变内存池')
        # 大桶例外只允许原桶分配调用点；普通调用即使尺寸相同也必须拒绝。
        try:m.call(0x16dc130,88)
        except ValueError as error:
            if '超出隔离预算' not in str(error):raise
        else:raise ValueError('原桶分配例外扩散到其他调用点')
        if m.heap!=heap:raise ValueError('拒绝非桶调用改变内存池')
        # 先执行原组件析构并核对所属节点全部释放，再执行原全表重建。
        self.destroy()
        self.construct()
        return dict(input_nodes=16,input_component_ids=[row[1] for row in self.records],
                    source_table='0x3c467e0',source_table_bytes=107*32,source_sha256=self.table_sha256,
                    native_empty_constructor_executed=False,native_node_insert_executed=True,
                    native_focus_read_write_modes=4,native_disable_enable=True,
                    native_hide_and_repeat=True,native_tree_erase='libstdc++ 0xa65e8',
                    component_containers=6,freed_nodes_per_hidden_component=6,double_free_rejected=True,
                    bounded_allocator_hard_limit=64,oversized_request_rejected=True,
                    typed_bucket_exceptions=[88,136,184],shared_allocator_pool_bytes=0x100000,
                    wheel_component_0x10_in_rect_tree=False,full_table_constructor_executed=True,
                    global_callback_registration_executed=True,native_component_destructor_executed=True,
                    global_callback_records_verified=15,wrong_bucket_caller_rejected=True,
                    pixel_rendering_verified=False,
                    fixture_boundaries=['bounded allocator/zero/free','exit registration envelope',
                        'UI lock/journal/notification backend',
                        'mode argument and model initial bytes'])

    def destroy(self):
        self.m.call(0x1af1bc0,self.object,limit=100000)
        if self.component_allocations-set(self.freed) or not self.m.redzones():
            raise ValueError('原组件析构未释放全部所属节点或越界')

    def navigation(self):
        # 在真实初始化隐藏替代布局之后，按原几何位置校验左右导航及首尾环绕。
        m,u=self.m,self.u
        previous=m.call(0x1af11f0,self.object)
        order=[row[1] for row in sorted(self.records,key=lambda row:row[2])
               if self.state(row[1]) is not None and not self.state(row[1])['disabled']]
        if len(order) not in (8,9) or not set(range(18,26))<=set(order):
            raise ValueError('初始化后原参数导航集合不符')
        for entry,direction in ((0x1af3a44,-1),(0x1af3ad8,1)):
            for i,component in enumerate(order):
                self.set_focus(component);m.call(entry,self.object)
                if m.call(0x1af11f0,self.object)!=order[(i+direction)%len(order)]:
                    raise ValueError('原参数导航未保持几何顺序或首尾环绕')
        m.call(0x1af1d48,self.object,21,1)
        for start,entry,expected in ((22,0x1af3ad8,20),(20,0x1af3a44,22)):
            self.set_focus(start);m.call(entry,self.object)
            if m.call(0x1af11f0,self.object)!=expected:raise ValueError('原参数导航未跳过禁用项')
        m.call(0x1af1d48,self.object,21,0)
        self.set_focus(previous)
        return dict(native_entries=['0x1af3a44','0x1af3ad8'],enabled_order=order,
                    direction_and_wrap_cases=2*len(order),disabled_skip_cases=2,
                    hidden_layout_components=7,qt_keyboard_verified=False,touch_wheel_verified=False)

    def finish(self):
        self.destroy()
        for callback,obj,dso in reversed(self.exit_callbacks):self.m.call(callback,obj,limit=100000)
        if self.owned-set(self.freed) or not self.m.redzones():raise ValueError('原焦点注册表析构后仍有未释放节点')
        return dict(all_owned_allocations_released=True,exit_destructors_executed=2,
                    allocated_blocks=len(self.owned),freed_blocks=len(self.freed),
                    bucket_sizes=sorted({n for a,n in self.allocations().items() if n>64}),
                    native_qt_page_lifecycle_verified=False)
