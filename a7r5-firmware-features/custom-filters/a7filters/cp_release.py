"""执行原资源守卫至两类退役/缓冲归还请求；不把请求归还当实际释放。"""
import struct

from .access_evidence import CP_SHA,require_source
from .cp_machine import CpMachine,WORK
from .investigate import CP_BASE,instructions


def guard_release(cp):
    from unicorn import UC_HOOK_CODE
    results=[]
    for failed in (False,True):
        m=CpMachine(cp)
        m.enable_initialized_data(0x1116000,0x1000)
        m.map_ram(0x1934000,0x1000);m.map_ram(0x1e26000,0x1000)
        resource,node,pair,owner,pool,input_handles,output_handles,header_a,header_b=[
            WORK+x for x in (0x1000,0x2000,0x3000,0x5000,0x7000,0x8000,0x9000,0xa000,0xb000)]
        sentinel=resource+0x11c
        m.word(resource,0xe40794);m.word(resource+4,0x39);m.word(resource+8,5)
        m.word(resource+0x24,17);m.word(resource+0x28,1)
        m.word(resource+0x64,owner);m.word(resource+0x6c,1)
        m.word(resource+0x124,1);m.word(resource+0x128,pool)
        m.word(sentinel,node);m.word(sentinel+4,node)
        m.word(node,sentinel);m.word(node+4,sentinel);m.word(node+8,0x123)
        m.put(node+0xc,b'\1\1\0\0')
        m.word(resource+0xc,1);m.word(resource+0x10,input_handles)
        m.word(resource+0x34,100);m.word(resource+0x38,101)
        m.word(owner+8,5);m.word(owner+0x18,output_handles);m.word(owner+0x68,resource)
        m.word(input_handles,7);m.word(output_handles,8)
        for handle,header in ((7,header_a),(8,header_b)):
            m.word(0x1116854+4*handle,header);m.word(header,0x20)
            m.word(0x1e26a3c+4*handle,0x1234)
        m.word(pair,0x123);m.word(pair+4,resource)
        events=[];held=set()
        def boundary(cpu,at,size,data):
            if at in (0x506dec,0x507074,0x50689c):
                if m.register('r0')!=17:raise ValueError('原资源守卫JPEG身份不符')
                result=-7 if failed and at==0x506dec else 0
                events.append(dict(kind='driver fixture',entry=hex(at),result=result))
                m.register('r0',result&0xffffffff)
            elif at in (0x461f48,0x461fa8,0x5c9034):m.register('r0',0)
            elif at in (0x5b8d6c,0x5b8910,0x5c4e08,0x5c5260):
                identity=m.register('r0');expected=0x39 if at in (0x5b8d6c,0x5b8910) else 0x2f
                acquire=at in (0x5b8d6c,0x5c4e08)
                if identity!=expected or (identity in held)==acquire:
                    raise ValueError('原资源守卫锁模型状态不符')
                if acquire:held.add(identity)
                else:held.remove(identity)
                m.register('r0',0)
            else:return
            m.register('pc',m.register('lr'))
        hook=m.cpu.hook_add(UC_HOOK_CODE,boundary)
        m.run(0xae4170,arguments=(pair,))
        if held:raise ValueError('原资源守卫锁未释放')
        state=dict(requests=m.word(resource+0x28),rights=m.word(resource+0x6c),
                   node_use=m.read(node+0xc,1)[0],node_hold=m.read(node+0xd,1)[0],
                   registered_nodes=m.word(resource+0x124),node_pool_count=m.word(pool+8),
                   owner_back_reference=m.word(owner+0x68))
        expected=dict(requests=int(failed),rights=0,node_use=int(failed),node_hold=0,
                      registered_nodes=0,node_pool_count=1,owner_back_reference=0)
        if state!=expected:raise ValueError('原守卫返回后的使用/持有退役不符：'+str(state))
        headers=[m.word(header_a),m.word(header_b)]
        if headers!=[0x80000020,0x80000020] or m.word(0x1934564)!=1:
            raise ValueError('原缓冲归还请求标记不符')
        if any(m.word(0x1e26a3c+4*h)!=0 for h in (7,8)):
            raise ValueError('原缓冲句柄登记未清除')
        m.cpu.hook_del(hook)
        results.append(dict(jpeg_driver_failure_fixture=failed,state_after=state,
            original_guard_returned=True,original_buffer_release_request_executed=True,
            buffer_headers_after=[hex(x) for x in headers],release_request_latch='0x1934564 = 1',
            deferred_buffer_manager_completion_observed=False,events=events,
            whole_frame_release_proven=False))
    return results


def collect(cp):
    require_source(cp,CP_SHA,'CP')
    from capstone import Cs,CS_ARCH_ARM,CS_MODE_THUMB
    md=Cs(CS_ARCH_ARM,CS_MODE_THUMB)
    return dict(schema='a7r5-cp-resource-guard-release/1',cp_sha256=CP_SHA,
        cases=guard_release(cp),windows={hex(a):instructions(md,cp[a-CP_BASE:a-CP_BASE+n],a)
            for a,n in ((0xae416a,26),(0x462734,126),(0xae2bda,132),(0x462c5c,104),
                         (0x462cdc,136),(0xb2b42c,68),(0xb2a5a4,44),(0x4802b6,62))},
        fixture_boundaries=['caller/resource pair and circular list', 'resource/buffer metadata',
            'JPEG driver results','0x39 and 0x2f lock/task-context models','diagnostic calls'],
        camera_io=False,firmware_modified=False,whole_frame_release_proven=False)
