"""生产源码宿主编译与真实 CP 指令执行；不提供硬件模型。"""
import ctypes as C
import hashlib
import json
import io
import os
from pathlib import Path
import subprocess
import struct

from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm_const as A
from unicorn import UC_ARCH_ARM64, UC_HOOK_CODE
from unicorn import arm64_const as A64
from elftools.elf.elffile import ELFFile

HERE = Path(__file__).resolve().parents[1]
SOURCE = HERE / 'upstream/firmware/r5/src'
BASELINE = Path(os.environ.get('A7R5_NATIVE12_BASELINE', HERE / 'build/baseline'))


class Look(C.Structure):
    _fields_ = [('short', C.c_char*24), ('full', C.c_char*64),
                ('cc1', C.c_int16*24), ('matrix', C.c_int16*288),
                ('gamma', C.c_uint32*129), ('grid', C.c_int8*1215), ('pad', C.c_uint8)]


class LookSet(C.Structure):
    _fields_ = [('mask', C.c_uint32), ('look', Look*12)]


class Transfer(C.Structure):
    _fields_ = [('set', C.c_void_p), ('token', C.c_uint32), ('mask', C.c_uint32),
                ('crc', C.c_uint32), ('slot', C.c_uint32), ('seq', C.c_uint32),
                ('phase', C.c_uint32), ('error', C.c_uint32),
                ('deadline', C.c_uint64), ('last', C.c_uint64), ('retry', C.c_uint64)]


Send = C.CFUNCTYPE(C.c_int, C.c_void_p, C.c_void_p, C.c_size_t)


class IO(C.Structure):
    _fields_ = [('context', C.c_void_p), ('send', Send)]


def library(folder, name, sources, extra=()):
    out = folder / (name + '.dylib')
    command = ['clang', '-shared', '-fPIC', '-O1', '-g', '-fno-builtin',
               '-Wall', '-Wextra', '-Werror', '-Wno-misleading-indentation',
               '-I'+str(SOURCE/'import'), '-I'+str(SOURCE/'gamma'),
               '-I'+str(SOURCE/'menu_research'), *map(str, sources), *extra, '-o', str(out)]
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode:
        raise AssertionError(result.stderr)
    return C.CDLL(str(out))


def decoded(lib):
    raw = (HERE/'upstream/filters/FUJ_12_v45/R5NATIVE.BIN').read_bytes()
    value = LookSet()
    assert C.sizeof(Look) == 2444 and C.sizeof(value) == 29332
    assert lib.r5_decode_look_file(raw, len(raw), C.byref(value)) == 0
    return value


class CP:
    """加载当前合并CP；调用公开符号。仅内存、CPU及虚拟栈。"""
    BANK, CONTEXT, PACKET, ACK = 0x3000000, 0x3100000, 0x3101000, 0x3103000
    STOP, STACK = 0x3200000, 0x3210000

    def __init__(self, raw):
        self.cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
        self.cpu.mem_map(0x100000, 0x1b00000)
        self.cpu.mem_write(0x108000, raw)
        self.cpu.mem_map(0x3000000, 0x300000)
        report = json.loads((BASELINE/'work/cp/build.json').read_text())
        self.symbols = {k: int(v, 16) for k, v in report['symbols'].items()}
        # 执行真实复制器，曲线指针现在指向其搬迁目的地。
        self.cpu.reg_write(A.UC_ARM_REG_R4, self.CONTEXT)
        self.cpu.reg_write(A.UC_ARM_REG_SP, self.STACK+0x8000)
        self.cpu.emu_start(0x108524, 0x108528, count=200000)
        assert self.cpu.reg_read(A.UC_ARM_REG_PC) == 0x108528

    def call(self, function, *args, count=50000000):
        for i, n in enumerate(args[:4]):
            self.cpu.reg_write(getattr(A, 'UC_ARM_REG_R'+str(i)), n)
        self.cpu.reg_write(A.UC_ARM_REG_SP, self.STACK+0x8000)
        if len(args) > 4:
            self.write(self.STACK+0x8000, struct.pack('<'+'I'*(len(args)-4), *args[4:]))
        self.cpu.reg_write(A.UC_ARM_REG_LR, self.STOP|1)
        target = self.symbols[function] if isinstance(function, str) else function
        self.cpu.emu_start(target, self.STOP, count=count)
        assert self.cpu.reg_read(A.UC_ARM_REG_PC) == self.STOP, hex(target)
        assert self.cpu.reg_read(A.UC_ARM_REG_SP) == self.STACK+0x8000
        n = self.cpu.reg_read(A.UC_ARM_REG_R0)
        return n if n < 0x80000000 else n - 0x100000000

    def read(self, at, n):
        return bytes(self.cpu.mem_read(at, n))

    def words(self, at, n):
        return struct.unpack('<'+'I'*n, self.read(at, n*4))

    def write(self, at, data):
        self.cpu.mem_write(at, bytes(data))

    def receive(self, packet):
        self.write(self.PACKET, packet)
        assert self.call('r5_transfer_cp_receive', self.CONTEXT, self.BANK,
                         self.PACKET, len(packet), self.ACK) == 1
        return self.read(self.ACK, 44)

    def receiver_services(self, budget=1048576):
        """原资源24接收器；仅OSAL消息服务及堆用替身。"""
        self.cpu.mem_map(0x4000000,0x900000)
        self.heap_used=0;self.heap_allocations=[];self.native_acks=[]
        self.packet_size=0;self.tx_size=0;self.send_failure=False;self.frees=0
        def service(cpu,at,size,_):
            result=0
            if at==0x5ef69c:
                n=cpu.reg_read(A.UC_ARM_REG_R0)
                if self.heap_used+n>budget:result=0
                else:
                    result=0x4000000+len(self.heap_allocations)*0x80000
                    self.heap_allocations.append(n);self.heap_used+=n
            elif at==0xbaad0c:result=self.packet_size
            elif at==0x53c220:
                self.tx_size=cpu.reg_read(A.UC_ARM_REG_R2)
                self.write(cpu.reg_read(A.UC_ARM_REG_R1),struct.pack('<I',0x3105000))
            elif at==0x53bb54:
                self.native_acks.append(self.read(cpu.reg_read(A.UC_ARM_REG_R1),self.tx_size))
                result=int(self.send_failure)
            elif at==0x53c31c:self.frees+=1
            elif at!=0xbaaaa0:return
            cpu.reg_write(A.UC_ARM_REG_R0,result)
            cpu.reg_write(A.UC_ARM_REG_PC,cpu.reg_read(A.UC_ARM_REG_LR))
        self.cpu.hook_add(UC_HOOK_CODE,service)

    def consume(self,packet,source=0x80020002):
        self.write(self.PACKET,packet);self.packet_size=len(packet)
        before=len(self.native_acks)
        result=self.call('r5_cp_stage413_consume',self.PACKET,source)
        if result==0:return None
        return self.native_acks[-1] if len(self.native_acks)>before else None


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class AP:
    STOP, STACK, DATA = 0x60000000, 0x60010000, 0x60100000

    def __init__(self, raw):
        self.cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        elf = ELFFile(io.BytesIO(raw))
        self.cpu.mem_map(0, 0x9200000)
        for segment in elf.iter_segments():
            if segment['p_type']=='PT_LOAD':
                self.cpu.mem_write(segment['p_vaddr'],segment.data())
        self.cpu.mem_map(self.STOP,0x400000)
        self.audit=json.loads((BASELINE/'work/import/module_audit.json').read_text())
        self.symbols=self.audit['symbols']
        self.stubs={}
        self.pending=[]
        self.depth=0
        def dispatch(cpu,at,size,_):
            if at in self.stubs:
                result=self.stubs[at](self)
                if result is not None: cpu.reg_write(A64.UC_ARM64_REG_X0,result)
                cpu.reg_write(A64.UC_ARM64_REG_PC,cpu.reg_read(A64.UC_ARM64_REG_LR))
                if self.pending:cpu.emu_stop()
        self.cpu.hook_add(UC_HOOK_CODE,dispatch)

    def stub(self,name,callback):
        self.stubs[self.symbols[name] if isinstance(name,str) else name]=callback

    def call(self,name,*args,count=3000000):
        self.depth+=1
        stack=self.STACK+self.depth*0x8000
        for i,n in enumerate(args):self.cpu.reg_write(getattr(A64,'UC_ARM64_REG_X'+str(i)),n)
        self.cpu.reg_write(A64.UC_ARM64_REG_SP,stack)
        self.cpu.reg_write(A64.UC_ARM64_REG_LR,self.STOP)
        start=self.symbols[name] if isinstance(name,str) else name
        while True:
            self.cpu.emu_start(start,self.STOP,count=count)
            if not self.pending:break
            saved=self.cpu.context_save()
            pending,self.pending=self.pending,[]
            for function,arguments in pending:self.call(function,*arguments,count=count)
            self.cpu.context_restore(saved)
            start=self.cpu.reg_read(A64.UC_ARM64_REG_PC)
        assert self.cpu.reg_read(A64.UC_ARM64_REG_PC)==self.STOP
        assert self.cpu.reg_read(A64.UC_ARM64_REG_SP)==stack
        self.depth-=1
        return self.arg(0)

    def arg(self,i):return self.cpu.reg_read(getattr(A64,'UC_ARM64_REG_X'+str(i)))
    def read(self,at,n):return bytes(self.cpu.mem_read(at,n))
    def write(self,at,data):self.cpu.mem_write(at,bytes(data))
    def words(self,at,n):return struct.unpack('<'+'I'*n,self.read(at,n*4))
    def string(self,at):
        return self.read(at,256).split(b'\0',1)[0].decode()
