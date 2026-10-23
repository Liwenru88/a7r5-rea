"""从现有已验证容器读取器定向冻结；只接受普通文件。"""
import hashlib
from pathlib import Path
import stat
import struct
import zlib
CHUNK = 4 << 20


def require(condition, message):
    if not condition:
        raise ValueError(message)

def sha(data):
    return hashlib.sha256(data).hexdigest()

def regular(path):
    path = Path(path).absolute()
    require(not path.is_symlink() and stat.S_ISREG(path.stat().st_mode), '只接受普通文件：' + str(path))
    resolved = path.resolve(strict=True)
    require(not resolved.is_relative_to('/dev'), '禁止设备路径')
    return resolved

def digest(path):
    with regular(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()

def crc_prefix(path, size):
    crc = 0
    with regular(path).open('rb') as stream:
        while size:
            raw = stream.read(min(CHUNK, size))
            require(raw, 'CRC 区域短读')
            crc = zlib.crc32(raw, crc)
            size -= len(raw)
    return crc & 0xffffffff

def inspect_dat(path):
    path = regular(path)
    total = path.stat().st_size
    chunks = []
    with path.open('rb') as stream:
        require(stream.read(8) == b'\x89UFU\r\n\x1a\n', 'DAT 魔数不符')
        while stream.tell() < total:
            header_offset = stream.tell()
            raw = stream.read(8)
            require(len(raw) == 8, 'DAT 块头短读')
            size, kind = struct.unpack('>I4s', raw)
            require(kind in (b'DATV', b'PROV', b'UDID', b'FDAT', b'DEND'), '未知 DAT 块')
            require(stream.tell() + size <= total, 'DAT 块越界')
            chunks.append({'kind': kind.decode(), 'offset': stream.tell(), 'size': size})
            if kind == b'DEND':
                require(size == 4 and stream.tell() + 4 == total, 'DEND 长度或尾随数据异常')
                stored = struct.unpack('>I', stream.read(4))[0]
                require(crc_prefix(path, header_offset) == stored, 'DAT 外层 CRC 失败')
                break
            stream.seek(size, 1)
    require([c['kind'] for c in chunks] == ['DATV', 'PROV', 'UDID', 'FDAT', 'DEND'], 'DAT 块集合、顺序或数量不符')
    fdat = chunks[3]
    require(fdat['size'] > 272 and (fdat['size'] - 272) % 1024 == 0, 'FDAT 长度不符')
    return {'size': total, 'chunks': chunks, 'signed_offset': fdat['offset'],
            'signed_size': fdat['size'] - 256,
            'signature_offset': fdat['offset'] + fdat['size'] - 256,
            'ciphertext_bytes': fdat['size'] - 272, 'crc32': stored}

def signature_parts(path, layout, *, flip_first=False):
    from Cryptodome.Hash import SHA256
    h = SHA256.new()
    with regular(path).open('rb') as stream:
        stream.seek(layout['signed_offset'])
        left, first = layout['signed_size'], True
        while left:
            raw = stream.read(min(CHUNK, left))
            require(raw, '签名区域短读')
            h.update(bytes([raw[0] ^ 1]) + raw[1:] if first and flip_first else raw)
            first = False
            left -= len(raw)
        signature = stream.read(256)
        require(len(signature) == 256, '签名短读')
    return h, signature

def verify_signature(path, public):
    from Cryptodome.PublicKey import RSA
    from Cryptodome.Signature import pkcs1_15
    layout = inspect_dat(path)
    h, sig = signature_parts(path, layout)
    pkcs1_15.new(RSA.import_key(public)).verify(h, sig)
    return layout, h, sig

def decode_frames(raw, final):
    """校验解密后的帧；独立于加密器的打包代码。"""
    import numpy as np
    require(len(raw) > 0 and len(raw) % 1024 == 0, '解密帧长度异常')
    words = np.frombuffer(raw, dtype='<u2').reshape(-1, 512)
    require(bool(np.all((words[:, 1:].sum(axis=1, dtype=np.uint64) & 65535) == words[:, 0])), '帧加和失败')
    sizes, flags = words[:, 1] & 32767, words[:, 1] >> 15
    expected = np.zeros(len(words), dtype=np.uint16)
    if final:
        expected[-1] = 1
    require(bool(np.array_equal(flags, expected)), '末帧标记异常')
    require(bool(np.all(sizes[:-1] == 1020)) and 0 < int(sizes[-1]) <= 1020, '帧载荷长度异常')
    require(final or int(sizes[-1]) == 1020, '非末帧短载荷')
    payload = np.frombuffer(raw, dtype=np.uint8).reshape(-1, 1024)[:, 4:].tobytes()
    padding = 1020 - int(sizes[-1]) if final else 0
    if padding:
        require(payload[-padding:] == b'\xff' * padding, '帧填充不符')
        payload = payload[:-padding]
    return payload

def decoded_chunks(path, layout):
    from Cryptodome.Cipher import AES
    from . import constants
    with regular(path).open('rb') as stream:
        stream.seek(layout['signature_offset'] - 16)
        iv = stream.read(16)
        cbc = AES.new(constants.key_cxd90057_k8, AES.MODE_CBC, iv)
        ecb = AES.new(constants.key_aes, AES.MODE_ECB)
        stream.seek(layout['signed_offset'])
        left, first = layout['ciphertext_bytes'], True
        while left:
            raw = stream.read(min(CHUNK, left))
            require(raw and len(raw) % 1024 == 0, '密文短读')
            clear = ecb.decrypt(raw[:512]) + cbc.decrypt(raw[512:]) if first else cbc.decrypt(raw)
            first = False
            left -= len(raw)
            yield decode_frames(clear, not left)

def decrypt_to(path, target):
    layout = inspect_dat(path)
    total, h = 0, hashlib.sha256()
    for chunk in decoded_chunks(path, layout):
        target.write(chunk)
        total += len(chunk)
        h.update(chunk)
    target.flush()
    target.seek(0)
    return {'plaintext_bytes': total, 'plaintext_sha256': h.hexdigest(),
            'frame_count': layout['ciphertext_bytes'] // 1024}

def header_info(header, total):
    require(len(header) == 512 and header[:8] == b'UDTRFIRM', 'FDAT 明文头不符')
    require(zlib.crc32(header[12:]) == struct.unpack_from('<I', header, 8)[0], 'FDAT 头 CRC 不符')
    minor, major = header[32], header[33]
    model, region = struct.unpack_from('<II', header, 36)
    offset, size, count = struct.unpack_from('<III', header, 48)
    require((model, region, header[16:17], header[20:21]) == (0x11030080, 0, b'U', b'N'), '机型、地区或更新模式不符')
    # 原厂 4.00 同时声明 U 槽和空 P 槽，不能删掉第二项或改写数量。
    require(count == 2, '原厂 U／P 文件系统槽数量不符')
    require(header[64:65] == b'U', '更新器文件系统模式不符')
    fs_offset, fs_size = struct.unpack_from('<II', header, 68)
    require(header[80:81] == b'P' and struct.unpack_from('<II', header, 84) == (512, 0), '原厂空 P 槽布局不符')
    require(fs_offset == 512 and fs_size > 0 and offset == 512 + fs_size and offset + size == total, 'FDAT 区域或尾随明文异常')
    require(all((v & 15) <= 9 and (v >> 4) <= 9 for v in (minor, major)), '非 BCD 版本')
    return {'major': major, 'minor': minor, 'model': hex(model), 'region': region,
            'tar_offset': offset, 'tar_bytes': size, 'updater_offset': fs_offset, 'updater_bytes': fs_size,
            'filesystem_slots': ['U', 'P-empty']}

class Part:
    """有界普通文件切片，不允许越过声明区域。"""
    def __init__(self, stream, offset, size):
        self.stream, self.offset, self.size, self.pos = stream, offset, size, 0

    def read(self, size=-1):
        size = self.size - self.pos if size < 0 else min(size, self.size - self.pos)
        self.stream.seek(self.offset + self.pos)
        raw = self.stream.read(size)
        self.pos += len(raw)
        return raw

    def seek(self, value, whence=0):
        pos = value if whence == 0 else self.pos + value if whence == 1 else self.size + value
        require(0 <= pos <= self.size, '切片 seek 越界')
        self.pos = pos
        return pos

    def tell(self):
        return self.pos
