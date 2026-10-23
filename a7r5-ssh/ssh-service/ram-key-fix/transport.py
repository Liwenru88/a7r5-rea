"""有界固定报文通道；每帧由操作层精确授权，失败不重传。"""
import struct

HEADER = struct.Struct('<IHHBBBB')
READ = struct.pack('<HH', 0x1001, 17) + b'\0\xff\0'
DEBUG = struct.pack('<HH', 0x1001, 5) + b'\0\0\0'


class FileResultError(ValueError):
    def __init__(self, result):
        self.result = result
        super().__init__(f'文件服务结果0x{result:08x}')


class Channel:
    def __init__(self, driver, operation, log):
        self.driver, self.operation, self.log = driver, operation, log
        self.sequence, self.usable = 1, True
        self.reads, self.writes, self.debug_attempts = 0, 0, 0

    def exchange(self, body, limit):
        if not self.usable or self.sequence > 256:
            raise PermissionError('通道失败或帧数超限')
        self.usable = False
        packet = HEADER.pack(len(body), 0x40, self.sequence, 0, 0, 0, 0) + body
        self.operation.permitted_packet = packet
        self.operation.guard_packet(packet)
        # 真USB驱动还会在发送边界再次核对同一个完整报文。
        if self.driver.write(packet) != len(packet):
            raise OSError('USB短写，不重试')
        self.operation.permitted_packet = None
        raw = self.driver.read(HEADER.size)
        self.log('response_header', sequence=self.sequence, raw_hex=raw.hex(), response_limit=limit)
        if len(raw) != HEADER.size:
            raise ValueError('响应头长度错误')
        size, function, sequence, version, micon, offset, status = HEADER.unpack(raw)
        if function != 0x40 or sequence != self.sequence or not 4 <= size <= limit or status:
            raise ValueError('响应头功能、序号、长度或状态错误')
        content = bytearray()
        while len(content) < size:
            chunk = self.driver.read(min(4096, size - len(content)))
            if not chunk or len(chunk) > size - len(content):
                raise ValueError('响应体边界错误')
            content.extend(chunk)
        if size % 512 == 0 and self.driver.read(512) != b'':
            raise ValueError('缺少空边界包')
        self.sequence += 1
        self.usable = True
        result, = struct.unpack_from('<I', content)
        self.log('file_result', result=f'0x{result:08x}', bytes=size - 4, version=version, micon=micon, offset=offset)
        if result:
            raise FileResultError(result)
        return bytes(content[4:])

    def select(self, path):
        wire = path if path.startswith('/tmp/jiritsu/') else '/tmp/jiritsu/../..' + path
        self.exchange(struct.pack('<HH', 0x1001, 15) + b'\0' + wire.encode() + b'\0', 4)

    def read(self, path, limit):
        if path not in self.operation.reads or limit != self.operation.reads[path]:
            raise PermissionError('非固定读取')
        self.reads += 1
        self.select(path)
        return self.exchange(READ, limit + 4)

    def put(self, path, raw):
        if path not in self.operation.writes or raw != self.operation.writes[path]:
            raise PermissionError('非固定写入或完整字节不符')
        self.writes += 1
        self.log('fixed_write_attempt', path=path, bytes=len(raw))
        self.select(path)
        if self.exchange(struct.pack('<HH', 0x1001, 16) + b'\0\xff\0' + raw, 4):
            raise ValueError('写入回执含额外内容')

    def debug(self):
        if self.debug_attempts:
            raise PermissionError('DEBUG不重发')
        self.debug_attempts += 1
        self.log('debug_attempt', attempt=1)
        if self.exchange(DEBUG, 4):
            raise ValueError('DEBUG回执含额外内容')
