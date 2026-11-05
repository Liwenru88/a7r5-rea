"""严格验证客体只读导出，独立重算记录CRC及载荷SHA；不生成缺失记录。"""
import hashlib
import json
from pathlib import Path
import re
import struct
import zlib

NAMES = ['STORE.ID']+[f'C{i:02d}_{b}.rec' for i in range(1,21) for b in 'AB']


def validate(name, raw):
    result=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    if name=='STORE.ID':
        wanted=bytearray(96);wanted[:8]=b'A7STORE1';struct.pack_into('<4I',wanted,8,1,262463,0,20)
        wanted[24:56]=bytes.fromhex('3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2')
        if raw!=wanted:raise ValueError('仓库标记不符')
        return result
    if name not in NAMES or len(raw)<288:raise ValueError('记录名称／长度不符')
    slot=int(name[1:3]);h=bytearray(raw[:32]);payload=raw[32:]
    if h[:8]!=b'A7F1\x01\0'+bytes([slot,0]) or any(h[28:]):raise ValueError('记录头不符')
    generation,count,crc,headcrc=struct.unpack_from('<QIII',h,8);h[24:28]=bytes(4)
    if not generation or count!=len(payload) or zlib.crc32(payload)!=crc or zlib.crc32(h)!=headcrc:raise ValueError('记录CRC／长度／代号不符')
    if payload[:8]!=b'AFD1\x01\0\0\x01' or any(payload[240:256]):raise ValueError('文档头不符')
    schema,converter,n,image_bytes=struct.unpack_from('<4I',payload,8)
    present=struct.unpack_from('<I',payload,236)[0]
    if present!=1 or not 1<=n<=63 or 256+n+image_bytes!=len(payload):raise ValueError('文档长度／状态不符')
    text=payload[256:256+n].decode('utf-8',errors='strict')
    if any(ord(c)<32 or ord(c)==127 for c in text):raise ValueError('非法名称')
    presets=[]
    for offset in (88,162):
        p=payload[offset:offset+74];values=list(struct.unpack('8b',p[2:10]))
        limits=((-9,9),(-9,9),(-9,9),(0,9),(-9,9),(0,9),(1,5),(0,9))
        if p[0] not in (*range(10),17,18) or p[1]>1 or any(not lo<=v<=hi for v,(lo,hi) in zip(values,limits)):raise ValueError('预设非法')
        presets.append(dict(base=p[0],kind=p[1],parameters=values,payload_sha256=p[10:42].hex(),lut_sha256=p[42:74].hex()))
    if presets[0]['kind']!=presets[1]['kind']:raise ValueError('类型不一致')
    if presets[0]['kind']:
        if schema!=0x314a4641 or converter not in (1,2,3) or image_bytes not in (1943,2483):raise ValueError('未知配方格式')
        image=payload[256+n:]
        if hashlib.sha256(image).hexdigest()!=presets[0]['payload_sha256'] or presets[0]['payload_sha256']!=presets[1]['payload_sha256']:raise ValueError('载荷SHA不符')
    elif schema or converter or image_bytes or any(payload[20:88]) or any(payload[98:162]) or any(payload[172:236]):raise ValueError('纯参数文档含额外载荷')
    result.update(slot=slot,generation=generation,name=text,initial=presets[0],saved=presets[1],schema=schema,converter=converter,image_bytes=image_bytes)
    return result


def export(text, directory):
    if len(text)>8*1024*1024:raise ValueError('导出超预算')
    lines=[line for line in text.splitlines() if line.startswith('AF_STORE_')]
    # 运行器在只读助手结束后记录独立退出码；只接受唯一、末尾的零退出码。
    if lines and lines[-1]=='AF_STORE_RC=0':lines.pop()
    if not lines or lines[0]!='AF_STORE_BEGIN v=1 root=/setting/A7LOOKS1':raise ValueError('缺少开始锚点')
    data={};active=None;buf=bytearray();size=0;done=False
    for line in lines[1:]:
        if done:raise ValueError('结束后存在多余数据')
        if line.startswith('AF_STORE_CHECK '):continue  # 独立校验下面的实际字节，不相信文本自报。
        m=re.fullmatch(r'AF_STORE_FILE name=(\S+) bytes=(\d+)',line)
        if m:
            if active is not None or m[1]!=NAMES[len(data)] or not 0<int(m[2])<=262495:raise ValueError('文件顺序／预算不符')
            active=m[1];size=int(m[2]);buf=bytearray();continue
        m=re.fullmatch(r'AF_STORE_HEX offset=([0-9a-f]{8}) data=([0-9a-f]+)',line)
        if m:
            if active is None or int(m[1],16)!=len(buf) or len(m[2])!=2*min(64,size-len(buf)):raise ValueError('HEX偏移／长度错误')
            buf.extend(bytes.fromhex(m[2]));continue
        m=re.fullmatch(r'AF_STORE_END name=(\S+) bytes=(\d+)',line)
        if m:
            if m[1]!=active or int(m[2])!=size or len(buf)!=size:raise ValueError('文件未完整结束')
            data[active]=bytes(buf);active=None;continue
        m=re.fullmatch(r'AF_STORE_ABSENT name=(\S+)',line)
        if m:
            if active is not None or m[1]!=NAMES[len(data)] or not len(data):raise ValueError('缺失文件顺序错误')
            data[m[1]]=None;continue
        m=re.fullmatch(r'AF_STORE_DONE files=(\d+) bytes=(\d+) status=0',line)
        if m:
            present=[v for v in data.values() if v is not None]
            if active is not None or list(data)!=NAMES or int(m[1])!=len(present) or int(m[2])!=sum(map(len,present)):raise ValueError('总计不符')
            done=True;continue
        raise ValueError('未知导出行')
    if not done:raise ValueError('缺少完整结束锚点')
    checked={name:validate(name,raw) for name,raw in data.items() if raw is not None}
    directory=Path(directory);directory.mkdir(exist_ok=False)
    for name,raw in data.items():
        if raw is not None:(directory/name).write_bytes(raw)
    report=dict(status='PASS_READONLY_STORE_EXPORT',files=checked,absent=[n for n,v in data.items() if v is None])
    (directory/'records.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    return report
