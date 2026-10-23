#!/usr/bin/env python3
"""在新解包的工作副本中重建固定4.00派生组件；不连接设备，不读取私钥。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import struct
import tempfile

HERE=Path(__file__).resolve().parent


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def require(ok,message):
    if not ok:raise ValueError(message)


def path_in(work,name):
    parts=name.split('/')
    require(not name.startswith('/') and all(p not in ('','.','..') for p in parts),'非法工作路径')
    target=work
    for part in parts:
        target=target/part
        require(not target.is_symlink(),'拒绝符号链接：'+str(target))
    require(target.is_file() and not target.resolve().is_relative_to('/dev'),'只接受普通工作文件')
    return target


def patch(raw,record):
    require(len(raw)==record['before_bytes'] and sha(raw)==record['before_sha256'],'完整前像不匹配：'+record['path'])
    result=bytearray(raw);end=0
    for row in record['patches']:
        at=row['offset'];before=bytes.fromhex(row['before']);after=bytes.fromhex(row['after'])
        require(at>=end and len(before)==len(after) and at+len(before)<=len(raw),'补丁范围或顺序错误')
        require(raw[at:at+len(before)]==before,'局部前像不匹配')
        result[at:at+len(after)]=after;end=at+len(after)
    result=bytes(result)
    require(len(result)==record['after_bytes'] and sha(result)==record['after_sha256'],'目标摘要不匹配')
    return result


def resource(raw,record,names):
    require(len(raw)==record['before_bytes'] and sha(raw)==record['before_sha256'],'名称资源前像不匹配')
    require(len(names)==6 and len(raw)>6080,'资源长度或名称数错误')
    count=struct.unpack_from('<I',raw,12)[0]
    require(count==(3032|(3032<<12)),'UXC条目数前像不匹配')
    base=6092
    target=bytearray(raw[:6080]+bytes(12)+raw[6080:])
    struct.pack_into('<I',target,12,3038|(3038<<12))
    for index,name in enumerate(names):
        ptr=(len(target)-base)//4
        require(ptr<65535,'UXC相对偏移溢出')
        struct.pack_into('<H',target,16+2*(3032+index),ptr)
        target.extend(struct.pack('<I',0x1e000000|((0x0200abd8+index)&0xffffff)))
        target.extend(name.encode('utf8')+b'\0');target.extend(bytes(-len(target)%4))
    result=bytes(target)
    require(len(result)==record['after_bytes'] and sha(result)==record['after_sha256'],'名称资源目标摘要不匹配')
    return result


def run(work,feature,receipt):
    recipe=json.loads((HERE/'recipes.json').read_text())
    require(feature in ('all','ntsc-only'),'不支持的组合')
    require(work.is_dir() and not work.is_symlink() and not receipt.exists(),'工作目录或回执输出不合法')
    require(receipt.parent.is_dir() and not receipt.is_symlink(),'回执父目录不存在或回执是符号链接')
    manifest=json.loads(path_in(work,'manifest.json').read_text())
    require(manifest['source']['sha256']==recipe['official_DAT_sha256'],'必须从指定原厂4.00重新解包')
    require(manifest['header']['major']==4 and manifest['header']['minor']==0,'解包来源版本不符')
    records=recipe['integrated'] if feature=='all' else [recipe['ntsc_only']]
    prepared=[]
    for rec in records:
        p=path_in(work,rec['path']);raw=p.read_bytes()
        prepared.append((p,patch(raw,rec),rec['before_sha256']))
    if feature=='all':
        for rec in recipe['resources']:
            p=path_in(work,rec['path']);raw=p.read_bytes()
            prepared.append((p,resource(raw,rec,recipe['names']),rec['before_sha256']))
    # 两种组合都保留本研究的WBI标记变化；不宣称它证明冷启动或CP NOR已更新。
    rec=recipe['WBI'];p=path_in(work,rec['path']);raw=p.read_bytes()
    prepared.append((p,patch(raw,rec),rec['before_sha256']))
    result=dict(status='APPLYING_WORKSPACE_COPY',feature=feature,source_DAT_sha256=recipe['official_DAT_sha256'],
        files=[],camera_IO=False,SD_IO=False,private_key_read=False)
    try:
        # 所有文件先校验并生成，再改动工作副本；不替换原DAT或校验清单。
        for p,target,before_sha in prepared:
            require(sha(p.read_bytes())==before_sha,'工作文件在核对后变化')
            fd,temp=tempfile.mkstemp(prefix='.offline-component-',dir=p.parent)
            temp=Path(temp)
            try:
                with os.fdopen(fd,'wb') as stream:
                    stream.write(target);stream.flush();os.fsync(stream.fileno())
                require(sha(temp.read_bytes())==sha(target),'临时文件回读失败')
                os.replace(temp,p)
            finally:
                if temp.exists():temp.unlink()
            result['files'].append(dict(path=str(p.relative_to(work)),bytes=len(target),sha256=sha(target)))
        result['status']='WORKSPACE_COMPONENTS_VERIFIED'
    except Exception as error:
        result.update(status='FAILED_PARTIAL_WORKSPACE_DO_NOT_PACK',error=str(error))
        raise
    finally:
        with receipt.open('x') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--workspace',required=True,type=Path)
    parser.add_argument('--feature',choices=['all','ntsc-only'],default='all')
    parser.add_argument('--receipt',required=True,type=Path)
    args=parser.parse_args();os.umask(0o077)
    try:
        result=run(args.workspace.absolute(),args.feature,args.receipt.absolute())
        print(json.dumps(result,ensure_ascii=False,indent=2));return 0
    except (OSError,ValueError,KeyError) as error:
        print('停止；不应继续打包：'+str(error));return 1


if __name__=='__main__':raise SystemExit(main())
