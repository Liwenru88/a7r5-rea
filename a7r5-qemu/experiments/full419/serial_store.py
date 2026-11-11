"""串口异步内核日志不能混入声音文件的十六进制载荷。"""
import base64
import hashlib
import importlib.util
from pathlib import Path
import re
import struct
import zlib


def decode_serial_hex(encoded):
    encoded = re.sub(rb'\[\s*\d+\.\d+\] \[K\]\*\*UIPC ERROR\*\* [^\r\n]*', b'', encoded)
    parts = []
    for line in encoded.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.fullmatch(rb'[0-9a-f]+', line):
            parts.append(line)
        elif not re.fullmatch(rb'\[\s*\d+\.\d+\] \[K\]\*\*UIPC ERROR\*\* .*', line):
            raise ValueError('导出串口出现未知数据，拒绝补写文件')
    return bytes.fromhex(b''.join(parts).decode('ascii'))


def validate_exports(exported):
    files = {k: base64.b64decode(v, validate=True) for k, v in exported.items()}
    pro, idx = files['R5SOUND.PRO'], files['R5SOUND.IDX']
    if (len(pro) != 96 or pro[:8] != b'R5SNDPF1'
            or struct.unpack_from('<I', pro, 92)[0] != zlib.crc32(pro[:92])
            or idx[:8] != b'R5SNDIDX' or len(idx) != 624
            or struct.unpack_from('<I', idx, 24)[0] != zlib.crc32(idx[32:])):
        raise ValueError('导出的设置或目录校验失败')
    tool = Path(__file__).resolve().parents[3] / 'a7r5-firmware-features/photo-electronic-shutter-sound/host/prepare_sound.py'
    spec = importlib.util.spec_from_file_location('full419_sound_reader', tool)
    reader = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(reader)
    expected = {'R5SOUND.PRO', 'R5SOUND.IDX'}
    for i in range(2):
        row = idx[32+i*296:32+(i+1)*296]
        identity = row[256:288]
        name = 'R5SN_' + identity.hex() + '.R5S'
        blob = files[name]
        if hashlib.sha256(blob[:416]).digest() != identity or len(blob) != struct.unpack_from('<I', row, 288)[0]:
            raise ValueError('导出的声音内容身份不符')
        reader.inspect_bytes(blob)
        expected.add(name)
    if set(files) != expected:
        raise ValueError('导出文件集合不符')
