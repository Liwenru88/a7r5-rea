"""从本次已回读的 AP 派生；不提供机身或设置写入入口。"""
from pathlib import Path
import hashlib
import io
import struct
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SOURCE = ROOT/'analysis/custom-features-20261021-03/research-materials-v3/candidate/appFw.so'
SOURCE_SHA = 'b051590a61cf6fac9f0026601ca431405d9278d6ed3c814cf34f99164b0f3d3a'
ENTRY, END, TITLE = 0x3550354, 0x35503d8, 0x500fbc0
DEFAULTS = 0x4a422f8
sys.path.insert(0,str(ROOT/'analysis/custom-features-20261021-03/research-materials-v3/code'))
from assembler import assemble


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def build(source):
    if sha(source) != SOURCE_SHA:
        raise ValueError('AP完整前像不符')
    from elftools.elf.elffile import ELFFile
    elf=ELFFile(io.BytesIO(source))
    # 只修改原函数、已存在名称助手及初始化常量，不增加段、重定位或映射。
    entry_range=next(s for s in elf.iter_segments() if s['p_type']=='PT_LOAD' and s['p_flags']==5)
    if (entry_range['p_offset'],entry_range['p_vaddr'],entry_range['p_filesz'],entry_range['p_memsz']) != (0,0,0x500fc10,0x500fc10):
        raise ValueError('AP既有RX布局变化')
    code=assemble([
        'cmp w0,#16','b.eq special',
        'cmp w0,#17','b.eq fl2','cmp w0,#18','b.eq fl3',
        'sub w3,w0,#10','cmp w3,#5','b.ls custom',
        'cmp w1,#11',f'b.hi 0x{END:x}',
        'adrp x0,0x4b72000','add x0,x0,#0x4d0','ldrb w0,[x0,w1,uxtw]',
        'store:','strb w0,[x2]','ret',
        'fl2:','mov w0,#19','b store',
        'fl3:','mov w0,#20','b store',
        'custom:','add w0,w3,#249','b store',
        'special:','mov w0,#-1','b store'],ENTRY,'aarch64')
    if len(code)>END-ENTRY or len(code)%4:
        raise ValueError('AP原转换函数空间不足')
    code+=assemble(['nop']*((END-ENTRY-len(code))//4),ENTRY+len(code),'aarch64')
    target=bytearray(source);patches=[]
    def put(at,after,reason):
        before=source[at:at+len(after)]
        if len(before)!=len(after) or before==after:
            raise ValueError('修改范围无效或无变化')
        if any(max(at,p['offset'])<min(at+len(after),p['offset']+p['bytes']) for p in patches):
            raise ValueError('AP修改范围重叠')
        target[at:at+len(after)]=after
        patches.append(dict(offset=at,bytes=len(after),before=before.hex(),after=after.hex(),reason=reason))
    put(ENTRY,code,'六个固定自定义槽及原生FL2/FL3按菜单身份选择；不依赖旧保存基底')
    guard=TITLE+24
    if source[guard:guard+4]!=bytes.fromhex('00010035'):
        raise ValueError('名称基底门槛前像不符')
    put(guard,assemble(['nop'],guard,'aarch64'),'仅移除六个槽的ST名称门槛；保留原虚调用及非目标名称路径')
    defaults=[]
    for index in range(54):
        at=DEFAULTS+index*8
        api,old=struct.unpack_from('<II',source,at)
        if api!=0x163a+index:raise ValueError('AP默认表身份不符')
        slot=index%18
        wanted=0 if 10<=slot<=15 else {16:10,17:11}.get(slot,old)
        if wanted!=old:put(at+4,struct.pack('<I',wanted),'current/still/movie外观默认基础类型')
        defaults.append(dict(property=hex(api),before=old,after=wanted))
    inverse=bytearray(target)
    for p in patches:inverse[p['offset']:p['offset']+p['bytes']]=bytes.fromhex(p['before'])
    if bytes(inverse)!=source:raise ValueError('AP反向全字节还原失败')
    return bytes(target),dict(source_sha256=SOURCE_SHA,target_sha256=sha(target),bytes=len(target),
        patches=patches,defaults=defaults,inverse_exact=True,file_size_unchanged=True,
        changed_bytes=sum(a!=b for a,b in zip(source,target)),ELF_headers_and_relocations_unchanged=True,
        no_new_code_regions=True,persistent_settings_modified=False,full_AP_boot_verified=False,
        policy='八个目标身份固定路由；六个自定义槽不再用基底选择其他原生外观，其他主菜单不变')
