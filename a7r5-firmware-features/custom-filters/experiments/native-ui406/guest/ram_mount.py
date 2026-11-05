"""只识别本实验固定16MiB tmpfs；不提供任意路径或挂载命令。"""
import re

STORE_PATH='/tmp/a7r5-custom-filters-lab'

def private_tmpfs(raw:bytes,mode:str)->dict:
    if mode not in ('ro','rw'):raise ValueError('未知RAM挂载模式')
    rows=[line.split() for line in raw.splitlines() if len(line.split())>=2 and line.split()[1]==STORE_PATH.encode()]
    if len(rows)!=1:raise ValueError('私有RAM挂载记录缺失或重复')
    row=rows[0]
    if len(row)!=6 or row[0]!=b'tmpfs' or row[2]!=b'tmpfs' or row[4:]!=[b'0',b'0']:
        raise ValueError('存储父目录不是已验证的tmpfs')
    options=row[3].decode('ascii').split(',')
    if mode not in options or ('rw' if mode=='ro' else 'ro') in options:raise ValueError('私有RAM模式不匹配')
    sizes=[x[5:] for x in options if x.startswith('size=')]
    match=re.fullmatch(r'(\d+)([kmg]?)',sizes[0]) if len(sizes)==1 else None
    if not match:raise ValueError('私有RAM容量未知')
    capacity=int(match[1])*(1024**({'':0,'k':1,'m':2,'g':3}[match[2]]))
    if capacity!=16*1024*1024:raise ValueError('私有RAM容量不符')
    return dict(source='tmpfs',path=STORE_PATH,fstype='tmpfs',capacity=capacity,mode=mode,options=options)
