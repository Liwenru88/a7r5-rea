"""执行锁定4.06的有界接入窗口；所有替代边界显式记录，不运行设备接口。"""
import hashlib
import struct

from .investigate import AP, CP_BASE, PARAMETERS, instructions

AP_SHA = 'd15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9'
CP_SHA = '18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97'
BACKUP_SHA = '6a3c5f6067620c00d790cbe520844acdbb721fa5d0e7433b00a227f922ab9d0d'
MANAGER_SHA = 'ef95ca41dadcad9a732b1b1f75e0f9de994093222bd3613c15dbf55ee4bdba9e'
WORK, STACK, STOP = 0x90000000, 0x90100000, 0x9000f000


def require_source(raw, expected, name):
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(name+'不是已锁定4.06组件，拒绝执行指令')


def arm64_cpu(image, pages):
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
    from unicorn.arm64_const import UC_ARM64_REG_SP, UC_ARM64_REG_LR
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    for page in pages:
        available = next(min(0x1000,s['p_vaddr']+s['p_filesz']-page)
                         for s in image.segments if s['p_vaddr'] <= page < s['p_vaddr']+s['p_filesz'])
        cpu.mem_map(page, 0x1000)
        cpu.mem_write(page, image.read(page, available))
    cpu.mem_map(WORK, 0x10000)
    cpu.mem_map(STACK, 0x10000)
    cpu.reg_write(UC_ARM64_REG_SP, STACK+0x8000)
    cpu.reg_write(UC_ARM64_REG_LR, STOP)
    return cpu


def run64(cpu, start, limit=10000):
    from unicorn.arm64_const import UC_ARM64_REG_PC, UC_ARM64_REG_SP
    cpu.emu_start(start, STOP, count=limit)
    if cpu.reg_read(UC_ARM64_REG_PC) != STOP or cpu.reg_read(UC_ARM64_REG_SP) != STACK+0x8000:
        raise ValueError('原指令未有界返回，或栈未恢复')


def menu_enumeration(ap):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_PC, UC_ARM64_REG_LR
    current = [ap.u32(0x3f4a280+i*128+4) for i in range(19)]
    synthetic = list(range(0x100000, 0x100021))
    cases = [(current, 19, {current[-1]}), (synthetic, 0, set()),
             (synthetic, 1, set()), (synthetic, 18, set()),
             (synthetic, 32, set()), (synthetic, 33, set()),
             (synthetic, 33, {synthetic[-1]})]
    result = []
    for rows, capacity, hidden in cases:
        cpu = arm64_cpu(ap, [0x1bcf000])
        obj, vt, desc, table, output = [WORK+x for x in (0x100, 0x400, 0x1000, 0x2000, 0x5008)]
        get, visible = WORK+0xa000, WORK+0xa010
        cpu.mem_write(obj, struct.pack('<Q', vt))
        cpu.mem_write(vt+0x10, struct.pack('<Q', get))
        cpu.mem_write(vt+0x1a8, struct.pack('<Q', visible))
        cpu.mem_write(desc+0x54, struct.pack('<I', len(rows)))
        cpu.mem_write(desc+0x58, struct.pack('<Q', table))
        for i, menu in enumerate(rows):
            cpu.mem_write(table+i*128, struct.pack('<2I', menu, menu))
        before = b'\xa5'*(capacity*4+16)
        cpu.mem_write(output-8, before)

        def boundary(u, at, size, data):
            if at in (get, visible):
                value = desc if at == get else int(u.reg_read(UC_ARM64_REG_X1) not in hidden)
                u.reg_write(UC_ARM64_REG_X0, value)
                u.reg_write(UC_ARM64_REG_PC, u.reg_read(UC_ARM64_REG_LR))

        cpu.hook_add(UC_HOOK_CODE, boundary)
        for reg, value in ((UC_ARM64_REG_X0,obj), (UC_ARM64_REG_X1,0xd9),
                           (UC_ARM64_REG_X2,output), (UC_ARM64_REG_X3,capacity)):
            cpu.reg_write(reg, value)
        run64(cpu, 0x1bcf3fc)
        wanted = [n for n in rows if n not in hidden][:capacity]
        actual = cpu.reg_read(UC_ARM64_REG_X0)
        expected = bytearray(before)
        if wanted:
            struct.pack_into('<'+'I'*len(wanted), expected, 8, *wanted)
        if actual != len(wanted) or bytes(cpu.mem_read(output-8,len(before))) != expected:
            raise ValueError('原厂枚举器输出或缓冲边界不符')
        result.append(dict(rows=len(rows), capacity=capacity, hidden=len(hidden), returned=actual))
    return dict(function='0x1bcf3fc', cases=result, redzones_unchanged=True,
                fixture_boundaries=['descriptor getter +0x10', 'visibility predicate +0x1a8'],
                synthetic_ids_registered=False, actual_renderer_allocation_verified=False)


def selection_dispatch(ap):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_PC, UC_ARM64_REG_LR
    rows = [(0x100000+i, i) for i in range(32)] + [(0x100020, 16)]
    checked = 0
    for menu, expected in rows+[(0x7fffffff,None)]:
        cpu = arm64_cpu(ap, [0x1bd8000,0x1bd9000])
        cpu.mem_map(0x5961000,0x1000)
        obj, vt, holder, desc, table = [WORK+x for x in (0x100,0x400,0x800,0x1000,0x2000)]
        gate, screen, setter = WORK+0xa000, WORK+0xa010, WORK+0xa020
        cpu.mem_write(obj,struct.pack('<Q',vt))
        cpu.mem_write(vt+0x250,struct.pack('<Q',gate))
        cpu.mem_write(vt+0x328,struct.pack('<Q',screen))
        cpu.mem_write(holder,struct.pack('<Q',desc))
        cpu.mem_write(desc+0x54,struct.pack('<I',len(rows)))
        cpu.mem_write(desc+0x58,struct.pack('<Q',table))
        cpu.mem_write(desc+0x80,struct.pack('<Q',setter))
        for i,(key,selector) in enumerate(rows):
            cpu.mem_write(table+i*128+4,struct.pack('<I',key))
            cpu.mem_write(table+i*128+0x34,struct.pack('<I',selector))
        dispatched=[]

        def boundary(u,at,size,data):
            replies={gate:0,screen:0xd9,0x1bd851c:0x1f2,0x1bd906c:1,0x1bd90c4:holder}
            if at in replies:
                u.reg_write(UC_ARM64_REG_X0,replies[at])
            elif at==setter:
                dispatched.append(u.reg_read(UC_ARM64_REG_X0)&0xffffffff)
            else:
                return
            u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))

        cpu.hook_add(UC_HOOK_CODE,boundary)
        cpu.reg_write(UC_ARM64_REG_X0,obj)
        cpu.reg_write(UC_ARM64_REG_X1,menu)
        run64(cpu,0x1bd924c)
        if dispatched != ([] if expected is None else [expected]):
            raise ValueError('原厂选择写入分派身份不符')
        checked+=1
    return dict(function='0x1bd924c', queries=checked, setter_tail_dispatch_verified=True,
                fixture_boundaries=['page gate','screen identity','registry mapping/lookup','setter call'],
                real_model_write_executed=False, synthetic_ids_registered=False)


def backup_messages(raw):
    """执行库的完整变参打包助手，传输只观察消息并注入回执。"""
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_X1, UC_ARM64_REG_X2, UC_ARM64_REG_X3, UC_ARM64_REG_PC, UC_ARM64_REG_LR
    image=AP(raw)
    records=[]
    cases=[('write',0x1ff0,9,0,0),('write_error',0x1ff0,9,-7,0),
           ('allocation_failure',0x1ff0,9,0,1),('transport_failure',0x1ff0,9,0,2),
           ('write_vsize',0x2034,10,0,0),('sync',0x2258,15,0,0),
           ('sync_error',0x2258,15,-7,0)]
    for name,entry,opcode,reply,failure in cases:
        cpu=arm64_cpu(image,[0x1000,0x2000])
        payload,message=WORK+0x1000,WORK+0x2000
        cpu.mem_write(payload,b'candidate')
        cpu.reg_write(UC_ARM64_REG_X0,0x2cf)
        cpu.reg_write(UC_ARM64_REG_X1,0x02cf0d20)
        cpu.reg_write(UC_ARM64_REG_X2,payload)
        cpu.reg_write(UC_ARM64_REG_X3,9)
        observed=[]
        freed=[]

        def boundary(u,at,size,data):
            if at==0x1530:
                u.reg_write(UC_ARM64_REG_PC,0x1a10)
                return
            if at==0x1570:
                if u.reg_read(UC_ARM64_REG_X2)!=0x70:
                    raise ValueError('Backup消息分配长度变化')
                u.mem_write(u.reg_read(UC_ARM64_REG_X1),struct.pack('<Q',message))
                u.reg_write(UC_ARM64_REG_X0,1 if failure==1 else 0)
            elif at==0x15d0:
                packet=bytes(u.mem_read(message,0x70))
                command,status,argc,reserved,target=struct.unpack_from('<5I',packet)
                args=struct.unpack_from('<'+'Q'*argc,packet,0x20)
                if (command,target,reserved)!=(opcode,0x3e014d,0):
                    raise ValueError('Backup消息头变化')
                observed.append((command,args))
                u.mem_write(message+4,struct.pack('<i',reply))
                u.reg_write(UC_ARM64_REG_X0,1 if failure==2 else 0)
            elif at==0x15f0:
                freed.append(u.reg_read(UC_ARM64_REG_X1))
                u.reg_write(UC_ARM64_REG_X0,0)
            else:
                return
            u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))

        cpu.hook_add(UC_HOOK_CODE,boundary)
        run64(cpu,entry)
        actual=cpu.reg_read(UC_ARM64_REG_X0)&0xffffffff
        expected=(-1 if failure else reply)&0xffffffff
        args=(0x2cf,) if entry==0x2258 else (0x2cf,0x02cf0d20,payload)+( (9,) if name=='write_vsize' else () )
        if actual!=expected or observed!=([] if failure==1 else [(opcode,args)]):
            raise ValueError('Backup打包或回执错误传播不符')
        if freed!=([] if failure==1 else [message]):
            raise ValueError('Backup消息释放路径不符')
        records.append(dict(case=name,opcode=opcode,result=actual if actual<0x80000000 else actual-0x100000000,
                            sent=bool(observed),released=bool(freed)))
    return dict(library_sha256=BACKUP_SHA, cases=records, service_target='0x3e014d',
                fixture_boundaries=['message allocation','synchronous transport/reply','message release'],
                server_executed=False, new_record_allocation_verified=False, durable_storage_verified=False)


def backup_sync_wrapper(ap):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0, UC_ARM64_REG_PC, UC_ARM64_REG_LR
    cases=[]
    for sync_result,log_result in ((0,0),(-7,0),(-7,-9)):
        cpu=arm64_cpu(ap,[0x35b8000,0x3694000,0x3693000,0x3691000,0x16da000])
        seen=[]
        def boundary(u,at,size,data):
            if at==0x3694648:
                seen.append(u.reg_read(UC_ARM64_REG_X0)&0xffffffff)
                return
            if at==0x16da600:
                if u.reg_read(UC_ARM64_REG_X0)!=0x2cf:
                    raise ValueError('同步子系统变化')
                result=sync_result
            elif at==0x369352c:
                result=1
            elif at==0x36919fc:
                result=log_result
            else:
                return
            u.reg_write(UC_ARM64_REG_X0,result&0xffffffff)
            u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))
        cpu.hook_add(UC_HOOK_CODE,boundary)
        run64(cpu,0x35b8908)
        if seen!=[sync_result&0xffffffff] or cpu.reg_read(UC_ARM64_REG_X0)&0xffffffff!=log_result&0xffffffff:
            raise ValueError('同步包装器错误覆盖证据变化')
        cases.append(dict(sync_result=sync_result,log_fixture_result=log_result,wrapper_result=log_result))
    return dict(function='0x35b8908',cases=cases,sync_status_preserved=False,
                fixture_boundaries=['Backup_sync_subsystem','log context','log submission'],
                implication='不能将该包装器返回值作为持久化成功依据')


def backup_manager(raw):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_X3,UC_ARM64_REG_PC,UC_ARM64_REG_LR
    image=AP(raw)
    records=[]
    for size,enqueue_result in ((-1,0),(9,0),(9,1)):
        u=arm64_cpu(image,[0,0x1000])
        payload=WORK+0x1000
        u.mem_write(payload,b'candidate')
        for reg,value in ((UC_ARM64_REG_X0,WORK),(UC_ARM64_REG_X1,0x2cf),
                          (UC_ARM64_REG_X2,0x02cf0d20),(UC_ARM64_REG_X3,payload)):
            u.reg_write(reg,value)
        sent=[]
        def boundary(cpu,at,length,data):
            if at==0xeb0:
                if cpu.reg_read(UC_ARM64_REG_X0)!=0x02cf0d20:
                    raise ValueError('BackupManager查询身份变化')
                result=size
            elif at==0xe60:
                sent.append((cpu.reg_read(UC_ARM64_REG_X0),cpu.reg_read(UC_ARM64_REG_X1),cpu.reg_read(UC_ARM64_REG_X2)))
                result=enqueue_result
            else:
                return
            cpu.reg_write(UC_ARM64_REG_X0,result&0xffffffff)
            cpu.reg_write(UC_ARM64_REG_PC,cpu.reg_read(UC_ARM64_REG_LR))
        u.hook_add(UC_HOOK_CODE,boundary)
        run64(u,0x135c)
        expected=-1 if size<0 or enqueue_result else size
        if (u.reg_read(UC_ARM64_REG_X0)&0xffffffff)!=expected&0xffffffff or sent!=([] if size<0 else [(0x02cf0d20,payload,size)]):
            raise ValueError('BackupManager既有记录检查或返回语义变化')
        records.append(dict(queried_size=size,enqueue_fixture_result=enqueue_result,returned=expected,forwarded=bool(sent)))
    return dict(library_sha256=MANAGER_SHA,function='0x135c',cases=records,
                forwarding_function='0x128c',transport='osal_snd_msg',
                fixture_boundaries=['Backup_get_datasize','BkDmn_write enqueue'],
                creates_unknown_records=False,durable_completion_verified=False)


def cp_buffer_switch(cp):
    from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB,UC_HOOK_CODE
    from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_LR,UC_ARM_REG_SP,UC_ARM_REG_PC
    cases=[]
    for previous in (0,1):
        u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
        u.mem_map(0x907000,0x1000)
        u.mem_write(0x907000,cp[0x907000-CP_BASE:0x908000-CP_BASE])
        u.mem_map(WORK,0x10000)
        u.mem_map(0x157c000,0x1000)
        u.mem_map(0x19c9000,0x1000)
        u.mem_write(0x19c98b2,bytes([previous]))
        callback=WORK+0xa000
        u.mem_write(0x157c33c,struct.pack('<2I',callback|1,0))
        u.mem_write(0x157c350,struct.pack('<I',0x12345678))
        u.reg_write(UC_ARM_REG_LR,STOP|1)
        u.reg_write(UC_ARM_REG_SP,WORK+0xe000)
        events=[]
        def boundary(cpu,at,size,data):
            if at==0x9072a6:
                events.append(dict(boundary='parameter builder',context=hex(cpu.reg_read(UC_ARM_REG_R0)),
                                   output=hex(cpu.reg_read(UC_ARM_REG_R1)),index=cpu.mem_read(0x19c98b2,1)[0]))
            elif at==callback:
                events.append(dict(boundary='completion callback',context=hex(cpu.reg_read(UC_ARM_REG_R0)),
                                   argument=hex(cpu.reg_read(UC_ARM_REG_R1)),index=cpu.mem_read(0x19c98b2,1)[0]))
            else:
                return
            cpu.reg_write(UC_ARM_REG_PC,cpu.reg_read(UC_ARM_REG_LR))
        u.hook_add(UC_HOOK_CODE,boundary)
        u.emu_start(0x907250|1,STOP,count=120)
        expected=0x1f52cf8+(previous^1)*0x1270
        if (u.reg_read(UC_ARM_REG_PC),u.reg_read(UC_ARM_REG_SP))!=(STOP,WORK+0xe000):
            raise ValueError('CP缓冲切换窗口未正确返回')
        if events!=[dict(boundary='parameter builder',context='0x157c278',output=hex(expected),index=previous),
                    dict(boundary='completion callback',context='0x157c33c',argument='0x12345678',index=previous^1)]:
            raise ValueError('CP双缓冲选择/切换/回调顺序不符')
        cases.append(dict(previous=previous,events=events))
    return dict(function='0x907250',stride='0x1270',cases=cases,
                fixture_boundaries=['parameter builder','completion callback'],
                callback_is_frame_release_proven=False,capture_reference_lifetime_verified=False)


def cp_forwarding(cp):
    from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB
    from unicorn.arm_const import UC_ARM_REG_R0, UC_ARM_REG_R4, UC_ARM_REG_R5, UC_ARM_REG_LR, UC_ARM_REG_SP, UC_ARM_REG_PC
    def cpu_for(pages):
        u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
        for page in pages:
            u.mem_map(page,0x1000)
            u.mem_write(page,cp[page-CP_BASE:page-CP_BASE+0x1000])
        u.mem_map(WORK,0x10000)
        u.mem_map(0x157a000,0x3000)
        u.mem_map(0x1915000,0x1000)
        u.reg_write(UC_ARM_REG_LR,STOP|1)
        u.reg_write(UC_ARM_REG_SP,WORK+0xe000)
        return u
    state=0x157aa10
    receiver_cases=[]
    for index,(name,pid,get,set_,send,msg,recv,field,backup,fl2,fl3) in enumerate(PARAMETERS):
        u=cpu_for([recv&~0xfff])
        value=(index+1) if name not in ('contrast','highlights','shadows','saturation') else -3
        if name=='fineness':value=5
        before=bytearray(b'\xa5'*0x1000)
        u.mem_write(state,bytes(before))
        u.mem_write(WORK+8,struct.pack('<b',value))
        u.reg_write(UC_ARM_REG_R0,WORK)
        u.emu_start(recv|1,STOP,count=100)
        before[field]=value&255
        if u.reg_read(UC_ARM_REG_PC)!=STOP or u.reg_read(UC_ARM_REG_R0)!=1 or bytes(u.mem_read(state,0x1000))!=before:
            raise ValueError('CP通知接收结果或非目标字节变化')
        receiver_cases.append(dict(parameter=name,field=hex(field),value=value))
    # 只证明这两个窗口以指定来源复制；真实上下文指针的建立另列缺口。
    for fine in range(1,6):
        u=cpu_for([0x905000,0x92e000])
        u.mem_write(state+0xa40,struct.pack('<I',19))
        u.mem_write(state+0xd2e,b'\x07'+bytes([fine]))
        u.reg_write(UC_ARM_REG_R0,state)
        u.reg_write(UC_ARM_REG_R4,WORK+0x1000)
        u.emu_start(0x905430|1,0x905446,count=20)
        if bytes(u.mem_read(WORK+0x1020,6))!=struct.pack('<I',19)+bytes([7,fine]):
            raise ValueError('CP派生锐度参数复制不符')
        u.reg_write(UC_ARM_REG_R5,WORK+0x1000)
        u.reg_write(UC_ARM_REG_R0,WORK+0x2000)
        u.emu_start(0x92e688|1,0x92e6c0,count=40)
        if bytes(u.mem_read(WORK+0x235c,2))!=bytes([7,fine]):
            raise ValueError('CP下游锐度参数复制不符')
    return dict(receivers=receiver_cases, fineness_values_executed=list(range(1,6)),
                forwarding_windows=['0x905430..0x905442','0x92e688..0x92e6bc'],
                fixture_boundaries=['state/context pointers','diagnostic flag disabled'],
                real_context_source_proven=False, hardware_consumer_verified=False,
                rejected_fineness_chain='0x37e98c reads another structure; +0x25 is overwritten at 0x37e870/0x37e8ae')


def collect(ap_raw,cp,backup,manager_raw):
    require_source(ap_raw,AP_SHA,'AP')
    require_source(cp,CP_SHA,'CP')
    require_source(backup,BACKUP_SHA,'libbackup')
    require_source(manager_raw,MANAGER_SHA,'libBackupManager')
    from capstone import Cs,CS_ARCH_ARM64,CS_ARCH_ARM,CS_MODE_LITTLE_ENDIAN,CS_MODE_THUMB
    ap=AP(ap_raw)
    if struct.unpack_from('<3I',cp,0xd0f3bc-CP_BASE)!=(0x02a40000,0x16afd14,0x1200):
        raise ValueError('CP记录表前像变化')
    ad=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    cd=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_LITTLE_ENDIAN)
    manager_image=AP(manager_raw)
    ap_windows={hex(a):instructions(ad,ap.read(a,n),a) for a,n in (
        (0x1b47474,80),(0x1bcf3fc,164),(0x1bd924c,204),(0x35b88d8,76),
        (0x1bd9eb0,84),(0x220fb20,48),(0x2210378,80),(0x3694648,48))}
    cp_windows={hex(a):instructions(cd,cp[a-CP_BASE:a-CP_BASE+n],a) for a,n in (
        (0x907250,86),(0x9073a4,26),(0x9073ca,16),(0x37e5a8,24),
        (0x37e85c,88),(0x37e98c,8),(0x92e372,22),(0x92e6a0,32))}
    return dict(schema='a7r5-access-evidence/1',status='OFFLINE_BOUNDARIES_EXECUTED',
                sources=dict(ap=AP_SHA,cp=CP_SHA,libbackup=BACKUP_SHA,libBackupManager=MANAGER_SHA),
                menu_enumeration=menu_enumeration(ap),selection_dispatch=selection_dispatch(ap),
                backup=backup_messages(backup),backup_sync_wrapper=backup_sync_wrapper(ap),
                backup_manager=backup_manager(manager_raw),
                cp=cp_forwarding(cp),cp_buffer_switch=cp_buffer_switch(cp),
                ap_windows=ap_windows,cp_windows=cp_windows,
                manager_windows={hex(a):instructions(ad,manager_image.read(a,n),a) for a,n in ((0x128c,196),(0x135c,88))},
                record_at_d0f3bc=dict(id='0x02a40000',address='0x016afd14',bytes=0x1200,
                    notification_state_alias_proven=False),
                gates=dict(ui_32_capacity=False,internal_persistence=False,frame_snapshot=False),
                camera_io=False,firmware_modified=False,installable_candidate_allowed=False)
