"""执行真实 AP 选择、名称及两处调用窗口；外部接口边界只记录输入。"""
import struct
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn.arm64_const import *

STOP, OBJ, VT, STACK = 0x90000000, 0x90001000, 0x90002000, 0x90100000
BASE_GETTER, TEXT_TABLE = 0x90003000, 0x90004000


def cpu_for(ap):
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    # 不加载整个模拟相机，不借用旧缓存结果。
    for start, size in ((0x3550000,0x1000),(0x3559000,0x1000),
                        (0x3561000,0x1000),(0x1bc7000,0x1000),
                        (0x500f000,0x1000),(0x4b72000,0x1000),
                        (0x3694000,0x1000),(0x3558000,0x1000)):
        cpu.mem_map(start,size);cpu.mem_write(start,ap[start:start+size])
    cpu.mem_map(0x5936000,0x1000)
    cpu.mem_map(STOP,0x10000);cpu.mem_map(STACK,0x10000)
    cpu.mem_write(0x5936018,struct.pack('<Q',TEXT_TABLE))
    cpu.mem_write(TEXT_TABLE,struct.pack('<12I',*(0x12340000+i for i in range(12))))
    cpu.mem_write(OBJ,struct.pack('<Q',VT))
    cpu.mem_write(VT+0x8d0,struct.pack('<Q',BASE_GETTER))
    cpu.reg_write(UC_ARM64_REG_SP,STACK+0x8000)
    cpu.reg_write(UC_ARM64_REG_LR,STOP)
    for i in range(19,30):cpu.reg_write(globals()[f'UC_ARM64_REG_X{i}'],0x01020300+i)
    return cpu


def run(ap,selector,base,route='direct',title_id=None):
    cpu=cpu_for(ap);calls=[];diagnostic=[];before_sp=cpu.reg_read(UC_ARM64_REG_SP)
    saved={i:cpu.reg_read(globals()[f'UC_ARM64_REG_X{i}']) for i in range(19,30)}
    output=OBJ+0x800
    cpu.mem_write(output-8,b'\xa5'*24)
    if title_id is not None:
        # 明示的纯模型 getter 边界，返回本轮设置夹具值；执行MOV/RET本身。
        cpu.mem_write(BASE_GETTER,struct.pack('<II',0x52800000 | ((base&0xffff)<<5),0xd65f03c0))
        cpu.reg_write(UC_ARM64_REG_X0,OBJ);cpu.reg_write(UC_ARM64_REG_X1,title_id)
        start=0x1bc78a4
    elif route=='direct':
        cpu.reg_write(UC_ARM64_REG_X0,selector);cpu.reg_write(UC_ARM64_REG_X1,base)
        cpu.reg_write(UC_ARM64_REG_X2,output);start=0x3550354
    elif route=='bulk':
        # 原厂大参数打包器中真正的结构读取和转换调用窗口。
        cpu.reg_write(UC_ARM64_REG_X19,OBJ);cpu.reg_write(UC_ARM64_REG_X20,OBJ+0x400)
        cpu.mem_write(OBJ+0xf8,struct.pack('<II',selector,base))
        output=OBJ+0x400+0x1c8;cpu.mem_write(output-8,b'\xa5'*24);start=0x35598d8
        saved[19]=OBJ;saved[20]=OBJ+0x400
    elif route=='notify':
        # 原厂局部更新函数，从结构加载 selector/base，生成402f通知。
        cpu.mem_write(OBJ,struct.pack('<3I',7,selector,base))
        cpu.reg_write(UC_ARM64_REG_X0,OBJ);cpu.reg_write(UC_ARM64_REG_X1,OBJ+0x500)
        cpu.reg_write(UC_ARM64_REG_X2,1);start=0x35614b4
    else:raise ValueError('未知AP调用路径')

    def hook(u,at,size,data):
        if at==0x35503d8:
            diagnostic.append('native_invalid_base');u.emu_stop()
        elif at==0x35598e4 and route=='bulk':u.emu_stop()
        elif at==0x369448c:
            n=u.reg_read(UC_ARM64_REG_X2)
            calls.append({'kind':'property_boundary','id':u.reg_read(UC_ARM64_REG_X0),
                          'data':bytes(u.mem_read(u.reg_read(UC_ARM64_REG_X1),n)).hex()})
            u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))
        elif at==0x355882c:
            n=u.reg_read(UC_ARM64_REG_X2)
            calls.append({'kind':'transport_boundary','id':u.reg_read(UC_ARM64_REG_X0),
                          'data':bytes(u.mem_read(u.reg_read(UC_ARM64_REG_X1),n)).hex()})
            u.reg_write(UC_ARM64_REG_PC,u.reg_read(UC_ARM64_REG_LR))
    cpu.hook_add(UC_HOOK_CODE,hook)
    cpu.emu_start(start,STOP,count=600)
    pc=cpu.reg_read(UC_ARM64_REG_PC)
    assert pc in (STOP,0x35598e4,0x35503d8),hex(pc)
    if not diagnostic:
        assert cpu.reg_read(UC_ARM64_REG_SP)==before_sp
        for i,value in saved.items():assert cpu.reg_read(globals()[f'UC_ARM64_REG_X{i}'])==value,(route,i)
    if title_id is not None:wire=cpu.reg_read(UC_ARM64_REG_X0)
    elif route=='notify':
        props=[c for c in calls if c['kind']=='property_boundary']
        wire=bytes.fromhex(props[0]['data'])[0] if props else None
    else:
        redzone=bytes(cpu.mem_read(output-8,24))
        if not diagnostic:assert redzone[:8]==b'\xa5'*8 and redzone[9:]==b'\xa5'*15
        wire=redzone[8]
    return {'wire':wire,'diagnostic':diagnostic,'calls':calls}
