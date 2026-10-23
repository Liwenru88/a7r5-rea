"""只将既有第四槽Eterna替换为Astia，保持UXC长度、索引和其他名称。"""
from pathlib import Path
import struct
import sys

HERE=Path(__file__).resolve().parent;ROOT=HERE.parents[1]
sys.path.insert(0,str(ROOT/'analysis/custom-features-20261021-03/research-materials-v3/vendor'))
from looktool.resources import decode

LABEL=0x0200abdb


def rename(raw):
    before=decode(raw)
    if before['group']!=5 or before['count']!=3038 or before['entries'][LABEL]['text']!='Eterna':
        raise ValueError('第四槽菜单前像不符')
    at=before['data_base']+before['entries'][LABEL]['pointer']*4+4
    if raw[at:at+8]!=b'Eterna\0\0':raise ValueError('Eterna记录边界不符')
    target=bytearray(raw);target[at:at+8]=b'Astia\0\0\0';target=bytes(target)
    after=decode(target)
    if any(after['entries'][key]['text']!=('Astia' if key==LABEL else row['text'])
           for key,row in before['entries'].items()):raise ValueError('其他名称发生变化')
    restored=bytearray(target);restored[at:at+8]=raw[at:at+8]
    if bytes(restored)!=raw:raise ValueError('名称反向还原不符')
    return target,dict(offset=at,before='Eterna',after='Astia',bytes=8,
        resource_length_unchanged=True,index_unchanged=True,other_names_unchanged=True,inverse_exact=True)
