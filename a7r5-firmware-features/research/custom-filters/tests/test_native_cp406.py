"""真实C纯参数适配：基底转换、其余帧字段保持、非法/LUT输入不写输出。"""
import ctypes as c
from pathlib import Path
import subprocess

import pytest

from test_native_slots import Preset, preset

NATIVE = Path(__file__).resolve().parents[1] / 'native'
SIZE = 0xe70
FIELDS = [0xa44, 0xa46, 0xa45, 0xa47, 0xa48, 0xd2e, 0xd2f, 0xd30]
ROUTES = [(0,0),(1,3),(2,2),(3,1),(4,16),(5,15),(6,17),(7,18),(8,5),(9,13),(17,19),(18,20)]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    output = tmp_path_factory.mktemp('af-cp406') / 'cp406.so'
    result = subprocess.run(['clang', '-std=c11', '-Wall', '-Wextra', '-Werror', '-O2',
                             '-fPIC', '-shared', str(NATIVE/'af_slots.c'),
                             str(NATIVE/'af_cp406.c'), '-o', str(output)],
                            capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    lib = c.CDLL(str(output))
    lib.af_cp406_overlay.argtypes = [c.POINTER(Preset), c.c_void_p, c.c_void_p, c.c_size_t]
    lib.af_cp406_matches.argtypes = [c.POINTER(Preset), c.c_void_p, c.c_size_t]
    return lib


def test_every_base_matches_wire_fields_and_retains_frame_metadata(api):
    original = bytes((i * 17 + 3) % 256 for i in range(SIZE))
    source = c.create_string_buffer(original)
    for index, (base, wire) in enumerate(ROUTES):
        p = preset(base)
        p.params[:] = [-9, 9, -8, 7, -6, 5, 4, 3] if index & 1 else [9,-9,8,0,6,0,1,9]
        output = c.create_string_buffer(b'\xa5' * (SIZE + 16))
        at = c.addressof(output) + 8
        assert api.af_cp406_overlay(c.byref(p), source, at, SIZE) == 0
        expected = bytearray(original)
        expected[0xa40:0xa44] = wire.to_bytes(4, 'little')
        for field, value in zip(FIELDS, p.params):
            expected[field] = value & 255
        assert output.raw[:SIZE+16] == b'\xa5'*8 + bytes(expected) + b'\xa5'*8
        assert source.raw[:SIZE] == original
        assert api.af_cp406_matches(c.byref(p), at, SIZE) == 0
        for field in [0xa40, 0xa41, 0xa42, 0xa43, *FIELDS]:
            changed = c.create_string_buffer(bytes(expected))
            changed[field] = bytes([expected[field] ^ 1])
            assert api.af_cp406_matches(c.byref(p), changed, SIZE) == -5


def test_rejected_inputs_keep_destination_and_source(api):
    source, output = c.create_string_buffer(b'\x33'*SIZE), c.create_string_buffer(b'\xa5'*SIZE)
    bad = [None, preset(16), preset(19), preset(255)]
    lut = preset(17)
    lut.kind = 1
    lut.payload_sha256[:] = [1]*32
    lut.lut_sha256[:] = [2]*32
    bad.append(lut)
    for parameter, value in ((0, 10), (3, -1), (6, 0), (6, 6), (7, 10)):
        p = preset()
        p.params[parameter] = value
        bad.append(p)
    for p in bad:
        pointer = c.byref(p) if p is not None else None
        assert api.af_cp406_overlay(pointer, source, output, SIZE) == -1
        assert api.af_cp406_matches(pointer, source, SIZE) == -1
        assert output.raw[:SIZE] == b'\xa5'*SIZE
    p = preset()
    for src, dst, size in ((None, output, SIZE), (source, None, SIZE),
                           (source, output, SIZE-1), (source, source, SIZE),
                           (source, c.addressof(source)+1, SIZE),
                           (c.addressof(source)+1, source, SIZE),
                           (source, output, c.c_size_t(-1).value)):
        assert api.af_cp406_overlay(c.byref(p), src, dst, size) == -1
    assert output.raw[:SIZE] == b'\xa5'*SIZE and source.raw[:SIZE] == b'\x33'*SIZE
