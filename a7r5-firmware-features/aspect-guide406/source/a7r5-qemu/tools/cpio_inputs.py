"""只读比对 newc 客体中的内容和元数据，不展开或执行归档。"""
import hashlib


def entries(path):
    result={}
    with path.open('rb') as stream:
        while True:
            raw=stream.read(110)
            if len(raw)!=110 or raw[:6]!=b'070701':raise ValueError('newc 头不符')
            values=[int(raw[6+i*8:14+i*8],16) for i in range(13)]
            size,namesize=values[6],values[11]
            if not 1<=namesize<=4096:raise ValueError('newc 名称长度不符')
            name=stream.read(namesize)
            if len(name)!=namesize or name[-1:]!=b'\0':raise ValueError('newc 名称不完整')
            name=name[:-1].decode().removeprefix('./')
            stream.read((-110-namesize)%4)
            remaining=size;digest=hashlib.sha256()
            while remaining:
                chunk=stream.read(min(remaining,1024*1024))
                if not chunk:raise ValueError('newc 内容截断')
                digest.update(chunk);remaining-=len(chunk)
            stream.read((-size)%4)
            if name in result:raise ValueError('newc 重复路径')
            result[name]={'metadata':values[:6]+values[7:], 'bytes':size,'sha256':digest.hexdigest()}
            if name=='TRAILER!!!':break
    return result


def only_observer_changed(before,after):
    original,rebuilt=entries(before),entries(after)
    if original.keys()!=rebuilt.keys():raise ValueError('客体条目集合变化')
    changed=[name for name in original if original[name]!=rebuilt[name]]
    if changed not in ([],['simulation/menu-observe-a7r5-baseline.so']):
        raise ValueError('模拟库以外的客体内容变化: '+str(changed))
    return {'entries':len(original),'changed':changed,'all_other_entries_identical':True}
