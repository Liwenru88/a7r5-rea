"""原通信任务的一次启动及轮询；目标系统导入使用显式内存后端，无宿主设备I/O。"""
import hashlib
import struct
import time

from .access_evidence import AP_SHA,CP_SHA,WORK,STACK,STOP,require_source
from .ap_cp_messages import IPC_BASE,IPC_SHA,QUEUE,SOURCE
from .cp_message_pool import NativeMessagePool
from .native_handshake import HandshakeAP,load,AP_ENTRY,CP_ENTRY
from .ui_evidence import STD_SHA
from .investigate import AP,CP_BASE

AP_START,CP_START=0x3554d38,0x495fd8
CLOCK=WORK+0xf300


class RuntimeAP(HandshakeAP):
    def __init__(self,ap_raw,ipc_raw):
        super().__init__(ap_raw,ipc_raw)
        self.nonce=bytes.fromhex('ffeeddccbbaa9988');self.read_offset=0
        self.read_plan=[];self.open_error=False;self.close_error=False;self.dlsym_error=False
        self.clock_error=False;self.bad_nanoseconds=False;self.allocation_error=False
        self.receive_error=None;self.pending=[];self.system_events=[];self.receives=[]
        self.loop_running=False;self.loop_entered=False;self.loop_end=None;self.errno=4

    def _boundary(self,cpu,at,size,data):
        if self.loop_running:
            if at==AP_START:self.loop_entered=True
            elif self.loop_entered and at in (0x3554d24,0x3554d3c):
                self.loop_end=at;cpu.emu_stop();return
        if at==0x16dac90:
            if self.register('x0') or bytes(cpu.mem_read(self.register('x1'),14))!=b'clock_gettime\0':
                raise ValueError('只允许解析目标clock_gettime')
            self.system_events.append('dlsym clock_gettime');self._return(0 if self.dlsym_error else CLOCK);return
        if at==CLOCK:
            if self.register('w0')!=1:raise ValueError('目标时钟不是CLOCK_MONOTONIC')
            self.clock_calls+=1
            cpu.mem_write(self.register('x1'),struct.pack('<qq',self.now//1000,
                1000000000 if self.bad_nanoseconds else (self.now%1000)*1000000))
            self._return(-1 if self.clock_error else 0);return
        if at==0x16d9740:
            if bytes(cpu.mem_read(self.register('x0'),13))!=b'/dev/urandom\0' or self.register('w1'):
                raise ValueError('目标随机源路径/打开标志不符')
            self.system_events.append('open urandom fixture');self._return(-1 if self.open_error else 61);return
        if at==0x16d9840:
            fd,dest,n=[self.register('x'+str(i)) for i in range(3)]
            if fd!=61 or not 0<n<=8 or self.read_offset+n>8:raise ValueError('目标随机读取越界')
            result=self.read_plan.pop(0) if self.read_plan else n
            if result>0:
                if result>n:raise ValueError('随机后端短读计划超过请求')
                cpu.mem_write(dest,self.nonce[self.read_offset:self.read_offset+result]);self.read_offset+=result
            self.system_events.append('read '+str(result));self._return(result);return
        if at==0x16db580:
            self.word(WORK+0xf380,self.errno);self._return(WORK+0xf380);return
        if at==0x16dba00:
            if self.register('w0')!=61:raise ValueError('目标随机描述符关闭不符')
            self.system_events.append('close urandom fixture');self._return(-1 if self.close_error else 0);return
        if at==0x16daf60:
            if self.register('w0')!=50000:raise ValueError('原空错误退避时长不符')
            self.system_events.append('usleep 50000 fixture');self.now+=50;self._return();return
        if at in (0x16dae10,IPC_BASE+0x27a0):
            self.register('pc',IPC_BASE+(0x6468 if at==0x16dae10 else 0x3c60));return
        if at==IPC_BASE+0x2530:
            fd,request,args=[self.register('x'+str(i)) for i in range(3)]
            queue,pointer=self.word(args),self.quad(args+8)
            if (request&0xffffffff)==0x80000007:
                out,wait=self.quad(pointer),self.word(pointer+8)
                if fd!=37 or queue!=SOURCE or wait not in (0xffffffff,*range(1,51)):
                    raise ValueError('原OSAL接收fd/队列/超时不符')
                result=0
                if self.receive_error is not None:result=self.receive_error
                elif self.pending:
                    raw=self.pending.pop(0);incoming=WORK+0x7000
                    cpu.mem_write(incoming-24,b'\0'*24+raw)
                    self.word(incoming-12,QUEUE);self.word(incoming-8,len(raw))
                    cpu.mem_write(out,struct.pack('<Q',incoming))
                else:
                    if wait==0xffffffff:raise ValueError('不伪造原无限等待的超时')
                    self.now+=wait;result=-1022
                self.receives.append(dict(wait=wait if wait!=0xffffffff else -1,result=result))
                self._return(result);return
            if (request&0xffffffff)==0x8000000a:
                dest=self.quad(pointer);count,wait=self.word(pointer+8),self.word(pointer+12)
                if fd!=37 or queue!=QUEUE or count!=128 or wait!=0 or self.serial>=16:
                    raise ValueError('启动HELLO必须使用原分配器的非等待模式')
                if self.allocation_error:self._return(-1022);return
                message=WORK+0x6000+self.serial*0x100;self.serial+=1
                cpu.mem_write(message-24,b'\0'*152);self.word(message-8,128)
                cpu.mem_write(dest,struct.pack('<Q',message))
                self.observed.append(dict(operation='allocate',wait=wait,bytes=count));self._return();return
        super()._boundary(cpu,at,size,data)

    def step(self):
        frame=STACK+0xc000
        self.register('fp',frame);self.register('sp',frame);self.register('x23',frame+0xa0)
        self.register('lr',STOP)
        for i in range(3,19):self.register('x'+str(i),0x4000+i)
        for i in range(32):self.register('q'+str(i),int.from_bytes(bytes([i+1])*16,'little'))
        self.cpu.reg_write(self.reg.UC_ARM64_REG_NZCV,0xa0000000)
        self.cpu.reg_write(self.reg.UC_ARM64_REG_FPCR,0x1000000)
        self.cpu.reg_write(self.reg.UC_ARM64_REG_FPSR,0x800009f)
        self.loop_running=True;self.loop_entered=False;self.loop_end=None
        try:self.cpu.emu_start(0x3554d24,STOP,count=120000)
        finally:self.loop_running=False
        if self.loop_end is None or self.register('sp')!=frame:
            raise ValueError('运行时没有回到原AP接收或非空分派入口')
        if (any(self.register('x'+str(i))!=0x4000+i for i in range(3,19)) or
            any(self.register('q'+str(i))!=int.from_bytes(bytes([i+1])*16,'little') for i in range(32)) or
            self.cpu.reg_read(self.reg.UC_ARM64_REG_NZCV)!=0xa0000000 or
            self.cpu.reg_read(self.reg.UC_ARM64_REG_FPCR)!=0x1000000 or
            self.cpu.reg_read(self.reg.UC_ARM64_REG_FPSR)!=0x800009f):
            raise ValueError('原接收循环插桩破坏通用/SIMD/浮点或条件状态')
        return self.loop_end


def state(a,syms):
    session,deadline,required,status,now,attempted,fault=struct.unpack('<QQIIQII',
        a.cpu.mem_read(syms['af_ap_runtime'],40))
    return dict(session=session,deadline=deadline,required=required,state=status,now=now,
                attempted=attempted,fault=fault)


def install(a,p,aps,cps,cp):
    before=((AP_START,a.image.read(AP_START,4)),(AP_ENTRY,a.image.read(AP_ENTRY,4)),
            (CP_START,cp[CP_START-CP_BASE:CP_START-CP_BASE+8]),
            (CP_ENTRY,cp[CP_ENTRY-CP_BASE:CP_ENTRY-CP_BASE+8]))
    if [raw.hex() for _,raw in before]!=['36188697','60024039','f0b503af2de9000f','242022f192ee3078']:
        raise ValueError('运行时四处入口前像不符')
    for address,target in ((AP_START,aps['af_ap_runtime_gate']),(AP_ENTRY,aps['af_ap_hs_gate'])):
        delta=target-address
        if delta&3 or not -(1<<27)<=delta<(1<<27):raise ValueError('运行时AP分支越界')
        a.cpu.mem_write(address,struct.pack('<I',0x14000000|((delta//4)&0x3ffffff)))
        a.cpu.ctl_remove_cache(address,address+4)
    for address,target in ((CP_START,cps['af_cp_runtime_gate']),(CP_ENTRY,cps['af_cp_hs_gate'])):
        if not target&1:raise ValueError('运行时CP入口不是Thumb')
        p.m.cpu.mem_write(address,bytes.fromhex('dff800f0')+struct.pack('<I',target))
        p.m.cpu.ctl_remove_cache(address,address+8)
    return before


def boot_cp(p,cps):
    p.m.run(CP_START,0x496002,returned=False,limit=10000)
    if (p.m.register('r4')!=QUEUE or p.m.register('fp')!=0x7a0020 or
        p.m.register('sl')!=STACK+0xe000-40 or p.m.register('sp')!=STACK+0xe000-40):
        raise ValueError('CP任务启动未保持原序言或队列身份')
    return struct.unpack('<QQII',p.m.read(cps['af_cp_handshake'],24))


def registration(ap_raw,ipc_raw):
    """原注册器执行至线程创建服务；服务只登记参数，不创建宿主线程。"""
    from unicorn import UC_HOOK_CODE,UC_PROT_READ,UC_PROT_WRITE,UC_PROT_EXEC
    a=RuntimeAP(ap_raw,ipc_raw);seen=[]
    for page in (0x3552000,0x3702000,0x5782000,0x89bc000,0x8e82000,0x5008000,0x5c75000):
        segment=next(s for s in a.image.segments if s['p_vaddr']<=page<s['p_vaddr']+s['p_memsz'])
        flags=segment['p_flags']
        a.cpu.mem_map(page,4096,UC_PROT_READ|(UC_PROT_WRITE if flags&2 else 0)|(UC_PROT_EXEC if flags&1 else 0))
        size=max(0,min(4096,segment['p_vaddr']+segment['p_filesz']-page))
        if size:a.cpu.mem_write(page,a.image.read(page,size))
    def boundary(cpu,at,size,data):
        if at==0x16d9fc0:
            desc,output=a.register('x0'),a.register('x1')
            raw=bytes(cpu.mem_read(desc,40));name_pointer=struct.unpack_from('<Q',raw)[0]
            name=a.image.read(name_pointer,48).split(b'\0')[0].decode('ascii')
            if (struct.unpack_from('<Q',raw,16)[0]!=0x3702a88 or
                struct.unpack_from('<Q',raw,24)[0]!=0x8e82e98):
                raise ValueError('原通信线程创建参数/注册对象不符')
            seen.append(dict(descriptor=raw.hex(),name=name,trampoline=hex(0x3702a88),
                registration_record=hex(0x8e82e98),native_service='osal_create_waitable_thread',
                actual_thread_created=False))
            cpu.mem_write(output,struct.pack('<Q',0x1234));a._return()
        elif at==0x17fc630:a._return()
    hook=a.cpu.hook_add(UC_HOOK_CODE,boundary)
    try:
        if a.call(0x3552d50) or len(seen)!=1:raise ValueError('原通信线程注册窗口未有界返回')
        data=bytes(a.cpu.mem_read(0x8e82e98,48))
        handle,entry,arg,identity,priority=struct.unpack_from('<QQQII',data)
        if (handle,entry,arg,identity,priority)!=(0x1234,0x3554cf8,0,64,8):
            raise ValueError('原线程登记未保留函数/参数/身份/优先级')
        if a.quad(0x89bcd80)!=handle:raise ValueError('原启动入口未保存线程句柄')
        return dict(creation=seen[0],handle_fixture=handle,entry=hex(entry),argument=arg,
            identity=identity,priority=priority,native_registration_executed=True,
            thread_tls_initialization_executed=False,thread_stack_budget_verified=False)
    finally:a.cpu.hook_del(hook);a.cpu=None


def collect(ap_raw,cp,ipc_raw,std_raw,ap_elf,cp_elf):
    require_source(ap_raw,AP_SHA,'AP');require_source(cp,CP_SHA,'CP')
    require_source(ipc_raw,IPC_SHA,'OSAL');require_source(std_raw,STD_SHA,'libstdc++')
    ap_image,std_image=AP(ap_raw),AP(std_raw)
    def imports(image):
        table=image.elf.get_section_by_name('.rela.plt')
        symbols=image.elf.get_section(table['sh_link'])
        start=image.elf.get_section_by_name('.plt')['sh_addr']+32
        return {symbols.get_symbol(r['r_info_sym']).name:start+16*i for i,r in enumerate(table.iter_relocations())}
    expected={'open':0x16d9740,'read':0x16d9840,'close':0x16dba00,'dlsym':0x16dac90,
              '__errno_location':0x16db580,'osal_rcv_msg_tmo':0x16dae10,
              'osal_valloc_msg_wait':0x16dc740,'osal_set_msg_src':0x16d99c0,'osal_snd_msg':0x16dafc0,
              'usleep':0x16daf60}
    actual=imports(ap_image)
    if any(actual.get(n)!=v for n,v in expected.items()) or imports(std_image).get('clock_gettime')!=0x891e0:
        raise ValueError('目标运行时导入符号或PLT入口不符')
    from capstone import Cs,CS_ARCH_ARM64
    steady=list(Cs(CS_ARCH_ARM64,0).disasm(
        std_image.read(0xb1208,24),0xb1208))
    if (not any(i.mnemonic=='mov' and i.op_str=='w0, #1' for i in steady) or
        not any(i.mnemonic=='bl' and i.op_str=='#0x891e0' for i in steady)):
        raise ValueError('同包steady_clock不使用CLOCK_MONOTONIC')
    cases=[]
    names=('success','deadline no message','partial read EINTR','random open failure','zero nonce',
           'random EOF','random close failure','clock symbol missing','clock error','invalid timespec',
           'allocation failure','send failure','receive error','clock rollback','bound CP refuses restart')
    for name in names:
        began=time.monotonic()
        a=RuntimeAP(ap_raw,ipc_raw);p=NativeMessagePool(cp)
        aps,cps=load(a.cpu,ap_elf,'ap'),load(p.m.cpu,cp_elf,'cp')
        for syms,needed in ((aps,('af_ap_runtime','af_ap_runtime_gate','af_ap_runtime_clock','af_ap_runtime_nonce')),
                            (cps,('af_cp_runtime_gate','af_cp_hs_start_once'))):
            if any(n not in syms for n in needed):raise ValueError('运行时研究ELF缺少入口')
        before=install(a,p,aps,cps,cp)
        try:
            if boot_cp(p,cps)!=(0,0,0x1fff,4):raise ValueError('CP原任务未自动初始化HELLO')
            if name=='partial read EINTR':a.read_plan=[-1,3,2,3]
            elif name=='random open failure':a.open_error=True
            elif name=='zero nonce':a.nonce=b'\0'*8
            elif name=='random EOF':a.read_plan=[3,0]
            elif name=='random close failure':a.close_error=True
            elif name=='clock symbol missing':a.dlsym_error=True
            elif name=='clock error':a.clock_error=True
            elif name=='invalid timespec':a.bad_nanoseconds=True
            elif name=='allocation failure':a.allocation_error=True
            elif name=='send failure':a.send_result=-7
            elif name=='receive error':a.receive_error=-7
            # 失败后的原无限接收仍交付旧消息，不伪造驱动或线程恢复。
            start_fault=name in names[3:12]
            old=struct.pack('<BBHII',5,0,0x402f,0x11223344,19)
            if start_fault:a.pending.append(old)
            a.step();first=state(a,aps)
            if start_fault:
                if not first['fault'] or first['state']!=3 or a.receives[-1]['wait']!=-1:
                    raise ValueError('启动故障未关闭私有入口并保留原接收')
            elif name=='receive error':
                if first['fault']!=4 or a.system_events.count('usleep 50000 fixture')!=1:
                    raise ValueError('接收错误未关闭握手并请求退避')
            elif name=='deadline no message':
                for _ in range(19):a.step()
                if state(a,aps)['state']!=3 or len(a.receives)!=20 or a.now!=1100:
                    raise ValueError('无消息时原循环未按单调截止时间过期')
            elif name=='clock rollback':
                a.now=99;a.pending.append(old);a.step()
                if state(a,aps)['fault']!=2:raise ValueError('时钟回退没有关闭私有协议')
            else:
                raw=a.last_packet
                if raw is None or struct.unpack_from('<Q',raw,16)[0]!=int.from_bytes(a.nonce,'little'):
                    raise ValueError('启动会话不是从目标随机源取得')
                if name=='bound CP refuses restart':
                    previous=bytearray(raw);struct.pack_into('<Q',previous,16,17)
                    import zlib
                    struct.pack_into('<I',previous,124,zlib.crc32(previous[:124]))
                    p.dispatch(p.allocate(bytes(previous)))
                    pointer=p.sent[-1]['pointer'];p.release(SOURCE,pointer);p.sent.clear()
                    prior=p.m.read(cps['af_cp_handshake'],24);boot_cp(p,cps)
                    if p.m.read(cps['af_cp_handshake'],24)!=prior:raise ValueError('CP启动挂钩意外清除已有会话')
                p.dispatch(p.allocate(raw))
                if name=='bound CP refuses restart':
                    if p.sent:raise ValueError('CP为不同会话自动重建')
                    for _ in range(19):a.step()
                    if state(a,aps)['state']!=3:raise ValueError('CP旧会话拒绝后AP不应READY')
                else:
                    if len(p.sent)!=1:raise ValueError('原CP未回复运行时HELLO')
                    a.pending.append(bytes.fromhex(p.sent[0]['packet']))
                    if a.step()!=0x3554d3c:raise ValueError('回复未进入原AP非空分派')
                    a.receive(p,p.sent[0]['pointer'])
                    if state(a,aps)['state']!=2 or p.allocated(SOURCE):raise ValueError('自动启动至双向HELLO未闭环')
            # 原消息不触发额外随机源/HELLO发送；协议失败也不能吞旧消息。
            before_events=list(a.system_events);before_sent=len([e for e in a.observed if e.get('operation')=='send'])
            a.pending.append(old);a.receive_error=None;a.step();a.check_old_delegation()
            if (a.system_events!=before_events or
                len([e for e in a.observed if e.get('operation')=='send'])!=before_sent):
                raise ValueError('后续原消息意外触发启动重试')
            if p.allocated(QUEUE) or p.allocated(SOURCE):raise ValueError('运行时CP消息未归还')
            cases.append(dict(name=name,seconds=round(time.monotonic()-began,3),first=first,final=state(a,aps),system_events=a.system_events,
                receives=a.receives,monotonic_import_calls=a.clock_calls,
                native_cp_message_pool_restored=p.m.word(p.pool+0x18)==0x1000,
                ap_failed_send_buffer_ownership='UNVERIFIED' if name=='send failure' else 'not exercised'))
        finally:
            for address,raw in before:
                cpu=a.cpu if address in (AP_START,AP_ENTRY) else p.m.cpu
                cpu.mem_write(address,raw);cpu.ctl_remove_cache(address,address+len(raw))
                if bytes(cpu.mem_read(address,len(raw)))!=raw:raise ValueError('运行时分支未精确撤销')
            a.cpu=None;p.m.cpu=None
    return dict(status='OFFLINE_TASK_RUNTIME_VERIFIED',cases=cases,
        native_ap_registration=registration(ap_raw,ipc_raw),
        modules=[dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest()) for raw in (ap_elf,cp_elf)],
        ap_native_task_registration=hex(0x3552d50),ap_native_task=hex(0x3554cf8),
        runtime_imports=dict(open=hex(0x16d9740),read=hex(0x16d9840),close=hex(0x16dba00),
            dlsym=hex(0x16dac90),receive=hex(0x16dae10)),
        same_package_steady_clock=dict(entry=hex(0xb1208),clock_id=1,clock_gettime_import=True),
        checked_ap_imports={k:hex(v) for k,v in expected.items()},
        source_windows=[dict(address=hex(v),bytes=ap_image.read(v,n).hex())
            for v,n in ((0x3552d50,40),(0x3554d24,32),(0x35bb54c,100),(0x35ac690,40))],
        host_system_services_executed=False,physical_driver_timeout_verified=False,
        full_camera_boot_verified=False,bank_frame_binding_verified=False,automatic_rebuild=False,
        installable=False)
