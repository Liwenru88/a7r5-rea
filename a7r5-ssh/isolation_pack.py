#!/usr/bin/env python3
"""只归档本次离线补证材料；不遍历旧实机结果、批准或尝试锁。"""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

import isolation
import lab


def archive(directory,destination):
    directory=Path(directory).absolute();destination=Path(destination).absolute()
    operation=isolation.check(directory)
    if not directory.is_relative_to(lab.ROOT):raise ValueError('归档操作须在当前材料根目录内')
    if destination.exists() or destination.is_relative_to('/dev') or any(p.is_symlink() for p in (destination,*destination.parents)):
        raise ValueError('拒绝覆盖、设备或链接输出')
    if any((directory/name).exists() for name in ('approval-probe.json','approval-collect.json',
                'ATTEMPT_LOCK_PROBE','ATTEMPT_LOCK_COLLECT','result-probe','result-collect')):
        raise PermissionError('不能归档已批准或已尝试补证包')
    files={lab.ROOT/name for name in operation['sources']}
    files|={directory/name for name in operation['artifacts']}
    files|={directory/name for name in ('operation.json','approval-probe-template.json','approval-collect-template.json')}
    files|={lab.ROOT/name for name in ('隔离与跨STOP补证-执行方案.md','隔离与跨STOP补证-验证记录.md','tests/test_isolation.py')}
    data={}
    for path in sorted(files):
        path=lab.regular(path);name='a7r5-ssh/'+str(path.relative_to(lab.ROOT))
        if path.suffix in ('.img','.zip') or path.name.startswith('approval-') and not path.name.endswith('-template.json'):
            raise ValueError('包内含未批准的镜像或批准文件')
        data[name]=path.read_bytes()
    manifest={name:hashlib.sha256(raw).hexdigest() for name,raw in data.items()}
    with zipfile.ZipFile(destination,'x',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,raw in data.items():z.writestr(name,raw)
        z.writestr('SHA256-MANIFEST.json',json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
    destination.chmod(0o600)
    with zipfile.ZipFile(destination) as z:
        if z.testzip() is not None:raise ValueError('ZIP CRC不符')
        if set(z.namelist())!=set(manifest)|{'SHA256-MANIFEST.json'}:raise ValueError('归档集合不符')
        for name,expected in manifest.items():
            if hashlib.sha256(z.read(name)).hexdigest()!=expected:raise ValueError('ZIP成员摘要不符')
    receipt=dict(archive=str(destination),bytes=destination.stat().st_size,sha256=lab.digest(destination),
                 members=len(manifest)+1,all_members_sha256_verified=True,zip_crc_verified=True,
                 operation_sha256=lab.digest(directory/'operation.json'),run_id=operation['run_id'],
                 valid_approval_included=False,original_partition_images_included=False,
                 host_network_accessed=False,camera_io=False,execution_bound_to_original_paths=True)
    lab.save(directory/'archive-receipt.json',receipt)
    return receipt


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--operation',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    args=p.parse_args()
    print(json.dumps(archive(args.operation,args.output),ensure_ascii=False,indent=2))
