"""对固定更新器 SquashFS 进行有界、可独立回读的脚本替换。"""

import hashlib
import struct
import zlib

SOURCE_SHA = 'c4b18a82eea52a507fb82b86ad50bab6047070b8908d03c28edcce4a9577d348'


def metadata(raw, start, offset, size):
    decoded = bytearray()
    while len(decoded) < offset + size:
        header, = struct.unpack_from('<H', raw, start)
        start += 2
        block = raw[start:start + (header & 0x7fff)]
        if len(block) != header & 0x7fff:
            raise ValueError('SquashFS 元数据短读')
        block = block if header & 0x8000 else zlib.decompress(block)
        if not block or len(block) > 8192:
            raise ValueError('SquashFS 元数据块长度错误')
        decoded.extend(block)
        start += header & 0x7fff
    return bytes(decoded[offset:offset + size])


def inode_ref(raw, path):
    inode_start, directory_start = struct.unpack_from('<QQ', raw, 64)
    reference, = struct.unpack_from('<Q', raw, 32)
    for wanted in path.strip('/').split('/'):
        start, offset = inode_start + (reference >> 16), reference & 65535
        kind, = struct.unpack_from('<H', metadata(raw, start, offset, 16))
        if kind != 1:
            raise ValueError('固定路径不是基本目录 inode')
        block, _links, length, at, _parent = struct.unpack('<IIHHI', metadata(raw, start, offset + 16, 16))
        data = metadata(raw, directory_start + block, at, length - 3)
        pos, found = 0, None
        while pos < len(data):
            count, block, _number = struct.unpack_from('<III', data, pos)
            pos += 12
            for _ in range(count + 1):
                at, _number_delta, _type, length = struct.unpack_from('<HhHH', data, pos)
                pos += 8
                name = data[pos:pos + length + 1].decode('ascii')
                pos += length + 1
                if name == wanted:
                    found = (block << 16) | at
        if found is None:
            raise ValueError('固定更新器缺少路径：' + path)
        reference = found
    return reference


def encoded_metadata(data):
    if not 0 < len(data) <= 8192:
        raise ValueError('元数据必须落在单个 SquashFS 块内')
    packed = zlib.compress(data, 9)
    if len(packed) < len(data):
        return struct.pack('<H', len(packed)) + packed
    return struct.pack('<H', len(data) | 0x8000) + data


def replace_script(raw, content, bodylib=None):
    if hashlib.sha256(raw).hexdigest() != SOURCE_SHA:
        raise ValueError('更新器完整前像不符')
    if not content.startswith(b'#! /bin/sh\n') or len(content) >= 131072:
        raise ValueError('脚本内容为空、格式不符或超出单片段范围')
    reference = inode_ref(raw, '/bin/nor_loader_writer.sh')
    if reference >> 16:
        raise ValueError('目标 inode 不在固定首元数据块')
    inode_start, directory_start, fragment_table = struct.unpack_from('<QQQ', raw, 64)
    header, = struct.unpack_from('<H', raw, inode_start)
    if inode_start + 2 + (header & 0x7fff) != directory_start:
        raise ValueError('固定 inode 表不再是单元数据块')
    packed = raw[inode_start + 2:directory_start]
    inodes = bytearray(packed if header & 0x8000 else zlib.decompress(packed))
    kind, = struct.unpack_from('<H', inodes, reference)
    if kind != 2:
        raise ValueError('目标不是基本文件 inode')
    fragments, = struct.unpack_from('<I', raw, 16)
    if fragments != 5:
        raise ValueError('固定片段表身份不符')
    pointer, = struct.unpack_from('<Q', raw, fragment_table)
    fragment_entries = metadata(raw, pointer, 0, fragments * 16)
    used, = struct.unpack_from('<Q', raw, 40)
    result = bytearray(raw[:used])
    # 保留全部原始数据；新元数据表保持原生顺序及原 inode 引用位置。
    content_start = len(result)
    packed_content = zlib.compress(content, 9)
    result.extend(packed_content)
    struct.pack_into('<IIII', inodes, reference + 16, 0, fragments, 0, len(content))
    added_fragments = [struct.pack('<QII', content_start, len(packed_content), 0)]
    if bodylib is not None:
        if hashlib.sha256(bodylib).hexdigest() != 'dd19e2cd42b6f1303317c3f7b90b4c9debe8da4c660cb3677f54bcd794abc002':
            raise ValueError('Shell 调用库修复结果身份不符')
        reference = inode_ref(raw, '/bodylib/libupdaterbody.so')
        if reference >> 16 or struct.unpack_from('<H', inodes, reference)[0] != 2:
            raise ValueError('Shell 调用库 inode 身份不符')
        old_size, = struct.unpack_from('<I', inodes, reference + 28)
        if len(bodylib) != old_size or not 131072 < old_size < 262144:
            raise ValueError('Shell 调用库块布局不符')
        block_start = len(result)
        packed_block = zlib.compress(bodylib[:131072], 9)
        result.extend(packed_block)
        fragment_start = len(result)
        packed_tail = zlib.compress(bodylib[131072:], 9)
        result.extend(packed_tail)
        struct.pack_into('<IIII', inodes, reference + 16, block_start, fragments + 1, 0, old_size)
        struct.pack_into('<I', inodes, reference + 32, len(packed_block))
        added_fragments.append(struct.pack('<QII', fragment_start, len(packed_tail), 0))
    new_inode_start = len(result)
    result.extend(encoded_metadata(inodes))
    new_directory_start = len(result)
    result.extend(raw[directory_start:pointer])
    new_fragment_meta = len(result)
    result.extend(encoded_metadata(fragment_entries + b''.join(added_fragments)))
    new_fragment_table = len(result)
    result.extend(struct.pack('<Q', new_fragment_meta))
    export_table, = struct.unpack_from('<Q', raw, 88)
    export_pointer, = struct.unpack_from('<Q', raw, export_table)
    inode_count, = struct.unpack_from('<I', raw, 4)
    exports = metadata(raw, export_pointer, 0, inode_count * 8)
    new_export_meta = len(result)
    result.extend(encoded_metadata(exports))
    new_export_table = len(result)
    result.extend(struct.pack('<Q', new_export_meta))
    id_table, = struct.unpack_from('<Q', raw, 48)
    id_pointer, = struct.unpack_from('<Q', raw, id_table)
    id_count, = struct.unpack_from('<H', raw, 26)
    ids = metadata(raw, id_pointer, 0, id_count * 4)
    new_id_meta = len(result)
    result.extend(encoded_metadata(ids))
    new_id_table = len(result)
    result.extend(struct.pack('<Q', new_id_meta))
    struct.pack_into('<I', result, 16, fragments + len(added_fragments))
    struct.pack_into('<Q', result, 40, len(result))
    struct.pack_into('<Q', result, 64, new_inode_start)
    struct.pack_into('<Q', result, 72, new_directory_start)
    struct.pack_into('<Q', result, 80, new_fragment_table)
    struct.pack_into('<Q', result, 88, new_export_table)
    struct.pack_into('<Q', result, 48, new_id_table)
    result.extend(bytes((-len(result)) % 4096))
    return bytes(result)
