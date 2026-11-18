"""参数来源隔离和CC1选择；合成字节只验证解码，不冒充公开捕获。"""
import hashlib
from pathlib import Path
import struct
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from a7filters.reference_snapshot import decode_parameters, load_edit_snapshot, EditSnapshot, FILES


def context(mode=1):
    runtime = bytearray(670656)
    raw = bytearray(5120)
    settings = bytearray(768)
    struct.pack_into('<f', runtime, 0x91964, 1.0)
    struct.pack_into('<i', settings, 0x1e8, mode)
    return runtime, raw, settings


def test_cc1_direct_weighted_delta_modes_and_signed_halfword():
    runtime, raw, settings = context()
    raw[0x1c] = 1
    direct = (-123, 456, -32768, 32767, 12, -13, 14, -15)
    struct.pack_into('<8h', raw, 0xddc, *direct)
    assert decode_parameters(bytes(runtime), bytes(raw), bytes(settings)).cc1 == direct
    raw[0x1c] = 0
    struct.pack_into('<8h', raw, 0xdec, *([32767]*8))
    # -1/1024必须算术右移为-1，不能向零截断。
    struct.pack_into('<32h', raw, 0xdfc, *([-1]*8 + [2]*8 + [0]*16))
    struct.pack_into('<4h', raw, 0xe44, 1, 0, 0, 0)
    assert decode_parameters(bytes(runtime), bytes(raw), bytes(settings)).cc1 == (32766,)*8
    struct.pack_into('<i', settings, 0x1e8, 7)
    struct.pack_into('<8h', raw, 0xe1c, *([1]*8))
    assert decode_parameters(bytes(runtime), bytes(raw), bytes(settings)).cc1 == (-32768,)*8
    struct.pack_into('<i', settings, 0x1e8, 9)
    with pytest.raises(ValueError, match='选择模式'):
        decode_parameters(bytes(runtime), bytes(raw), bytes(settings))


def test_parameters_keep_native_ranges_and_reject_invalid_context():
    runtime, raw, settings = context()
    runtime[0x18f6:0x18fa] = b'\x34\x12\xcd\xab'
    struct.pack_into('<3h', runtime, 0x218f6, -32768, 12, 32767)
    struct.pack_into('<h', settings, 0x2ac, -3)
    struct.pack_into('<h', settings, 0x2b0, 511)
    p = decode_parameters(bytes(runtime), bytes(raw), bytes(settings))
    assert len(p.gamma) == 131072 and p.gamma[:4] == b'\x34\x12\xcd\xab'
    assert p.luma == (-32768, 12, 32767) and p.level == -3
    assert len(p.y_gamma) == 65536 and len(p.gamma_axis) == 128
    assert len(p.matrix_payload) == 276 and p.keep_chroma_unclipped is False
    struct.pack_into('<f', runtime, 0x91964, float('nan'))
    with pytest.raises(ValueError, match='明度'):
        decode_parameters(bytes(runtime), bytes(raw), bytes(settings))
    with pytest.raises(ValueError, match='长度'):
        decode_parameters(bytes(runtime[:-1]), bytes(raw), bytes(settings))


def test_snapshot_cannot_accept_wrong_size_hash_or_symbolic_file(tmp_path):
    name, size, digest = FILES[0]
    path = tmp_path/name
    path.write_bytes(b'wrong')
    with pytest.raises(ValueError, match='大小'):
        load_edit_snapshot(tmp_path)
    path.write_bytes(b'\0'*size)
    assert hashlib.sha256(path.read_bytes()).hexdigest() != digest
    with pytest.raises(ValueError, match='摘要'):
        load_edit_snapshot(tmp_path)
    # 创建新的目录验证符号链接，无需覆盖原测试证据。
    linked = tmp_path/'linked'
    linked.mkdir()
    (linked/name).symlink_to(path)
    with pytest.raises(OSError):
        load_edit_snapshot(linked)


def test_snapshot_parameters_are_derived_and_cannot_be_injected():
    class Spoof:
        def __ne__(self, other):
            return False
    with pytest.raises(TypeError):
        EditSnapshot(b'', b'', b'', Spoof())
    with pytest.raises(TypeError):
        EditSnapshot(b'', b'', b'', parameters=Spoof())
