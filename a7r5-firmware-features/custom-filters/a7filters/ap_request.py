"""原AP完整单向请求/C++清理及待回复阻塞边界；不执行宿主syscall。"""
import hashlib
import struct

from .access_evidence import AP_SHA,CP_SHA,WORK,STACK,STOP,require_source
from .ap_cp_messages import MessageMachine,IPC_SHA,QUEUE,refresh,consume
from .cp_message_pool import NativeMessagePool
from .investigate import AP,instructions
from .ui_evidence import STD_SHA

STD_BASE=0x71000000
FREE,FUTEX=WORK+0xf100,WORK+0xf110


class RequestMachine(MessageMachine):
    def __init__(self,ap_raw,ipc_raw,std_raw):
        require_source(ap_raw,AP_SHA,'AP');require_source(ipc_raw,IPC_SHA,'OSAL')
        require_source(std_raw,STD_SHA,'libstdc++')
        super().__init__(ap_raw,ipc_raw)
        from unicorn import UC_HOOK_MEM_UNMAPPED,UC_HOOK_MEM_READ,UC_HOOK_CODE
        self.images=((AP(ap_raw),0),(AP(std_raw),STD_BASE))
        self.exports={};self.imports={};self.relative={}
        self.lazy_pages=set();self.allocations={};self.freed=[];self.heap=WORK+0x9000
        self.wait_boundary=None;self.diagnostics=[];self.entry_hits={}
        for image,base in self.images:
            for symbol in image.elf.get_section_by_name('.dynsym').iter_symbols():
                if symbol.name and symbol['st_shndx']!='SHN_UNDEF' and symbol['st_info']['type']!='STT_TLS':
                    self.exports.setdefault(symbol.name,base+int(symbol['st_value']))
            for section in image.elf.iter_sections():
                if section['sh_type']!='SHT_RELA':continue
                symbols=image.elf.get_section(section['sh_link'])
                for rel in section.iter_relocations():
                    slot=base+int(rel['r_offset'])
                    if rel['r_info_type']==1027:self.relative[slot]=base+int(rel['r_addend'])
                    elif rel['r_info_type'] in (257,1025,1026):
                        self.imports[slot]=(symbols.get_symbol(rel['r_info_sym']).name,int(rel['r_addend']))
        self.exports.update(free=FREE,syscall=FUTEX)
        self.cpu.hook_add(UC_HOOK_MEM_UNMAPPED,self._map_source)
        self.cpu.hook_add(UC_HOOK_MEM_READ,self._check_import)
        self.cpu.hook_add(UC_HOOK_CODE,self._request_boundary)

    def _map_source(self,cpu,access,address,size,value,data):
        from unicorn import UC_PROT_READ,UC_PROT_WRITE,UC_PROT_EXEC
        page=address&~4095
        if len(self.lazy_pages)>=64:raise ValueError('原AP请求的源页预算耗尽')
        for image,base in self.images:
            segment=next((s for s in image.segments if base+s['p_vaddr']<=page<base+s['p_vaddr']+s['p_memsz']),None)
            if segment is None:continue
            flags=int(segment['p_flags'])
            cpu.mem_map(page,4096,UC_PROT_READ|(UC_PROT_WRITE if flags&2 else 0)|(UC_PROT_EXEC if flags&1 else 0))
            available=max(0,min(4096,base+segment['p_vaddr']+segment['p_filesz']-page))
            if available:cpu.mem_write(page,image.read(page-base,available))
            for slot,addend in self.relative.items():
                if page<=slot<=page+4088:cpu.mem_write(slot,struct.pack('<Q',addend))
            for slot,(name,addend) in self.imports.items():
                if page<=slot<=page+4088 and name in self.exports:
                    cpu.mem_write(slot,struct.pack('<Q',self.exports[name]+addend))
            self.lazy_pages.add(page);return True
        raise ValueError('原AP请求触及未知源映射：'+hex(address))

    def _check_import(self,cpu,access,address,size,value,data):
        if address in self.imports:
            name,_=self.imports[address]
            # 库尚未进行线程初始化，显式保留弱线程存在标记为0；不伪造pthread服务。
            if name not in self.exports and name!='__pthread_key_create':
                raise ValueError('原AP请求触及未绑定导入：'+name)

    def _request_boundary(self,cpu,at,size,data):
        if at in (0x355882c,0x352be50,0x352132c,0x352a7e8,0x30bedb0,0x351fdd4):
            self.entry_hits[hex(at)]=self.entry_hits.get(hex(at),0)+1
        if at==0x16dc130:
            count=self.register('x0')
            if count not in (32,48) or self.heap+count+32>WORK+0xe000:
                raise ValueError('原AP请求对象分配超出预算')
            pointer=self.heap;self.heap+=count+32
            cpu.mem_write(pointer-16,b'\xa5'*(count+32));self.allocations[pointer]=count
            self._return(pointer)
        elif at==FREE:
            pointer=self.register('x0')
            if pointer not in self.allocations or pointer in self.freed:
                raise ValueError('原AP请求重复或外来释放')
            self.check_redzones();self.freed.append(pointer);self._return()
        elif at in (0x17fc630,0x35b858c):
            if at==0x35b858c:self.diagnostics.append(dict(entry=hex(at),transport_error_fixture=True))
            self._return()
        elif at==FUTEX:
            values=[self.register('x'+str(i)) for i in range(6)]
            if (values[0]!=98 or values[2]!=0 or values[3]!=0x80000000 or values[4] or
                not any(p<=values[1]<=p+n-4 for p,n in self.allocations.items())):
                raise ValueError('原AP待回复状态未到达已知futex等待边界')
            self.wait_boundary=dict(syscall=98,operation=values[2],expected=hex(values[3]),
                address=hex(values[1]),timeout_pointer=values[4],host_syscall_executed=False)
            cpu.emu_stop()

    def check_redzones(self):
        for pointer,size in self.allocations.items():
            if (bytes(self.cpu.mem_read(pointer-16,16))!=b'\xa5'*16 or
                bytes(self.cpu.mem_read(pointer+size,16))!=b'\xa5'*16):
                raise ValueError('原AP请求对象保护区被覆盖')

    def invoke(self,reply=False,failed=False):
        if self.serial or self.allocations:raise ValueError('原AP请求研究对象只能运行一次')
        self.send_result=-7 if failed else 0
        if reply:
            self.cpu.mem_write(WORK+0x1000,struct.pack('<BBHII',5,0,0x402f,0x11223344,19))
            arguments=(QUEUE,WORK+0x1000,12,0x402f,WORK+0x2000,12);entry=0x355882c
        else:
            # 从真实基底发送器进入完整包装器，不只手工调用其发送子窗口。
            self.cpu.mem_write(WORK+0x1000,struct.pack('<3I20x',0x11223344,17,10))
            self.word(WORK+0x2000,0xa5a5a5a5)
            arguments=(WORK+0x1000,WORK+0x2000);entry=0x35614b4
        for i,arg in enumerate(arguments):self.register('x'+str(i),arg)
        self.register('sp',STACK+0x8000);self.register('lr',STOP)
        self.cpu.emu_start(entry,STOP,count=100000)
        if reply:
            if not self.wait_boundary or self.register('pc')!=FUTEX:
                raise ValueError('原带回复请求没有在未执行syscall前停止')
        elif self.register('pc')!=STOP or self.register('sp')!=STACK+0x8000:
            raise ValueError('原单向请求未完整返回')
        self.check_redzones()
        if [x['operation'] for x in self.observed]!=['allocate','send']:
            raise ValueError('原完整请求的传输分配/发送顺序不符')
        expected=struct.pack('<BBHII',5,0,0x402f,0x11223344,19).hex()
        if self.observed[-1]['packet']!=expected:raise ValueError('原基底请求格式不符')
        if not reply and (set(self.freed)!=set(self.allocations) or self.word(WORK+0x2000)!=0):
            raise ValueError('原单向请求没有释放全部C++对象或原输出状态不符')
        return dict(reply_requested=reply,failed_send_fixture=failed,full_request_wrapper_executed=not reply,
            native_entry_hits=self.entry_hits,allocation_sizes=list(self.allocations.values()),
            freed_objects=len(self.freed),wait_boundary=self.wait_boundary,
            sender_output_status=None if reply else self.word(WORK+0x2000),
            native_library_pages=len(self.lazy_pages),transport_events=self.observed,
            diagnostics=self.diagnostics,redzones_valid=True,
            transport_send_is_apply_acknowledgement=False,physical_reply_observed=False)


def collect(ap_raw,cp,ipc_raw,std_raw):
    for raw,digest,name in ((ap_raw,AP_SHA,'AP'),(cp,CP_SHA,'CP'),(ipc_raw,IPC_SHA,'OSAL'),(std_raw,STD_SHA,'libstdc++')):
        require_source(raw,digest,name)
    cases=[]
    for reply,failed in ((False,False),(False,True),(True,False)):
        a=RequestMachine(ap_raw,ipc_raw,std_raw);case=a.invoke(reply,failed)
        if not reply and not failed:
            body=bytes.fromhex(a.observed[-1]['packet'])
            p=NativeMessagePool(cp);pointer=p.allocate(body);p.dispatch(pointer)
            values=refresh(p.m)
            case['native_ap_to_cp_consumption']=consume(p.m,values)
            if p.allocated(QUEUE) or p.m.word(p.pool+0x18)!=0x1000:
                raise ValueError('完整AP到CP消费后消息池未恢复')
            case['native_cp_message_released']=True
        cases.append(case)
        # 解除CPU回调对执行器的持有，避免批量审计保留整份AP解析对象。
        a.cpu=None
        if not reply and not failed:p.m.cpu=None
    from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
    md=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN);image=AP(ap_raw)
    return dict(schema='a7r5-native-ap-request-lifetime/1',ap_sha256=AP_SHA,cp_sha256=CP_SHA,
        ipc_sha256=IPC_SHA,stdlib_sha256=STD_SHA,cases=cases,
        windows={hex(a):instructions(md,image.read(a,n),a) for a,n in
                 ((0x355882c,560),(0x352be50,116),(0x352bdb0,144),(0x352a7e8,112),
                  (0x3554d24,144),(0x3554ec8,68))},
        fixture_boundaries=['C++ allocation/free with 16-byte redzones; sizes32/48 and bounded heap',
            'OSAL ioctl/diagnostic/lock/memcpy backends','64 source-page budget; explicit ELF relocation/load bases',
            'uninitialized weak thread presence marker zero; single-thread library branch only',
            'CP native pool descriptors/free block and pool-lock model',
            'stop before libc futex syscall; no reply or wakeup invented'],
        version_handshake_verified=False,full_reply_request_completed=False,
        whole_frame_release_proven=False,camera_io=False,firmware_modified=False)
