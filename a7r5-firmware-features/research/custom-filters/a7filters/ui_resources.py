"""默认名称资源仅在内存构造夹具；无固件、归档或资源文件写入接口。"""
import hashlib
import struct

HEADER = bytes.fromhex('757863070000000008000500')


def decode(raw):
    if len(raw)<16 or raw[:12]!=HEADER or len(raw)>16+8192+4*65535:
        raise ValueError('UXC-v7资源头或长度不符')
    packed=struct.unpack_from('<I',raw,12)[0]
    count=packed&4095
    if not count or packed!=count|(count<<12):
        raise ValueError('UXC资源计数副本不一致')
    base=(16+count*2+3)&~3
    if base>len(raw):raise ValueError('UXC指针表被截断')
    entries={}
    for index in range(count):
        pointer=struct.unpack_from('<H',raw,16+index*2)[0]
        if pointer==65535:continue
        at=base+pointer*4
        if at+4>len(raw):raise ValueError('UXC记录指针越界')
        label=0x0200a000+index
        if struct.unpack_from('<I',raw,at)[0] != 0x1e000000|(label&0xffffff):
            raise ValueError('UXC记录身份不符')
        end=raw.find(b'\0',at+4)
        if end<0:raise ValueError('UXC文本未终止')
        try:text=raw[at+4:end].decode('utf-8')
        except UnicodeDecodeError as error:raise ValueError('UXC文本不是合法UTF-8') from error
        entries[label]=dict(pointer=pointer,text=text)
    return dict(count=count,data_base=base,entries=entries)


def append_name_fixture(raw):
    before=decode(raw)
    if before['count']!=3038 or before['data_base']!=6092:
        raise ValueError('需要当前4.06的3038项名称前像')
    if any(0x0200abd8+i not in before['entries'] for i in range(6)):
        raise ValueError('当前六款名称缺失')
    base=before['data_base']
    candidate=bytearray(raw[:base]+b'\0'*28+raw[base:])
    new_base=base+28
    count=3052
    struct.pack_into('<I',candidate,12,count|(count<<12))
    for i in range(14):
        pointer=(len(candidate)-new_base)//4
        if pointer>=65535 or len(candidate)%4:
            raise ValueError('新增UXC记录指针溢出或未对齐')
        struct.pack_into('<H',candidate,16+2*(3038+i),pointer)
        label=0x0200abde+i
        candidate.extend(struct.pack('<I',0x1e000000|(label&0xffffff))+f'C{i+7:02d}'.encode()+b'\0')
    candidate=bytes(candidate)
    after=decode(candidate)
    if any(after['entries'][key]!=value for key,value in before['entries'].items()):
        raise ValueError('原UXC记录发生变化')
    inverse=bytearray(candidate[:base]+candidate[new_base:len(raw)+28])
    inverse[12:16]=raw[12:16]
    if inverse!=raw:raise ValueError('UXC反向重建不符')
    return candidate,dict(source_sha256=hashlib.sha256(raw).hexdigest(),
                          candidate_sha256=hashlib.sha256(candidate).hexdigest(),
                          before_bytes=len(raw),after_bytes=len(candidate),
                          before_count=3038,after_count=3052,
                          old_entries_unchanged=len(before['entries']),inverse_exact=True,
                          new_names=[dict(resource=hex(0x0200abde+i),text=f'C{i+7:02d}') for i in range(14)],
                          fixture_only=True,resource_file_written=False)
