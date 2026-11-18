"""照片/ScalarInfra LiveView阶段及JPEG最后请求退役；区别资源归还和整帧释放。"""
import struct

from .access_evidence import CP_SHA,require_source
from .cp_machine import CpMachine,WORK
from .investigate import CP_BASE,instructions


def source_layout(cp):
    def words(address,count):return struct.unpack_from('<'+'I'*count,cp,address-CP_BASE)
    if words(0xe4078c,7)!=(0,0xe407a8,0xae2d1f,0xae3ffb,0x4662f5,0x4664c9,0x4665ad):
        raise ValueError('原JPEG资源虚表不符')
    label=b'N6Camera7Capture11CapRsrc_JPGE\0'
    if cp[0xca80c0-CP_BASE:0xca80c0-CP_BASE+len(label)]!=label:
        raise ValueError('原照片JPEG资源类型不符')
    types=[]
    for name,at,table,name_at,entry in (
            ('jpeg',0x1183e94,0xe6dfcc,0xcab740,0x581ae8),
            ('jpeg_ack',0x1183e98,0xe6dff0,0xcab790,0xbe8dc8),
            ('jpeg_comp',0x1183e9c,0xe6e014,0xcab7e0,0xbe8de2),
            ('wait',0x1183ea0,0xe6e038,0xcab830,0x581f0c)):
        if words(at,1)!=(table,) or words(table+8,1)!=(entry|1,):
            raise ValueError('原LiveView阶段对象/虚表不符：'+name)
        rtti=words(table-4,1)[0]
        if words(rtti+4,1)!=(name_at,):raise ValueError('原LiveView阶段类型指针不符')
        raw=cp[name_at-CP_BASE:name_at-CP_BASE+128].split(b'\0')[0].decode('ascii')
        if 'ScalarInfraSequenceLiveViewStageAutoexec_'+name not in raw:
            raise ValueError('原LiveView阶段类型名称不符')
        types.append(dict(stage=name,object=hex(at),vtable=hex(table),entry=hex(entry),type_name=raw))
    return types


def last_request(cp):
    from unicorn import UC_HOOK_CODE
    results=[]
    drivers=(0x506dec,0x507074,0x50689c)
    for retain,failed_at in ((1,None),(0,None),(1,0),(1,1),(1,2)):
        m=CpMachine(cp)
        m.map_ram(0x1987000,0x1000);m.map_ram(0x190f000,0x1000)
        resource,node,holder,output,previous,next_,pool=[WORK+x for x in
            (0x1000,0x2000,0x3000,0x4000,0x5000,0x6000,0x7000)]
        m.word(resource,0xe40794)
        m.word(resource+0x24,17);m.word(resource+0x28,1)
        m.word(resource+0x6c,int(bool(retain)))
        m.word(resource+0x124,1);m.word(resource+0x128,pool)
        m.put(resource+0x12c,b'\x03')
        m.word(node,next_);m.word(node+4,previous)
        m.word(previous,node);m.word(next_+4,node)
        m.put(node+0xc,bytes([1,retain,0,0]))
        m.word(holder,node)
        events=[]
        locks=set()
        def boundary(cpu,at,size,data):
            if at in drivers:
                index=drivers.index(at)
                if m.register('r0')!=17:raise ValueError('JPEG最后请求驱动身份不符')
                events.append(dict(operation='driver',entry=hex(at),result=-7 if index==failed_at else 0))
                m.register('r0',0xfffffff9 if index==failed_at else 0)
            elif at in (0x461f48,0x461fa8):
                m.register('r0',0)
            elif at==0x5c9034:
                m.register('r0',0)
            elif at in (0x5c4e08,0x5c5260,0x5b8d6c,0xbeef3c):
                identity=m.register('r0')
                expected=0x2f if at in (0x5c4e08,0x5c5260) else 0x39
                acquire=at in (0x5c4e08,0x5b8d6c)
                if identity!=expected or (identity in locks)==acquire:
                    raise ValueError('JPEG资源锁边界身份或持有状态不符')
                if acquire:locks.add(identity)
                else:locks.remove(identity)
                events.append(dict(operation='lock' if acquire else 'unlock',identity=hex(identity)))
                m.register('r0',0)
            else:return
            m.register('pc',m.register('lr'))
        hook=m.cpu.hook_add(UC_HOOK_CODE,boundary)
        m.run(0xae2afa,arguments=(output,resource,holder))
        success=failed_at is None
        expected_count=0 if success else 1
        expected_identity=0xffffffff if success else 17
        if (m.word(resource+0x28)!=expected_count or m.word(resource+0x24)!=expected_identity or
                m.read(node+0xc,1)!=bytes([0 if success else 1])):
            raise ValueError('JPEG最后请求退役的计数/身份/节点状态不符')
        if m.read(output,1)!=bytes([int(success)]) or m.word(output+4)!=(0 if success else 0xfffffff9):
            raise ValueError('JPEG最后请求的原结果传播不符')
        if len([e for e in events if e['operation']=='driver'])!=(3 if success else failed_at+1):
            raise ValueError('JPEG驱动失败后未停止后续步骤')
        if success and not retain:
            if (m.word(previous)!=next_ or m.word(next_+4)!=previous or m.word(resource+0x124)!=0 or
                    m.word(pool)!=node or m.word(pool+8)!=1):
                raise ValueError('JPEG原节点摘链/回收未闭环')
        if m.word(resource+0x6c)!=int(bool(retain)):
            raise ValueError('JPEG请求退役意外改变独立持有计数')
        if success and not retain:
            # 使用原资源虚表的reset（原指令为bx lr），不能冒充帧析构。
            m.run(0xae3f6a,arguments=(resource,))
            if m.word(0x190f7b4)!=resource or m.word(0x190f7b4+8)!=1:
                raise ValueError('原照片JPEG资源未归还正确池')
        if locks:raise ValueError('JPEG资源夹具锁未释放')
        m.cpu.hook_del(hook)
        results.append(dict(retain=retain,failed_driver=failed_at,events=events,
            outstanding_after=expected_count,resource_identity_after=hex(expected_identity),
            rights_after=int(bool(retain)),node_recycled=success and not retain,
            resource_pool_returned=success and not retain,
            whole_frame_owner_released=False,driver_returns_are_explicit_fixture=True))
    return results


def parameter_bank_publication(cp):
    m=CpMachine(cp)
    for address,size in ((0x164e000,0x6000),(0x165d000,0x1000),
                         (0x198d000,0x1000),(0x19c9000,0x1000)):
        m.map_ram(address,size)
    root,context,counters=0x164eef0,0x165d758,0x165d908
    old_color,old_sharp=0x12340000,0x22340000
    results=[]
    for selected in (0,1):
        for pending in (0,8,64,72):
            m.put(0x198d5ca,bytes([selected]));m.put(0x19c98b2,bytes([selected]))
            m.word(root+0x1ac8,pending)
            m.word(root+0x4b34,old_color);m.word(context+0x44,old_color)
            m.word(context+0x74,old_color+0x19c0);m.word(context+0xa0,old_color+0x2c0)
            m.word(root+0x4b3c,old_sharp);m.word(context+0x4c,old_sharp)
            m.word(context+0x7c,old_sharp+0x3c);m.word(context+0xb8,old_sharp+0x48)
            m.register('fp',root);m.register('r5',context)
            m.run(0x4be0ca,0x4be120,returned=False)
            m.register('fp',root);m.register('r5',context);m.register('r4',counters)
            m.run(0x4be158,0x4be196,arguments=(pending,),returned=False)
            color=old_color if pending&8 else 0x1efb7d0+selected*0x19d8
            sharp=old_sharp if pending&64 else 0x1f52cf8+selected*0x1270
            if (m.word(root+0x4b34)!=color or m.word(context+0x44)!=color or
                    m.word(context+0x74)!=color+0x19c0 or m.word(context+0xa0)!=color+0x2c0 or
                    m.word(root+0x4b3c)!=sharp or m.word(context+0x4c)!=sharp or
                    m.word(context+0x7c)!=sharp+0x3c or m.word(context+0xb8)!=sharp+0x48):
                raise ValueError('原参数银行独立发布/保留窗口不符')
            results.append(dict(selected=selected,pending_mask=pending,
                color_pointer=hex(color),sharpness_pointer=hex(sharp),
                color_preserved=bool(pending&8),sharpness_preserved=bool(pending&64)))
    return dict(cases=results,context=hex(context),root=hex(root),
        native_color_getter='0x7195b0',native_sharpness_getter='0x9075ac',
        consumers_publish_independently=True,same_version_guaranteed=False,
        camera_stream_identity_proven=False,fixture='old pointers and pending states; no concurrent worker')


def collect(cp):
    require_source(cp,CP_SHA,'CP')
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
    decoder=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    types=source_layout(cp)
    return dict(schema='a7r5-cp-frame-stages/1',cp_sha256=CP_SHA,live_view_stages=types,
        jpeg_resource_type='Camera::Capture::CapRsrc_JPG',jpeg_resource_vtable='0xe40794',
        last_request_cases=last_request(cp),
        parameter_bank_publication=parameter_bank_publication(cp),
        windows={hex(a):instructions(decoder,cp[a-CP_BASE:a-CP_BASE+n],a) for a,n in
            ((0x469a48,172),(0x469104,132),(0x466744,30),(0x4665ac,174),
             (0xae2afa,122),(0xae3f6a,68),(0xbe8dc8,26),(0xbe8de2,76),(0x581f0c,80),
             (0x4be0ca,86),(0x4be158,62),(0x7195b0,28),(0x9075ac,28))},
        actual_live_view_input_path_proven=False,camera_evf_identity_proven=False,
        hardware_completion_observed=False,whole_frame_release_proven=False,
        fixture_boundaries=['original resource vtable with fixture object fields',
            'three JPEG driver return values','diagnostic services',
            'mutex/semaphore ownership and task context models'],
        camera_io=False,firmware_modified=False)
