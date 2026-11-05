"""绑定同包C++/编译器辅助库；不以主机算法替代原散列表扩容。"""
import struct

from .access_evidence import require_source
from .investigate import AP
from .ui_evidence import STD_SHA

GCC_PATH='/lib/libgcc_s.so.1'
GCC_BYTES=71920
GCC_SHA='9a348469b43aaf815f32104139a62116ef1247662a965b24e38e88e574814805'


class NativeHashRuntime:
    def __init__(self,machine,gcc_raw):
        require_source(machine.std.raw,STD_SHA,'libstdc++')
        require_source(gcc_raw,GCC_SHA,'libgcc_s')
        from unicorn import UC_HOOK_CODE, UC_HOOK_MEM_READ
        self.machine=machine
        self.images=((machine.std,0x10000000),(AP(gcc_raw),0x11000000))
        self.exports={};self.pages={0x100a6000};self.bindings=[];self.unbound={};self.hits={}
        for image,base in self.images:
            for symbol in image.elf.get_section_by_name('.dynsym').iter_symbols():
                if symbol.name and symbol['st_shndx']!='SHN_UNDEF' and symbol['st_info']['type']!='STT_TLS':
                    self.exports.setdefault(symbol.name,base+int(symbol['st_value']))
            for segment in image.segments:
                start=int(segment['p_vaddr']);end=start+int(segment['p_memsz'])
                if end>0x200000:raise ValueError('同包辅助库超出映射预算')
                for page in range(start&~4095,(end+4095)&~4095,4096):
                    if base+page not in self.pages:
                        machine.cpu.mem_map(base+page,4096);self.pages.add(base+page)
                machine.cpu.mem_write(base+start,segment.data())
            for address,addend in image.relocations.items():
                machine.cpu.mem_write(base+address,struct.pack('<Q',base+addend))
        for image,base in (*self.images,(machine.ap,0)):
            for section in image.elf.iter_sections():
                if section['sh_type']!='SHT_RELA':continue
                symbols=image.elf.get_section(section['sh_link'])
                for rel in section.iter_relocations():
                    if rel['r_info_type'] not in (1025,1026):continue
                    name=symbols.get_symbol(rel['r_info_sym']).name
                    if (image is machine.ap and 'Prime_rehash_policy' not in name
                            and name not in ('__floatunditf','__trunctfdf2',
                                             '_ZSt18_Rb_tree_incrementPSt18_Rb_tree_node_base')):continue
                    address=base+rel['r_offset']
                    if image is machine.ap:machine.map_ap(address&~4095)
                    value=self.exports.get(name,0)
                    machine.cpu.mem_write(address,struct.pack('<Q',value))
                    if value:self.bindings.append(dict(slot=hex(address),symbol=name,target=hex(value)))
                    else:self.unbound[address]=name
        for name in ('_ZNKSt8__detail20_Prime_rehash_policy14_M_need_rehashEmmm',
                     '_ZNKSt8__detail20_Prime_rehash_policy11_M_next_bktEm',
                     '__extendsftf2','__floatunditf','__divtf3','__getf2','__trunctfdf2','__multf3'):
            address=self.exports[name];self.hits[address]=0
        def code(cpu,address,size,data):
            if address in self.hits:self.hits[address]+=1
        def read(cpu,access,address,size,value,data):
            if address in self.unbound:raise ValueError('未绑定同包辅助库符号: '+self.unbound[address])
        machine.cpu.hook_add(UC_HOOK_CODE,code)
        for image,base in self.images:
            machine.cpu.hook_add(UC_HOOK_MEM_READ,read,begin=base,end=base+0x200000-1)

    def report(self):
        return dict(gcc_path=GCC_PATH,gcc_bytes=GCC_BYTES,gcc_sha256=GCC_SHA,
                    stdlib_sha256=STD_SHA,bindings=self.bindings,
                    native_entry_hits={hex(k):v for k,v in self.hits.items()},
                    unbound_imports_rejected_on_use=True,library_initializers_executed=False,
                    fixture_boundaries=['explicit offline load bases','bounded allocator/zero/free'])
