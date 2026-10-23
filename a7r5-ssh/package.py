#!/usr/bin/env python3
"""离线归档与独立摘要核对；不生成实机批准或访问设备。"""
import hashlib
import json
from pathlib import Path
import sys
import zipfile

import lab


def files():
    return sorted(p for p in lab.ROOT.rglob('*') if p.is_file() and '__pycache__' not in p.parts
                  and p.name not in ('MANIFEST.sha256','archive-receipt.json') and p.suffix!='.zip'
                  and p.name not in ('approval.json','ATTEMPT_LOCK') and not p.name.startswith('.'))


def verify():
    seen=set()
    for line in (lab.ROOT/'MANIFEST.sha256').read_text().splitlines():
        sha,name=line.split('  ',1); relative=Path(name)
        if relative.is_absolute() or '..' in relative.parts or name in seen: raise ValueError('摘要路径不符')
        seen.add(name)
        if lab.digest(lab.ROOT/relative)!=sha: raise ValueError('文件摘要变化：'+name)
    actual={str(p.relative_to(lab.ROOT)) for p in files()}
    if actual!=seen: raise ValueError('文件集合变化')
    lab.check(lab.ROOT/'packages/preflight-once')
    return dict(verified=True,files=len(seen),camera_io=False)


def archive(destination):
    destination=Path(destination).absolute()
    if destination.exists(): raise FileExistsError('归档已存在，不覆盖旧包')
    for p in lab.ROOT.rglob('*'):
        if p.is_symlink(): raise ValueError('包内有链接，拒绝归档')
        if p.name in ('approval.json','ATTEMPT_LOCK'): raise ValueError('不能归档有效批准或已尝试操作')
    current=files()
    (lab.ROOT/'MANIFEST.sha256').write_text(''.join(lab.digest(p)+'  '+str(p.relative_to(lab.ROOT))+'\n' for p in current))
    with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for p in current+[lab.ROOT/'MANIFEST.sha256']:
            z.write(p,'a7r5-ssh/'+str(p.relative_to(lab.ROOT)))
    with zipfile.ZipFile(destination) as z:
        if z.testzip() is not None: raise ValueError('ZIP CRC不符')
        expected={str(p.relative_to(lab.ROOT)):lab.digest(p) for p in current+[lab.ROOT/'MANIFEST.sha256']}
        if set(z.namelist())!={'a7r5-ssh/'+name for name in expected}: raise ValueError('ZIP成员集合不符')
        for name,sha in expected.items():
            if hashlib.sha256(z.read('a7r5-ssh/'+name)).hexdigest()!=sha: raise ValueError('ZIP成员摘要不符')
    report=dict(archive=str(destination),bytes=destination.stat().st_size,sha256=lab.digest(destination),
                members=len(expected),zip_crc_verified=True,all_member_sha256_verified=True,
                contains_live_approval=False,contains_original_partition_images=False,
                camera_io=False,material_verification=verify())
    lab.save(lab.ROOT/'archive-receipt.json',report)
    return report


if __name__=='__main__':
    if len(sys.argv)==2 and sys.argv[1]=='verify': result=verify()
    elif len(sys.argv)==3 and sys.argv[1]=='archive': result=archive(sys.argv[2])
    else: raise SystemExit('用法：package.py verify | package.py archive ZIP路径')
    print(json.dumps(result,ensure_ascii=False,indent=2))
