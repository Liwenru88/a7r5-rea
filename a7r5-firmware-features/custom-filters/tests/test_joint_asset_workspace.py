"""完整配方在调用者工作区解码，错误不改变输出。"""
import ctypes as c
import hashlib
from pathlib import Path
import struct
import subprocess

import pytest

from import_support import Asset
from joint_support import seed

HOME = Path(__file__).resolve().parents[1]


class DecodeWork(c.Structure):
    _fields_ = [('checked', c.c_uint8 * 2483), ('candidate', Asset), ('gamma_scratch', c.c_uint32 * 129)]


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    output = tmp_path_factory.mktemp('asset-work') / 'native.so'
    result = subprocess.run(['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
        '-shared', '-fPIC', *[str(HOME / 'native' / name) for name in
        ('af_joint.c', 'af_joint_asset.c', 'af_sha256.c')], '-o', str(output)],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stderr
    lib = c.CDLL(str(output))
    lib.af_joint_asset_decode_work.argtypes = [c.c_void_p, c.c_size_t,
        c.POINTER(DecodeWork), c.POINTER(Asset)]
    lib.af_joint_asset_decode.argtypes = [c.c_void_p, c.c_size_t, c.POINTER(Asset)]
    return lib


def source():
    recipe = seed()
    body = struct.pack('<129I18h24h1215b', *recipe.gamma, *recipe.matrix,
                       *recipe.cc1, *recipe.grid)
    header = bytearray(128)
    struct.pack_into('<4sHH6I', header, 0, b'AJR1', 1, 128, len(body), 3, 0, 1, 15, 0)
    header[32:64] = bytes.fromhex('18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97')
    header[64:96] = bytes([17]) * 32
    raw = header + body
    raw[96:128] = hashlib.sha256(raw).digest()
    return c.create_string_buffer(bytes(raw)), recipe


def test_explicit_workspace_matches_original_decoder_without_borrowed_payload(api):
    raw, recipe = source()
    workspace = DecodeWork()
    output, legacy = Asset(), Asset()
    assert api.af_joint_asset_decode_work(raw, 1943, c.byref(workspace), c.byref(output)) == 0
    assert api.af_joint_asset_decode(raw, 1943, c.byref(legacy)) == 0
    assert bytes(output) == bytes(legacy)
    assert list(output.recipe.gamma) == list(recipe.gamma)
    raw[200] = b'\xff'
    assert bytes(output) == bytes(legacy)


@pytest.mark.parametrize('failure', ['corrupt', 'range', 'alias', 'null'])
def test_workspace_failure_never_publishes_partial_asset(api, failure):
    raw, _ = source()
    workspace = DecodeWork()
    output = Asset.from_buffer_copy(b'\x5a' * c.sizeof(Asset))
    before = bytes(output)
    if failure == 'corrupt':
        raw[200] = b'\xff'
    elif failure == 'range':
        data = bytearray(raw.raw[:1943])
        struct.pack_into('<I', data, 128, 1)
        data[96:128] = bytes(32)
        data[96:128] = hashlib.sha256(data).digest()
        raw = c.create_string_buffer(bytes(data))
    work = None if failure == 'null' else c.byref(workspace)
    destination = c.cast(c.byref(workspace.candidate), c.POINTER(Asset)) if failure == 'alias' else c.byref(output)
    assert api.af_joint_asset_decode_work(raw, 1943, work, destination) == -1
    assert bytes(output) == before
