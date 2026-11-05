"""只读组件与内存内补丁计划核对；不写AP/CP/DAT、不签名、不执行目标指令。"""
from __future__ import annotations
import ast
import hashlib
import io
import re
import struct
from elftools.elf.elffile import ELFFile

AP_SHA='d15933ceb5ff9ad0b4f789cbabd6ff0a51526472dd35c90db97196dd227820e9'
CPIO_SHA='c01948220e1cced7f4e1d6a6dd28221c587050214d32cc405291cc00d2f1ed80'
EXITS={'af_ap_hs_original_return':0x3554d94,'af_ap_hs_owned_return':0x3554ec8,
       'af_ap_receive_return':0x3554d3c,'af_ap_receive_loop':0x3554d24}

def sha(raw):return hashlib.sha256(raw).hexdigest()

def require(ok,message):
    if not ok:raise ValueError(message)

def recipe_pairing(*reports):
    """旧回执缺字段按关闭；新配方桥必须在AP、CP软件及启动清单成对构建。"""
    require(bool(reports),'缺少协议构建回执')
    values=[report.get('recipe_bridge_enabled',False) for report in reports]
    require(all(type(value) is bool for value in values) and len(set(values))==1,
            '完整配方桥构建开关不一致或格式错误')
    return values[0]

def read_cpio(path,wanted):
    """只读固定newc成员，不导出整镜像或导入模拟器。"""
    result={}
    with path.open('rb') as f:
        require(hashlib.file_digest(f,'sha256').hexdigest()==CPIO_SHA,'CPIO来源不符')
        f.seek(0)
        while True:
            h=f.read(110);require(len(h)==110 and h[:6]==b'070701','CPIO头不符')
            v=[int(h[6+8*i:14+8*i],16) for i in range(13)]
            require(1<=v[11]<=4096,'CPIO名称长度不符')
            name_raw=f.read(v[11]);require(name_raw.endswith(b'\0'),'CPIO名称未终止')
            name=name_raw[:-1].decode().removeprefix('./');f.read((-110-v[11])%4)
            if name in wanted:
                require(name not in result and v[1]&0xf000==0x8000,'重复或非普通源成员')
                data=f.read(v[6]);require(len(data)==v[6],'CPIO短读');result[name]=data
            else:f.seek(v[6],1)
            f.read((-v[6])%4)
            if name=='TRAILER!!!':break
    require(result.keys()==set(wanted),'缺少指定源成员')
    return result

class Image:
    def __init__(self,raw):
        self.raw=raw;self.elf=ELFFile(io.BytesIO(raw))
        self.segments=[s for s in self.elf.iter_segments() if s['p_type']=='PT_LOAD']
    def offset(self,address,n):
        matches=[s for s in self.segments if s['p_vaddr']<=address and address+n<=s['p_vaddr']+s['p_filesz']]
        require(len(matches)==1,'地址不唯一或不属于文件段')
        s=matches[0];return int(s['p_offset']+address-s['p_vaddr'])
    def read(self,address,n):
        at=self.offset(address,n);return self.raw[at:at+n]

def compose(raw,expected,patches):
    """所有前像对同一原源核验，拒绝重叠；仅返回内存中的候选。"""
    require(sha(raw)==expected,'完整源摘要不符')
    ranges=[]
    for p in patches:
        at=p['offset'];before=bytes.fromhex(p['before']);after=bytes.fromhex(p['after'])
        require(type(at) is int and 0<=at and before and len(before)==len(after) and at+len(before)<=len(raw),'补丁范围或定长不符')
        require(raw[at:at+len(before)]==before,'补丁前像不符')
        require(all(at+len(before)<=a or b<=at for a,b in ranges),'补丁范围重叠')
        ranges.append((at,at+len(before)))
    out=bytearray(raw)
    for p in patches:
        data=bytes.fromhex(p['after']);out[p['offset']:p['offset']+len(data)]=data
    return bytes(out)

def branch(source,target,link=False):
    delta=target-source
    require(not(source&3 or target&3) and -(1<<27)<=delta<(1<<27),'A64分支不对齐或超距')
    return struct.pack('<I',(0x94000000 if link else 0x14000000)|((delta//4)&0x3ffffff))

def dynamic(raw,entry,budget=0x50000):
    image=Image(raw);e=image.elf
    require(e['e_type']=='ET_DYN' and e['e_machine']=='EM_AARCH64' and e.little_endian,'非A64小端ET_DYN')
    pages=set();segments=[]
    for s in image.segments:
        at=int(s['p_vaddr']);n=int(s['p_memsz']);file_n=int(s['p_filesz'])
        require(0<=at<at+n<=budget and 0<=file_n<=n and s['p_flags'] in (5,6),'段预算或W^X不符')
        ps=set(range(at&~4095,(at+n+4095)&~4095,4096))
        require(not pages&ps,'段共页');pages|=ps
        segments.append(dict(va=at,file_bytes=file_n,memory_bytes=n,flags=int(s['p_flags'])))
    table=e.get_section_by_name('.symtab');require(table is not None,'缺少审计符号表')
    symbols={s.name:int(s['st_value']) for s in table.iter_symbols() if s.name and s['st_shndx']!='SHN_UNDEF'}
    require(not any(s.name and s['st_shndx']=='SHN_UNDEF' for s in table.iter_symbols()),'仍有未解析符号')
    require(not any(s.name and s['st_shndx']=='SHN_ABS' and s['st_info']['type']!='STT_FILE' and s.name.startswith('af_') for s in table.iter_symbols()),'残留原AP绝对导入')
    require(entry in symbols and e['e_entry']==symbols[entry],'入口身份不符')
    def inside(at,n=1,write=False):
        return any(s['p_vaddr']<=at and at+n<=s['p_vaddr']+s['p_memsz'] and (not write or s['p_flags']&2) for s in image.segments)
    rels=[]
    for section in e.iter_sections():
        require(section['sh_type']!='SHT_REL','不支持REL')
        if section['sh_type']!='SHT_RELA':continue
        for r in section.iter_relocations():
            at,add=int(r['r_offset']),int(r['r_addend'])
            require(r['r_info_type']==1027 and not r['r_info_sym'] and at%8==0 and inside(at,8,True) and inside(add),'相对重定位不符')
            require(not any(at==x[0] for x in rels),'重复重定位目标');rels.append((at,add))
    return dict(image=image,symbols=symbols,segments=segments,relocations=rels,pages=len(pages))

def runtime_plan(ap_raw,module_raw,ap_base,module_base,island_base,hooks,entry='af_ap_register'):
    require(sha(ap_raw)==AP_SHA,'非当前修改4.06 AP')
    require(all(type(v) is int and v>0 and v%4096==0 for v in (ap_base,module_base,island_base)),'基址缺失或非页对齐')
    require(all(v+(1<<28)<1<<64 for v in (ap_base,module_base,island_base)),'地址溢出')
    mod=dynamic(module_raw,entry);source=Image(ap_raw)
    ap_end=ap_base+0x8e84000;mod_end=module_base+max(s['va']+s['memory_bytes'] for s in mod['segments'])
    ranges=[(ap_base,ap_end),(module_base,mod_end),(island_base,island_base+4096)]
    require(all(b<=c or d<=a for i,(a,b) in enumerate(ranges) for c,d in ranges[i+1:]),'AP/模块/跳板所有权重叠')
    patches=[];island=bytearray();seen=set()
    for offset,name,link,_stock in hooks:
        require(offset not in seen,'重复入口');seen.add(offset)
        require(name in mod['symbols'],'目标符号缺失')
        require(any(s['flags']&1 and s['va']<=mod['symbols'][name]<s['va']+s['file_bytes'] for s in mod['segments']),'目标不属于模块RX段')
        require(any(s['p_flags']&1 and s['p_vaddr']<=offset<offset+4<=s['p_vaddr']+s['p_filesz'] for s in source.segments),'入口不属于源RX段')
        src=ap_base+offset;target=module_base+mod['symbols'][name]
        try:after=branch(src,target,link);kind='direct'
        except ValueError:
            after=branch(src,island_base+len(island),link);kind='veneer'
            island.extend(struct.pack('<IIQ',0x58000050,0xd61f0200,target))
        patches.append(dict(offset=source.offset(offset,4),before=source.read(offset,4).hex(),after=after.hex(),
                            source_va=offset,name=name,kind=kind))
    require(len(island)<=4096,'跳板预算超限')
    memory_only=compose(ap_raw,AP_SHA,patches)
    return dict(patches=patches,island_hex=island.hex(),segments=mod['segments'],
                relocation_count=len(mod['relocations']),memory_ap_sha256=sha(memory_only),
                runtime_only=True,file_patch_authorized=False)

def exit_plan(module_raw,ap_base,module_base):
    mod=dynamic(module_raw,'af_ap_hs_gate');patches=[]
    for name,target in EXITS.items():
        require(name in mod['symbols'],'缺少全状态返回出口')
        at=mod['symbols'][name];before=mod['image'].read(at,4)
        require(before==struct.pack('<I',0xd42080c0),'返回出口不是未绑定陷阱')
        patches.append(dict(name=name,offset=mod['image'].offset(at,4),before=before.hex(),
                            after=branch(module_base+at,ap_base+target).hex(),target=target))
    return compose(module_raw,sha(module_raw),patches),patches

def source_declarations(source):
    text=source.read_text();block=text.split('static const AfApCheck checks[] = {',1)[1].split('};',1)[0]
    rows=[(int(a,16),int(w,16)) for a,w in re.findall(r'\{(0x[0-9a-f]+),(0x[0-9a-f]+)\}',block)]
    require(rows and len(rows)==len(set(a for a,_ in rows)),'前像列表缺失或重复')
    return rows

def hooks_from_source(path):
    node=next(n for n in ast.parse(path.read_text()).body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='HOOKS' for t in n.targets))
    # 当前列表包含8项参数回调的推导式；只接受该受限表达式语法，不导入含模拟器的模块。
    allowed=(ast.Expression,ast.List,ast.Tuple,ast.Constant,ast.BinOp,ast.Add,ast.Mult,
             ast.ListComp,ast.comprehension,ast.Name,ast.Load,ast.Store,ast.Call,
             ast.JoinedStr,ast.FormattedValue)
    for child in ast.walk(node.value):
        require(isinstance(child,allowed),'挂钩声明出现未支持语法')
        if isinstance(child,ast.Name):require(child.id in ('p','range','str'),'挂钩声明名称不符')
        if isinstance(child,ast.Call):
            require(isinstance(child.func,ast.Name) and not child.keywords and len(child.args)==1 and
                    ((child.func.id=='range' and isinstance(child.args[0],ast.Constant) and child.args[0].value==8) or
                     (child.func.id=='str' and isinstance(child.args[0],ast.Name) and child.args[0].id=='p')),'挂钩函数不符')
    return eval(compile(ast.Expression(node.value),str(path),'eval'),{'__builtins__':{},'range':range,'str':str},{})

def component_policy(path):
    if path=='usr/lib/appFw.so':return 'existing_fixed_ap'
    if path=='cpapp-b.bin':return 'existing_fixed_cp'
    if re.fullmatch(r'usr/share/app/string_[a-z]+_(horizontal|vertical)\.uxc',path):return 'existing_string'
    if re.fullmatch(r'usr/share/app/image_00_(23|32)_IPSX\.uxc',path):return 'required_icon_dat_tool_gap'
    raise ValueError('未授权继承资源或新增组件：'+path)
