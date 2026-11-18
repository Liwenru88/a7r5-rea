"""双端私有HELLO在原收发入口的匿名分支联验；不开放成像功能。"""
import hashlib
import io
import struct
import zlib

from .access_evidence import AP_SHA,CP_SHA,WORK,STACK,STOP,require_source
from .ap_cp_messages import MessageMachine,IPC_BASE,IPC_SHA,QUEUE,SOURCE
from .cp_message_pool import NativeMessagePool,hello_fixture
from .investigate import AP,CP_BASE

NOW=WORK+0xf200
AP_ENTRY,CP_ENTRY=0x3554d90,0x496044


def load(cpu,raw,kind):
    from elftools.elf.elffile import ELFFile
    from unicorn import UC_PROT_READ,UC_PROT_WRITE,UC_PROT_EXEC
    base=0x9040000 if kind=='ap' else 0x92000000
    if len(raw)>0x20000:raise ValueError('握手ELF超过128KiB预算')
    elf=ELFFile(io.BytesIO(raw))
    if (elf['e_machine']!=('EM_AARCH64' if kind=='ap' else 'EM_ARM') or
        elf['e_type']!='ET_EXEC' or not elf.little_endian or
        any(s['sh_type'] in ('SHT_REL','SHT_RELA') for s in elf.iter_sections())):
        raise ValueError('握手ELF类型/重定位不符')
    table=elf.get_section_by_name('.symtab')
    if table is None:raise ValueError('握手ELF缺少符号表')
    syms={s.name:int(s['st_value']) for s in table.iter_symbols() if s['st_shndx']!='SHN_UNDEF'}
    for name in ('af_'+kind+'_hs_gate','af_'+kind+('_hs_begin' if kind=='ap' else '_hs_configure')):
        if name not in syms or not base<=syms[name]<base+0x10000:
            raise ValueError('握手ELF入口不在固定研究预算内')
    for segment in elf.iter_segments():
        if segment['p_type']!='PT_LOAD':continue
        start,end,flags=segment['p_vaddr'],segment['p_vaddr']+segment['p_memsz'],segment['p_flags']
        if flags not in (5,6) or not base<=start<end<=base+0x20000:
            raise ValueError('握手ELF映射/权限超出研究范围')
        cpu.mem_map(start&~4095,((end+4095)&~4095)-(start&~4095),
                    UC_PROT_READ|(UC_PROT_WRITE if flags&2 else 0)|(UC_PROT_EXEC if flags&1 else 0))
        cpu.mem_write(start,segment.data())
    return syms


class HandshakeAP(MessageMachine):
    def __init__(self,ap_raw,ipc_raw):
        super().__init__(ap_raw,ipc_raw)
        self.image=AP(ap_raw);self.now=100;self.owner=None;self.released=False
        for page in (0x3554000,0x16db000):
            self.cpu.mem_map(page,4096);self.cpu.mem_write(page,self.image.read(page,4096))
        self.clock_calls=0

    def _boundary(self,cpu,at,size,data):
        if at==NOW:
            self.clock_calls+=1;self._return(self.now);return
        if at==IPC_BASE+0x2470:
            self.register('pc',IPC_BASE+0x3f28);return
        if at in (0x16dabe0,0x16dbd50):
            self.register('pc',IPC_BASE+(0x7e08 if at==0x16dabe0 else 0x7e28));return
        if at==IPC_BASE+0x2530:
            fd,request,args=[self.register('x'+str(i)) for i in range(3)]
            if fd!=37:raise ValueError('握手ioctl虚拟fd不符')
            queue,pointer=self.word(args),self.quad(args+8)
            operation=request&0xffffffff
            event=dict(request=hex(request),queue=hex(queue))
            if operation==0x8000000a:
                destination=self.quad(pointer);count,wait=self.word(pointer+8),self.word(pointer+12)
                if queue!=QUEUE or count!=128 or wait!=1 or self.serial>=16:
                    raise ValueError('握手分配长度/目的或预算不符')
                payload=WORK+0x6000+self.serial*0x100;self.serial+=1
                cpu.mem_write(payload-24,b'\0'*152);self.word(payload-8,count)
                cpu.mem_write(destination,struct.pack('<Q',payload))
                event.update(operation='allocate',bytes=count);self._return()
            elif operation==0x80000004:
                if queue!=QUEUE or self.word(pointer-12)!=SOURCE:raise ValueError('握手发送来源不符')
                body=bytes(cpu.mem_read(pointer,128));self.last_packet=body
                event.update(operation='send',packet=body.hex(),result=self.send_result);self._return(self.send_result)
            elif operation==0x8000000b:
                if queue!=SOURCE or pointer!=WORK+0x7000 or self.owner is None or self.released:
                    raise ValueError('握手AP回复重复或外来释放')
                p,original=self.owner;p.release(SOURCE,original);self.released=True
                event.update(operation='free');self._return()
            else:raise ValueError('握手未知ioctl')
            self.observed.append(event);return
        super()._boundary(cpu,at,size,data)

    def call(self,entry,*args):
        for i,value in enumerate(args):self.register('x'+str(i),value)
        self.register('sp',STACK+0x8000);self.register('lr',STOP)
        self.cpu.emu_start(entry,STOP,count=100000)
        if self.register('pc')!=STOP or self.register('sp')!=STACK+0x8000:
            raise ValueError('握手AP入口未有界返回')
        return self.register('w0')

    def send_hello(self,raw):
        self.cpu.mem_write(WORK+0x1000,raw)
        self.register('sp',STACK+0x8000);self.register('fp',STACK+0x8000)
        for register,value in (('x25',WORK+0x1000),('x26',128),('x23',QUEUE),('x22',0)):
            self.register(register,value)
        self.cpu.emu_start(0x35589a4,0x35589dc,count=30000)
        if self.register('pc')!=0x35589dc or self.last_packet!=raw:
            raise ValueError('原AP握手发送窗口未产生完整128字节')

    def receive(self,p,pointer):
        incoming=WORK+0x7000
        length=p.m.word(pointer-8)
        if length!=128:raise ValueError('握手CP回复长度不符')
        self.cpu.mem_write(incoming-24,p.m.read(pointer-24,length+24))
        self.owner=(p,pointer);self.released=False
        frame=STACK+0xc000
        self.cpu.mem_write(frame+0xa0,struct.pack('<Q',incoming))
        self.register('sp',frame);self.register('fp',frame)
        self.cpu.emu_start(0x3554d3c,0x3554ed8,count=100000)
        if self.register('pc')!=0x3554ed8 or self.register('sp')!=frame or not self.released:
            raise ValueError('原AP接收/私有入口/释放未闭环')

    def check_old_delegation(self,raw=None):
        body=WORK+0x7500
        payload=raw if raw is not None else struct.pack('<BBHII',5,0,0x402f,0x11223344,19)
        self.cpu.mem_write(body,payload);self.word(body-8,len(payload))
        for i in range(19):self.register('x'+str(i),0x1000+i)
        self.register('x19',body);self.register('x20',QUEUE)
        self.register('sp',STACK+0x8000);self.register('lr',STOP)
        self.cpu.reg_write(self.reg.UC_ARM64_REG_NZCV,0xa0000000)
        old_reads=self.clock_calls
        self.cpu.emu_start(AP_ENTRY,AP_ENTRY+4,count=30000)
        if (self.register('pc')!=AP_ENTRY+4 or self.register('w0')!=payload[0] or
            self.register('sp')!=STACK+0x8000 or self.register('lr')!=STOP or
            self.cpu.reg_read(self.reg.UC_ARM64_REG_NZCV)!=0xa0000000 or
            self.clock_calls!=old_reads or any(self.register('x'+str(i))!=0x1000+i for i in range(1,19))):
            raise ValueError('AP旧消息委派未保留寄存器/标志或触及时钟')

    def check_private_vectors(self,raw,state_address):
        # 任意指令处的插桩还须保留完整SIMD状态；C ABI本身只保留部分寄存器。
        body=WORK+0x7600;backup=bytes(self.cpu.mem_read(state_address,24))
        self.cpu.mem_write(body,raw);self.word(body-8,128)
        for i in range(32):self.register('q'+str(i),int.from_bytes(bytes([i+1])*16,'little'))
        self.register('x19',body);self.register('x20',QUEUE)
        self.register('sp',STACK+0x8000);self.register('lr',STOP)
        self.cpu.reg_write(self.reg.UC_ARM64_REG_FPCR,0x1000000)
        self.cpu.reg_write(self.reg.UC_ARM64_REG_FPSR,0x800009f)
        try:
            self.cpu.emu_start(AP_ENTRY,0x3554ec8,count=100000)
            if (self.register('pc')!=0x3554ec8 or self.register('sp')!=STACK+0x8000 or
                any(self.register('q'+str(i))!=int.from_bytes(bytes([i+1])*16,'little') for i in range(32)) or
                self.cpu.reg_read(self.reg.UC_ARM64_REG_FPCR)!=0x1000000 or
                self.cpu.reg_read(self.reg.UC_ARM64_REG_FPSR)!=0x800009f):
                raise ValueError('AP私有入口未保留完整SIMD/浮点状态')
        finally:self.cpu.mem_write(state_address,backup)


def collect(ap_raw,cp,ipc_raw,ap_elf,cp_elf):
    require_source(ap_raw,AP_SHA,'AP');require_source(cp,CP_SHA,'CP');require_source(ipc_raw,IPC_SHA,'OSAL')
    cases=[]
    for delayed,corrupt,send_failed in ((False,False,False),(True,False,False),
                                      (False,True,False),(False,False,True)):
        a=HandshakeAP(ap_raw,ipc_raw);p=NativeMessagePool(cp)
        p.send_failure=send_failed
        aps,cps=load(a.cpu,ap_elf,'ap'),load(p.m.cpu,cp_elf,'cp')
        before_ap=a.image.read(AP_ENTRY,4);before_cp=cp[CP_ENTRY-CP_BASE:CP_ENTRY-CP_BASE+8]
        if before_ap!=bytes.fromhex('60024039') or before_cp!=bytes.fromhex('242022f192ee3078'):
            raise ValueError('双端握手入口前像不符')
        delta=aps['af_ap_hs_gate']-AP_ENTRY
        if delta&3 or not -(1<<27)<=delta<(1<<27):raise ValueError('AP握手分支越界')
        patch_ap=struct.pack('<I',0x14000000|((delta//4)&0x3ffffff))
        patch_cp=bytes.fromhex('dff800f0')+struct.pack('<I',cps['af_cp_hs_gate'])
        a.cpu.mem_write(AP_ENTRY,patch_ap);p.m.cpu.mem_write(CP_ENTRY,patch_cp)
        a.cpu.ctl_remove_cache(AP_ENTRY,AP_ENTRY+4);p.m.cpu.ctl_remove_cache(CP_ENTRY,CP_ENTRY+8)
        try:
            a.check_old_delegation(hello_fixture())
            if a.call(aps['af_ap_hs_begin'],43,0x1fff,50,NOW,WORK+0x1000):raise ValueError('AP握手启动失败')
            cold=bytes(a.cpu.mem_read(WORK+0x1000,128))
            p.dispatch(p.allocate(cold))
            if p.sent or p.allocated(QUEUE):raise ValueError('默认关闭CP入口改变原通路或未归还消息')
            if p.m.run(cps['af_cp_hs_configure'],arguments=(0x1fff,))['r0']:raise ValueError('CP握手配置失败')
            raw=bytes(a.cpu.mem_read(WORK+0x1000,128));a.send_hello(raw)
            delivered=bytearray(a.last_packet)
            if corrupt:delivered[55]^=1
            pointer=p.allocate(bytes(delivered));p.dispatch(pointer)
            if p.allocated(QUEUE):raise ValueError('CP私有消息未归还')
            if corrupt or send_failed:
                if corrupt and p.sent:raise ValueError('损坏HELLO不应产生回复')
                if send_failed and (len(p.sent)!=1 or p.sent[0]['accepted']):
                    raise ValueError('失败回复意外被交付')
                a.now=150
                if a.call(aps['af_ap_hs_poll'])!=0xfffffffb:
                    raise ValueError('无回复时不能通过轮询进入过期')
            else:
                if len(p.sent)!=1 or bytes.fromhex(p.sent[0]['packet'])!=raw:
                    raise ValueError('原CP发送器未回传同一会话HELLO')
                if not delayed:a.check_private_vectors(raw,aps['af_ap_handshake'])
                if delayed:a.now=150
                a.receive(p,p.sent[0]['pointer'])
            state=struct.unpack('<QQII',a.cpu.mem_read(aps['af_ap_handshake'],24))
            expected=3 if delayed or corrupt or send_failed else 2
            if state!=(43,150,0x1fff,expected) or p.allocated(SOURCE) or p.m.word(p.pool+0x18)!=0x1000:
                raise ValueError('双端握手状态或原消息池回收不符')
            a.check_old_delegation()
            preset=bytearray(raw)
            struct.pack_into('<H',preset,6,2);struct.pack_into('<Q',preset,24,1)
            struct.pack_into('<I',preset,32,1);preset[36]=17;preset[44]=3
            struct.pack_into('<I',preset,124,zlib.crc32(preset[:124]))
            old_state=p.m.read(0x157aa10,0xdbc);old_replies=len(p.sent)
            p.dispatch(p.allocate(bytes(preset)))
            if (p.m.read(0x157aa10,0xdbc)!=old_state or len(p.sent)!=old_replies or p.allocated(QUEUE)):
                raise ValueError('仅HELLO入口意外开放了PRESET成像写入')
            # 同一已挂钩CP仍委派原参数，并保留原0x24互斥及消息归还。
            old=struct.pack('<BBHII',5,0,0x402f,0x12345678,20)
            p.dispatch(p.allocate(old))
            if p.m.word(0x157aa10+0xa40)!=20 or p.allocated(QUEUE):
                raise ValueError('握手CP分流破坏了原参数分派')
            cases.append(dict(delayed_reply=delayed,corrupted_request=corrupt,failed_reply_send=send_failed,ap_state=expected,
                native_ap_send_and_receive=True,native_cp_reply_and_message_free=True,
                native_cp_old_parameter_delegation=True,pool_restored=True,
                native_ap_old_message_registers_and_flags_preserved=True,
                private_ap_simd_preservation_verified=not delayed and not corrupt and not send_failed,
                default_disabled_delegation_verified=True,preset_application_rejected_without_write=True,
                ap_patch=patch_ap.hex(),cp_patch=patch_cp.hex(),transport_events=a.observed,
                imaging_application_enabled=False))
        finally:
            a.cpu.mem_write(AP_ENTRY,before_ap);p.m.cpu.mem_write(CP_ENTRY,before_cp)
            a.cpu.ctl_remove_cache(AP_ENTRY,AP_ENTRY+4);p.m.cpu.ctl_remove_cache(CP_ENTRY,CP_ENTRY+8)
            if bytes(a.cpu.mem_read(AP_ENTRY,4))!=before_ap or p.m.read(CP_ENTRY,8)!=before_cp:
                raise ValueError('双端握手分支未精确撤销')
            a.cpu=None;p.m.cpu=None
    return dict(schema='a7r5-private-native-hello/1',ap_sha256=AP_SHA,cp_sha256=CP_SHA,
        ap_module_sha256=hashlib.sha256(ap_elf).hexdigest(),cp_module_sha256=hashlib.sha256(cp_elf).hexdigest(),
        cases=cases,anonymous_native_hello_roundtrip_verified=True,branches_restored=True,
        physical_transport_verified=False,on_camera_handshake_verified=False,imaging_application_enabled=False,
        fixture_boundaries=['AP base0; AP/CP standalone research ELF load bases',
            'nonzero session43 and explicit monotonic clock callback100/150',
            'OSAL ioctl and CP queue-send backends; immutable bytes and header copied between CPUs',
            'independent SIMD sentinel probe restores 24-byte client state before actual reply delivery',
            'CP original pool with fixture descriptors and locks; no RTOS or hardware'],
        boot_session_and_clock_provider_bound=False,real_event_loop_poll_connected=False,
        camera_io=False,firmware_modified=False)
