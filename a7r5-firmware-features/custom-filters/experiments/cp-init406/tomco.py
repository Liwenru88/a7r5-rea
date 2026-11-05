"""读取同源CPIO的原TOMCO；不修改看门狗或启动组。"""
import hashlib
from pathlib import Path

CPIO_SHA='c01948220e1cced7f4e1d6a6dd28221c587050214d32cc405291cc00d2f1ed80'
TOMCO_SHA='524bb8c841f29e609e7606d56e6d393023afa8e0d3f61acbce7f957572323115'


def load(path):
    path=Path(path)
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        while chunk:=stream.read(1024*1024):digest.update(chunk)
    if digest.hexdigest()!=CPIO_SHA:raise ValueError('TOMCO的原CPIO身份不符')
    found=None
    with path.open('rb') as stream:
        while True:
            header=stream.read(110)
            if len(header)!=110 or header[:6]!=b'070701':raise ValueError('原CPIO头不符')
            fields=[int(header[6+i*8:14+i*8],16) for i in range(13)]
            size,namesize=fields[6],fields[11]
            if not 1<=namesize<=4096:raise ValueError('原CPIO名称越界')
            name=stream.read(namesize)
            if len(name)!=namesize or name[-1:]!=b'\0':raise ValueError('原CPIO名称截断')
            stream.seek((-110-namesize)%4,1)
            member=name[:-1].decode().removeprefix('./')
            if member=='cp/tomco.txt':
                if found is not None or size!=686:raise ValueError('原TOMCO重复或长度不符')
                found=stream.read(size)
            else:stream.seek(size,1)
            stream.seek((-size)%4,1)
            if member=='TRAILER!!!':break
    if found is None or hashlib.sha256(found).hexdigest()!=TOMCO_SHA:
        raise ValueError('原TOMCO内容身份不符')
    return found
