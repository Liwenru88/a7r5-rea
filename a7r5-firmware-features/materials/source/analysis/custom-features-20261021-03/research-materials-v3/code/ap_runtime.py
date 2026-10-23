"""R5 六个 ST 槽位选择和显示名；不写个人 Backup，也没有设备入口。"""
import hashlib
import struct
import io

from assembler import assemble

SOURCE_SHA = '8ee4d5876b7e127df39f8f820b9d21834c300ff895e02ca522636ed4733efc4b'
ENTRY, END, TITLE = 0x3550354, 0x35503d8, 0x500fbc0
MAP, GETTER, SLOT_ID = 0x4b724d0, 0x1bc78a4, 0x858
NAME_HOOK=GETTER+4
NAME_DATA,NAME_BYTES=TITLE,80
LABEL = 0x0200abd8
NAMES = ('Classic Neg.', 'Classic Chrome', 'Nostalgic Neg.', 'Eterna', 'GR Positive Film', 'GR Negative Film')
NATIVE_MAP = bytes([0,3,2,1,16,15,17,18,5,13,19,20])


def build(source):
    if hashlib.sha256(source).hexdigest() != SOURCE_SHA:
        raise ValueError('AP 完整前像不符')
    converter = assemble(['cmp w0,#16', 'b.eq special', 'cbnz w1,legacy',
        'sub w0,w0,#10', 'cmp w0,#5', 'b.hi legacy', 'mov w3,#63',
        'lsr w3,w3,w0', 'tbz w3,#0,legacy', 'add w0,w0,#249', 'b store',
        'legacy:', 'cmp w1,#11', f'b.hi 0x{END:x}', f'adrp x0,0x{MAP & ~4095:x}',
        f'add x0,x0,#{MAP & 4095}', 'ldrb w0,[x0,w1,uxtw]',
        'store:', 'strb w0,[x2]', 'ret', 'special:', 'mov w0,#-1','b store'], ENTRY, 'aarch64')
    # 运行追踪及 _f 资源确认：8d0 返回基础风格，3e18840 映射其显示文字。
    # 保留原虚调用；仅六个已选 ST 槽位返回新资源，其余仍读原生表。
    title = assemble(['mov x29,sp','stp x19,x20,[sp,#-16]!','mov w19,w1',
        'ldr x2,[x0]','ldr x2,[x2,#0x8d0]','blr x2','cbnz w0,native',
        f'sub w19,w19,#{SLOT_ID}','cmp w19,#5','b.hi native',
        f'mov w0,#{LABEL & 65535}','movk w0,#0x200,lsl#16','add w0,w0,w19','b done',
        'native:','adrp x1,0x5936000','ldr x1,[x1,#0x18]','ldr w0,[x1,w0,sxtw#2]',
        'done:','ldp x19,x20,[sp],#16','ldp x29,x30,[sp],#16','ret'],TITLE,'aarch64')
    if len(converter) != 80 or len(title)!=NAME_BYTES or len(converter)>END-ENTRY:
        raise ValueError('AP 原有函数范围不足')
    patches = []
    target = bytearray(source)

    def put(at, raw, purpose):
        if at<0 or at+len(raw)>len(source) or any(max(at,p['offset'])<min(at+len(raw),p['offset']+p['bytes']) for p in patches):
            raise ValueError('AP 修改越界或重叠')
        patches.append({'offset':at, 'before':source[at:at+len(raw)].hex(),
                        'after':raw.hex(), 'bytes':len(raw), 'purpose':purpose})
        target[at:at+len(raw)] = raw

    if source[MAP:MAP+12] != bytes.fromhex('1200020406080a0c0e100000'):
        raise ValueError('原转换函数专用跳表前像不符')
    if source[NAME_HOOK:NAME_HOOK+4]!=assemble(['mov x29,sp'],NAME_HOOK,'aarch64'):
        raise ValueError('原生显示文字 getter 前像不符')
    # 只在既有 RX 段末页扩展专用辅助代码，不增加映射页或碰 RW/BSS。
    from elftools.elf.elffile import ELFFile
    import numpy as np
    elf=ELFFile(io.BytesIO(source))
    segments=list(elf.iter_segments())
    selected=[(i,s) for i,s in enumerate(segments) if s['p_type']=='PT_LOAD' and s['p_flags']==5 and s['p_offset']==0]
    if len(selected)!=1:raise ValueError('AP RX 段身份不符')
    index,rx=selected[0];end=NAME_DATA+NAME_BYTES
    if (rx['p_filesz'],rx['p_memsz'])!=(0x500fbb7,0x500fbb7) or any(source[rx['p_filesz']:end]):
        raise ValueError('AP RX 尾部前像或零填充不符')
    if (rx['p_filesz']+4095)//4096!=(end+4095)//4096:raise ValueError('名称常量会增加 RX 映射页')
    for section in elf.iter_sections():
        if section['sh_size'] and section['sh_type']!='SHT_NOBITS' and max(NAME_DATA,section['sh_offset'])<min(end,section['sh_offset']+section['sh_size']):
            raise ValueError('名称区域与现有 section 重叠')
        if section['sh_type']=='SHT_RELA':
            records=np.frombuffer(section.data(),dtype='<u8').reshape(-1,3)
            if np.any((records[:,0]>=NAME_DATA)&(records[:,0]<end)) or np.any((records[:,2]>=NAME_DATA)&(records[:,2]<end)):
                raise ValueError('名称区域已有重定位引用')
    put(ENTRY, converter, '原函数范围内容纳六槽选择，保留原诊断尾部')
    put(MAP, NATIVE_MAP, '复用该转换函数已经弃用的专用跳表，保留十二款原生映射')
    put(NAME_HOOK,assemble([f'b 0x{TITLE:x}'],NAME_HOOK,'aarch64'),'拦截实测的 Creative Look 显示文字 getter')
    put(NAME_DATA,title,'保留原虚调用、非 ST 及非自定义槽位的原生文字')
    for field in (32,40):
        put(elf['e_phoff']+index*elf['e_phentsize']+field,struct.pack('<Q',end),'扩展既有 RX 文件尾常量范围，映射页不增加')
    for slot in range(6):
        at = 0x3f4a888 + slot*0x80
        if struct.unpack_from('<2I', source, at-8) != (SLOT_ID+slot, SLOT_ID+slot) or struct.unpack_from('<I',source,at)[0] != 0x200a302:
            raise ValueError('R5 自定义槽位登记前像不符')
        put(at, struct.pack('<I',LABEL+slot), '自定义槽位登记名称')
    inverse = bytearray(target)
    for p in patches:
        inverse[p['offset']:p['offset']+p['bytes']] = bytes.fromhex(p['before'])
    if inverse != source:
        raise ValueError('AP 反向重建失败')
    return bytes(target), {'source_sha256':SOURCE_SHA, 'target_sha256':hashlib.sha256(target).hexdigest(),
        'patches':patches, 'inverse_exact':True, 'file_size_unchanged':len(source)==len(target),
        'slot_ids':list(range(SLOT_ID,SLOT_ID+6)), 'markers':list(range(249,255)),
        'labels':list(range(LABEL,LABEL+6)), 'names':NAMES,
        'settings_policy':'用户明确选择基于 ST 的自定义槽位；包内不覆盖个人保存设置',
        'name_path':'native getter 1bc78a4 -> original 8d0 virtual base -> _f text table; ST slots only',
        'name_helper':{'offset':NAME_DATA,'bytes':NAME_BYTES,'rx_before_end':rx['p_filesz'],'rx_after_end':end,'mapped_pages_unchanged':True,'section_or_relocation_overlap':False},
        'physical_hardware_verified':False}
