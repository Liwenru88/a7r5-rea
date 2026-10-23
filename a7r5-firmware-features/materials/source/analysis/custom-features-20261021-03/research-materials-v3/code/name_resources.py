"""在 R5 UXC-v7 中追加六项名称，严格保留原索引与原记录。"""
import struct
import sys
from pathlib import Path

from ap_runtime import LABEL, NAMES

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'custom-features-20261021-01/upstream/leonard/src/looks'))
from looktool.resources import decode


def append_names(raw):
    before = decode(raw)
    if before['group'] != 5 or before['count'] != 3032 or before['data_base'] != 6080:
        raise ValueError('R5 名称资源分组或项数不符')
    base = before['data_base'] + 12
    result = bytearray(raw[:before['data_base']] + bytes(12) + raw[before['data_base']:])
    struct.pack_into('<I', result, 12, 3038 | (3038 << 12))
    for i, name in enumerate(NAMES):
        offset = (len(result)-base)//4
        if offset >= 65535:
            raise ValueError('UXC 记录偏移溢出')
        struct.pack_into('<H', result, 16+2*(3032+i), offset)
        result.extend(struct.pack('<I',0x1e000000 | ((LABEL+i)&0xffffff)) + name.encode('utf8') + b'\0')
        result.extend(bytes(-len(result)%4))
    after = decode(result)
    if any(after['entries'][key] != value for key,value in before['entries'].items()):
        raise ValueError('原名称或相对索引发生变化')
    if [after['entries'][LABEL+i]['text'] for i in range(6)] != list(NAMES):
        raise ValueError('新增名称回读不符')
    inverse = bytearray(result[:before['data_base']]+result[base:len(raw)+12])
    inverse[12:16] = raw[12:16]
    if inverse != raw:
        raise ValueError('UXC 完整反向重建失败')
    return bytes(result), {'before_bytes':len(raw), 'after_bytes':len(result),
        'before_count':3032, 'after_count':3038, 'inverse_exact':True,
        'old_entries_unchanged':len(before['entries']), 'labels':list(range(LABEL,LABEL+6))}
