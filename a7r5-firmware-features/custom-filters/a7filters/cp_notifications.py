"""原EVF通知的实际截断/封装及缓冲标志查询；不把通知当作帧最后引用。"""
import struct

from .access_evidence import CP_SHA,require_source
from .cp_machine import CpMachine,WORK
from .investigate import CP_BASE,instructions


def claim_reuse(cp):
    """执行原句柄占用/归还；旧拥有者归还由夹具重放，不声称观察到真实迟到帧。"""
    from unicorn import UC_HOOK_CODE
    m=CpMachine(cp);m.enable_initialized_data(0x1116000,4096)
    m.map_ram(0x1934000,4096);m.map_ram(0x1e26000,4096)
    held=set();events=[]
    for handle in (7,8):
        header=WORK+0x1000+handle*0x100
        m.word(0x1116854+handle*4,header);m.word(header,0x80000020)
    def boundary(cpu,at,size,data):
        if at==0x5c9034:m.register('r0',0)
        elif at in (0x5c4e08,0x5c5260):
            identity=m.register('r0');acquire=at==0x5c4e08
            if identity!=0x35 or (identity in held)==acquire:raise ValueError('缓冲占用互斥顺序不符')
            if acquire:held.add(identity)
            else:held.remove(identity)
            events.append('acquire' if acquire else 'release');m.register('r0',0)
        elif at==0xb2a68a:events.append('busy diagnostic fixture');m.register('r0',0)
        else:return
        m.register('pc',m.register('lr'))
    hook=m.cpu.hook_add(UC_HOOK_CODE,boundary)
    try:
        first=m.run(0xb2b37e,arguments=(7,))['r0']
        claimed=(m.word(0x1e26a3c+28),m.word(WORK+0x1700))
        busy=m.run(0xb2b37e,arguments=(7,))['r0']
        m.run(0xb2b42c,arguments=(7,))
        second=m.run(0xb2b37e,arguments=(7,))['r0']
        claimed_again=(m.word(0x1e26a3c+28),m.word(WORK+0x1700))
        # 原接口只有同一个句柄；夹具重放旧拥有者释放，观察当前占用是否被清除。
        m.run(0xb2b42c,arguments=(7,))
        stale_result=(m.word(0x1e26a3c+28),m.word(WORK+0x1700))
        released_latch=m.word(0x1934564)
        other=m.run(0xb2b37e,arguments=(8,))['r0']
        latch_after_other_claim=m.word(0x1934564)
        if ((first,second,other)!=(7,7,8) or busy!=0xfffffff6 or
            claimed!=(0x378,0x20) or claimed_again!=claimed or stale_result!=(0,0x80000020) or
            released_latch!=1 or latch_after_other_claim!=0 or m.word(WORK+0x1700)!=0x80000020 or held):
            raise ValueError('原缓冲重复占用/旧归还或全局标志覆盖反例不成立')
        return dict(first_claim=first,busy_result=-10,second_claim=second,
            first_and_second_metadata_identical=True,claimed_metadata=[hex(x) for x in claimed],
            replayed_old_release_fixture=True,metadata_after_old_release=[hex(x) for x in stale_result],
            release_latch=released_latch,release_latch_after_unrelated_claim=latch_after_other_claim,
            released_header_still_marked=True,lock_events=events,
            native_claim_release_executed=True,pixel_allocator_reuse_executed=False,
            actual_late_callback_observed=False,whole_frame_release_proven=False)
    finally:m.cpu.hook_del(hook);m.cpu=None


def collect(cp):
    require_source(cp,CP_SHA,'CP')
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
    cases=[]
    for value in (0x1234,0x11234,0xffffffff):
        m=CpMachine(cp);m.map_ram(0x198b000,4096)
        result=m.run(0x1f62b0,arguments=(0,0,value),stop_before=(0x66075a,))
        if result['status']!='STOPPED_BEFORE_BOUNDARY' or m.register('r2')!=24:
            raise ValueError('原EVF通知没有到达24字节序列化边界')
        raw=m.read(m.register('r1'),24)
        if struct.unpack_from('<4H',raw)!=(0x2001,0xf002,24,1) or raw[8]!=0x39:
            raise ValueError('原EVF通知头或操作不符')
        if struct.unpack_from('<HI',raw,10)!=(12,value&0xffff):
            raise ValueError('原EVF通知没有保留实际16位截断结果')
        cases.append(dict(callback_argument=hex(value),encoded_value=value&0xffff,packet=raw.hex(),
            native_service='0x1f9180',stopped_before_serializer=True,
            unused_payload_words='zero stack fixture; original wrapper does not initialize them'))
    if cases[0]['packet']!=cases[1]['packet']:raise ValueError('EVF截断身份反例未成立')
    m=CpMachine(cp);m.enable_initialized_data(0x1116000,4096)
    m.map_ram(0x1934000,4096);m.map_ram(0x1e26000,4096)
    header=WORK+0x1000;handle=7
    m.word(0x1116854+handle*4,header);m.word(header,0x20)
    m.word(0x1e26a3c+handle*4,0x1234)
    before=m.run(0xb2a58a,arguments=(handle,))['r0']
    m.run(0xb2b42c,arguments=(handle,))
    marked=m.word(header);after=m.run(0xb2a58a,arguments=(handle,))['r0']
    m.run(0xb2b528,arguments=(handle,1))
    restored=m.word(header);again=m.run(0xb2a58a,arguments=(handle,))['r0']
    if (before,marked,after,restored,again)!=(1,0x80000020,0,0x20,1):
        raise ValueError('原缓冲标志设置/清除及查询结果不符')
    if m.word(0x1e26a3c+handle*4):raise ValueError('原归还未清除句柄登记')
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    return dict(schema='a7r5-native-evf-notification/1',cp_sha256=CP_SHA,cases=cases,
        same_low_16_bits_produce_same_notification=True,
        buffer_mark_query=dict(handle=handle,query_before=before,marked_header=hex(marked),
            query_after_release_request=after,restored_header=hex(restored),query_after_mark_clear=again,
            generation_field_observed=False,actual_allocator_reuse_executed=False),
        buffer_claim_reuse=claim_reuse(cp),
        windows={hex(a):instructions(md,cp[a-CP_BASE:a-CP_BASE+n],a) for a,n in
            ((0x6a3070,36),(0x6b4f00,10),(0x1f9180,100),(0xb2a58a,26),(0xb2b528,54),
             (0xb2b37e,142),(0xb2a5a4,44))},
        fixture_boundaries=['callback argument and zeroed stack','EVF diagnostic flag zero',
            'buffer header and handle metadata','stop before notification serialization/send'],
        notification_is_filter_version=False,bank_to_evf_or_jpg_bound=False,
        whole_frame_release_proven=False,camera_io=False,firmware_modified=False)
