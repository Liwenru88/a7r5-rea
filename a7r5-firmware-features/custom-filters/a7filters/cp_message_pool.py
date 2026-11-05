"""执行原CP消息池和接收至归还；消息引用不代表像素或参数银行引用。"""
import struct
import zlib

from .access_evidence import AP_SHA,CP_SHA,require_source
from .ap_cp_messages import cp_task,QUEUE,SOURCE
from .cp_machine import WORK,STACK
from .investigate import CP_BASE,instructions


class NativeMessagePool:
    def __init__(self,cp):
        require_source(cp,CP_SHA,'CP')
        from unicorn import UC_HOOK_CODE
        self.m=cp_task(cp)
        self.m.enable_bss_prefix(0x119c000,4096)
        # 与既有消费窗口的WORK+0x2000～0x6000工作区分离。
        self.pool,self.raw=WORK+0xd000,WORK+0x8000
        self.descriptors={QUEUE:WORK+0xb000,SOURCE:WORK+0xc000}
        for queue,descriptor in self.descriptors.items():
            self.m.word(0x119c7c0+8+4*(queue&0xffff),descriptor)
            self.m.word(descriptor+0x18,self.pool)
        self.m.word(self.pool+8,self.raw)
        for at in (0x10,0x18,0x1c):self.m.word(self.pool+at,0x1000)
        self.m.word(self.raw,0);self.m.word(self.raw+4,0x1000)
        self.locks=set();self.events=[];self.sent=[];self.send_failure=False
        self.m.cpu.hook_add(UC_HOOK_CODE,self._boundary)

    def _boundary(self,cpu,at,size,data):
        m=self.m
        if at in (0xbaa258,0xbaa2b4):
            identity=m.register('r0');acquire=at==0xbaa258
            if identity!=self.pool or (identity in self.locks)==acquire:
                raise ValueError('原消息池锁后端身份或所有权不符')
            if acquire:self.locks.add(identity)
            else:self.locks.remove(identity)
            self.events.append(dict(operation='pool lock fixture' if acquire else 'pool unlock fixture'))
            m.register('r0',0)
        elif at in (0xb0de92,0xaf05fc):
            self.events.append(dict(operation='diagnostic fixture',entry=hex(at)));m.register('r0',0)
        elif at==0x53bb54:
            queue,pointer=m.register('r0'),m.register('r1')
            length=m.word(pointer-8)
            if queue!=SOURCE or not 0<length<=4096 or m.word(pointer-12)!=QUEUE:
                raise ValueError('原CP消息发送身份或长度不符')
            self.sent.append(dict(queue=hex(queue),source=hex(m.word(pointer-12)),pointer=pointer,
                packet=m.read(pointer,length).hex(),accepted=not self.send_failure))
            m.register('r0',0xfffffff9 if self.send_failure else 0)
        else:return
        m.register('pc',m.register('lr'))

    def allocated(self,queue):
        return struct.unpack('<h',self.m.read(self.descriptors[queue]+2,2))[0]

    def allocate(self,body,source=SOURCE):
        if not 0<len(body)<=4096:raise ValueError('研究消息长度超出原分配上限')
        output=WORK+0x100
        self.m.word(output,0)
        result=self.m.run(0x53c220,arguments=(QUEUE,output,len(body),1))
        pointer=self.m.word(output)
        if result['r0'] or not pointer or self.m.word(pointer-8)!=len(body):
            raise ValueError('原CP分配没有返回正确的声明长度')
        self.m.put(pointer,body)
        self.m.run(0xbaaaa0,arguments=(pointer,source))
        return pointer

    def release(self,queue,pointer):
        result=self.m.run(0x53c31c,arguments=(queue,pointer))
        if result['r0'] or self.locks:raise ValueError('原CP消息归还失败或锁未释放')

    def dispatch(self,pointer):
        m=self.m
        m.word(STACK+0xe000,pointer);m.register('r4',QUEUE);m.register('fp',0x7a0020)
        m.run(0x496018,0x496076,returned=False)
        if self.locks or m.semaphore['held']:raise ValueError('原CP接收循环没有释放全部互斥')


def hello_fixture():
    # 与C字节契约独立生成，只验证未安装新入口的旧端行为；不是发给真实设备。
    raw=bytearray(128)
    struct.pack_into('<4sHHIIQQI',raw,0,b'A7P1',1,1,128,0x1fff,43,0,0)
    raw[48:80]=bytes.fromhex(AP_SHA);raw[80:112]=bytes.fromhex(CP_SHA)
    struct.pack_into('<I',raw,112,1);struct.pack_into('<I',raw,124,zlib.crc32(raw[:124]))
    return bytes(raw)


def collect(cp):
    require_source(cp,CP_SHA,'CP')
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
    cases=[]
    bodies=(('base',struct.pack('<BBHII',5,0,0x402f,0x11223344,19),False,False),
            ('retained base',struct.pack('<BBHII',5,0,0x402f,0x11223344,20),True,False),
            ('unsupported',struct.pack('<BBHII',5,0,0x4004,0x11223344,0),False,False),
            ('unsupported send failure',struct.pack('<BBHII',5,0,0x4004,0x11223344,0),False,True),
            ('uninstalled HELLO',hello_fixture(),False,False))
    for name,body,retained,send_failed in bodies:
        p=NativeMessagePool(cp);m=p.m;p.send_failure=send_failed
        pointer=p.allocate(body)
        declared_length=m.word(pointer-8)
        allocated_free=m.word(p.pool+0x18)
        if retained:m.put(pointer-14,struct.pack('<H',2))
        before=m.read(0x157aa10,0xdbc)
        p.dispatch(pointer)
        after=m.read(0x157aa10,0xdbc)
        count=p.allocated(QUEUE)
        if count!=int(retained):raise ValueError('原接收归还后的消息引用不符')
        if name in ('base','retained base'):
            expected=bytearray(before);struct.pack_into('<I',expected,0xa40,19 if name=='base' else 20)
            if after!=bytes(expected):raise ValueError('完整原消息循环的基底写入不符')
        elif after!=before:raise ValueError('非参数消息改变了参数状态')
        if name.startswith('unsupported'):
            expected=struct.pack('<BBHII',1,0,0x4004,0x11223344,0xf001)
            if len(p.sent)!=1 or bytes.fromhex(p.sent[0]['packet'])!=expected:
                raise ValueError('原不支持命令未生成对应错误回复')
        elif p.sent:raise ValueError('旧参数/未知HELLO意外生成新协议回复')
        if retained:
            if m.word(p.pool+0x18)!=allocated_free:raise ValueError('保留消息引用时内存已复用')
            p.release(QUEUE,pointer)
        for sent in p.sent:
            if sent['accepted']:p.release(SOURCE,sent['pointer'])
        if (p.allocated(QUEUE) or p.allocated(SOURCE) or m.word(p.pool+0x18)!=0x1000 or
            m.word(p.pool+8)!=p.raw or m.word(p.raw+4)!=0x1000):
            raise ValueError('原消息全部归还后空闲块未合并恢复')
        cases.append(dict(name=name,body_bytes=len(body),native_declared_length=declared_length,
            extra_reference_fixture=retained,allocated_after_task=count,reply_events=p.sent,
            native_pool_restored=True,original_task_message_release_executed=True,
            parameter_changed=after!=before,events=p.events,
            new_protocol_handshake_verified=False,image_frame_release_proven=False))
        p.m.cpu=None
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    return dict(schema='a7r5-native-message-pool/1',cp_sha256=CP_SHA,cases=cases,
        windows={hex(a):instructions(md,cp[a-CP_BASE:a-CP_BASE+n],a) for a,n in
                 ((0x53c220,202),(0x53c660,414),(0x53c31c,152),(0xbaaaec,136),
                  (0x53d394,84),(0x53d544,206),(0x496018,94))},
        payload_header_bytes=24,source_offset=-12,length_offset=-8,reference_offset=-14,
        original_message_lifetime_executed=True,version_handshake_verified=False,
        whole_frame_release_proven=False,physical_transport_verified=False,
        fixture_boundaries=['registered queue descriptors and 4KiB native pool free block',
            'pool-lock ownership and 0x24 semaphore backends','diagnostics and queue send',
            'delivered request bytes and explicit extra reference','accepted reply owner retires in test'],
        camera_io=False,firmware_modified=False)
