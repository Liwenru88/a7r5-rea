"""Android sparse 格式的整分区覆盖：只用于离线生成/校验回滚镜像。"""
import struct
from filesystems import require

MAGIC = 0xED26FF3A
SECTOR = 512


def make_sparse(before, after):
    require(len(before) == len(after) and len(before) % SECTOR == 0, '镜像长度不符')
    blocks = len(before) // SECTOR
    changed = {i for i in range(blocks) if before[i*SECTOR:(i+1)*SECTOR] != after[i*SECTOR:(i+1)*SECTOR]}
    chunks, pos = [], 0
    while pos < blocks:
        start, flag = pos, pos in changed
        while pos < blocks and (pos in changed) == flag:
            pos += 1
        n = pos - start
        chunks.append(struct.pack('<2H2I', 0xCAC1 if flag else 0xCAC3, 0,
                                   n, 12 + n*SECTOR if flag else 12) +
                      (after[start*SECTOR:pos*SECTOR] if flag else b''))
    return struct.pack('<I4H4I', MAGIC, 1, 0, 28, 12, SECTOR, blocks, len(chunks), 0) + b''.join(chunks)


def apply_sparse(before, patch):
    require(len(patch) >= 28, 'sparse 长度不足')
    magic, major, minor, header, chunk_header, block_size, blocks, count, checksum = struct.unpack_from('<I4H4I', patch)
    require((magic, major, minor, header, chunk_header, block_size, checksum) ==
            (MAGIC, 1, 0, 28, 12, SECTOR, 0), 'sparse 头不符')
    require(len(before) == blocks * SECTOR, '镜像长度与 sparse 头不符')
    out, pos, block = bytearray(before), 28, 0
    written = []
    for _ in range(count):
        require(pos + 12 <= len(patch), 'sparse 块截断')
        kind, reserved, n, total = struct.unpack_from('<2H2I', patch, pos)
        require(reserved == 0 and n > 0 and block + n <= blocks, 'sparse 块范围异常')
        require(pos + total <= len(patch), 'sparse 载荷越界')
        if kind == 0xCAC1:
            require(total == 12 + n*SECTOR, 'RAW 块长度不符')
            out[block*SECTOR:(block+n)*SECTOR] = patch[pos+12:pos+total]
            written.extend(range(block, block+n))
        else:
            require(kind == 0xCAC3 and total == 12, '未知 sparse 块')
        block += n
        pos += total
    require(pos == len(patch) and block == blocks, 'sparse 尾部或块数不符')
    return bytes(out), written
