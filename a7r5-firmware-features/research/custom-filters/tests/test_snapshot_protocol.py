"""快照覆盖退出控制的字节契约和未协商端拒绝；仅执行宿主C。"""
import ctypes as c
from pathlib import Path
import struct
import subprocess
import zlib

NATIVE = Path(__file__).resolve().parents[1] / 'native'


class Preset(c.Structure):
    _fields_ = [('base', c.c_uint8), ('kind', c.c_uint8), ('params', c.c_int8 * 8),
                ('payload', c.c_uint8 * 32), ('lut', c.c_uint8 * 32)]


class Packet(c.Structure):
    _fields_ = [('operation', c.c_uint32), ('required', c.c_uint32), ('slot', c.c_uint32),
                ('session', c.c_uint64), ('version', c.c_uint64), ('preset', Preset)]


def test_release_requires_negotiated_overlay_and_has_no_fabricated_preset(tmp_path):
    apis = []
    for overlay in (False, True):
        out = tmp_path / f'wire-{overlay}.so'
        cmd = ['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror', '-shared', '-fPIC',
               '-DAF_FACTORY_RESTORE406=1', '-I'+str(NATIVE)]
        if overlay:
            cmd += ['-DAF_SNAPSHOT_OVERLAY406=1']
        cmd += [str(NATIVE / n) for n in ('af_slots.c', 'af_apply_wire.c')]
        built = subprocess.run(cmd + ['-o', str(out)], capture_output=True, text=True)
        assert built.returncode == 0, built.stderr
        api = c.CDLL(str(out))
        api.af_apply_packet_encode.argtypes = [c.POINTER(Packet), c.c_void_p, c.c_size_t, c.POINTER(c.c_size_t)]
        api.af_apply_packet_decode.argtypes = [c.c_void_p, c.c_size_t, c.POINTER(Packet)]
        apis.append(api)
    old, current = apis
    wire = c.create_string_buffer(128)
    size = c.c_size_t()
    packet = Packet(operation=3, required=0x31fff, session=71, version=9)
    assert current.af_apply_packet_encode(c.byref(packet), wire, 128, c.byref(size)) == 0
    raw = wire.raw
    assert size.value == 128 and struct.unpack_from('<H', raw, 6)[0] == 3
    assert struct.unpack_from('<QQI', raw, 16) == (71, 9, 0)
    assert raw[36:48] == bytes(12) and raw[116:124] == bytes(8)
    assert struct.unpack_from('<I', raw, 124)[0] == zlib.crc32(raw[:124])
    parsed = Packet()
    assert current.af_apply_packet_decode(wire, 128, c.byref(parsed)) == 0
    assert old.af_apply_packet_decode(wire, 128, c.byref(parsed)) == -1
    for field, value in (('required', 0x11fff), ('slot', 7), ('version', 0), ('session', 0)):
        previous = getattr(packet, field)
        setattr(packet, field, value)
        assert current.af_apply_packet_encode(c.byref(packet), wire, 128, c.byref(size)) == -1
        assert wire.raw == raw
        setattr(packet, field, previous)
    # 控制包不接受隐藏配方/摘要，解码也不得接受有CRC的非零载荷。
    packet.preset.payload[0] = 1
    assert current.af_apply_packet_encode(c.byref(packet), wire, 128, c.byref(size)) == -1
    bad = bytearray(raw)
    bad[38] = 2
    struct.pack_into('<I', bad, 124, zlib.crc32(bad[:124]))
    assert current.af_apply_packet_decode(c.create_string_buffer(bytes(bad)), 128, c.byref(parsed)) == -1
