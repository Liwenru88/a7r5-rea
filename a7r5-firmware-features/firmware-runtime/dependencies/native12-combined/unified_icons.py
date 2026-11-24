"""十二款滤镜的独立图形编号；复用已研究的UXD布局，不接入32槽后端，不生成菜单帧。"""
import hashlib
import struct

COUNT=7844
FIRST=0x02001ea4
ADDED=24
HEADER=bytes.fromhex('757864070000000008000000')
SOURCES={
    'usr/share/app/image_00_23_IPSX.uxc':'80637a7bb69ccf2ddc6308a148847d1f14a88aa2001e4fc7de04b3e4c83ef061',
    'usr/share/app/image_00_32_IPSX.uxc':'d5ec718d642fa8b813cf05c45bb0bc53f68b9bc4152fe003f01cdc39efc8a9db',
}
# 自主定义的5×7编号字形，只用于新滤镜编号，不复刻原厂风格图标。
GLYPHS={
    'F':('11111','10000','10000','11110','10000','10000','10000'),
    '0':('01110','10001','10011','10101','11001','10001','01110'),
    '1':('00100','01100','00100','00100','00100','00100','01110'),
    '2':('01110','10001','00001','00010','00100','01000','11111'),
    '3':('11110','00001','00001','01110','00001','00001','11110'),
    '4':('00010','00110','01010','10010','11111','00010','00010'),
    '5':('11111','10000','10000','11110','00001','00001','11110'),
    '6':('01110','10000','10000','11110','10001','10001','01110'),
    '7':('11111','00001','00010','00100','01000','01000','01000'),
    '8':('01110','10001','10001','01110','10001','10001','01110'),
    '9':('01110','10001','10001','01111','00001','00001','01110'),
}


def icon_pixels(slot,selected=False):
    if slot not in range(1,13):raise ValueError('仅生成F01～F12编号')
    width,height,stride=70,35,80
    pixels=bytearray(stride*height*2)
    def white(x,y):struct.pack_into('<H',pixels,(y*stride+x)*2,65535)
    for x in range(3,67):white(x,2);white(x,32)
    for y in range(2,33):white(3,y);white(66,y)
    for character,glyph in enumerate(f'F{slot:02d}'):
        for y,row in enumerate(GLYPHS[glyph]):
            for x,value in enumerate(row):
                if value=='1':
                    for dy in range(3):
                        for dx in range(3):white(9+character*18+x*3+dx,7+y*3+dy)
    if selected:
        for y in range(3,32):
            for x in range(4,66):
                at=(y*stride+x)*2
                value=struct.unpack_from('<H',pixels,at)[0]
                struct.pack_into('<H',pixels,at,0 if value else 65535)
    return bytes(pixels)


def literal_stream(pixels):
    if not pixels or len(pixels)>65535:raise ValueError('原生文字图标载荷越界')
    # Sony LZ77的0x0f原样块；实际解压仍由原资源消费路径执行。
    return b'\x0f\x00'+struct.pack('<H',len(pixels))+pixels


def payload_fields(raw,at,flags):
    # 原libObj以record+4为相对基准；复杂图像先越过两组8字节切片描述。
    field=12
    if flags&0x08000000:
        if at+40>len(raw) or struct.unpack_from('<I',raw,at+12)[0]!=0x10002:
            raise ValueError('未验证或截断的复杂图像记录')
        field=32
    size,offset=struct.unpack_from('<II',raw,at+field)
    return field,size,offset


def layout(raw):
    if len(raw)<16 or raw[:12]!=HEADER or len(raw)>16*1024*1024:raise ValueError('UXD头或预算不符')
    packed=struct.unpack_from('<I',raw,12)[0];count=packed&8191
    if count not in (COUNT,COUNT+ADDED) or packed!=count|(count<<12):raise ValueError('UXD计数前像不符')
    base=(16+count*2+3)&~3
    records={};bitmap=[]
    for i in range(count):
        pointer=struct.unpack_from('<H',raw,16+i*2)[0]
        if pointer==65535:continue
        at=base+pointer*4
        if at+20>len(raw):raise ValueError('UXD记录越界')
        tag,flags,shape,size,offset=struct.unpack_from('<5I',raw,at)
        if tag!=0x1a000000|i or flags not in (0x40000000,0xc0000000,0x48000000,0xc8000000):
            raise ValueError('UXD位图身份或类型不符')
        records[i]=(at,flags,shape,size,offset)
        field,payload_size,payload_offset=payload_fields(raw,at,flags)
        target=at+4+payload_offset
        if not payload_size or target+payload_size>len(raw):raise ValueError('UXD像素载荷越界')
        bitmap.append((i,target,payload_size))
    if not bitmap or len({r[0] for r in records.values()})!=len(records):raise ValueError('UXD空表或记录别名')
    boundary=min(target for _,target,_ in bitmap)
    if any(at+(40 if flags&0x08000000 else 20)>boundary for at,flags,*_ in records.values()):
        raise ValueError('UXD记录与像素区域重叠')
    return count,base,boundary,records,bitmap


def append_icons(raw):
    count,base,boundary,records,bitmap=layout(raw)
    if count!=COUNT or len(raw)%4:raise ValueError('需要当前原图标资源前像')
    table_growth=ADDED*2;record_growth=ADDED*20
    new_base=base+table_growth;new_boundary=boundary+table_growth
    candidate=bytearray(raw[:base]+bytes(table_growth)+raw[base:boundary]+bytes(record_growth)+raw[boundary:])
    new_count=count+ADDED
    struct.pack_into('<I',candidate,12,new_count|(new_count<<12))
    for i,_,_ in bitmap:
        at,flags,*_=records[i]
        field,_,offset=payload_fields(raw,at,flags)
        struct.pack_into('<I',candidate,at+table_growth+field+4,offset+record_growth)
    new=[]
    for i in range(ADDED):
        at=new_boundary+i*20;pointer=(at-new_base)//4
        if pointer>=65535:raise ValueError('UXD新增图标记录指针溢出')
        struct.pack_into('<H',candidate,16+(count+i)*2,pointer)
        slot=i//2+1;selected=bool(i&1)
        pixels=icon_pixels(slot,selected);stream=literal_stream(pixels)
        offset=len(candidate)-at-4
        struct.pack_into('<5I',candidate,at,0x1a000000|count+i,0xc0000000,35<<16|70,len(stream),offset)
        candidate.extend(stream)
        new.append({'resource':hex(FIRST+i),'label':f'F{slot:02d}','selected':selected,'pixel_sha256':hashlib.sha256(pixels).hexdigest()})
    candidate=bytes(candidate)
    _,_,_,after,after_bitmap=layout(candidate)
    for i,(at,flags,shape,size,offset) in records.items():
        aat,aflags,ashape,asize,aoffset=after[i]
        if (aat,aflags,ashape,asize)!=(at+table_growth,flags,shape,size):raise ValueError('原图标属性变化')
        if aoffset!=offset+(record_growth if not flags&0x08000000 else 0):raise ValueError('原图标相对载荷变化')
    for i,target,size in bitmap:
        at,flags,*_=after[i]
        _,_,offset=payload_fields(candidate,at,flags)
        if candidate[at+4+offset:at+4+offset+size]!=raw[target:target+size]:raise ValueError('原图标像素载荷变化')
    inverse=bytearray(candidate[:base]+candidate[new_base:new_boundary]+candidate[new_boundary+record_growth:len(raw)+table_growth+record_growth])
    struct.pack_into('<I',inverse,12,count|(count<<12))
    for i,_,_ in bitmap:
        at,flags,*_=records[i];field,_,offset=payload_fields(raw,at,flags)
        struct.pack_into('<I',inverse,at+field+4,offset)
    if inverse!=raw:raise ValueError('原图标资源无法精确反向重建')
    return candidate,{'source_sha256':hashlib.sha256(raw).hexdigest(),
        'candidate_sha256':hashlib.sha256(candidate).hexdigest(),'before_count':count,'after_count':new_count,
        'old_records_preserved':len(records),
        'old_bitmap_payloads_identical':sum(not row[1]&0x08000000 for row in records.values()),
        'old_complex_payloads_identical':sum(bool(row[1]&0x08000000) for row in records.values()),
        'new_icons':new,'inverse_exact':True,'research_candidate_only':True,'menu_frame_generated':False}
