"""固定合成FAT16库；写入VFAT中文长名，不读取任何设备或用户照片。"""
import struct

NAMES=('暖光.cube','电脑参数.a7filter','a'*59+'暖光影.cube')
CUBE=b'LUT_3D_SIZE 2\n'+b''.join(f'{r} {g} {b}\n'.encode() for b in range(2) for g in range(2) for r in range(2))


def payloads():
    name='电脑参数示例'.encode();d=bytearray(256+len(name));d[:8]=b'AFD1\x01\0\0\x01'
    struct.pack_into('<I',d,16,len(name));struct.pack_into('<I',d,236,1)
    preset=bytes(2)+struct.pack('8b',1,2,0,0,0,4,3,1)+bytes(64)
    d[88:162]=preset;d[162:236]=preset;d[256:]=name
    return dict(zip(NAMES,(CUBE,bytes(d),CUBE)))


def make_library(make_fixture):
    raw=bytearray(make_fixture());next_cluster=3
    def allocate(data):
        nonlocal next_cluster
        count=max(1,(len(data)+511)//512);first=next_cluster;assert first+count<=8097
        for i in range(count):
            value=first+i+1 if i+1<count else 65535
            for at in (512,33*512):struct.pack_into('<H',raw,at+(first+i)*2,value)
        start=(97+first-2)*512;raw[start:start+len(data)]=data;next_cluster+=count;return first
    def short(name,cluster,directory=False,size=0):
        assert len(name)==11
        e=bytearray(32);e[:11]=name;e[11]=0x10 if directory else 0x20
        struct.pack_into('<H',e,24,0x21);struct.pack_into('<HI',e,26,cluster,size);return bytes(e)
    def long(name,alias):
        checksum=0
        for b in alias:checksum=(((checksum&1)<<7)+(checksum>>1)+b)&255
        units=name.encode('utf-16le')+b'\0\0';units+=b'\xff\xff'*((-len(units)//2)%13)
        count=len(units)//26;result=b''
        for i in range(count,0,-1):
            e=bytearray(32);e[0]=i|(0x40 if i==count else 0);e[11]=15;e[13]=checksum
            part=units[(i-1)*26:i*26];e[1:11]=part[:10];e[14:26]=part[10:22];e[28:32]=part[22:];result+=bytes(e)
        return result
    dirs=[allocate(bytes(1024)) for _ in range(4)]
    raw[65*512+32:65*512+64]=short(b'PRIVATE    ',dirs[0],True)
    for index,first in enumerate(dirs):
        parent=dirs[index-1] if index else 0
        body=short(b'.          ',first,True)+short(b'..         ',parent,True)
        if index<3:body+=short((('SONY','PRO','LUT')[index]).ljust(11).encode(),dirs[index+1],True)
        else:
            for j,(name,data) in enumerate(payloads().items(),1):
                alias=f'AF{j:06d}'.encode()+b'BIN';body+=long(name,alias)+short(alias,allocate(data),False,len(data))
        assert len(body)<1024;start=(97+first-2)*512;raw[start:start+len(body)]=body
    return bytes(raw)
