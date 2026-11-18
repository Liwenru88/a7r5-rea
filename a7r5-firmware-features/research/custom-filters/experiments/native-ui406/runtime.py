"""同包原AP/C++运行片段；仅分配、屏幕资格和明确的外部服务为边界。"""
import hashlib
import struct

from unicorn import Uc,UC_ARCH_ARM64,UC_MODE_ARM,UC_HOOK_CODE,UC_HOOK_MEM_UNMAPPED
from unicorn import arm64_const as regs
from a7filters.investigate import AP
from a7filters.access_evidence import AP_SHA
from a7filters.ui_evidence import STD_SHA
from a7filters.ui_resource_lookup import OBJ_SHA


class ShiftedRegistry:
    def __init__(self, ap_raw, std_raw, obj_raw, base):
        if (hashlib.sha256(ap_raw).hexdigest()!=AP_SHA or hashlib.sha256(std_raw).hexdigest()!=STD_SHA or
            hashlib.sha256(obj_raw).hexdigest()!=OBJ_SHA):
            raise ValueError('原AP、C++库或Obj库身份不符')
        self.ap,self.std,self.base = AP(ap_raw),AP(std_raw),base
        self.obj,self.obj_base = AP(obj_raw),0x7600000000
        self.std_base = 0x7300000000
        self.work,self.stack,self.stop = 0x7400000000,0x7400100000,0x7400200000
        self.heap,self.heap_end = 0x7500000010,0x7500100000
        self.u = Uc(UC_ARCH_ARM64,UC_MODE_ARM)
        self.u.mem_map(self.work,0x20000,3);self.u.mem_map(self.stack,0x10000,3)
        # 五个显式屏幕资格回调占用独立RX页；其余工作区保持RW且不可执行。
        self.u.mem_protect(self.work+0xa000,4096,5)
        self.u.mem_map(self.stop,4096,5);self.u.mem_map(self.heap&~4095,0x100000,3)
        self.pages,self.permissions = set(),{}
        self.extra,self.allocations,self.hits = {},[],{}
        self.ap_rel,self.std_rel,self.obj_rel = {},{},{}
        for image,index in ((self.ap,self.ap_rel),(self.std,self.std_rel),(self.obj,self.obj_rel)):
            for at,value in image.relocations.items():index.setdefault(at&~4095,[]).append((at,value))
        def missing(cpu,access,address,size,value,data):
            if self.base<=address<self.base+0x8e84000:
                self.map_ap(address-self.base);return True
            if self.std_base<=address<self.std_base+0x200000:
                self._map_image(self.std,self.std_base,address-self.std_base,self.std_rel);return True
            if self.obj_base<=address<self.obj_base+0x300000:
                self._map_image(self.obj,self.obj_base,address-self.obj_base,self.obj_rel);return True
            return False
        self.u.hook_add(UC_HOOK_MEM_UNMAPPED,missing)
        def boundary(cpu,pc,size,data):
            self.hits[pc] = self.hits.get(pc,0)+1
            offset = pc-self.base
            native = {0x16d9f20:0xa6350,0x16d9c70:0xa6210,0x16da520:0xa6280,
                      0x16dbc80:0xa6288,0x16dc870:0xa65e8}
            if offset in native:
                cpu.reg_write(regs.UC_ARM64_REG_PC,self.std_base+native[offset]);return
            if offset == 0x16dc130:
                size = cpu.reg_read(regs.UC_ARM64_REG_X0)
                if size not in (40,48) or self.heap+size+16>self.heap_end:raise ValueError('原注册器分配超界')
                node = self.heap;self.heap += 96
                self.allocations.append((node,size));cpu.mem_write(node-16,b'\xa5'*(size+32))
                result = node
            elif pc in self.extra:result = self.extra[pc](cpu)
            else:return
            cpu.reg_write(regs.UC_ARM64_REG_X0,result)
            cpu.reg_write(regs.UC_ARM64_REG_PC,cpu.reg_read(regs.UC_ARM64_REG_LR))
        self.u.hook_add(UC_HOOK_CODE,boundary)

    def _map_image(self,image,base,offset,relocations):
        page = offset&~4095;absolute = base+page
        if absolute in self.pages:return
        if len(self.pages)>2048:raise ValueError('原映射超过有界预算')
        s = next((s for s in image.segments if s['p_vaddr']<=page<s['p_vaddr']+s['p_memsz']),None)
        if s is None:raise ValueError('访问不属于原ELF段：'+hex(absolute))
        self.u.mem_map(absolute,4096,3)
        available = min(4096,s['p_vaddr']+s['p_filesz']-page)
        if available>0:self.u.mem_write(absolute,image.read(page,available))
        for at,value in relocations.get(page,[]):self.u.mem_write(base+at,struct.pack('<Q',base+value))
        permission = ((1 if s['p_flags']&4 else 0)|(2 if s['p_flags']&2 else 0)|(4 if s['p_flags']&1 else 0))
        self.u.mem_protect(absolute,4096,permission)
        self.pages.add(absolute);self.permissions[absolute] = permission

    def map_ap(self,offset):self._map_image(self.ap,self.base,offset,self.ap_rel)

    def write_ap_code(self,address,raw):
        if len(raw)!=4 or address&3:raise ValueError('只允许原子宽度的单指令补丁')
        self.map_ap(address-self.base);page = address&~4095
        permission = self.permissions[page]
        if not permission&4:raise ValueError('目标不是原执行页')
        if not any(start<=page<=end and current==permission for start,end,current in self.u.mem_regions()):
            raise ValueError('原页权限已被其他拥有者改变')
        self.u.mem_protect(page,4096,(permission|2)&~4)
        try:self.u.mem_write(address,raw)
        finally:self.u.mem_protect(page,4096,permission)

    def call(self,address,*arguments,stop=None,limit=3000000):
        u = self.u
        for i,v in enumerate(arguments):u.reg_write(getattr(regs,'UC_ARM64_REG_X'+str(i)),v)
        before = {}
        for i in range(19,30):
            value = 0x1234567800000000+i
            u.reg_write(getattr(regs,'UC_ARM64_REG_X'+str(i)),value);before[i] = value
        for i in range(8,16):u.reg_write(getattr(regs,'UC_ARM64_REG_Q'+str(i)),0x1234567800000000+i)
        u.reg_write(regs.UC_ARM64_REG_SP,self.stack+0x8000)
        u.reg_write(regs.UC_ARM64_REG_LR,self.stop)
        stop = self.stop if stop is None else stop
        u.emu_start(address,stop,count=limit)
        if u.reg_read(regs.UC_ARM64_REG_PC)!=stop or u.reg_read(regs.UC_ARM64_REG_SP)!=self.stack+0x8000:
            raise ValueError('原入口未恢复PC/SP：'+hex(u.reg_read(regs.UC_ARM64_REG_PC)))
        if any(u.reg_read(getattr(regs,'UC_ARM64_REG_X'+str(i)))!=value for i,value in before.items()):
            raise ValueError('原入口破坏被调用者保存寄存器')
        if any((u.reg_read(getattr(regs,'UC_ARM64_REG_Q'+str(i)))&((1<<64)-1))!=0x1234567800000000+i
               for i in range(8,16)):raise ValueError('原入口破坏V8..V15的被调用者保存低64位')
        value = u.reg_read(regs.UC_ARM64_REG_X0)
        return value-(1<<32) if value<1<<32 and value&(1<<31) else value

    def initialize_tree(self,address):
        self.u.mem_write(address,bytes(48))
        self.u.mem_write(address+0x10,struct.pack('<QQQQ',0,address+8,address+8,0))

    def redzones(self):
        return all(bytes(self.u.mem_read(at-16,16))==b'\xa5'*16 and
                   bytes(self.u.mem_read(at+size,16))==b'\xa5'*16 for at,size in self.allocations)
