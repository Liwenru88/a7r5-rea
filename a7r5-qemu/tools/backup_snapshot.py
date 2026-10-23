"""只读解析模拟客体的 BK4 设置副本；不提供修改或写回接口。"""
import struct


class BackupSnapshot:
    def __init__(self, data):
        self.data = bytes(data)
        if len(data) < 256 or data[12:16] != b'BK4\0':
            raise ValueError('不是支持的 BK4 设置副本')
        self.subsystems, self.properties, self.offset, length, checksum = struct.unpack_from('<5I', data, 16)
        self.size = self.offset + length
        self.table = 256 + self.subsystems * 6
        if self.size > len(data) or self.table + self.properties * 6 > self.offset:
            raise ValueError('设置副本表或数据区越界')
        if sum(data[:32]) + sum(data[36:self.size]) != checksum:
            raise ValueError('设置副本校验和不符')

    def property(self, ident):
        if not isinstance(ident, int) or not 0 <= ident <= 0xffffffff:
            raise ValueError('设置 ID 不符')
        subsystem, index = ident >> 16, ident & 0xffff
        if subsystem >= self.subsystems:
            raise ValueError('设置子系统越界')
        count, start = struct.unpack_from('<HI', self.data, 256+subsystem*6)
        if index >= count or start + count > self.properties:
            raise ValueError('设置索引越界')
        attr, pointer = struct.unpack_from('<HI', self.data, self.table+(start+index)*6)
        if pointer == 0xffffffff:
            raise ValueError('设置项不存在')
        size, offset = pointer >> 24, pointer & 0xffffff
        extra = 2 if size == 255 else 4 if size == 0 else 0
        if offset < self.offset or offset + extra > self.size:
            raise ValueError('设置指针越界')
        if size == 255:
            size, = struct.unpack_from('<H', self.data, offset); offset += 2
            maximum = size
        elif size == 0:
            size, maximum = struct.unpack_from('<HH', self.data, offset); offset += 4
        else:
            maximum = size
        if size > maximum or offset + maximum > self.size:
            raise ValueError('设置长度越界')
        return attr, self.data[offset:offset+size]
