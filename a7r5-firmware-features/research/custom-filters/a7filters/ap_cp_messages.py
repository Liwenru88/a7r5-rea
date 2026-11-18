"""同包原AP发送、OSAL ioctl封装与CP任务分派联验；物理通信由显式隔离后端替代。"""
import hashlib
import struct

from .access_evidence import AP_SHA,CP_SHA,require_source,arm64_cpu,run64,WORK,STACK,STOP
from .cp_machine import CpMachine
from .investigate import AP,PARAMETERS,instructions,CP_BASE

IPC_PATH='/lib/libosal_uipc.so'
IPC_BYTES=43752
IPC_SHA='09ebf5980237fc473077dc844763dcb00cba423f431646e3be7c0ca49ea70ff3'
IPC_BASE=0x70000000
QUEUE=0x90030001
SOURCE=0x80020002


class MessageMachine:
    """运行原库，仅在分配/发送/释放ioctl、errno、诊断/锁和memcpy边界提供内存后端。"""
    def __init__(self,ap_raw,ipc_raw):
        require_source(ap_raw,AP_SHA,'AP')
        require_source(ipc_raw,IPC_SHA,'OSAL')
        from unicorn import UC_HOOK_CODE,arm64_const as reg
        self.reg=reg
        self.cpu=arm64_cpu(AP(ap_raw),[0x3550000,0x3558000,0x3561000,0x35ac000,
            0x4b72000,0x16d9000,0x16da000,0x16dc000,0x3692000,0x3694000,0x17fc000])
        lib=AP(ipc_raw)
        for segment in lib.segments:
            start,end=segment['p_vaddr'],segment['p_vaddr']+segment['p_memsz']
            if not 0<=start<end<0x20000:
                raise ValueError('OSAL库映射超出隔离预算')
            self.cpu.mem_map(IPC_BASE+(start&~4095),((end+4095)&~4095)-(start&~4095))
            self.cpu.mem_write(IPC_BASE+start,segment.data())
        # 只绑定本窗口读取的uconf重定位；其内容是显式的虚拟fd，绝不打开设备。
        self.cpu.mem_write(IPC_BASE+0x19fc8,struct.pack('<Q',IPC_BASE+0x1b560))
        self.cpu.mem_write(IPC_BASE+0x1b560,struct.pack('<i',37))
        self.observed=[]
        self.send_result=0
        self.serial=0
        self.last_packet=None
        self.inject_sender_result=0
        self.capture_sender=False
        self.sender_trace=[]
        self.cpu.hook_add(UC_HOOK_CODE,self._boundary)

    def register(self,name,value=None):
        register=getattr(self.reg,'UC_ARM64_REG_'+name.upper())
        if value is not None:self.cpu.reg_write(register,value)
        return self.cpu.reg_read(register)

    def word(self,address,value=None):
        if value is not None:self.cpu.mem_write(address,struct.pack('<I',value))
        return struct.unpack('<I',self.cpu.mem_read(address,4))[0]

    def quad(self,address):
        return struct.unpack('<Q',self.cpu.mem_read(address,8))[0]

    def _return(self,value=0):
        self.register('x0',value&((1<<64)-1))
        self.register('pc',self.register('lr'))

    def _boundary(self,cpu,at,size,data):
        # AP导入跳转和库内PLT仍进入同包原函数，不直接改消息或确认参数生效。
        routes={0x16dc740:0x67b0,0x16dafc0:0x5e60,0x16d99c0:0x7e20,
                0x16dca60:0x6970,IPC_BASE+0x2670:0x3e98,
                IPC_BASE+0x2310:0x3a10,IPC_BASE+0x24e0:0x3f28}
        if at in routes:
            self.register('pc',IPC_BASE+routes[at]);return
        if at==0x16d9770:
            target,source,count=[self.register('x'+str(i)) for i in range(3)]
            if not 0<=count<=4096:raise ValueError('消息复制超出研究预算')
            cpu.mem_write(target,bytes(cpu.mem_read(source,count)))
            self._return(target);return
        if at in (0x369448c,0x17fc5d4,0x3692384):
            self._return();return
        if at==0x355882c and self.capture_sender:
            destination,body,count=[self.register('x'+str(i)) for i in range(3)]
            if destination!=QUEUE or count!=12:raise ValueError('原AP发送目标/长度不符')
            self.last_packet=bytes(cpu.mem_read(body,count))
            self.sender_trace.append(dict(destination=hex(destination),bytes=count))
            # 此处只观察原发送器；未来/锁包装器不在本窗口执行。
            self._return(self.inject_sender_result);return
        if at==IPC_BASE+0x2530:
            fd,request,args=[self.register('x'+str(i)) for i in range(3)]
            if fd!=37:raise ValueError('OSAL虚拟fd不符')
            operation=request&0xffffffff
            queue,pointer=self.word(args),self.quad(args+8)
            if queue!=QUEUE:raise ValueError('OSAL消息队列身份不符')
            if len(self.observed)>=128:raise ValueError('OSAL研究消息预算耗尽')
            event=dict(request=hex(request),queue=hex(queue))
            if operation==0x8000000a:
                destination=self.quad(pointer)
                count,wait=self.word(pointer+8),self.word(pointer+12)
                if count!=12 or wait!=1 or self.serial>=32:
                    raise ValueError('OSAL分配长度/模式或数量不符')
                payload=WORK+0x6000+self.serial*0x40
                self.serial+=1
                cpu.mem_write(payload-16,b'\0'*32)
                cpu.mem_write(destination,struct.pack('<Q',payload))
                event.update(operation='allocate',payload=hex(payload),bytes=count,wait=wait)
                self._return()
            elif operation==0x80000004:
                source=self.word(pointer-12)
                body=bytes(cpu.mem_read(pointer,12))
                if source!=SOURCE:raise ValueError('原OSAL来源写入不符')
                event.update(operation='send',source=hex(source),packet=body.hex(),
                             result=self.send_result)
                self._return(self.send_result)
            elif operation==0x8000000b:
                event.update(operation='free',payload=hex(pointer))
                self._return()
            else:
                raise ValueError('OSAL触及未声明ioctl')
            self.observed.append(event)
            return
        if at==IPC_BASE+0x26b0:
            raise ValueError('本批未声明errno后端，停止原库错误分支')

    def pack(self,entry,value,*,base=None,failed=False):
        source,output=WORK+0x1000,WORK+0x2000
        raw=bytearray(32)
        struct.pack_into('<I',raw,0,0x11223344)
        if base is None:raw[4]=value&255
        else:struct.pack_into('<2I',raw,4,base,(base if base<10 else base-7))
        self.cpu.mem_write(source,bytes(raw));self.word(output,0xa5a5a5a5)
        self.capture_sender=True
        self.inject_sender_result=-7 if failed else 0
        self.last_packet=None
        for i,arg in enumerate((source,output)):self.register('x'+str(i),arg)
        self.register('sp',STACK+0x8000);self.register('lr',STOP)
        run64(self.cpu,entry)
        self.capture_sender=False
        if self.last_packet is None or self.word(output)!=0:
            raise ValueError('原参数发送器未产生消息或输出状态变化')
        return self.last_packet

    def send(self,body,failed=False):
        if len(body)!=12:raise ValueError('研究消息必须为原12字节格式')
        pointer=WORK+0x3000
        self.cpu.mem_write(pointer,body)
        self.send_result=-7 if failed else 0
        self.register('sp',STACK+0x8000);self.register('fp',STACK+0x8000)
        self.register('x25',pointer);self.register('x26',12);self.register('x23',QUEUE)
        self.register('x22',0)
        before=len(self.observed)
        # 原355882c的实际分配/发送窗口；未来对象和外层锁初始化不在本窗口执行。
        self.cpu.emu_start(0x35589a4,0x35589dc,count=30000)
        if self.register('pc')!=0x35589dc or self.register('sp')!=STACK+0x8000:
            raise ValueError('原消息发送窗口没有有界结束')
        result=self.register('w0')
        events=self.observed[before:]
        if [e['operation'] for e in events]!=['allocate','send']:
            raise ValueError('原消息分配/发送顺序不符')
        if result!=(0xfffffff9 if failed else 0):raise ValueError('原OSAL发送错误未原样返回')
        return dict(source=SOURCE,packet=bytes.fromhex(events[-1]['packet']),
                    accepted=result==0,result=result,ioctl_events=events)


def cp_task(cp):
    m=CpMachine(cp)
    m.enable_initialized_data(0x10ff000,0x2000)
    for address,size in ((0x157a000,0x2000),(0x164e000,0x3000),(0x1653000,0x6000),
                         (0x1915000,0x1000),(0x192b000,0x1000),(0x172e000,0x1000),
                         (0x19c9000,0x1000)):
        m.map_ram(address,size)
    m.model_semaphore()
    m.put(0x157aa10+0xd2f,b'\x03')
    return m


def receive(m,body,source=SOURCE):
    if len(body)!=12:raise ValueError('CP研究接收拒绝非12字节消息')
    packet=WORK+0x1000
    m.word(packet-12,source)
    m.put(packet,body)
    m.word(STACK+0xe000,packet)
    m.register('r4',QUEUE);m.register('fp',0x7a0020)
    m.run(0x496018,0x49606e,returned=False,stop_before=(0x5d9b24,0xb0de92,0x49826c))
    if m.boundary is not None:raise ValueError('CP消息意外到达未执行服务边界')
    if m.word(0x172e1c0)!=source or m.semaphore['held']:
        raise ValueError('原CP来源身份或互斥释放不符')
    return dict(source=hex(source),native_source_getter=True,native_task_dispatch=True,
                native_table_dispatch=True,message_release_executed=False)


def refresh(m):
    m.register('r4',0x164eef0)
    m.run(0x4b8d88,0x4b8dc4,returned=False)
    m.run(0x4baa9e,0x4baaba,returned=False)
    return [struct.unpack('b',m.read(0x1653c68+p[7],1))[0] for p in PARAMETERS]


def consume(m,values):
    m.map_ram(0x157c000,0x1000)
    m.map_ram(0x16af000,0x1000);m.map_ram(0x16ba000,0x1000)
    context=0x192b070
    m.run(0xafd2da,arguments=(0x1653c68,context))
    m.put(WORK+0x2000,struct.pack('<5I',0x60daa5,0,0x4bf3e1,0,0))
    m.run(0x9071cc,0x9071fa,arguments=(context,WORK+0x2000,6),returned=False)
    output,box=WORK+0x5000,WORK+0x6000
    m.run(0x9053f8,0x905446,arguments=(output,0x157c278),returned=False)
    if m.read(output+0x20,6)!=struct.pack('<I2B',19,values[5],values[6]):
        raise ValueError('消息链快照没有进入原锐度/精细度派生字段')
    m.word(STACK+0xe024,context);m.word(box+0x104,WORK+0x500)
    m.register('fp',output);m.register('sl',box)
    m.run(0x240da8,0x240df0,returned=False)
    if m.register('r8')!=0x1653c68:raise ValueError('消息链颜色窗口来源根不符')
    m.run(0x24119a,0x241280,returned=False)
    if (m.read(output+0x2e,1)!=b'\x13' or m.read(output+0x30,1)!=bytes([values[4]&255]) or
            m.read(output+0x33,1)!=bytes([values[0]&255])):
        raise ValueError('消息链参数没有进入原颜色选择/饱和度/对比度字段')
    return dict(native_context_constructor=True,native_sharpness_and_fineness=True,
                native_color_selector_saturation_contrast=True,
                all_eight_fields_in_snapshot=True,deep_frame_metadata='explicit zero fixture',
                hardware_or_full_algorithm_executed=False)


def rejection_windows(cp):
    results=[]
    for kind,message,boundary in ((2,0x4030,0x49826c),(5,0x4167,0xb0de92)):
        m=cp_task(cp)
        before=m.read(0x157aa10,0xdbc)
        pointer=WORK+0x1000
        m.word(pointer-12,SOURCE)
        m.put(pointer,struct.pack('<BBHI4B',kind,0,message,1,7,0,0,0))
        m.word(STACK+0xe000,pointer)
        m.register('r4',QUEUE);m.register('fp',0x7a0020)
        result=m.run(0x496018,0x49606e,returned=False,stop_before=(boundary,))
        if (result['status']!='STOPPED_BEFORE_BOUNDARY' or
                m.read(0x157aa10,0xdbc)!=before):
            raise ValueError('原CP非参数/未知命令隔离窗口不符')
        results.append(dict(kind=kind,message=hex(message),boundary=hex(boundary),
                            parameter_state_unchanged=True,task_return_or_cleanup_executed=False))
    return results


def collect(ap_raw,cp,ipc_raw):
    require_source(ap_raw,AP_SHA,'AP');require_source(cp,CP_SHA,'CP')
    require_source(ipc_raw,IPC_SHA,'OSAL')
    a=MessageMachine(ap_raw,ipc_raw)
    m=cp_task(cp)
    values=(-3,4,-5,2,6,7,4,8)
    packets=[('base',0x35614b4,0x402f,0x33f5b8,0xa40,19)]
    packets += [(p[0],p[4],p[5],p[6],p[7],v) for p,v in zip(PARAMETERS,values)]
    cases=[]
    mixed=None
    for index,(name,entry,message,receiver,field,value) in enumerate(packets):
        body=a.pack(entry,value,base=17 if index==0 else None)
        expected=struct.pack('<BBHI4B',5,0,message,0x11223344,value&255,0,0,0)
        if body!=expected:raise ValueError('原AP消息格式与独立字节契约不符：'+name)
        sent=a.send(body)
        m.put(0x19c999d,b'\0')
        receive(m,sent['packet'],sent['source'])
        actual=m.word(0x157aa10+field) if index==0 else m.read(0x157aa10+field,1)[0]
        if actual!=(value&255):raise ValueError('原AP消息未通过CP任务进入对应字段：'+name)
        cases.append(dict(name=name,message=hex(message),ap_sender=hex(entry),cp_receiver=hex(receiver),
                          packet=body.hex(),state_offset=hex(field),value=value,
                          original_dispatcher_dirty_flag=m.read(0x19c999d,1)[0]))
        if index==1:mixed=refresh(m)
    full=refresh(m)
    if mixed!=[values[0],0,0,0,0,0,3,0] or full!=list(values):
        raise ValueError('逐条消息的中间/完整参数快照不符')
    consumption=consume(m,values)
    previous=m.read(0x157aa10,0xdbc)
    rejected=a.send(a.pack(PARAMETERS[0][4],8,failed=True),failed=True)
    if rejected['accepted']:receive(m,rejected['packet'],rejected['source'])
    if rejected['accepted'] or m.read(0x157aa10,0xdbc)!=previous:
        raise ValueError('隔离后端把失败发送误交给CP')
    return dict(schema='a7r5-native-ap-cp-messages/1',ap_sha256=AP_SHA,cp_sha256=CP_SHA,
                ipc_sha256=IPC_SHA,ipc_bytes=len(ipc_raw),queue=hex(QUEUE),source=hex(SOURCE),cases=cases,
                ioctl_events=a.observed,cp_semaphore_events=m.semaphore_events,
                consumption=consumption,
                rejection_windows=rejection_windows(cp),
                mixed_snapshot_between_messages=mixed,complete_snapshot=full,
                single_parameter_messages_are_atomic_preset=False,
                failed_send=dict(return_code=-7,delivered_to_cp=False,
                    original_ap_sender_output_status=0,output_is_apply_acknowledgement=False),
                original_cp_task_entry='0x495fd8',original_cp_dispatch='0x345b98',
                native_message_body_and_source_verified=True,physical_transport_verified=False,
                full_request_wrapper_executed=False,cp_message_release_executed=False,
                frame_release_proven=False,image_pixels_proven=False,camera_io=False,firmware_modified=False,
                fixture_boundaries=['uconf virtual fd 37','allocation and send ioctl',
                    'diagnostic/lock/memcpy boundaries','native sender future wrapper observed only',
                    'native request allocation/send window','immutable body plus source copied to CP queue fixture',
                    'CP mutex ownership model','stop before native CP message free'])
