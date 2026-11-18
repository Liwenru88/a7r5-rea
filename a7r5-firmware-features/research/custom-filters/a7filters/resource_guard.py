"""匿名资源机的五指令保护；地址仅供隔离研究，不用于机身部署。"""
import struct

from .access_evidence import require_source
from .ui_resource_lookup import OBJ_SHA

ENTRY,STUB,FAILED,READY=0x118468,0x300000,0x11846c,0x118484


def _branch(source,target):
    delta=target-source
    if delta&3 or not -(1<<27)<=delta<(1<<27):raise ValueError('资源保护分支越界')
    return struct.pack('<I',0x14000000|((delta//4)&0x3ffffff))


def stub_bytes():
    return struct.pack('<3I',0xb4000060,0xb100041f,0x54000041)+_branch(STUB+12,FAILED)+_branch(STUB+16,READY)


def install(machine):
    require_source(machine.image.raw,OBJ_SHA,'libObj')
    before=machine.image.read(ENTRY,4)
    if before!=struct.pack('<I',0xb50000e0) or bytes(machine.cpu.mem_read(ENTRY,4))!=before:
        raise ValueError('资源mmap检查分支前像不符')
    if any(s['p_vaddr']<STUB+4096 and STUB<s['p_vaddr']+s['p_memsz'] for s in machine.image.segments):
        raise ValueError('资源保护跳板与原库段重叠')
    machine.cpu.mem_map(STUB,4096);machine.cpu.mem_write(STUB,stub_bytes())
    machine.cpu.mem_protect(STUB,4096,5)
    after=_branch(ENTRY,STUB);machine.cpu.mem_write(ENTRY,after)
    return dict(applied=True,entry=hex(ENTRY),stub=hex(STUB),before=before.hex(),after=after.hex(),
                stub_bytes=stub_bytes().hex(),restored=False,runtime_base_verified=False)


def restore(machine):
    record=machine.guard_patch
    if bytes(machine.cpu.mem_read(ENTRY,4)).hex()!=record['after']:
        raise ValueError('资源保护分支被其他修改覆盖，拒绝撤销')
    machine.cpu.mem_write(ENTRY,bytes.fromhex(record['before']))
    machine.cpu.mem_unmap(STUB,4096)
    record['restored']=bytes(machine.cpu.mem_read(ENTRY,4)).hex()==record['before']
    if not record['restored']:raise ValueError('资源保护分支撤销不精确')
