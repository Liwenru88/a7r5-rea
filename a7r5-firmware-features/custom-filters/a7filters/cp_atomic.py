"""新ARMv7整组写入与原CP快照交错联验；不表示银行发布或相机生效。"""
import hashlib
import io
import struct

from .access_evidence import CP_SHA,require_source
from .cp_machine import CpMachine,WORK,STACK,STOP
from .investigate import PARAMETERS

STATE,MASTER,MARKER=0x157aa10,0x164eef0,0x19c999d


def machine(cp,raw):
    from elftools.elf.elffile import ELFFile
    from unicorn import UC_PROT_READ,UC_PROT_EXEC
    if len(raw)>0x20000:raise ValueError('原子写入研究ELF超出文件预算')
    elf=ELFFile(io.BytesIO(raw))
    if elf['e_machine']!='EM_ARM' or elf['e_type']!='ET_EXEC' or not elf.little_endian:
        raise ValueError('原子写入适配器必须为独立小端ARM ELF')
    if any(s['sh_type'] in ('SHT_REL','SHT_RELA') for s in elf.iter_sections()):
        raise ValueError('原子写入适配器不能有运行时重定位')
    table=elf.get_section_by_name('.symtab')
    if table is None:raise ValueError('原子写入适配器缺少符号表')
    symbols={s.name:int(s['st_value']) for s in table.iter_symbols() if s['st_shndx']!='SHN_UNDEF'}
    for name in ('af_cp406_locked_prepare','af_cp406_write_state','af_validate'):
        if name not in symbols or not 0x92000000<=symbols[name]<0x92010000 or not symbols[name]&1:
            raise ValueError('原子写入适配器符号/Thumb地址不符')
    m=CpMachine(cp)
    for segment in elf.iter_segments():
        if segment['p_type']!='PT_LOAD':continue
        start,end,flags=segment['p_vaddr'],segment['p_vaddr']+segment['p_memsz'],segment['p_flags']
        if flags not in (4,5) or not ((start==0x10000 and end<=0x11000) or
                                      0x92000000<=start<end<=0x92020000):
            raise ValueError('原子写入适配器映射/权限超出预算')
        pages=set(range(start&~4095,(end+4095)&~4095,4096))
        if pages&m.pages:raise ValueError('原子写入适配器映射重叠')
        m.cpu.mem_map(start&~4095,len(pages)*4096,UC_PROT_READ|(UC_PROT_EXEC if flags==5 else 0))
        m.cpu.mem_write(start,segment.data());m.pages.update(pages)
    for at,size in ((0x157a000,0x2000),(0x164e000,0x3000),(0x1915000,0x1000),(0x19c9000,0x1000)):
        m.map_ram(at,size)
    m.model_semaphore()
    return m,symbols


def values(raw):
    return [struct.unpack('b',raw[p[7]:p[7]+1])[0] for p in PARAMETERS]


def setup(cp,adapter):
    m,symbols=machine(cp,adapter)
    old=bytearray(0xdbc);old[0xd2f]=3
    target=bytearray(old);struct.pack_into('<I',target,0xa40,19)
    wanted=(-3,4,-5,2,6,7,4,8)
    for p,v in zip(PARAMETERS,wanted):target[p[7]]=v&255
    m.put(STATE,bytes(old));m.put(MASTER,b'\x5a'*0xdbc)
    m.put(WORK+0x1000,struct.pack('<BB8b64x',17,0,*wanted))
    return m,symbols,bytes(old),bytes(target)


def competing_snapshot(m):
    owner=m.cpu.context_save()
    old_master=m.read(MASTER,0xdbc)
    # 独立栈和寄存器代表竞争者；不在写入者活跃栈上运行快照。
    m.register('sp',STACK+0x8000);m.register('lr',STOP|1)
    result=m.run(0x898548,arguments=(MASTER,),returned=False,preserve_state=True)
    if m.register('sp')!=STACK+0x8000:raise ValueError('竞争快照栈未恢复')
    after=m.read(MASTER,0xdbc)
    m.cpu.context_restore(owner)
    return dict(return_r0=result['r0'],previous=old_master,after=after)


def collect(cp,adapter):
    require_source(cp,CP_SHA,'CP')
    m,symbols,old,target=setup(cp,adapter)
    result=m.run(symbols['af_cp406_locked_prepare'],arguments=(WORK+0x1000,))
    if result['r0'] or m.read(STATE,0xdbc)!=target or m.read(MARKER,1)!=b'\1' or m.semaphore['held']:
        raise ValueError('整组写入器未准备全部参数或未释放互斥')
    writes=[]
    for w in m.writes:
        address=int(w['address'],0)
        if STATE<=address<STATE+0xdbc or address==MARKER:
            pc=int(w['pc'],0)
            if pc not in writes:writes.append(pc)
    if len(writes)<3:raise ValueError('整组写入器可观察写点不足')
    cases=[]
    for point in (writes[0],writes[len(writes)//2],writes[-1]):
        current,syms,_,expected=setup(cp,adapter)
        stopped=current.run(syms['af_cp406_locked_prepare'],arguments=(WORK+0x1000,),stop_before=(point,))
        if stopped['status']!='STOPPED_BEFORE_BOUNDARY' or not current.semaphore['held']:
            raise ValueError('原子写入交错点没有持有0x24锁')
        partial=current.read(STATE,0xdbc)
        probe=competing_snapshot(current)
        if probe['after']!=probe['previous']:raise ValueError('持锁写入期间原快照读到了部分状态')
        current.run(current.register('pc'),preserve_state=True)
        current.register('r4',MASTER)
        current.run(0x4b8d88,0x4b8dc4,returned=False)
        if current.read(MASTER,0xdbc)!=expected or current.semaphore['held']:
            raise ValueError('整组写入释放后原快照没有读到完整新值')
        cases.append(dict(write_pc=hex(point),partial_values=values(partial),
            native_snapshot_while_locked_unchanged=True,original_snapshot_return_r0=probe['return_r0'],
            native_snapshot_after_unlock_complete=True))
    # 相同原指令在没有互斥的叶函数中间确实能读到混合参数；不是只测“锁标志”为真。
    unlocked,syms,old,target=setup(cp,adapter)
    unlocked.run(syms['af_cp406_write_state'],arguments=(WORK+0x1000,STATE,0xdbc,MARKER),
                 stop_before=(writes[len(writes)//2],))
    mixed=competing_snapshot(unlocked)['after']
    if mixed in (old,target) or values(mixed)==values(old) or values(mixed)==values(target):
        raise ValueError('无锁反例未产生可区分的部分参数快照')
    rejected=[]
    for kind,fineness in ((0,0),(1,3)):
        bad,syms,before,_=setup(cp,adapter)
        packet=struct.pack('<BB8b',17,kind,0,0,0,0,0,0,fineness,0)
        packet+=(b'\1'*64 if kind else b'\0'*64)
        bad.put(WORK+0x1000,packet)
        result=bad.run(syms['af_cp406_locked_prepare'],arguments=(WORK+0x1000,))
        if result['r0']!=0xffffffff or bad.read(STATE,0xdbc)!=before or bad.semaphore_events:
            raise ValueError('非法/LUT预设在拒绝前改变输入或获取锁')
        rejected.append(dict(kind=kind,fineness=fineness,no_state_or_lock_effect=True))
    return dict(schema='a7r5-cp-atomic-prepare/1',cp_sha256=CP_SHA,
        adapter_bytes=len(adapter),adapter_sha256=hashlib.sha256(adapter).hexdigest(),
        interleavings=cases,unlocked_counterexample_values=values(mixed),rejections=rejected,
        native_whole_input_write=True,whole_bank_publish_verified=False,
        actual_message_entry_installed=False,actual_rtos_executed=False,
        frame_release_verified=False,hardware_apply_acknowledgement=False,
        fixture_boundaries=['preset and state memory','0x24 mutex ownership backend',
            'competing CPU register contexts with independent stacks'],
        camera_io=False,firmware_modified=False)
