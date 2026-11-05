"""原CP回复封装/分配/来源与失败传播；分配/队列仅为匿名隔离后端。"""
import struct

from .access_evidence import CP_SHA,require_source
from .cp_machine import CpMachine,WORK
from .investigate import CP_BASE,instructions


def collect(cp):
    require_source(cp,CP_SHA,'CP')
    from unicorn import UC_HOOK_CODE
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
    results=[]
    # 仅复用原“不支持命令”回复的格式；它不是参数应用确认。
    body=struct.pack('<BBHII',1,0,0x402f,0x11223344,0xf001)
    for failure,destination in ((None,0x80020002),('allocate',0x80020002),
                                ('send',0x80020002),(None,0x80bf0002),(None,0x80dc0002)):
        m=CpMachine(cp)
        packet,payload=WORK+0x1000,WORK+0x3000
        m.put(packet,body)
        events=[]
        def boundary(cpu,at,size,data):
            if at==0xaf05fc:
                events.append(dict(operation='diagnostic fixture',type=m.register('r0'),bytes=m.register('r1')))
                m.register('r0',0)
            elif at==0x53c220:
                queue,output,count,mode=[m.register('r'+str(i)) for i in range(4)]
                if (queue,count,mode)!=(destination,12,1):raise ValueError('原CP回复分配参数不符')
                if failure!='allocate':m.word(output,payload)
                events.append(dict(operation='allocate fixture',destination=hex(queue),bytes=count))
                m.register('r0',0xfffffff9 if failure=='allocate' else 0)
            elif at==0x53bb54:
                if m.register('r0')!=destination or m.register('r1')!=payload:
                    raise ValueError('原CP回复发送对象不符')
                actual=m.read(payload,12)
                if actual!=body or m.word(payload-12)!=0x90030001:
                    raise ValueError('原CP回复复制/来源不符')
                events.append(dict(operation='send fixture',source=hex(m.word(payload-12)),packet=actual.hex()))
                m.register('r0',0xfffffff9 if failure=='send' else 0)
            elif at==0x53c31c:
                if (m.register('r0'),m.register('r1'))!=(destination,payload):
                    raise ValueError('原CP回复释放对象不符')
                events.append(dict(operation='free fixture'));m.register('r0',0)
            elif at==0xb0de92:
                events.append(dict(operation='error diagnostic fixture'));m.register('r0',0)
            else:return
            m.register('pc',m.register('lr'))
        hook=m.cpu.hook_add(UC_HOOK_CODE,boundary)
        answer=m.run(0x898210,arguments=(packet,12,destination))
        operations=[e['operation'] for e in events]
        filtered=destination!=0x80020002
        expected=[] if filtered else ['diagnostic fixture','allocate fixture']
        if not filtered and failure!='allocate':expected.append('send fixture')
        if failure=='send':expected.append('free fixture')
        if failure:expected.append('error diagnostic fixture')
        if operations!=expected or answer['r0']!=(0xffffffff if failure else 0):
            raise ValueError('原CP回复成功/失败/过滤语义不符：'+str((operations,answer)))
        m.cpu.hook_del(hook)
        results.append(dict(destination=hex(destination),failure_fixture=failure,events=events,
            return_r0=answer['r0'],filtered_without_send=filtered,
            physical_reply_observed=False,preset_applied_acknowledgement=False))
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    return dict(schema='a7r5-native-cp-reply/1',cp_sha256=CP_SHA,cases=results,
        windows={hex(a):instructions(md,cp[a-CP_BASE:a-CP_BASE+n],a) for a,n in
                 ((0x898210,58),(0x496180,130),(0xbaaaa0,12),(0x345c38,48))},
        native_memcpy_and_source_write=True,
        fixture_boundaries=['reply body fixture, not preset acknowledgement','allocation/queue/free',
            'diagnostic emission; native reply wrapper/copy/source setter execute'],
        physical_reply_observed=False,version_handshake_verified=False,camera_io=False,firmware_modified=False)
