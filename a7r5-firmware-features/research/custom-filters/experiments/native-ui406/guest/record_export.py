"""严格重组固定五文件；CRC之后仅额外接收256字节规范AFD1墓碑。"""
from pathlib import Path
import hashlib,json,re,struct,sys,zlib
NAMES=('STORE.ID','C07_A.rec','C07_B.rec','C20_A.rec','C20_B.rec')
ROOT='/tmp/a7r5-custom-filters-lab/A7LOOKS1'
MAX=262495
def parse(text):
    if len(text)>4*1024*1024:raise ValueError('导出日志超预算')
    lines=[s for s in text.splitlines() if s.startswith('AF_EXPORT_')]
    if not lines or lines[0]!='AF_EXPORT_BEGIN v=1 files=5 root='+ROOT:raise ValueError('缺少唯一导出开始锚点')
    results={};active=None;data=bytearray();expected=0;done=False
    for line in lines[1:]:
        if done:raise ValueError('结束锚点后又有导出内容')
        m=re.fullmatch(r'AF_EXPORT_FILE name=(\S+) bytes=([0-9]+)',line)
        if m:
            name,n=m[1],int(m[2])
            if active is not None or len(results)>=5 or name!=NAMES[len(results)] or not 0<n<=MAX:raise ValueError('文件顺序/长度不符')
            active=name;expected=n;data=bytearray();continue
        m=re.fullmatch(r'AF_EXPORT_HEX offset=([0-9a-f]{8}) data=([0-9a-f]+)',line)
        if m:
            if active is None or int(m[1],16)!=len(data) or len(m[2])!=2*min(64,expected-len(data)):raise ValueError('HEX偏移/长度不符')
            data.extend(bytes.fromhex(m[2]));continue
        m=re.fullmatch(r'AF_EXPORT_END name=(\S+) bytes=([0-9]+)',line)
        if m:
            if active is None or m[1]!=active or int(m[2])!=expected or len(data)!=expected:raise ValueError('文件未完整结束')
            results[active]=bytes(data);active=None;continue
        if line=='AF_EXPORT_ABSENT name=C20_B.rec required=0':
            if active is not None or len(results)!=4:raise ValueError('ABSENT顺序不符')
            results['C20_B.rec']=None;continue
        m=re.fullmatch(r'AF_EXPORT_DONE files=5 present=([0-9]+) bytes=([0-9]+) status=0',line)
        if m:
            if active is not None or tuple(results)!=NAMES or int(m[1])!=sum(v is not None for v in results.values()) or int(m[2])!=sum(len(v) for v in results.values() if v is not None):raise ValueError('总结束计数不符')
            done=True;continue
        raise ValueError('错误或未知导出行：'+line[:100])
    if not done:raise ValueError('缺少完整成功锚点')
    return results
def preset(p):
    if len(p)!=74 or p[0] not in (*range(10),17,18) or p[1] or any(p[10:]):raise ValueError('不是有效纯参数预设')
    values=list(struct.unpack('8b',p[2:10]));limits=((-9,9),(-9,9),(-9,9),(0,9),(-9,9),(0,9),(1,5),(0,9))
    if any(not low<=v<=high for v,(low,high) in zip(values,limits)):raise ValueError('预设参数越界')
    return dict(base=p[0],kind=0,parameters=values)
def decode(name,raw):
    if raw is None:return dict(absent=True)
    result=dict(bytes=len(raw),sha256=hashlib.sha256(raw).hexdigest())
    if name=='STORE.ID':
        wanted=bytearray(96);wanted[:8]=b'A7STORE1';struct.pack_into('<4I',wanted,8,1,262463,0,20)
        wanted[24:56]=bytes.fromhex('3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2')
        if raw!=wanted:raise ValueError('STORE.ID不是当前96B marker')
        result['marker_verified']=True;return result
    slot=int(name[1:3]);header=bytearray(raw[:32]);payload=raw[32:]
    if len(raw)<32 or header[:8]!=b'A7F1\1\0'+bytes([slot,0]) or any(header[28:32]):raise ValueError('记录头无效')
    generation,size,crc,headcrc=struct.unpack_from('<QIII',header,8);header[24:28]=b'\0'*4
    if not generation or size!=len(payload) or zlib.crc32(payload)!=crc or zlib.crc32(header)!=headcrc:raise ValueError('记录长度/CRC/代号无效')
    # 墓碑仍有完整记录头和CRC；不把空文件或非规范present=0当空槽。
    if len(payload)==256 and payload[:8]==b'AFD1\1\0\0\1' and not any(payload[8:]):
        result.update(slot=slot,generation=generation,tombstone=True,crc_verified=True)
        return result
    if len(payload)<256 or payload[:8]!=b'AFD1\1\0\0\1' or any(payload[8:16]) or any(payload[20:88]) or any(payload[240:256]) or struct.unpack_from('<I',payload,236)[0]!=1:raise ValueError('不是当前纯参数AFD1文档')
    length=struct.unpack_from('<I',payload,16)[0]
    if not 1<=length<=63 or length!=len(payload)-256:raise ValueError('名称长度不符')
    text=payload[256:].decode('utf-8',errors='strict')
    if any(ord(c)<32 or ord(c)==127 for c in text):raise ValueError('名称控制字符')
    result.update(slot=slot,generation=generation,name=text,initial=preset(payload[88:162]),saved=preset(payload[162:236]),crc_verified=True)
    return result
def verify(text):
    raw=parse(text);return raw,{name:decode(name,data) for name,data in raw.items()}
if __name__=='__main__':
    if len(sys.argv)!=3:raise SystemExit('用法：parse_export.py helper-command.log 新输出目录')
    source=Path(sys.argv[1]);raw,report=verify(source.read_bytes().decode('utf-8',errors='replace'))
    out=Path(sys.argv[2]);out.mkdir(mode=0o700)
    for name,data in raw.items():
        if data is not None:
            with (out/name).open('xb') as f:f.write(data)
    result=dict(status='PASS',source_log=str(source),source_log_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),files=report,missing_records_reconstructed=False)
    with (out/'records.json').open('x') as f:json.dump(result,f,ensure_ascii=False,indent=2)
    print(json.dumps(result,ensure_ascii=False,indent=2))
