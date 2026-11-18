"""二级别名和全局缓存的新行跳过窗口；不替代完整AP初始化验收。"""
import struct

from .access_evidence import AP_SHA, WORK, STACK, require_source, arm64_cpu
from .investigate import AP
from .ui_evidence import RegistryMachine, STD_SHA, MENU_IDS, candidate_rows


def collect(ap_raw,std_raw):
    require_source(ap_raw,AP_SHA,'AP')
    require_source(std_raw,STD_SHA,'libstdc++')
    from unicorn import UC_HOOK_MEM_WRITE
    from unicorn import arm64_const as regs
    ap,std=AP(ap_raw),AP(std_raw)
    m=RegistryMachine(ap,std);u=m.cpu
    m.map_ap(0x5943000,0x1bd2000,0x1bdf000)
    registry=WORK+0x100;m.initialize(registry)
    raw=ap.read(0x3e47f88,0xaeb8)
    pairs=list(struct.iter_unpack('<2I',raw))
    if pairs!=[(i,i) for i in range(5591)]:
        raise ValueError('当前4.06二级别名表不是已验证的5591项直接映射')
    m.append(0x1c938a8,registry,raw)
    if m.count(registry)!=5591:raise ValueError('原厂二级别名注册数量不符')
    u.mem_write(0x59430d0,struct.pack('<Q',registry))
    old=[];new=[]
    for menu in MENU_IDS:
        actual=m.call(0x1bd8ee8,menu)&0xffffffff
        expected=menu if menu<=0x15d6 else 0x2b36
        if actual!=expected:raise ValueError('二级别名的现有/新增身份语义不符')
        (old if menu<=0x15d6 else new).append(dict(menu=hex(menu),secondary=hex(actual)))
    candidate=candidate_rows(ap)
    u.mem_write(0x91300000,candidate)
    writes=[]
    def write_boundary(cpu,access,address,size,value,data):
        writes.append((address,size))
        if not STACK<=address<address+size<=STACK+0x10000:
            raise ValueError('新增行缓存跳过窗口写入了栈以外的地址')
    hook=u.hook_add(UC_HOOK_MEM_WRITE,write_boundary)
    try:
        for index in range(18,32):
            # 仅提供真实循环当前节点的行指针，不替代别名解析、比较或跳转。
            node=WORK+0x400
            u.mem_write(node+0x20,struct.pack('<I',MENU_IDS[index]))
            u.mem_write(node+0x28,struct.pack('<Q',0x91300000+128*index))
            u.reg_write(regs.UC_ARM64_REG_X22,node)
            u.reg_write(regs.UC_ARM64_REG_X26,0x2b34)
            u.reg_write(regs.UC_ARM64_REG_SP,STACK+0x8000)
            u.emu_start(0x1bdfddc,0x1bdff90,count=1000)
            if (u.reg_read(regs.UC_ARM64_REG_PC)!=0x1bdff90 or
                u.reg_read(regs.UC_ARM64_REG_SP)!=STACK+0x8000 or
                u.reg_read(regs.UC_ARM64_REG_X19)!=0x2b36):
                raise ValueError('新行没有通过真实原指令跳过旧缓存写入')
    finally:u.hook_del(hook)
    if not m.redzones():raise ValueError('二级别名注册节点越界')
    return dict(schema='a7r5-secondary-alias-cache/1',ap_sha256=AP_SHA,
                table='0x3e47f88',table_bytes=len(raw),entries=5591,
                constructor='0x1c938a8',resolver='0x1bd8ee8 -> 0x1bd2084',
                original_queries=old,new_queries=new,unknown_secondary='0x2b36',
                cache_limit='0x2b34',cache_window=['0x1bdfddc','0x1bdff90'],
                new_rows_skipped=14,non_stack_writes=0,stack_writes=len(writes),
                node_redzones_valid=True,full_global_initialization_verified=False,
                other_secondary_consumers_verified=False,
                fixture_boundaries=['bounded allocator','loop current node and cache limit inputs'],
                camera_io=False,firmware_modified=False,installable_candidate_allowed=False)
