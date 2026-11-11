"""从指定官方前像还原已离线验证的 4.17 归档成员。"""

import gzip
import hashlib
import json
import shutil
import struct

VERSION = '4.17'
SOURCE_SHA256 = '51e1176a255a9a4b4782dfbcfa6c5f332b71173bdfe9ed2bcf4fca6bcbc6c2e2'
DAT_SHA256 = '49ec00bd5c179fc0f784bf8c64e5025877fde5b50c3ce48fe05dd3d51a24dcda'
FILTER_SHA256 = '19e020fa48c79643aaf9526e9c720d38ec5a92c3df11d0852b0a93a25ee880b6'
FILTER_NAME = 'R5NATIVE.BIN'
BLOCK_BYTES = 4096
INDEX = struct.Struct('>I')


def sha(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def write_delta(original, target, output):
    with original.open('rb') as before, target.open('rb') as after, output.open('xb') as packed:
        with gzip.GzipFile(filename='', mode='wb', fileobj=packed, mtime=0) as delta:
            index = 0
            while left := before.read(BLOCK_BYTES):
                right = after.read(len(left))
                if len(right) != len(left):
                    raise ValueError('4.17 归档成员长度变化')
                if left != right:
                    delta.write(INDEX.pack(index))
                    delta.write(right)
                index += 1
            if after.read(1):
                raise ValueError('4.17 归档成员长度变化')


def prepare(original, target, filters, destination):
    before = json.loads((original/'manifest.json').read_text())
    after = json.loads((target/'manifest.json').read_text())
    if (before['source']['sha256'] != SOURCE_SHA256 or after['source']['sha256'] != DAT_SHA256
            or before['updater_sha256'] != after['updater_sha256'] or sha(filters) != FILTER_SHA256):
        raise ValueError('4.17 封包材料身份不符')
    records = []
    # 校验清单由 DAT 工具依据变化后的成员自动重建。
    for left, right in zip(before['entries'], after['entries'], strict=True):
        name = left['name']
        if (name, left['type'], left['size']) != (right['name'], right['type'], right['size']):
            raise ValueError('4.17 归档布局变化')
        if left.get('sha256') == right.get('sha256') or name.endswith('.sum'):
            continue
        filename = f'{len(records):02d}.delta.gz'
        write_delta(original/'archive'/name, target/'archive'/name, destination/filename)
        records.append(dict(path=name, delta=filename, bytes=left['size'],
                            before_sha256=left['sha256'], after_sha256=right['sha256']))
    if not records:
        raise ValueError('4.17 归档增量为空')
    shutil.copyfile(filters, destination/FILTER_NAME)
    (destination/'manifest.json').write_text(json.dumps(records, ensure_ascii=False, indent=2)+'\n')


def apply_delta(path, delta, record):
    if path.stat().st_size != record['bytes'] or sha(path) != record['before_sha256']:
        raise ValueError('4.17 归档成员前像不符：'+record['path'])
    previous = -1
    with gzip.open(delta, 'rb') as changes, path.open('r+b') as target:
        while index_bytes := changes.read(INDEX.size):
            if len(index_bytes) != INDEX.size:
                raise ValueError('4.17 增量索引不完整')
            index, = INDEX.unpack(index_bytes)
            offset = index * BLOCK_BYTES
            if index <= previous or offset >= record['bytes']:
                raise ValueError('4.17 增量范围或顺序无效')
            size = min(BLOCK_BYTES, record['bytes'] - offset)
            raw = changes.read(size)
            if len(raw) != size:
                raise ValueError('4.17 增量数据不完整')
            target.seek(offset)
            target.write(raw)
            previous = index
    if sha(path) != record['after_sha256']:
        raise ValueError('4.17 归档成员回读不符：'+record['path'])


def apply(work, resources):
    from component_recipe import path_in

    for record in json.loads((resources/'manifest.json').read_text()):
        path = path_in(work/'archive', record['path'])
        delta = path_in(resources, record['delta'])
        apply_delta(path, delta, record)
