"""仅在 AVCAM 原有 FAT 簇链的预留空间内增长，不分配簇、不改变分区。"""
import hashlib
import struct
from a7r5dat.fat import FatImage


def replace(raw, content):
    fs = FatImage(raw)
    key = '/av-cam.bin'
    entry = fs.entries[key]
    allocated = sum(size for _, size in entry['extents'])
    if entry['is_directory'] or not entry['size'] <= len(content) <= allocated:
        raise ValueError('AVCAM 新代码超出原有 FAT 簇链预留空间')
    result = bytearray(raw)
    used, position = [], 0
    for at, size in entry['extents']:
        take = min(size, len(content) - position)
        if take <= 0: break
        result[at:at+take] = content[position:position+take]
        used.append((at, take))
        position += take
    if position != len(content):
        raise ValueError('AVCAM 写入长度不符')
    size_at = entry['directory_entry_offset'] + 28
    struct.pack_into('<I', result, size_at, len(content))
    after = FatImage(result)
    if after.read(key) != content or after.entries[key]['extents'] != entry['extents']:
        raise ValueError('AVCAM FAT 回读或原簇链不符')
    if fs.entries.keys() != after.entries.keys():
        raise ValueError('AVCAM FAT 目录集合发生变化')
    for name in fs.entries:
        if name != key and (fs.entries[name] != after.entries[name] or
                           not fs.entries[name]['is_directory'] and fs.read(name) != after.read(name)):
            raise ValueError('AVCAM FAT 的非目标文件发生变化')
    reverse = bytearray(result)
    for at, count in used: reverse[at:at+count] = raw[at:at+count]
    reverse[size_at:size_at+4] = raw[size_at:size_at+4]
    if reverse != raw:
        raise ValueError('AVCAM 簇链与文件大小字段之外发生变化')
    return bytes(result), dict(passed=True, camera_io=False, allocation_chain_unchanged=True,
        partition_bytes=len(raw), source_file_bytes=entry['size'], target_file_bytes=len(content),
        allocated_file_bytes=allocated, unrelated_bytes_exact=True,
        target_sha256=hashlib.sha256(result).hexdigest())
