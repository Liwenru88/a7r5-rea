"""生成按4KiB输出分块的F0流，保持原厂资源的块边界。

格式依据冻结的fwtool/lz77解码器；编码器独立实现，包含显式结束标记。
"""


def native_lz77_stream(pixels):
    if not pixels or len(pixels) > 65535:
        raise ValueError('图标像素载荷越界')
    if len(pixels) > 4096:
        # 每块独立字典、标志组及结束符，不能仅在长流中插入F0。
        encode = native_lz77_stream
        return b''.join(encode(pixels[start:start + 4096])
                        for start in range(0, len(pixels), 4096))
    lengths = tuple(range(3, 17)) + (32, 64)
    positions = {}
    output = bytearray(b'\xf0')
    group = []

    def emit(match, data):
        group.append((match, data))
        if len(group) == 8:
            flush()

    def flush():
        if group:
            output.append(sum(match << bit for bit, (match, _) in enumerate(group)))
            for _, data in group:
                output.extend(data)
            group.clear()

    offset = 0
    while offset < len(pixels):
        best, distance = 0, 0
        limit = min(64, len(pixels) - offset)
        if limit >= 3:
            for previous in reversed(positions.get(pixels[offset:offset + 3], ())):
                if offset - previous > 4095:
                    break
                size = 3
                while size < limit and pixels[previous + size] == pixels[offset + size]:
                    size += 1
                size = next(value for value in reversed(lengths) if value <= size)
                if size > best:
                    best, distance = size, offset - previous
                    if best == limit:
                        break
        consumed = best or 1
        if best:
            emit(1, bytes(((lengths.index(best) << 4) | (distance >> 8), distance & 255)))
        else:
            emit(0, pixels[offset:offset + 1])
        for position in range(offset, offset + consumed):
            if position + 2 < len(pixels):
                positions.setdefault(pixels[position:position + 3], []).append(position)
        offset += consumed
    emit(1, b'\0\0')
    flush()
    return bytes(output)
