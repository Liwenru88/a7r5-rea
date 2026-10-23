"""内存协议设备；不打开USB、不读取主机元数据。"""
from pathlib import Path
import struct
from types import SimpleNamespace
import read_only as recover
import evidence_policy as policy

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / 'reference'
if not REF.exists():
    REF = ROOT / 'packages/code85-evidence-20261021-01/reference'


def child(code=124, attempted=0, listener=0, account=1, banner=0, error=2):
    return (f'PRIVATE_RESULT code={code} errno={error} sshd_attempted={attempted} '
            f'listener_observed={listener} children_reaped=1 private_account_changed={account} '
            f'local_banner_verified={banner}\n').encode()


def files():
    return {'/version.txt': (REF / 'version.bin').read_bytes(),
            '/etc/ld.so.preload': policy.NEUTRAL,
            policy.PREFIX + '.state': policy.STATE, policy.PREFIX + '.output': policy.FINAL,
            policy.RAM + '/result': policy.FINAL, policy.RAM + '/child-result': child(),
            policy.RAM + '/diagnostic': b'', policy.RAM + '/heartbeat': b'A7R5_PRIVATE_ENDED\n'}


class Driver:
    def __init__(self, data=None, fault=None, diagnostic_error=0, errors=None):
        self.files = files() if data is None else data
        self.fault, self.diagnostic_error = fault, diagnostic_error
        self.errors = errors or {}
        self.commands, self.paths, self.labels = [], [], []
        self.reply, self.selected, self.parent_count, self.preload_count = b'', '', 0, 0

    def write(self, packet):
        size, fun, seq, *meta = recover.HEADER.unpack_from(packet)
        body = packet[recover.HEADER.size:]
        assert size == len(body) and fun == 0x40 and not any(meta)
        group, cmd = struct.unpack_from('<HH', body)
        assert group == 0x1001 and cmd in (15, 17), '禁止写、认证、START和DEBUG'
        self.commands.append(cmd)
        payload, result = b'', 0
        if cmd == 15:
            self.selected = body[5:-1].decode().replace('/tmp/jiritsu/../..', '', 1)
            self.paths.append(self.selected)
            assert body[4:5] == b'\0' and body[-1:] == b'\0'
        else:
            assert body == recover.READ
            payload = self.files[self.selected]
            if self.selected in self.errors:
                payload, result = b'', self.errors[self.selected]
            if self.selected == policy.RAM + '/diagnostic' and self.diagnostic_error:
                payload, result = b'', self.diagnostic_error
            if self.selected == policy.RAM + '/result':
                self.parent_count += 1
                if self.fault == 'parent_after' and self.parent_count == 2:
                    payload += b'changed'
            if self.selected == '/etc/ld.so.preload':
                self.preload_count += 1
                if self.fault == 'preload_after' and self.preload_count == 2:
                    payload = b''
        response = struct.pack('<I', result) + payload
        header = recover.HEADER.pack(len(response), fun, seq + (self.fault == 'sequence'), 3, 1, 2, 0)
        if self.fault in ('function', 'status', 'oversize', 'undersize'):
            values = list(recover.HEADER.unpack(header))
            values[{'function': 1, 'status': 6, 'oversize': 0, 'undersize': 0}[self.fault]] = {
                'function': 0x41, 'status': 1, 'oversize': 100000, 'undersize': 3}[self.fault]
            header = recover.HEADER.pack(*values)
        if self.fault == 'header_short':
            header = header[:-1]
        self.reply = header + response
        if self.fault == 'transport':
            raise OSError('离线传输错误')
        return len(packet) - (self.fault == 'short_write')

    def read(self, size):
        if self.fault == 'header_short':
            return self.reply[:recover.HEADER.size - 1]
        if self.fault == 'body_empty' and size != recover.HEADER.size:
            return b''
        result, self.reply = self.reply[:size], self.reply[size:]
        return result


class Interface(list):
    bInterfaceNumber = 0
    bAlternateSetting = 0
    bInterfaceClass = 255
    bInterfaceSubClass = 255
    bInterfaceProtocol = 255


def interface():
    return Interface([SimpleNamespace(bEndpointAddress=n, bmAttributes=2, wMaxPacketSize=512, bInterval=0)
                      for n in (0x81, 2, 0x83, 4)])


class Configuration:
    bConfigurationValue = 1
    def __init__(self, raw=None):
        self.raw = interface() if raw is None else raw
    def __getitem__(self, key):
        assert key == (0, 0)
        return self.raw


