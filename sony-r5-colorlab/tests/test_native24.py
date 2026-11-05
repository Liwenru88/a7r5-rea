"""用独立旧成品和固件解码器约束本地24槽格式。"""
import copy
import ctypes as C
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys
import zlib

import pytest

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent


def load_codec(path):
    spec = importlib.util.spec_from_file_location(path.parent.name + '_codec', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(params=['R5ColorLab/compilers/custom_filter_v4.py', 'R5GridCalibrator/bin_v4.py'])
def codec(request):
    return load_codec(ROOT / request.param)


def entries(codec, slots):
    original = codec.unpack((REPO / 'a7r5-firmware-features/native24-combined/dependencies/native12-combined/releases/4.11/R5NATIVE.BIN').read_bytes())
    result = []
    for slot in slots:
        entry = copy.deepcopy(original['entries'][(slot - 1) % 12])
        entry.update(number=slot, short_name=f'TEST{slot}', full_name=f'容量测试槽 {slot}')
        result.append(entry)
    return result


@pytest.mark.parametrize('slots,version', [(range(1, 13), 4), (range(1, 25), 5), ([24], 5), ([1, 12, 13, 24], 5)])
def test_expanded_slot_formats(codec, slots, version):
    value = codec.config(entries(codec, slots))
    data = codec.pack(value)
    assert data[:8] == f'R5CUST{version}\0'.encode()
    assert struct.unpack_from('<5I', data, 8) == (version, 128, 128 + len(slots) * 2452, len(slots), sum(1 << (i - 1) for i in slots))
    assert codec.unpack(data) == value


def test_original_twelve_bytes_preserved(codec):
    for name in ['a7r5-firmware-features/native24-combined/dependencies/native12-combined/releases/4.11/R5NATIVE.BIN',
                 'sony-r5-colorlab/filters/FUJ_12_v45_three_experts_20261102/R5NATIVE.BIN']:
        data = (REPO / name).read_bytes()
        assert codec.pack(codec.unpack(data)) == data


@pytest.fixture(scope='session')
def firmware_decoders(tmp_path_factory):
    candidate = json.loads((REPO / 'a7r5-firmware-features/native24-combined/current-candidate.json').read_text())
    build = REPO / candidate['build']
    receipt = json.loads((build / 'build.json').read_text())
    assert receipt['AP_sha256'] == candidate['AP_sha256']
    assert hashlib.sha256((build / 'appFw.so').read_bytes()).hexdigest() == candidate['AP_sha256']
    contracts = {r['path']: r['after_sha256'] for r in receipt['derived_files']}
    current = build / 'work/import'
    for name in ('r5_stage410_codec.c', 'sd_native_look.h'):
        assert hashlib.sha256((current / name).read_bytes()).hexdigest() == contracts['import/' + name]
    legacy = REPO / 'a7r5-firmware-features/native24-combined/dependencies/native12-combined/upstream/firmware/r5/src/import'
    folder = tmp_path_factory.mktemp('real-firmware-codecs')
    result = {}
    for count, source in ((12, legacy), (24, current)):
        output = folder / f'codec{count}.dylib'
        command = ['clang', '-shared', '-fPIC', '-O1', '-fno-builtin', '-I', str(source),
                   str(source / 'r5_stage410_codec.c'), '-o', str(output)]
        subprocess.run(command, check=True, capture_output=True)
        lib = C.CDLL(str(output))
        lib.r5_decode_look_file.argtypes = [C.c_void_p, C.c_size_t, C.c_void_p]
        lib.r5_encode_look_file.argtypes = [C.c_void_p, C.c_void_p, C.c_size_t]
        lib.r5_encode_look_file.restype = C.c_size_t
        result[count] = lib
    return result


@pytest.mark.parametrize('slots', [[], [1], list(range(1, 13)), [24], [1, 12, 13, 24], list(range(1, 25))])
def test_current_and_legacy_firmware_contract(codec, firmware_decoders, slots):
    data = codec.pack(codec.config(entries(codec, slots)))
    for count, lib in firmware_decoders.items():
        state = C.create_string_buffer(b'\xa5' * (4 + count * 2444))
        before = state.raw
        decoded = lib.r5_decode_look_file(data, len(data), state)
        if any(s > 12 for s in slots) and count == 12:
            assert decoded == 2 and state.raw == before
            continue
        assert decoded == 0
        assert struct.unpack_from('<I', state.raw)[0] == sum(1 << (s - 1) for s in slots)
        output = C.create_string_buffer(58976)
        size = lib.r5_encode_look_file(state, output, len(output))
        assert output.raw[:size] == data


@pytest.mark.parametrize('damage', ['crc', 'version', 'v4_high_slot', 'mask', 'model', 'baseline',
                                  'reserved', 'duplicate', 'last_grid', 'padding', 'utf8', 'truncated', 'trailing'])
def test_corruption_rejected_by_tool_and_firmware(codec, firmware_decoders, damage):
    data = bytearray(codec.pack(codec.config(entries(codec, [1, 24]))))
    if damage == 'version': struct.pack_into('<I', data, 8, 6)
    elif damage == 'v4_high_slot': data[:8] = b'R5CUST4\0'; struct.pack_into('<I', data, 8, 4)
    elif damage == 'mask': struct.pack_into('<I', data, 24, 1)
    elif damage == 'model': data[32] ^= 1
    elif damage == 'baseline': data[48] ^= 1
    elif damage == 'reserved': data[116] = 1
    elif damage == 'duplicate': struct.pack_into('<I', data, 128 + 2452, 1)
    elif damage == 'last_grid': data[128 + 2452 + 1232] = 64
    elif damage == 'padding': data[-1] = 1
    elif damage == 'utf8': data[132:134] = b'\xc0\x80'
    elif damage == 'truncated': data.pop()
    elif damage == 'trailing': data += b'\0'
    if damage == 'crc': data[220] ^= 1
    else:
        struct.pack_into('<I', data, 112, 0)
        struct.pack_into('<I', data, 112, zlib.crc32(data))
    with pytest.raises(ValueError): codec.unpack(data)
    output = C.create_string_buffer(b'\xa5' * 58660)
    before = output.raw
    assert firmware_decoders[24].r5_decode_look_file(bytes(data), len(data), output) == 2
    assert output.raw == before


@pytest.mark.parametrize('number', [0, 25, True, 1.0, '24'])
def test_invalid_slot_never_coerced(codec, number):
    value = entries(codec, [1]); value[0]['number'] = number
    with pytest.raises(ValueError): codec.pack(codec.config(value))


def test_command_line_format_and_no_overwrite(tmp_path):
    script = ROOT / 'R5ColorLab/compilers/custom_filter_v4.py'
    codec = load_codec(script)
    source = tmp_path / 'native.json'
    source.write_text(json.dumps(codec.config(entries(codec, [1, 24]))))
    original = source.read_bytes()
    target = tmp_path / 'R5NATIVE.BIN'
    command = [sys.executable, str(script), str(source), '--output', str(target)]
    bad = subprocess.run(command + ['--format', '4'], capture_output=True)
    assert bad.returncode != 0 and not target.exists()
    good = subprocess.run(command, capture_output=True, text=True)
    assert good.returncode == 0 and json.loads(good.stdout)['version'] == 5
    assert codec.unpack(target.read_bytes())['entries'] == codec.load(source)['entries']
    saved = target.read_bytes()
    again = subprocess.run(command, capture_output=True)
    assert again.returncode != 0 and target.read_bytes() == saved
    assert source.read_bytes() == original
