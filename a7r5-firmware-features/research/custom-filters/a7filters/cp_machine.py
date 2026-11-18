"""锁定4.06 CP的隔离执行器：未知访问停止，不转发设备或系统调用。"""
import struct
import weakref

from .access_evidence import CP_SHA, require_source
from .investigate import CP_BASE

WORK, STACK, STOP = 0x90000000, 0x90100000, 0x9000f000


class CpMachine:
    def __init__(self, raw):
        require_source(raw, CP_SHA, 'CP')
        from unicorn import Uc, UC_ARCH_ARM, UC_MODE_THUMB, UC_PROT_READ, UC_PROT_WRITE, UC_PROT_EXEC
        from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_WRITE
        from unicorn import arm_const as reg
        self.reg = reg
        self.cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
        self.raw, self.pages, self.ram_bytes, self.ram_ranges = raw, set(), 0, []
        end = (CP_BASE + len(raw) + 4095) & ~4095
        self.cpu.mem_map(CP_BASE, end - CP_BASE, UC_PROT_READ | UC_PROT_EXEC)
        self.cpu.mem_write(CP_BASE, raw)
        self.pages.update(range(CP_BASE, end, 4096))
        self.map_ram(WORK, 0x10000)
        self.map_ram(STACK, 0x10000)
        self.cpu.reg_write(reg.UC_ARM_REG_C1_C0_2, 0xf << 20)
        self.cpu.reg_write(reg.UC_ARM_REG_FPEXC, 1 << 30)
        self.writes, self.stop_before, self.boundary = [], set(), None
        self.semaphore, self.semaphore_events = None, []
        # Unicorn持有回调，不能让绑定方法反向持有执行器及整份CP映像。
        owner = weakref.ref(self)

        def code(*args):
            current = owner()
            if current is not None:
                current._code(*args)

        def write(*args):
            current = owner()
            if current is not None:
                current._write(*args)

        self.cpu.hook_add(UC_HOOK_CODE, code)
        self.cpu.hook_add(UC_HOOK_MEM_WRITE, write)

    def map_ram(self, address, size):
        from unicorn import UC_PROT_READ, UC_PROT_WRITE
        if address & 4095 or size <= 0 or size & 4095 or self.ram_bytes + size > 0x400000:
            raise ValueError('CP研究RAM对齐或预算不符')
        pages = set(range(address, address + size, 4096))
        if address < 0 or address + size > 1 << 32 or pages & self.pages:
            raise ValueError('CP研究RAM与原代码或已有区域重叠')
        if not (0x1200000 <= address < address + size <= 0x2200000 or
                WORK <= address < address + size <= STACK + 0x10000):
            raise ValueError('CP研究RAM不在已声明研究范围')
        self.cpu.mem_map(address, size, UC_PROT_READ | UC_PROT_WRITE)
        self.pages.update(pages)
        self.ram_bytes += size
        self.ram_ranges.append((address, address + size))

    def enable_initialized_data(self, address, size):
        """仅开放锁定镜像声明的数据整页；保留初值并去掉执行权限。"""
        from unicorn import UC_PROT_READ, UC_PROT_WRITE
        if (len(self.raw) < 0x20148 or
                struct.unpack_from('<3I',self.raw,0x2013c)!=(0xf57000,0x117f5c,0x107f000)):
            raise ValueError('CP数据段描述符不是锁定4.06布局')
        if (address & 4095 or size<=0 or size & 4095 or self.ram_bytes+size>0x400000 or
                not 0x107f000<=address<address+size<=0x1196f5c or
                any(address<end and start<address+size for start,end in self.ram_ranges)):
            raise ValueError('CP初始化数据页范围、重叠或预算不符')
        if not set(range(address,address+size,4096)) <= self.pages:
            raise ValueError('CP初始化数据页不在原映像映射中')
        self.cpu.mem_protect(address,size,UC_PROT_READ|UC_PROT_WRITE)
        self.ram_bytes+=size
        self.ram_ranges.append((address,address+size))

    def enable_bss_prefix(self,address,size):
        """只开放已在锁定平面镜像中的BSS前缀页；不执行或伪造完整启动清零。"""
        from unicorn import UC_PROT_READ,UC_PROT_WRITE
        if (len(self.raw)<0x20154 or
            struct.unpack_from('<3I',self.raw,0x20148)!=(0x106f000,0x8a3b40,0x1197000)):
            raise ValueError('CP BSS描述符不是锁定4.06布局')
        end=min(0x1200000,(CP_BASE+len(self.raw))&~4095)
        if (address&4095 or size<=0 or size&4095 or self.ram_bytes+size>0x400000 or
            not 0x1197000<=address<address+size<=end or
            any(address<last and first<address+size for first,last in self.ram_ranges)):
            raise ValueError('CP BSS前缀页范围、重叠或预算不符')
        self.cpu.mem_protect(address,size,UC_PROT_READ|UC_PROT_WRITE)
        self.ram_bytes+=size;self.ram_ranges.append((address,address+size))

    def _code(self, cpu, at, size, data):
        if at in self.stop_before:
            self.boundary = dict(address=hex(at), registers={
                'r'+str(i): hex(cpu.reg_read(getattr(self.reg, 'UC_ARM_REG_R'+str(i))))
                for i in range(4)})
            cpu.emu_stop()
        elif at in (0x5b8f58, 0x5b8d6c, 0x5b8910) and self.semaphore is not None:
            if self.register('r0') != 0x24:
                raise ValueError('CP互斥后端收到未声明的信号量')
            state = self.semaphore
            if at in (0x5b8f58,0x5b8d6c):
                success = not state['held'] and not state['denied']
                if at==0x5b8d6c and not success:
                    raise ValueError('CP阻塞互斥模型未获锁，停止而不伪造返回')
                if success:
                    state['held'] = True
                result = 0 if success else 1
                operation = 'acquire'
            else:
                if not state['held']:
                    raise ValueError('CP互斥后端释放未持有的信号量')
                state['held'] = False
                result, operation = 0, 'release'
            self.semaphore_events.append(dict(operation=operation, result=result, identity='0x24'))
            self.register('r0', result)
            self.register('pc', self.register('lr'))

    def model_semaphore(self):
        """只替代0x24的持有/拒绝状态；不提供任务、硬件或图像完成回执。"""
        self.semaphore = dict(held=False, denied=False)
        return self.semaphore

    def _write(self, cpu, access, address, size, value, data):
        if len(self.writes) >= 100000:
            raise ValueError('CP写入轨迹超出研究预算')
        self.writes.append(dict(pc=hex(cpu.reg_read(self.reg.UC_ARM_REG_PC)),
                                address=hex(address), bytes=size))

    def put(self, address, value):
        if not any(start <= address <= address + len(value) <= end for start, end in self.ram_ranges):
            raise ValueError('CP研究写入不在显式RAM中')
        self.cpu.mem_write(address, value)

    def read(self, address, size):
        return bytes(self.cpu.mem_read(address, size))

    def word(self, address, value=None):
        if value is not None:
            self.put(address, struct.pack('<I', value))
        return struct.unpack('<I', self.read(address, 4))[0]

    def register(self, name, value=None):
        at = getattr(self.reg, 'UC_ARM_REG_'+name.upper())
        if value is not None:
            self.cpu.reg_write(at, value)
        return self.cpu.reg_read(at)

    def run(self, start, end=STOP, *, arguments=(), stop_before=(), limit=30000, returned=True,
            preserve_state=False):
        self.stop_before, self.boundary, self.writes = set(stop_before), None, []
        if not preserve_state:
            self.register('sp', STACK + 0xe000)
            self.register('lr', STOP | 1)
        for i, value in enumerate(arguments):
            if i >= 4:
                raise ValueError('CP窗口参数超出寄存器接口')
            self.register('r'+str(i), value)
        self.cpu.emu_start(start | 1, end, count=limit)
        if self.boundary is not None:
            return dict(status='STOPPED_BEFORE_BOUNDARY', boundary=self.boundary)
        if self.register('pc') != end or (returned and self.register('sp') != STACK + 0xe000):
            raise ValueError('CP原指令未在预算内返回或栈未恢复')
        return dict(status='RETURNED' if returned else 'WINDOW_EXECUTED', r0=self.register('r0'))
