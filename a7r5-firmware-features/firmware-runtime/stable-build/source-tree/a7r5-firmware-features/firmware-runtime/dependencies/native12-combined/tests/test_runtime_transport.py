"""原AP编码/传输 → 合并CP接收/发布/选择/颜色，故障包独立校验。"""
import ctypes as C
import struct
import zlib

import pytest

from runtime_support import SOURCE, LookSet, Transfer, Send, IO, CP, decoded, library


@pytest.fixture(scope='module')
def codec(tmp_path_factory):
    folder = tmp_path_factory.mktemp('runtime-codec')
    lib = library(folder, 'transport', [SOURCE/'import'/s for s in
        ('r5_stage410_codec.c', 'r5_stage413_transfer_core.c')])
    lib.r5_filter_compact_set_crc.argtypes = [C.POINTER(LookSet)]
    lib.r5_filter_compact_set_crc.restype = C.c_uint32
    lib.r5_transfer_ap_begin.argtypes = [C.POINTER(Transfer), C.POINTER(LookSet),
                                        C.c_uint32, C.c_uint32, C.c_uint64, C.c_uint64]
    lib.r5_transfer_ap_step.argtypes = [C.POINTER(Transfer), C.POINTER(IO), C.c_uint64, C.c_void_p]
    lib.r5_transfer_ap_ack.argtypes = [C.POINTER(Transfer), C.c_void_p, C.c_size_t, C.c_uint64]
    return lib


def upload(codec, cp, value, damage=None):
    state, packet = Transfer(), C.create_string_buffer(2424)
    crc = codec.r5_filter_compact_set_crc(C.byref(value))
    assert codec.r5_transfer_ap_begin(C.byref(state), C.byref(value), 0x1234, crc, 0, 1000) == 0
    observed, failures = [], []

    @Send
    def send(_, p, n):
        try:
            data = C.string_at(p, n)
            assert struct.unpack_from('<I', data, 28)[0] == zlib.crc32(data[:28]+bytes(4)+data[32:])
            if damage:
                data = damage(data)
            observed.append(cp.receive(data))
            return 0
        except Exception as error:
            failures.append(error)
            return -1

    io = IO(None, send)
    while state.phase not in (4, 5):
        result = codec.r5_transfer_ap_step(C.byref(state), C.byref(io), len(observed), packet)
        if failures:
            raise failures[0]
        assert result == 0
        ack = observed[-1]
        status = codec.r5_transfer_ap_ack(C.byref(state), ack, len(ack), len(observed))
        if status < 0:
            break
    return state, observed


def select(cp, n, seq=1, alias=0x1234, crc=None):
    crc = cp.words(cp.BANK+16, 1)[0] if crc is None else crc
    p = bytearray(struct.pack('<4B7I', 0xea, 1, 1, 32, 0x53463552, seq, n, crc, alias, 0, 0))
    struct.pack_into('<I', p, 28, zlib.crc32(p))
    cp.write(cp.PACKET, p)
    assert cp.call('r5_filter423_select', cp.PACKET, 32, cp.ACK) == 1
    return cp.words(cp.ACK+24, 1)[0]


@pytest.mark.parametrize('mask', [0, 1, 0x801, 0xfff])
def test_complete_ap_cp_transfer_seals_and_selects_exact_bank(images, codec, mask):
    cp, value = CP(images[3]), decoded(codec)
    value.mask = mask
    state, acks = upload(codec, cp, value)
    assert state.phase == 4 and state.error == 0
    assert len(acks) == mask.bit_count()+2
    assert cp.words(cp.BANK, 4) == (0x35424c53, 0x1234, mask, mask)
    assert cp.words(cp.BANK+16, 1)[0] == codec.r5_filter_compact_set_crc(C.byref(value))
    # 底层transfer发布后，原资源接收器负责登记STATE和alias；此处显式完成该边界。
    cp.write(0x1a39448, struct.pack('<II', cp.BANK, 28768))
    cp.call('r5_filter423_accept', 0x1234, 1)
    snapshot = cp.read(cp.BANK, 522152)
    for n in range(13):
        status = select(cp, n, n+1)
        assert status == (0 if not n or mask & (1 << (n-1)) else 4)
        if status == 0:
            active = cp.words(0x1a39458, 1)[0]
            assert cp.words(active, 3) == (0x423f17e1, cp.BANK, n)
    assert cp.read(cp.BANK, 522152) == snapshot, 'SELECT不得改写已封存配置'
    assert select(cp, 0, 100) == 0
    assert select(cp, 0, 1) == 3
    assert select(cp, 0, 100, alias=0x1235) == 5
    assert select(cp, 0, 100, crc=0) == 5


@pytest.mark.parametrize('damage', ['crc', 'token', 'slot', 'values', 'digest'])
def test_bad_transfer_never_publishes_or_exposes_partial_bank(images, codec, damage):
    cp, value = CP(images[3]), decoded(codec)
    def corrupt(packet):
        p = bytearray(packet)
        if p[2] == (3 if damage == 'digest' else 2):
            if damage == 'crc': p[-8] ^= 1
            elif damage == 'token': struct.pack_into('<I', p, 8, 0x4321)
            elif damage == 'slot': struct.pack_into('<I', p, 16, 12)
            elif damage == 'values': p[32] = 0
            else: struct.pack_into('<I', p, 20, 0)
            if damage != 'crc':
                p[28:32] = bytes(4)
                struct.pack_into('<I', p, 28, zlib.crc32(p))
        return bytes(p)
    state, _ = upload(codec, cp, value, corrupt)
    assert state.phase == 5 and state.error == 3
    assert cp.words(cp.BANK, 1)[0] != 0x35424c53
    assert cp.words(0x1a39458, 1)[0] == 0


def test_ap_rejects_deadline_and_forged_ack_without_activation(images, codec):
    cp, value = CP(images[3]), decoded(codec)
    state, packet = Transfer(), C.create_string_buffer(2424)
    assert codec.r5_transfer_ap_begin(C.byref(state), C.byref(value), 1, 123, 10, 20) == 0
    @Send
    def sent(_, p, n): return 0
    io = IO(None, sent)
    assert codec.r5_transfer_ap_step(C.byref(state), C.byref(io), 9, packet) == -1
    assert state.phase == 5 and state.error == 1
    state = Transfer()
    assert codec.r5_transfer_ap_begin(C.byref(state), C.byref(value), 1, 123, 0, 20) == 0
    assert codec.r5_transfer_ap_step(C.byref(state), C.byref(io), 0, packet) == 0
    assert codec.r5_transfer_ap_ack(C.byref(state), bytes(44), 44, 1) == -1
    assert state.phase == 5 and state.error == 3
