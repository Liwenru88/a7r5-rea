"""固定来源前端逐码对照及拒绝契约；只用宿主 C/NumPy，不启动模拟器。"""
import ast
import base64
import ctypes as c
import hashlib
import json
import math
from pathlib import Path
import struct
import subprocess
from types import SimpleNamespace

import numpy as np
import pytest

HOME = Path(__file__).resolve().parents[1]
ROOT = HOME.parent.parent


class Front(c.Structure):
    _fields_ = [('black', c.c_uint16*3), ('scale', c.c_uint16),
                ('wb', c.c_int16*3), ('maximum', c.c_int16),
                ('threshold', c.c_int16*3), ('weights', c.c_uint16*3)]


def sha(data):
    return hashlib.sha256(data).hexdigest()


@pytest.fixture(scope='module')
def source():
    lock = json.loads((HOME/'tests/fixtures/edit_front32_source_lock.json').read_text())
    for path, digest in lock['files'].items():
        assert sha((ROOT/path).read_bytes()) == digest, path
    decoded = {}
    for name, digest in lock['decoded'].items():
        data = base64.b64decode((ROOT/'.local/fixed-custom-filters/continuation30-color'/name).read_bytes())
        assert sha(data) == digest
        decoded[name] = data
    ns = dict(np=np, math=math, struct=struct)
    selections = [
        ('.local/fixed-custom-filters/reference-20/R5ColorLab/scripts/edit_native_model.py',
         ['_integer_array'], None),
        ('.local/fixed-custom-filters/reference30/files/R5ColorLab/scripts/edit_raw_front.py',
         ['short', 'as_shot_wb', 'itp_flatfield'], None),
        ('.local/fixed-custom-filters/reference-20/R5ColorLab/scripts/edit_color_pipeline.py',
         ['sscs'], 'RuntimeColor')]
    for path, names, owner in selections:
        tree = ast.parse((ROOT/path).read_text())
        body = tree.body if owner is None else next(x for x in tree.body if isinstance(x, ast.ClassDef) and x.name == owner).body
        nodes = [x for x in body if isinstance(x, ast.FunctionDef) and x.name in names]
        assert len(nodes) == len(names)
        exec(compile(ast.Module(nodes, []), path, 'exec'), ns)
    return decoded['v45-raw.b64'], decoded['v45-settings.b64'], ns


@pytest.fixture(scope='module')
def api(tmp_path_factory):
    path = tmp_path_factory.mktemp('edit-front')/'front.so'
    cmd = ['clang', '-std=c11', '-O2', '-Wall', '-Wextra', '-Werror',
           '-ffp-contract=off', '-fno-fast-math', '-shared', '-fPIC',
           str(HOME/'native/af_edit_front.c'), '-o', str(path)]
    run = subprocess.run(cmd, capture_output=True, text=True)
    assert run.returncode == 0, run.stderr
    lib = c.CDLL(str(path))
    lib.af_edit_front_parse_neutral.argtypes = [c.c_void_p, c.c_size_t, c.c_void_p, c.c_size_t, c.c_void_p]
    for name in ('af_edit_front_itp', 'af_edit_front_sscs'):
        getattr(lib, name).argtypes = [c.c_void_p, c.c_void_p, c.c_size_t, c.c_void_p]
    return lib


def parsed(api, raw, settings):
    p = Front()
    assert api.af_edit_front_parse_neutral(raw, len(raw), settings, len(settings), c.byref(p)) == 0
    return p


def render(api, name, p, pixels):
    data = np.ascontiguousarray(pixels, dtype=np.uint16)
    result = np.empty_like(data)
    for start in range(0, len(data), 4096):
        a = data[start:start+4096]
        b = result[start:start+4096]
        assert getattr(api, name)(c.byref(p), a.ctypes.data, len(a), b.ctypes.data) == 0
    return result


def test_full_fixed_capture_front_matches_reference_and_matrix_input(api, source, tmp_path):
    raw, settings, ns = source
    p = parsed(api, raw, settings)
    assert list(p.black) == [512]*3 and list(p.wb) == [2687, 1056, 1844]
    assert list(p.weights) == [32, 64, 32]
    with np.load(ROOT/'.local/fixed-custom-filters/reference30/pairs-v45.npz', allow_pickle=False) as data:
        codes = data['sensor_codes'].copy()
        expected = data['input'][:, 0, :].copy()
        assert np.all(data['input'] == expected[:, None, :])
    itp = render(api, 'af_edit_front_itp', p, codes)
    original_itp = ns['itp_flatfield'](codes, raw, settings)
    assert np.array_equal(itp, original_itp)
    final = render(api, 'af_edit_front_sscs', p, itp)
    original_final = ns['sscs'](SimpleNamespace(raw=raw), original_itp)
    assert np.array_equal(final, original_final)
    # 此前直接把 ITP 当矩阵输入的反例必须保留，避免把漏 SSCS 重新变成默认。
    before = np.abs(itp.astype(np.int64)-expected)
    after = np.abs(final.astype(np.int64)-expected)
    assert np.count_nonzero(before) == 64805 and before.max() == 1111
    assert not np.any(after)
    report = dict(samples=len(codes), channels=codes.size,
                  itp_vs_public_formula_max_abs=int(np.abs(itp.astype(np.int64)-original_itp).max()),
                  itp_only_vs_matrix_input=dict(differing_channels=int(np.count_nonzero(before)), max_abs=int(before.max())),
                  itp_sscs_vs_public_formula_max_abs=int(np.abs(final.astype(np.int64)-original_final).max()),
                  itp_sscs_vs_recorded_matrix_input=dict(differing_channels=int(np.count_nonzero(after)), max_abs=int(after.max()), rmse=float(np.sqrt(np.mean(after.astype(float)**2)))),
                  output_min=int(final.min()), output_max=int(final.max()),
                  raw_codes_sha256=sha(codes.astype('<u2').tobytes()),
                  itp_sha256=sha(itp.astype('<u2').tobytes()),
                  final_sha256=sha(final.astype('<u2').tobytes()),
                  domain='fixed PT/5300K RGGB uniform-field integer source only',
                  srgb_or_complete_model_qualified=False)
    (tmp_path/'full-capture.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')


def test_sscs_threshold_division_wrap_and_asymmetric_weights(api, source):
    raw, settings, ns = source
    pixels = np.concatenate((np.array([[0,0,0], [2380,2381,2382], [2381,2380,2382],
                  [2382,2381,2380], [7934,7934,7934], [7935,7936,7937],
                  [65535,65535,65535], [65535,32768,2381], [2381,32768,65535]], dtype=np.uint16),
                  np.random.default_rng(20261030).integers(0,65536,(4096,3),dtype=np.uint16)))
    scenarios = [(7934,(2380,2380,2380),(32,32,32,32)),
                 (2380,(2380,2380,2380),(255,255,255,255)),
                 (32767,(0,32767,2),(255,0,1,253)),
                 (32767,(0,0,0),(255,255,255,255))]
    for maximum, thresholds, weights in scenarios:
        modified = bytearray(raw)
        struct.pack_into('<4h', modified, 0xf82, maximum, *thresholds)
        modified[0x1207:0x120b] = bytes(weights)
        p = parsed(api, bytes(modified), settings)
        expected = ns['sscs'](SimpleNamespace(raw=bytes(modified)), pixels)
        actual = render(api, 'af_edit_front_sscs', p, pixels)
        assert np.array_equal(actual, expected), (maximum, thresholds, weights)


def test_unsupported_context_alias_and_late_invalid_code_never_publish(api, source):
    raw, settings, _ = source
    p = parsed(api, raw, settings)
    output = Front.from_buffer_copy(b'\xa5'*c.sizeof(Front))
    untouched = bytes(output)
    for offset in (0x1e8,0x1f0,0x1f4,0x1f8):
        changed = bytearray(settings)
        struct.pack_into('<i', changed, offset, 2 if offset == 0x1e8 else 1)
        assert api.af_edit_front_parse_neutral(raw,len(raw),bytes(changed),len(changed),c.byref(output)) == -2
        assert bytes(output) == untouched
    for offset in (0x84,0x4e,0x3c):
        changed = bytearray(raw)
        changed[offset] ^= 1
        assert api.af_edit_front_parse_neutral(bytes(changed),len(changed),settings,len(settings),c.byref(output)) == -2
        assert bytes(output) == untouched
    # 输入尾部错误必须在任何写出之前发现；不是边算边发布。
    incoming = np.full((4096,3),512,dtype=np.uint16)
    incoming[-1,-1] = 65535
    result = np.full_like(incoming,0xa5a5)
    assert api.af_edit_front_itp(c.byref(p),incoming.ctypes.data,len(incoming),result.ctypes.data) == -1
    assert np.all(result == 0xa5a5)
    incoming[-1,-1] = 512
    for name in ('af_edit_front_itp','af_edit_front_sscs'):
        fn = getattr(api,name)
        assert fn(c.byref(p),incoming.ctypes.data,4096,incoming.ctypes.data) == -1
        assert fn(c.byref(p),incoming.ctypes.data,0,result.ctypes.data) == -1
        assert fn(c.byref(p),incoming.ctypes.data,4097,result.ctypes.data) == -1
        broken = Front.from_buffer_copy(p)
        broken.threshold[1] = broken.maximum+1
        assert fn(c.byref(broken),incoming.ctypes.data,4096,result.ctypes.data) == -1
        assert np.all(result == 0xa5a5)
    rawbuf = c.create_string_buffer(raw)
    assert api.af_edit_front_parse_neutral(rawbuf,len(raw),settings,len(settings),rawbuf) == -1
    assert rawbuf.raw[:len(raw)] == raw
