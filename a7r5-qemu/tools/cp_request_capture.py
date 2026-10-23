"""离线解析预留 RAM 中的原厂 CP 初始化请求；不生成或发送 CP 回复。"""
import hashlib
import json
from pathlib import Path
import socket
import struct

CAPTURE_ADDRESS = 0x41ea00000
CAPTURE_BYTES = 16384
SLOT_BYTES = 4096
PAYLOAD_BYTES = 2400


def fnv64(raw):
    value = 14695981039346656037
    for byte in raw:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return value


def decode_capture(raw):
    if len(raw) != CAPTURE_BYTES:
        raise ValueError('CP 捕获区域长度不符')
    records = []
    empty_seen = False
    for sequence in range(4):
        slot = raw[sequence*SLOT_BYTES:(sequence+1)*SLOT_BYTES]
        if slot == bytes(SLOT_BYTES):
            empty_seen = True
            continue
        if empty_seen:
            raise ValueError('CP 捕获序列不连续')
        magic, version, actual, destination, source, count, committed, checksum = struct.unpack_from('<8s6IQ', slot)
        if (magic, version, actual, destination, source, count, committed) != (
                b'A7CPINIT', 1, sequence, 0x90030001, 0x80020002, PAYLOAD_BYTES, 1):
            raise ValueError('CP 捕获头、来源或提交状态不符')
        payload = slot[64:64+count]
        if payload[:8] != bytes.fromhex('0500634003000080') or fnv64(payload) != checksum:
            raise ValueError('CP 初始化请求身份或完整性不符')
        if any(slot[40:64]) or any(slot[64+count:]):
            raise ValueError('CP 捕获保留区域非零')
        records.append({'sequence': sequence, 'payload': payload,
                        'sha256': hashlib.sha256(payload).hexdigest(),
                        'fnv1a64': f'{checksum:016x}', 'bytes': count})
    if not records:
        raise ValueError('没有捕获完整 CP 初始化请求')
    return records


def export_capture(vm):
    """协议失败后只通过宿主 QMP 暂停和导出；不再发送客体命令。"""
    target = vm.out/'cp-init-reserved.bin'
    receipt = vm.out/'cp-init-capture.json'
    if target.exists() or receipt.exists():
        raise ValueError('拒绝覆盖 CP 捕获证据')
    vm.set_native_paused(True)
    with socket.socket(socket.AF_UNIX) as sock:
        sock.settimeout(10)
        vm.connect_qmp(sock)
        with sock.makefile('rwb') as stream:
            if 'QMP' not in json.loads(stream.readline()):
                raise RuntimeError('CP 捕获 QMP 握手不符')
            for command in ({'execute': 'qmp_capabilities'}, {
                    'execute': 'pmemsave', 'arguments': {'val': CAPTURE_ADDRESS,
                    'size': CAPTURE_BYTES, 'filename': str(target)}}):
                stream.write(json.dumps(command).encode()+b'\n')
                stream.flush()
                while True:
                    reply = json.loads(stream.readline())
                    if 'error' in reply:
                        raise RuntimeError(str(reply['error']))
                    if 'return' in reply:
                        break
    rows = decode_capture(target.read_bytes())
    record = {'status': 'original_AP_request_captured', 'raw_sha256': hashlib.sha256(target.read_bytes()).hexdigest(),
              'records': [], 'CP_firmware_running': False, 'ISP_verified': False,
              'guest_commands_after_failure': 0, 'CP_replies_added': 0}
    for row in rows:
        row = dict(row)
        payload = row.pop('payload')
        name = f'cp-init-{row["sequence"]:02d}.bin'
        with (vm.out/name).open('xb') as output:
            output.write(payload)
        record['records'].append(dict(row, file=name))
    with receipt.open('x') as output:
        json.dump(record, output, ensure_ascii=False, indent=2)
        output.write('\n')
    return record
