"""继续执行当前4.06的原厂文件通路与CP来源链；无主机/设备I/O后端。"""
import struct

from .access_evidence import AP_SHA,CP_SHA,WORK,STACK,STOP,arm64_cpu,run64,require_source
from .investigate import AP,CP_BASE,PARAMETERS,instructions


def cstring(cpu,address):
    data=bytearray()
    for i in range(256):
        value=cpu.mem_read(address+i,1)[0]
        if value==0:
            return data.decode('ascii')
        data.append(value)
    raise ValueError('边界字符串超长')


def menu_cache_branch(ap):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X19,UC_ARM64_REG_X20,UC_ARM64_REG_X21,UC_ARM64_REG_FP,UC_ARM64_REG_PC,UC_ARM64_REG_LR
    start,end=0x502a980,0x5030590
    registry=[(ap.ptr(a),ap.ptr(a+8)) for a in range(start,end,16)]
    if len(registry)!=1473 or [(k,v) for k,v in registry if k==0x1f2]!=[(0x1f2,0x5858b08)]:
        raise ValueError('原厂描述符注册表前像变化')
    counts=[ap.u32(desc+0x54) for key,desc in registry]
    if tuple(ap.read(0x5858b08+0x28,3))!=(1,1,1):
        raise ValueError('创意外观缓存类别标志变化')
    cases=[]
    for rows in (19,33,82):
        u=arm64_cpu(ap,[0x1bd9000,0x1bcb000])
        obj,vt,desc,metadata,counter,output=[WORK+x for x in (0x100,0x400,0x1000,0x2000,0x3000,0x4008)]
        mapping=WORK+0xa000
        u.mem_write(obj,struct.pack('<Q',vt))
        u.mem_write(vt+0x748,struct.pack('<Q',mapping))
        descriptor=bytearray(ap.read(0x5858b08,0xc0))
        struct.pack_into('<I',descriptor,0x54,rows)
        u.mem_write(desc,bytes(descriptor))
        u.mem_write(metadata+0x70,struct.pack('<I',0x1f2))
        u.mem_write(output-8,b'\xa5'*32)
        for reg,value in ((UC_ARM64_REG_X0,desc),(UC_ARM64_REG_X1,metadata),(UC_ARM64_REG_X19,obj),
                          (UC_ARM64_REG_X20,counter),(UC_ARM64_REG_X21,output),(UC_ARM64_REG_FP,STACK+0x8000)):
            u.reg_write(reg,value)
        def boundary(cpu,at,size,data):
            if at==mapping:
                if cpu.reg_read(UC_ARM64_REG_X1)!=0x1f2:
                    raise ValueError('父项缓存身份读取变化')
                result=0x1f2
            elif at==0x1bcb6d8:
                result=0
            else:
                return
            cpu.reg_write(UC_ARM64_REG_X0,result)
            cpu.reg_write(UC_ARM64_REG_PC,cpu.reg_read(UC_ARM64_REG_LR))
        u.hook_add(UC_HOOK_CODE,boundary)
        u.emu_start(0x1bd9eb0,0x1bd9d64,count=100)
        if u.reg_read(UC_ARM64_REG_PC)!=0x1bd9d64 or bytes(u.mem_read(counter,4))!=struct.pack('<I',1):
            raise ValueError('父项缓存追加数量不符')
        expected=bytearray(b'\xa5'*32)
        struct.pack_into('<2I',expected,8,0,0x1f2)
        if bytes(u.mem_read(output-8,32))!=expected:
            raise ValueError('父项缓存内容或保护区不符')
        cases.append(dict(rows=rows,appended_parent_records=1,redzones_unchanged=True))
    return dict(registry=dict(start=hex(start),end_exclusive=hex(end),entries=len(registry),
                             total_declared_rows=sum(counts),largest_declared_list=max(counts)),
                look_category_flags=[1,1,1],cases=cases,
                invariant='只扩展现有描述符行且保持类别标志/父项元数据时，该缓存窗口不按行数追加',
                fixture_boundaries=['parent identity mapping','eligibility predicate'],
                entire_renderer_capacity_verified=False,new_identity_registration_verified=False)


def lut_mount(ap):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_X3,UC_ARM64_REG_X4,UC_ARM64_REG_PC,UC_ARM64_REG_LR
    cases=[]
    for enabled_a,enabled_b,mount_result in ((0,0,0),(1,0,0),(0,1,0),(1,1,-1)):
        pages=[0x30db000,0x30a2000,0x3691000,0x3692000,0x16da000,
               0x2e7b000,0x4af8000,0x4e23000]
        u=arm64_cpu(ap,pages)
        events=[]
        def boundary(cpu,at,length,data):
            if at==0x2e7b9e4:
                feature=cpu.reg_read(UC_ARM64_REG_X0)
                if feature not in (0x9c,0xa0):
                    raise ValueError('LUT功能门控身份变化')
                result=enabled_a if feature==0x9c else enabled_b
                events.append(dict(kind='feature',id=hex(feature),value=result))
            elif at==0x2e7b9d8:
                if cpu.reg_read(UC_ARM64_REG_X0)!=0x26b:
                    raise ValueError('后续功能身份变化')
                result=0
            elif at==0x16da690:
                args=[cstring(cpu,cpu.reg_read(reg)) for reg in
                      (UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2)]
                flags=cpu.reg_read(UC_ARM64_REG_X3)
                options=cstring(cpu,cpu.reg_read(UC_ARM64_REG_X4))
                if args!=['/dev/nflasha30','/usr/data/lut','vfat'] or flags!=0xc0ed0480 or options!='posix_attr':
                    raise ValueError('原厂LUT挂载参数变化')
                events.append(dict(kind='mount boundary',source=args[0],target=args[1],filesystem=args[2],
                                   flags=hex(flags),options=options,result=mount_result))
                result=mount_result
            elif at==0x3692384:
                result=0
            else:
                return
            cpu.reg_write(UC_ARM64_REG_X0,result&0xffffffff)
            cpu.reg_write(UC_ARM64_REG_PC,cpu.reg_read(UC_ARM64_REG_LR))
        u.hook_add(UC_HOOK_CODE,boundary)
        run64(u,0x30db520)
        mounts=[e for e in events if e['kind']=='mount boundary']
        if len(mounts)!=int(bool(enabled_a or enabled_b)):
            raise ValueError('LUT挂载条件分支不符')
        cases.append(dict(feature_9c=enabled_a,feature_a0=enabled_b,events=events))
    return dict(entry='0x30db520',cases=cases,actual_feature_values_verified=False,
                device_partition_free_or_unused_proven=False,
                fixture_boundaries=['feature predicates','mount syscall PLT','diagnostic log'],host_mount_called=False)


def lut_file_write(ap):
    from unicorn import UC_HOOK_CODE
    from unicorn.arm64_const import UC_ARM64_REG_X0,UC_ARM64_REG_X1,UC_ARM64_REG_X2,UC_ARM64_REG_PC,UC_ARM64_REG_LR
    cases=[]
    for name,opened,written,synced,closed in (
        ('success',7,9,0,0),('short_write',7,4,0,0),('write_error',7,-1,0,0),
        ('fsync_error',7,9,-1,0),('close_error',7,9,0,-1),('open_error',-1,0,0,0)):
        u=arm64_cpu(ap,[0x3691000,0x16d9000,0x16da000,0x16db000])
        path,payload=WORK+0x1000,WORK+0x2000
        u.mem_write(path,b'/isolated/LUT001.cube\0')
        u.mem_write(payload,b'candidate')
        u.reg_write(UC_ARM64_REG_X0,path)
        u.reg_write(UC_ARM64_REG_X1,payload)
        u.reg_write(UC_ARM64_REG_X2,9)
        events=[]
        def boundary(cpu,at,length,data):
            if at==0x16d9740:
                if (cpu.reg_read(UC_ARM64_REG_X0),cpu.reg_read(UC_ARM64_REG_X1),cpu.reg_read(UC_ARM64_REG_X2))!=(path,0x41,0x1e4):
                    raise ValueError('原厂文件打开参数变化')
                events.append('open');result=opened
            elif at==0x16da9b0:
                if (cpu.reg_read(UC_ARM64_REG_X0),cpu.reg_read(UC_ARM64_REG_X1),cpu.reg_read(UC_ARM64_REG_X2))!=(7,payload,9):
                    raise ValueError('原厂文件写入参数变化')
                events.append('write');result=written
            elif at in (0x16dbbc0,0x16dba00):
                if cpu.reg_read(UC_ARM64_REG_X0)!=7:
                    raise ValueError('原厂同步/关闭描述符变化')
                events.append('fsync' if at==0x16dbbc0 else 'close')
                result=synced if at==0x16dbbc0 else closed
            else:
                return
            cpu.reg_write(UC_ARM64_REG_X0,result&0xffffffff)
            cpu.reg_write(UC_ARM64_REG_PC,cpu.reg_read(UC_ARM64_REG_LR))
        u.hook_add(UC_HOOK_CODE,boundary)
        run64(u,0x3691384)
        expected=0 if opened<0 else written
        actual=u.reg_read(UC_ARM64_REG_X0)&0xffffffff
        if actual!=expected&0xffffffff or events!=(['open'] if opened<0 else ['open','write','fsync','close']):
            raise ValueError('原厂文件写入结果传播变化')
        cases.append(dict(case=name,write_result=written,fsync_result=synced,close_result=closed,returned=expected,events=events))
    return dict(function='0x3691384',cases=cases,open_flags='0x41',open_mode='0x1e4',
                sync_and_close_errors_preserved=False,short_write_retry=False,
                fixture_boundaries=['open','write','fsync','close'],host_files_opened=False)


def cp_source_chain(cp):
    from unicorn import Uc,UC_ARCH_ARM,UC_MODE_THUMB
    from unicorn.arm_const import UC_ARM_REG_R0,UC_ARM_REG_R1,UC_ARM_REG_R4,UC_ARM_REG_R5,UC_ARM_REG_LR,UC_ARM_REG_SP,UC_ARM_REG_PC
    cases=[]
    state,master,snapshot,context,installed=0x157aa10,0x164eef0,0x1653c68,0x192b070,0x157c278
    for fine in range(1,6):
        u=Uc(UC_ARCH_ARM,UC_MODE_THUMB)
        for page in (0x33f000,0xafc000,0x898000,0x5f5000,0x4ba000,0xafd000,0x907000,0x905000,0x92e000):
            u.mem_map(page,0x1000)
            u.mem_write(page,cp[page-CP_BASE:page-CP_BASE+0x1000])
        for address,size in ((WORK,0x10000),(0x157a000,0x3000),(0x164e000,0x2000),
                             (0x1653000,0x6000),(0x192b000,0x1000),(0x1915000,0x1000)):
            u.mem_map(address,size)
        values=(-3,4,-5,2,6,7,fine,8)
        for row,value in zip(PARAMETERS,values):
            u.mem_write(WORK+8,struct.pack('<b',value))
            u.reg_write(UC_ARM_REG_R0,WORK)
            u.reg_write(UC_ARM_REG_LR,STOP|1)
            u.reg_write(UC_ARM_REG_SP,WORK+0xe000)
            u.emu_start(row[6]|1,STOP,count=100)
            if u.reg_read(UC_ARM_REG_PC)!=STOP:
                raise ValueError('CP接收器未正常退出')
        u.mem_write(state+0xa40,struct.pack('<I',19))
        expected=bytes(u.mem_read(state,0xdbc))
        # 执行真实getter、Thumb调用窗口和ARM memcpy；不替代复制函数。
        u.mem_write(master-8,b'\xa5'*8)
        u.mem_write(master+0xdbc,b'\xa5'*16)
        u.reg_write(UC_ARM_REG_SP,WORK+0xe000)
        u.emu_start(0xafcb6c|1,0xafcb84,count=6000)
        if bytes(u.mem_read(master,0xdbc))!=expected or bytes(u.mem_read(master-8,8))!=b'\xa5'*8 or bytes(u.mem_read(master+0xdbc,16))!=b'\xa5'*16:
            raise ValueError('通知状态到master复制或边界不符')
        u.mem_write(snapshot-8,b'\x5a'*8)
        u.mem_write(snapshot+0xe70,b'\x5a'*16)
        u.emu_start(0x4baa9e|1,0x4baaba,count=6000)
        if bytes(u.mem_read(snapshot,0xe70))!=bytes(u.mem_read(master,0xe70)) or bytes(u.mem_read(snapshot-8,8))!=b'\x5a'*8 or bytes(u.mem_read(snapshot+0xe70,16))!=b'\x5a'*16:
            raise ValueError('master到参数快照复制或边界不符')
        u.reg_write(UC_ARM_REG_R0,snapshot)
        u.reg_write(UC_ARM_REG_R1,context)
        u.reg_write(UC_ARM_REG_LR,STOP|1)
        u.emu_start(0xafd2da|1,STOP,count=500)
        if u.reg_read(UC_ARM_REG_PC)!=STOP or struct.unpack('<I',u.mem_read(context,4))[0]!=snapshot:
            raise ValueError('真实上下文构造器来源不符')
        u.reg_write(UC_ARM_REG_R0,context)
        u.reg_write(UC_ARM_REG_R1,WORK+0x7000)
        u.emu_start(0x9071cc|1,0x9071fa,count=1000)
        if bytes(u.mem_read(installed,0xc4))!=bytes(u.mem_read(context,0xc4)):
            raise ValueError('CP构造器上下文安装不符')
        output=WORK+0x5000
        u.reg_write(UC_ARM_REG_R0,output)
        u.reg_write(UC_ARM_REG_R1,installed)
        u.emu_start(0x9053f8|1,0x905446,count=120)
        if bytes(u.mem_read(output+0x20,6))!=struct.pack('<I',19)+bytes([7,fine]):
            raise ValueError('原生来源链到派生参数不符')
        u.reg_write(UC_ARM_REG_R5,output)
        u.reg_write(UC_ARM_REG_R0,WORK+0x6000)
        u.emu_start(0x92e688|1,0x92e6c0,count=40)
        if bytes(u.mem_read(WORK+0x635c,2))!=bytes([7,fine]):
            raise ValueError('完整来源链到下游锐度字段不符')
        transferred=[u.mem_read(snapshot+row[7],1)[0] for row in PARAMETERS]
        if transferred!=[v&255 for v in values]:
            raise ValueError('八项参数未完整通过快照')
        # 单独更新接收状态不应反向改变已复制的master/快照。
        u.mem_write(WORK+8,b'\x01')
        u.reg_write(UC_ARM_REG_R0,WORK)
        u.reg_write(UC_ARM_REG_LR,STOP|1)
        u.emu_start(0x33f7c0|1,STOP,count=100)
        if bytes(u.mem_read(master,0xdbc))!=expected or bytes(u.mem_read(snapshot,0xdbc))!=expected:
            raise ValueError('接收状态更新意外改变既有快照')
        cases.append(dict(fineness=fine,all_eight_fields_preserved=True,copy_redzones_unchanged=True,
                          later_receiver_update_keeps_snapshot=True))
    return dict(cases=cases,notification_state=hex(state),master=hex(master),parameter_snapshot=hex(snapshot),
                context=hex(context),installed_context=hex(installed),native_memcpy='ARM 0x5f51bc',
                instruction_windows=['0xafcb6c..0xafcb80','0x4baa9e..0x4baab6','0xafd2da + 0xafd5b8',
                                     '0x9071cc..0x9071f6','0x9053f8..0x905442','0x92e688..0x92e6bc'],
                source_pointer_construction_executed=True,outer_scheduling_conditions_verified=False,
                later_live_update_paths_verified=False,frame_reference_release_verified=False,
                fixture_boundaries=['window entry registers','diagnostic flag disabled','sequential scheduler'])


def collect(ap_raw,cp,lut_directory_present):
    require_source(ap_raw,AP_SHA,'AP')
    require_source(cp,CP_SHA,'CP')
    from capstone import Cs,CS_ARCH_ARM64,CS_ARCH_ARM,CS_MODE_LITTLE_ENDIAN,CS_MODE_THUMB
    ap=AP(ap_raw)
    ad=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    cd=Cs(CS_ARCH_ARM,CS_MODE_THUMB|CS_MODE_LITTLE_ENDIAN)
    windows={hex(a):instructions(ad,ap.read(a,n),a) for a,n in (
        (0x16f6550,96),(0x1bd9eb0,84),(0x1bd9d9c,112),
        (0x30db520,80),(0x30a284c,80),(0x3691334,48),(0x3691384,112),
        (0x30a16b0,72),(0x30a1a80,80),(0x30a1b40,32))}
    cp_windows={hex(a):instructions(cd,cp[a-CP_BASE:a-CP_BASE+n],a) for a,n in (
        (0x89853e,10),(0xafcb6c,24),(0x4baa9e,28),(0xafd2da,32),(0xafd5b8,40),(0x499258,24))}
    from .cp_updates import collect as collect_updates
    from .cp_realtime import collect as collect_realtime
    return dict(schema='a7r5-native-paths/1',status='NATIVE_PATH_WINDOWS_EXECUTED',
                ap_sha256=AP_SHA,cp_sha256=CP_SHA,menu_cache_branch=menu_cache_branch(ap),
                lut_mount=lut_mount(ap),lut_file_write=lut_file_write(ap),
                cp_source_chain=cp_source_chain(cp),ap_windows=windows,cp_windows=cp_windows,
                cp_update_candidates=collect_updates(cp),
                cp_realtime=collect_realtime(cp),
                package_lut_mountpoint_present=bool(lut_directory_present),
                stock_lut_parser_stack_reservation_bytes=0x5c3250+0x60,
                stock_lut_dimensions=[17,33],declared_user_lut_identities=16,
                native_photo_lut_route_verified=False,storage_region_selected=False,
                executed_scenarios=18,
                camera_io=False,host_mount_called=False,firmware_modified=False,
                gates=dict(ui_32_capacity=False,internal_persistence=False,frame_snapshot=False))
