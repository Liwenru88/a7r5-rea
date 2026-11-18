"""锁定4.06的离线动态模块装载/入站分支；不提供客体或相机安装入口。"""
import hashlib
import io
import struct

from elftools.elf.elffile import ELFFile

from a7filters.access_evidence import AP_SHA
from a7filters.ap_ui_hooks import HOOKS, branch
from a7filters.ui_resource_lookup import OBJ_SHA

SPAN = 0x8e84000


class NativeUiLoader:
    """调用方须停止原UI线程；机器接口只用于隔离指令执行。

    原函数只覆盖4字节。远目标通过独立16字节岛跳转，避免破坏+4返回。
    预注册可撤销；原注册器持有新增行后禁止卸挂，避免残留名称标记进入原资源接口。
    """
    def __init__(self, machine, module_raw, module_base, island_base):
        self.m = machine
        if hashlib.sha256(machine.ap.raw).hexdigest() != AP_SHA:
            raise ValueError('AP来源不符')
        if hashlib.sha256(machine.obj.raw).hexdigest()!=OBJ_SHA or not machine.obj_base or machine.obj_base&4095:
            raise ValueError('同包Obj来源或基址不符')
        self.module_raw, self.base, self.island = module_raw,module_base,island_base
        if not module_base or module_base&4095 or not island_base or island_base&4095:
            raise ValueError('模块或岛地址未按页对齐')
        self.elf = ELFFile(io.BytesIO(module_raw))
        if (self.elf['e_type'],self.elf['e_machine'],self.elf.little_endian) != ('ET_DYN','EM_AARCH64',True):
            raise ValueError('只接受A64小端动态模块')
        symbols = self.elf.get_section_by_name('.symtab')
        if symbols is None:raise ValueError('模块缺少符号表')
        defined = {s.name:int(s['st_value']) for s in symbols.iter_symbols()
                   if s.name and s['st_shndx'] != 'SHN_UNDEF'}
        if any(s.name and s['st_shndx']=='SHN_UNDEF' for s in symbols.iter_symbols()):
            raise ValueError('模块仍有未解析符号')
        required = {h[1] for h in HOOKS}|{'af_ap_bind','af_ap_unbind','af_ap_research_enable','af_ap_rows',
                    'af_ap_detach_allowed','af_ap_labels','af_labels_init','af_ap_names_bind','af_ap_names_enable',
                    'af_ap_manager','af_ap_manage_menu_bind','af_ap_manage_menu_register','af_ap_manage_menu_enable',
                    'af_ap_manage_service_bind','af_ap_manage_service_poll','af_ap_manage_picker_bind',
                    'af_ap_manage_ui_open','af_ap_manage_ui_chosen','af_ap_targets_bind','af_ap_targets_register',
                    'af_ap_targets_enable','af_ap_targets_stage','af_ap_targets_presented','af_ap_browser_bind','af_ap_browser_register','af_ap_browser_enable',
                    'af_ap_media_bind','af_ap_media_prepare','af_ap_media_finish'}
        if not required<=defined.keys():raise ValueError('模块缺少接入符号')
        self.symbols = {name:module_base+offset for name,offset in defined.items()}
        self.segments = [s for s in self.elf.iter_segments() if s['p_type']=='PT_LOAD']
        pages = {}
        for s in self.segments:
            start,end = int(s['p_vaddr']),int(s['p_vaddr']+s['p_memsz'])
            if (s['p_flags'] not in (5,6) or s['p_filesz']>s['p_memsz'] or
                not 0<=start<end<=0x40000 or module_base+end>0xffffffffffffffff):
                raise ValueError('模块段权限或预算不符')
            permission = 1|(4 if s['p_flags']&1 else 2)
            for p in range(start&~4095,(end+4095)&~4095,4096):
                if p in pages:raise ValueError('模块段共页')
                pages[p] = permission
        self.pages = pages
        def inside(offset,size=1,writable=False):
            return any(s['p_vaddr']<=offset and offset+size<=s['p_vaddr']+s['p_memsz']
                       and (not writable or s['p_flags']&2) for s in self.segments)
        if any(not inside(defined[n]) for n in required):raise ValueError('模块符号超出段')
        if defined['af_ap_labels']&7 or not inside(defined['af_ap_labels'],1600,True):
            raise ValueError('唯一名称缓存未对齐或不完整属于可写段')
        if self.elf['e_entry'] != defined['af_ap_register']:raise ValueError('模块入口身份不符')
        self.relocations = []
        for section in self.elf.iter_sections():
            if section['sh_type'] != 'SHT_RELA':continue
            for rel in section.iter_relocations():
                at,value = int(rel['r_offset']),int(rel['r_addend'])
                if (rel['r_info_type']!=1027 or rel['r_info_sym'] or at&7 or
                    not inside(at,8,True) or not inside(value)):
                    raise ValueError('模块重定位类型或范围不符')
                self.relocations.append((at,value))
        self.patches = []
        island = bytearray()
        for offset,name,link,_ in HOOKS:
            source,target = machine.base+offset,self.symbols[name]
            before = machine.ap.read(offset,4)
            try:after = branch(source,target,link);kind = 'direct'
            except ValueError:
                entry = island_base+len(island)
                after = branch(source,entry,link);kind = 'island'
                # LDR X16,#8; BR X16; 目标64位地址。两条均不修改NZCV。
                island.extend(struct.pack('<IIQ',0x58000050,0xd61f0200,target))
            self.patches.append(dict(source=source,target=target,before=before,after=after,kind=kind,name=name))
        if len(island)>4096:raise ValueError('跳板岛超出单页预算')
        self.island_raw = bytes(island)
        all_pages = {module_base+p for p in pages}
        if island and island_base in all_pages:raise ValueError('岛与模块段重叠')
        self.state = 'NEW'

    def _preimages(self, installed):
        for p in self.patches:
            self.m.map_ap(p['source']-self.m.base)
            if bytes(self.m.u.mem_read(p['source'],4)) != p['after' if installed else 'before']:
                raise ValueError('入站前像已被其他拥有者改变：'+hex(p['source']))
            page = p['source']&~4095
            wanted = self.m.permissions[page]
            if not any(start<=page<=end and permission==wanted for start,end,permission in self.m.u.mem_regions()):
                raise ValueError('原AP页权限已被其他拥有者改变：'+hex(page))
        if installed and self.island_raw and bytes(self.m.u.mem_read(self.island,len(self.island_raw)))!=self.island_raw:
            raise ValueError('拥有的跳板岛已改变')

    def _module_ownership(self):
        regions = list(self.m.u.mem_regions())
        pages = {self.base+p:permission for p,permission in self.pages.items()}
        if self.island_raw:pages[self.island] = 5
        if any(not any(start<=page<=end and permission==wanted for start,end,permission in regions)
               for page,wanted in pages.items()):raise ValueError('所属映射权限被其他拥有者改变')
        for s in self.segments:
            if s['p_flags']==5 and bytes(self.m.u.mem_read(self.base+s['p_vaddr'],s['p_filesz']))!=s.data():
                raise ValueError('所属只读模块内容已改变')

    def prepare(self):
        if self.state != 'NEW':raise ValueError('装载状态不符')
        self._preimages(False)
        allocated = [self.base+p for p in self.pages]
        if self.island_raw:allocated.append(self.island)
        regions = list(self.m.u.mem_regions())
        if any(start<=p<=end for p in allocated for start,end,_ in regions):
            raise ValueError('装载地址已被占用')
        owned = []
        self.state = 'PREPARING'
        try:
            for p in allocated:
                self.m.u.mem_map(p,4096,3);owned.append(p)
            for s in self.segments:self.m.u.mem_write(self.base+s['p_vaddr'],s.data())
            for at,value in self.relocations:self.m.u.mem_write(self.base+at,struct.pack('<Q',self.base+value))
            for p,permission in self.pages.items():self.m.u.mem_protect(self.base+p,4096,permission)
            if self.island_raw:
                self.m.u.mem_write(self.island,self.island_raw);self.m.u.mem_protect(self.island,4096,5)
            config = struct.pack('<IIQQQ32s',1,64,self.m.base,SPAN,self.m.base+0x17feac0,bytes.fromhex(AP_SHA))
            self.m.u.mem_write(self.m.work,config)
            result = self.m.call(self.symbols['af_ap_bind'],self.m.work)
            if result != 0:raise ValueError('动态绑定拒绝：'+str(result))
            self.m.call(self.symbols['af_labels_init'],self.symbols['af_ap_labels'])
            config = struct.pack('<IIQQQ',1,32,self.m.base,self.m.obj_base,self.symbols['af_ap_labels'])
            self.m.u.mem_write(self.m.work,config)
            result = self.m.call(self.symbols['af_ap_names_bind'],self.m.work)
            if result != 0:raise ValueError('原Obj名称绑定拒绝：'+str(result))
        except Exception as error:
            self.failure = {'error':str(error),'owned_pages':list(owned),'unmap_errors':[]}
            for p in reversed(owned):
                try:self.m.u.mem_unmap(p,4096)
                except Exception as cleanup:self.failure['unmap_errors'].append({'page':p,'error':str(cleanup)})
            self.state = 'CONFLICT' if self.failure['unmap_errors'] else 'REJECTED'
            raise
        self.state = 'BOUND'

    def install(self):
        if self.state != 'BOUND':raise ValueError('尚未绑定或已安装')
        self._preimages(False)
        self._module_ownership()
        attempted = []
        try:
            for p in self.patches:
                attempted.append(p)
                self.m.write_ap_code(p['source'],p['after'])
        except Exception:
            # 只撤销仍是本次前像/后像的单指令；未知写入保留故障现场。
            for p in reversed(attempted):
                current = bytes(self.m.u.mem_read(p['source'],4))
                if current == p['after']:self.m.write_ap_code(p['source'],p['before'])
                elif current != p['before']:
                    self.state = 'CONFLICT';raise RuntimeError('安装失败且所属指令已改变，停止撤销')
            raise
        self.state = 'INSTALLED'

    def remove(self):
        if self.state != 'INSTALLED':raise ValueError('没有可移除的已安装挂钩')
        # 先检查全部所属指令和岛，再执行任何禁用或撤销。
        self._preimages(True)
        self._module_ownership()
        if self.m.call(self.symbols['af_ap_detach_allowed'])!=0:
            raise ValueError('原注册器已引用模块或可能留有名称标记，禁止卸挂')
        disabled = self.m.call(self.symbols['af_ap_research_enable'],0)
        if disabled not in (0,-1):raise ValueError('原列表已被其他拥有者改变，保留现场')
        for p in self.patches:self.m.write_ap_code(p['source'],p['before'])
        unbound = self.m.call(self.symbols['af_ap_unbind'])
        if self.island_raw:self.m.u.mem_unmap(self.island,4096)
        if unbound == 0:
            for p in self.pages:self.m.u.mem_unmap(self.base+p,4096)
            self.state = 'UNLOADED'
        else:raise ValueError('解绑状态异常，模块保持驻留')
        self._preimages(False)
        return self.state
