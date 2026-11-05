"""限定 4 MiB FAT16 普通文件夹具与独立读取；不接受设备路径。"""
import struct

SIZE = 0x400000
MARKER = b'A7R5 virtual media fixture; not camera capture\r\n'


def photo_payloads():
    """生成明确注明虚拟来源的两张 DCF JPEG，不读取用户照片。"""
    import io
    from PIL import Image, ImageDraw
    result={}
    for index in (1,2):
        image=Image.new('RGB',(1280,960),'#202632');draw=ImageDraw.Draw(image)
        colors=['#ff4040','#40ff40','#4080ff','#ffff40','#ff40ff','#40ffff']
        for i,color in enumerate(colors):draw.rectangle((i*213,180,(i+1)*213,740),fill=colors[(i+index-1)%6])
        draw.text((40,60),f'A7R5 VIRTUAL TEST IMAGE {index} - NOT CAMERA CAPTURE',fill='white',font_size=32)
        draw.text((40,810),'1280 x 960 / isolated FAT file backend',fill='white',font_size=30)
        exif=Image.Exif();exif[271]='SONY';exif[272]='ILCE-7RM5';exif[274]=1
        exif[305]='A7R5 virtual input';exif[306]='2022:01:01 12:00:00'
        stream=io.BytesIO();image.save(stream,'JPEG',quality=90,exif=exif)
        result[f'/DCIM/100MSDCF/DSC0000{index}.JPG']=stream.getvalue()
    return result


def make_fixture(photos=False):
    raw = bytearray(SIZE)
    raw[:3] = b'\xeb\x3c\x90'
    raw[3:11] = b'A7R5SIM '
    struct.pack_into('<HBHBHHBHHHII', raw, 11, 512, 1, 1, 2, 512, SIZE//512,
                     0xf8, 32, 32, 64, 0, 0)
    struct.pack_into('<BBBI', raw, 36, 0x80, 0, 0x29, 0xA7F50001)
    raw[43:54] = b'NO NAME    '
    raw[54:62] = b'FAT16   '
    raw[510:512] = b'\x55\xaa'
    for off in (512, 33*512):
        struct.pack_into('<HHH', raw, off, 0xfff8, 0xffff, 0xffff)
    off = 65*512
    raw[off:off+11] = b'SEED    TXT'
    raw[off+11] = 0x20
    struct.pack_into('<H', raw, off+24, 0x21)
    struct.pack_into('<HI', raw, off+26, 2, len(MARKER))
    raw[97*512:97*512+len(MARKER)] = MARKER
    if photos:
        next_cluster=3
        def allocate(data):
            nonlocal next_cluster
            count=max(1,(len(data)+511)//512);first=next_cluster
            if first+count>8097:raise ValueError('虚拟 FAT 夹具超出容量')
            for j in range(count):
                value=first+j+1 if j+1<count else 0xffff
                for fat_start in (512,33*512):struct.pack_into('<H',raw,fat_start+(first+j)*2,value)
            start=(97+first-2)*512;raw[start:start+len(data)]=data
            next_cluster+=count;return first
        def dir_entry(name,first,size=0,is_dir=False):
            data=bytearray(32);stem,_,ext=name.partition('.')
            if name in ('.','..'):stem=name;ext=''
            data[:11]=(stem.ljust(8)+ext.ljust(3)).encode();data[11]=0x10 if is_dir else 0x20
            struct.pack_into('<H',data,24,0x21);struct.pack_into('<HI',data,26,first,size);return data
        dcim=allocate(bytes(512));album=allocate(bytes(512))
        raw[65*512+32:65*512+64]=dir_entry('DCIM',dcim,is_dir=True)
        def directory(first,parent,children):
            data=dir_entry('.',first,is_dir=True)+dir_entry('..',parent,is_dir=True)+b''.join(children)
            start=(97+first-2)*512;raw[start:start+len(data)]=data
        directory(dcim,0,[dir_entry('100MSDCF',album,is_dir=True)])
        photo_entries=[]
        for name,data in photo_payloads().items():photo_entries.append(dir_entry(name.rsplit('/',1)[1],allocate(data),len(data)))
        directory(album,dcim,photo_entries)
    return bytes(raw)


def read_files(raw):
    """独立检查 FAT 镜像的边界、双表、环及文件长度，再取出普通文件。"""
    if len(raw) != SIZE or raw[510:512] != b'\x55\xaa':
        raise ValueError('FAT 长度或签名不符')
    sector, cluster, reserved, copies, roots, total, _, fats = struct.unpack_from('<HBHBHHBH', raw, 11)
    if (sector, cluster, reserved, copies, roots, total, fats) != (512,1,1,2,512,8192,32):
        raise ValueError('非约定 FAT16 布局')
    fat = raw[sector:33*sector]
    if fat != raw[33*sector:65*sector]:raise ValueError('两份 FAT 不一致')
    result = {}; owners = set()
    def chain(first):
        seen = set(); out = bytearray(); current = first
        while current < 0xfff8:
            if current < 2 or current >= 8097 or current in seen or current in owners:
                raise ValueError('FAT 越界、环或交叉链')
            seen.add(current); owners.add(current)
            start = (97+current-2)*512
            out += raw[start:start+512]
            current = struct.unpack_from('<H', fat, current*2)[0]
        return bytes(out)
    def directory(data, parent, depth=0):
        if depth > 8:raise ValueError('目录递归超限')
        for off in range(0,len(data),32):
            entry=data[off:off+32]
            if entry[0]==0:break
            if entry[0]==0xe5 or entry[11]==0xf or entry[11]&8:continue
            stem=entry[:8].decode('ascii').rstrip();ext=entry[8:11].decode('ascii').rstrip()
            if stem in ('.','..'):continue
            name=stem+('.'+ext if ext else '')
            if '/' in name or not stem:raise ValueError('FAT 名称不符')
            path=parent+'/'+name
            if path in result:raise ValueError('FAT 重名')
            first=struct.unpack_from('<H',entry,26)[0];size=struct.unpack_from('<I',entry,28)[0]
            contents=chain(first) if first else b''
            if entry[11]&0x10:directory(contents,path,depth+1)
            else:
                if len(contents)<size or len(contents)>=size+512:raise ValueError('文件长度与簇链不符')
                result[path]=contents[:size]
    directory(raw[65*512:97*512],'')
    return result
