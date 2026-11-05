"""原资源加载器的隔离执行机；系统接口只访问内存文件，不转调宿主I/O。"""
import struct

from .access_evidence import WORK, STACK, STOP, require_source, arm64_cpu, run64
from .investigate import AP
from .ui_resource_lookup import OBJ_SHA

MASK=(1<<64)-1


class ResourceMachine:
    def __init__(self,obj_raw,files,fault=None,guard=False):
        require_source(obj_raw,OBJ_SHA,'libObj')
        from unicorn import UC_HOOK_CODE
        from unicorn import arm64_const as r
        if any(not isinstance(p,str) or not p.startswith('/usr/share/app/') or '/' in p[15:] or '..' in p
               or not isinstance(raw,bytes) or not 16<=len(raw)<=0x80000 for p,raw in files.items()):
            raise ValueError('资源内存文件路径或尺寸越界')
        self.r=r;self.image=AP(obj_raw);self.cpu=arm64_cpu(self.image,[])
        self.files=files;self.fault=fault;self.heap=0x91000010
        self.allocations={};self.freed=set();self.fds={};self.maps={};self.events=[]
        self.nextfd=100;self.nextmap=0x93000000;self.hits={}
        self.cpu.mem_map(0x91000000,0x100000)
        for segment in self.image.segments:
            start=int(segment['p_vaddr']);end=start+int(segment['p_memsz'])
            if end>0x300000:raise ValueError('资源库映射超出预算')
            self.cpu.mem_map(start&~4095,((end+4095)&~4095)-(start&~4095))
            self.cpu.mem_write(start,segment.data())
        for address,value in self.image.relocations.items():self.cpu.mem_write(address,struct.pack('<Q',value))
        exports={s.name:int(s['st_value']) for s in self.image.elf.get_section_by_name('.dynsym').iter_symbols()
                 if s.name and s['st_shndx']!='SHN_UNDEF'}
        slots={}
        for section in self.image.elf.iter_sections():
            if section['sh_type']!='SHT_RELA':continue
            symbols=self.image.elf.get_section(section['sh_link'])
            for rel in section.iter_relocations():
                if rel['r_info_type'] not in (1025,1026):continue
                name=symbols.get_symbol(rel['r_info_sym']).name;address=rel['r_offset'];slots[address]=name
                self.cpu.mem_write(address,struct.pack('<Q',exports.get(name,0)))
        self.exports=exports;self.plts={}
        section=self.image.elf.get_section_by_name('.plt')
        for address in range(int(section['sh_addr'])+32,int(section['sh_addr']+section['sh_size']),16):
            first,second=struct.unpack('<2I',self.image.read(address,8))
            immediate=(((first>>5)&0x7ffff)<<2)|((first>>29)&3)
            immediate=(immediate^(1<<20))-(1<<20)
            slot=(address&~4095)+(immediate<<12)+((second>>10)&0xfff)*8
            if slot in slots:self.plts[address]=slots[slot]
        self.context=WORK+0x1000;self.allocator=WORK+0x1800
        self.core=WORK+0x3000;self.database=WORK+0x5000
        self.cpu.mem_write(self.context+0x80,struct.pack('<Q',self.allocator))
        self.cpu.mem_write(self.allocator,struct.pack('<Q',WORK+0x1900))
        self.cpu.mem_write(WORK+0x1900,struct.pack('<3Q',WORK+0xa010,0,WORK+0xa020))
        self.cpu.mem_write(0x2d1e28,struct.pack('<Q',WORK+0xa000))
        self.guard_patch=dict(applied=False,restored=None)
        if guard:
            from .resource_guard import install
            self.guard_patch=install(self)
        for address in (0x11857c,0x1183d4,0x122b1c,0x122dc8,0x123840,0x123090,0x123660,
                        0x1212d8,0x1213b4,0x122c90):self.hits[address]=0
        if guard:self.hits[0x300000]=0
        self.code_hook=self.cpu.hook_add(UC_HOOK_CODE,self._hook)
        self.call(0x12d270,self.core+0x938);self.call(0x12d270,self.core+0x948)
        self.call(0x122980,self.database)

    def string(self,address,limit=4096):
        result=bytearray()
        for i in range(limit):
            char=self.cpu.mem_read(address+i,1)
            if char==b'\0':return bytes(result)
            result.extend(char)
        raise ValueError('资源字符串超过预算')

    def write(self,address,data):
        end=address+len(data)
        local=WORK<=address<=end<=WORK+0x10000 or STACK<=address<=end<=STACK+0x10000
        owned=any(a<=address<=end<=a+n and a not in self.freed for a,n in self.allocations.items())
        if not local and not owned:raise ValueError('资源后端写入不属于工作区/存活分配')
        self.cpu.mem_write(address,data)

    def allocate(self,size):
        if not 0<size<=65536 or self.heap+size+16>0x91100000:raise ValueError('资源堆请求超过预算')
        result=self.heap;self.heap+=(size+47)&~15;self.allocations[result]=size
        self.cpu.mem_write(result-16,b'\xa5'*(size+32));return result

    def release(self,address):
        if not address:return 0
        if address not in self.allocations or address in self.freed:raise ValueError('资源释放未知或重复地址')
        self.freed.add(address);return 0

    def _hook(self,cpu,address,size,data):
        r=self.r
        if address in self.hits:self.hits[address]+=1
        if address not in (WORK+0xa000,WORK+0xa010,WORK+0xa020) and address not in self.plts:return
        args=[cpu.reg_read(getattr(r,'UC_ARM64_REG_X'+str(i))) for i in range(6)]
        if address==WORK+0xa000:result=self.context
        elif address==WORK+0xa010:result=self.allocate(args[1])
        elif address==WORK+0xa020:result=self.release(args[1])
        elif address in self.plts:
            name=self.plts[address]
            if name in self.exports:return
            result=self._system(name,args)
        else:return
        cpu.reg_write(r.UC_ARM64_REG_X0,result)
        cpu.reg_write(r.UC_ARM64_REG_PC,cpu.reg_read(r.UC_ARM64_REG_LR))

    def _system(self,name,args):
        cpu=self.cpu
        if name in ('malloc','_Znwm','_Znam'):return self.allocate(args[0])
        if name in ('free','_ZdlPv','_ZdlPvm','_ZdaPv'):return self.release(args[0])
        if name=='strlen':return len(self.string(args[0]))
        if name in ('memcpy','memmove','memset'):
            if args[2]>65536:raise ValueError('资源内存操作超过预算')
            raw=bytes([args[1]&255])*args[2] if name=='memset' else bytes(cpu.mem_read(args[1],args[2]))
            self.write(args[0],raw);return args[0]
        if name=='strncpy':
            if args[2]>4096:raise ValueError('资源路径复制超过预算')
            raw=self.string(args[1])[:args[2]].ljust(args[2],b'\0')
            self.write(args[0],raw);return args[0]
        if name in ('strchr','strrchr'):
            raw=self.string(args[0])+b'\0';char=bytes([args[1]&255])
            index=raw.find(char) if name=='strchr' else raw.rfind(char)
            return 0 if index<0 else args[0]+index
        if name=='stella_print_log':self.events.append(dict(operation='log',level=args[0]));return 0
        if name=='open':
            path=self.string(args[0]).decode()
            if args[1]!=0 or not path.startswith('/usr/share/app/') or '..' in path:
                raise ValueError('资源后端拒绝写入或越界路径')
            self.events.append(dict(operation='open',path=path))
            if path not in self.files or self.fault==('open',path):return MASK
            result=self.nextfd;self.nextfd+=1;self.fds[result]=path;return result
        if name=='__fxstat':
            if args[0]!=0 or args[1] not in self.fds:raise ValueError('资源stat参数或文件描述符不符')
            if self.fault==('stat',self.fds[args[1]]):return MASK
            self.write(args[2],b'\0'*128)
            self.write(args[2]+0x30,struct.pack('<Q',len(self.files[self.fds[args[1]]])));return 0
        if name=='mmap':
            address,length,prot,flags,fd,offset=args
            if address or fd not in self.fds or offset or prot!=1 or flags!=0x18002:
                raise ValueError('资源mmap参数超出只读契约')
            path=self.fds[fd];raw=self.files[path]
            if length!=len(raw):raise ValueError('资源mmap长度与文件不符')
            if self.fault==('mmap',path):
                self.events.append(dict(operation='mmap_failed',path=path));return MASK
            pages=(length+4095)&~4095
            if self.nextmap+pages>0x94000000 or sum(m['pages'] for m in self.maps.values())+pages>0x400000:
                raise ValueError('资源映射超过地址或活动预算')
            result=self.nextmap;self.nextmap+=pages+4096
            cpu.mem_map(result,pages);cpu.mem_write(result,raw);cpu.mem_protect(result,pages,1)
            self.maps[result]=dict(pages=pages,bytes=length,path=path)
            self.events.append(dict(operation='mmap',path=path,bytes=length));return result
        if name=='munmap':
            address,length=args[:2];mapped=self.maps.get(address)
            if mapped is None or length!=mapped['bytes']:raise ValueError('资源munmap地址或长度不符')
            cpu.mem_unmap(address,mapped['pages']);del self.maps[address]
            self.events.append(dict(operation='munmap',path=mapped['path']));return 0
        if name=='close':
            path=self.fds.pop(args[0],None)
            if path is None:raise ValueError('资源close未知文件描述符')
            self.events.append(dict(operation='close',path=path));return 0
        raise ValueError('资源机未绑定的导入: '+name)

    def call(self,address,*args):
        for i,value in enumerate(args):self.cpu.reg_write(getattr(self.r,'UC_ARM64_REG_X'+str(i)),value)
        self.cpu.reg_write(self.r.UC_ARM64_REG_LR,STOP);run64(self.cpu,address,500000)
        return self.cpu.reg_read(self.r.UC_ARM64_REG_X0)

    def load(self):
        self.write(WORK+0x7000,b'/usr/share/app/global.xdb\0')
        return self.call(0x122b1c,self.database,self.core,WORK+0x7000)

    def cleanup(self,banks=()):
        # 通过原分组切换、缓存再取得/强制释放收尾，不手工清空容器或引用计数。
        for namespace,bank in banks:
            self.call(0x1235d8,self.database,namespace,0xff,0)
            cached=self.call(0x1212d8,self.core,self.database,namespace,bank)
            if cached:self.call(0x1213b4,self.core,cached,1)
        self.call(0x122c90,self.database);self.call(0x1229c0,self.database)
        if self.fds or self.maps or set(self.allocations)-self.freed:raise ValueError('资源回收仍有文件/映射/所属分配')
        if not all(bytes(self.cpu.mem_read(a-16,16))==b'\xa5'*16 and
                   bytes(self.cpu.mem_read(a+n,16))==b'\xa5'*16 for a,n in self.allocations.items()):
            raise ValueError('资源堆保护区改变')
        return dict(open_files=0,mappings=0,live_allocations=0,allocated_blocks=len(self.allocations),
                    allocator_guards_valid=True,process_exit_verified=False)

    def dispose(self):
        # 仅解除模拟器回调，避免批量场景保留Python引用环；不冒充原库失败回收。
        if self.guard_patch['applied']:
            from .resource_guard import restore
            restore(self)
        self.cpu.hook_del(self.code_hook)
