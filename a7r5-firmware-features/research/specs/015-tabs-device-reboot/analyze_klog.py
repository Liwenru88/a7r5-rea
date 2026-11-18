"""只读解析已采集异常栈；仅导出与图标故障有关的脱敏证据。"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import struct


def analyze(text, resource, libobj):
    crashes = []
    for block in text.split('[register dump]'):
        registers = re.search(r' fp: 0x([0-9a-f]+)', block)
        if not registers:
            continue
        maps, memory = [], {}
        for line in block.splitlines():
            row = re.match(r'([0-9a-f]{16})-([0-9a-f]{16}) ([rwx-]{3}) 0x([0-9a-f]{16}) (.+)', line)
            if row:
                lo, hi, mode, offset, name = row.groups()
                maps.append((int(lo, 16), int(hi, 16), int(offset, 16), Path(name).name, mode))
            row = re.match(r'0x([0-9a-f]+):\|?(.*)', line)
            if row:
                start = int(row[1], 16)
                for index, value in enumerate(re.findall(r'0x([0-9a-f]{16})', row[2])):
                    memory[start + 8 * index] = int(value, 16)

        def resolve(address):
            for lo, hi, offset, name, _ in maps:
                if lo <= address < hi:
                    return name, address - lo + offset
            return None, None

        frame, frames, decode_frame = int(registers[1], 16), [], None
        for _ in range(32):
            if frame not in memory or frame + 8 not in memory:
                break
            name, offset = resolve(memory[frame + 8])
            frames.append({'module': name, 'offset': hex(offset) if offset is not None else None})
            if (name, offset) == ('libObj.so', 0x115330):
                decode_frame = frame
            frame = memory[frame]
        if decode_frame is None:
            continue
        request = b''.join(memory[decode_frame + offset].to_bytes(8, 'little') for offset in range(0x60, 0x80, 8))
        source, input_size, _, output_size, pages, channel, _ = struct.unpack('<Q6I', request)
        name, offset = resolve(source)
        if name != resource.name:
            raise ValueError('崩溃载荷不属于指定资源文件')
        raw = resource.read_bytes()
        resource_id = memory[decode_frame + 0x50] >> 32
        index = resource_id & 0xffff
        packed = struct.unpack_from('<I', raw, 12)[0]
        count = packed & 8191
        if packed != count | (count << 12) or index >= count:
            raise ValueError('资源编号／计数不符')
        base = (16 + count * 2 + 3) & ~3
        at = base + 4 * struct.unpack_from('<H', raw, 16 + 2 * index)[0]
        tag, flags, shape, size, relative = struct.unpack_from('<5I', raw, at)
        if (tag, flags, shape, size, at + 4 + relative) != (0x1a000000 | index, 0xc0000000, 35 << 16 | 70, input_size, offset):
            raise ValueError('堆栈中的请求与资源记录不一致')
        stream = raw[offset:offset + size]
        if len(stream) != size or output_size != 5600 or stream[:4] != b'\x0f\0\xe0\x15':
            raise ValueError('不是本次5600像素字节的长原样块')
        if b'false: ldec decompress error <UX_LOG_ERROR>\0' not in libobj.read_bytes():
            raise ValueError('解码库错误文本前像不符')
        crashes.append({'task': 'uxengine_res1' if 'im.elf(uxengine_res1)' in block else 'UNKNOWN',
                        'exception': 'Abort' if 'Abort (PC=' in block else 'UNKNOWN',
                        'frames': frames, 'resource': name, 'resource_id': hex(resource_id),
                        'slot': (index - 7844) // 2 + 1, 'selected': bool((index - 7844) & 1),
                        'source_file_offset': hex(offset), 'compressed_bytes': input_size,
                        'decoded_bytes': output_size, 'output_pages': pages, 'decoder_channel': channel,
                        'stream_header': stream[:4].hex(), 'stream_sha256': hashlib.sha256(stream).hexdigest()})
    if len(crashes) != 2 or any(row['task'] != 'uxengine_res1' or row['exception'] != 'Abort' for row in crashes):
        raise ValueError('预期的两次资源线程异常证据不完整')
    return {'schema': 'incident413-resource-crash/1', 'crashes': crashes,
            'klog_sha256': hashlib.sha256(text.encode()).hexdigest(),
            'resource_sha256': hashlib.sha256(resource.read_bytes()).hexdigest(),
            'libObj_sha256': hashlib.sha256(libobj.read_bytes()).hexdigest(),
            'camera_write': False, 'new_device_reproduction': False,
            'boundary': '已证实旧F01选中态长0F块在实机LDEC失败；新F0流仍待实机验收，不断言所有0F块均不受支持'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('klog', 'resource', 'libobj', 'output'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.klog.read_text(), args.resource, args.libobj)
    with args.output.open('x') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
        stream.write('\n')
    print(json.dumps({'crashes': len(result['crashes']), 'resource': result['crashes'][0]['resource_id'],
                      'slot': 1, 'selected': True, 'camera_write': False}, ensure_ascii=False))
