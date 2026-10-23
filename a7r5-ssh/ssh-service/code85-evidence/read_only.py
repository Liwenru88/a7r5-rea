"""固定只读协议；从已验证恢复包提取，不含认证或写文件接口。"""
import struct
import evidence_policy as policy
HEADER = struct.Struct('<IHHBBBB')
READ = struct.pack('<HH', 0x1001, 0x11) + b'\0\xff\0'


class FileResultError(ValueError):
    def __init__(self, result):
        self.result = result
        super().__init__(f'固定读取服务结果0x{result:08x}')


class ReadChannel:
    """只有固定顺序的select/get，无put、认证、START或DEBUG接口。"""
    def __init__(self, driver, log):
        self.driver, self.log = driver, log
        self.sequence, self.index, self.usable = 1, 0, True
        self.permitted_body = None

    def exchange(self, body, limit):
        if not self.usable or body != self.permitted_body or self.sequence > 2 * len(policy.READS):
            raise PermissionError('不允许的命令、顺序或已失败通道')
        self.permitted_body = None
        self.usable = False
        packet = HEADER.pack(len(body), 0x40, self.sequence, 0, 0, 0, 0) + body
        if self.driver.write(packet) != len(packet):
            raise OSError('USB短写，不重试')
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
            raise ValueError('响应缺少空边界包')
        self.sequence += 1
        self.usable = True
        result, = struct.unpack_from('<I', content)
        self.log('file_result', result=f'0x{result:08x}', bytes=size - 4,
                 version=version, micon=micon, offset=offset)
        if result:
            raise FileResultError(result)
        return bytes(content[4:])

    def read_next(self, label, path, limit):
        if self.index >= len(policy.READS) or (label, path, limit) != policy.READS[self.index]:
            raise PermissionError('只允许本次固定10次读取，不重发')
        self.index += 1
        wire = (path if path.startswith('/tmp/jiritsu/') else '/tmp/jiritsu/../..' + path).encode('ascii')
        self.permitted_body = struct.pack('<HH', 0x1001, 0x0f) + b'\0' + wire + b'\0'
        self.exchange(self.permitted_body, 4)
        self.permitted_body = READ
        return self.exchange(READ, limit + 4)


