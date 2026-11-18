"""电脑配方封装器与真实C codec交叉校验；仅执行宿主代码和普通临时文件。"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import struct
import subprocess
import sys

import pytest


TOOL = Path(__file__).resolve().parents[1] / "tools/recipe_file.py"
SPEC = importlib.util.spec_from_file_location("recipe_file_tool", TOOL)
tool = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(tool)
CP_SHA = "18b265c589eb4201d3b3680857d897b693d06c6dd491d795dbb3a616d6182e97"
MODEL = hashlib.sha256(b"EXPLICIT_DESKTOP_TEST_MODEL_NOT_CAMERA").digest()


@pytest.fixture(scope="module")
def api():
    with tool.native_codec() as value:
        yield value


def asset(native=True):
    seed = [i * 1024 for i in range(129)]
    body = bytearray(1815)
    if native:
        bits = sum(value << (18 * i) for i, value in enumerate(seed))
        body[:291] = bits.to_bytes(291, "little")
        struct.pack_into("<3h", body, 292, 32, -48, 64)
        body[300:332] = hashlib.sha256(struct.pack("<129I", *seed)).digest()
        struct.pack_into("<I", body, 332, 1)
    else:
        struct.pack_into("<129I", body, 0, *seed)
    header = struct.pack("<4sHH6I", b"AJR2" if native else b"AJR1", 2 if native else 1,
                         128, 1815, 7 if native else 3, 0, 1, 15, 0)
    raw = bytearray(header + bytes.fromhex(CP_SHA) + MODEL + bytes(32) + body)
    raw[96:128] = hashlib.sha256(raw).digest()
    return bytes(raw)


def metadata():
    return {"schema": tool.METADATA_SCHEMA, "target_cp_sha256": CP_SHA,
            "base": 0, "name": "电脑暖光", "lut_sha256": hashlib.sha256(b"original cube").hexdigest(),
            "model_sha256": MODEL.hex(), "initial_params": [0, 0, 0, 0, 0, 0, 3, 0],
            "saved_params": [2, -1, 1, 3, 1, 2, 4, 1],
            "report": {"samples": 43, "clipped": 2, "delta_e76_milli": [1000, 2000, 3000, 900, 1200], "scope": 1}}


def test_desktop_result_preserves_exact_ajr2_and_both_parameter_snapshots(api):
    raw, meta = asset(), metadata()
    packed = tool.pack(raw, meta, api)
    # 按公开字节布局独立检查，不通过Python重新封装作为预期值。
    assert packed[:8] == b"AFD1\x01\x00\x00\x01"
    assert struct.unpack_from("<2I", packed, 8) == (0x314A4641, 2)
    assert packed[256:256 + len(meta["name"].encode())] == meta["name"].encode()
    assert packed[-1943:] == raw
    assert struct.unpack_from("<8b", packed, 90) == tuple(meta["initial_params"])
    assert struct.unpack_from("<8b", packed, 164) == tuple(meta["saved_params"])
    assert packed[98:130] == packed[172:204] == hashlib.sha256(raw).digest()
    report = tool.inspect(packed, api)
    assert report["supported_for_sd_import"] is True
    assert report["camera_verified"] is False
    assert report["report_applies_to_saved"] is False
    assert report["report"]["delta_e76_milli"] == meta["report"]["delta_e76_milli"]
    assert report["saved_params"] == meta["saved_params"]


@pytest.mark.parametrize("field,value", [
    ("unknown", 1), ("schema", "future"), ("target_cp_sha256", "ab" * 32),
    ("model_sha256", "cd" * 32), ("base", 18), ("base", True),
    ("name", "坏\n名"), ("name", "暖" * 22), ("initial_params", [0] * 7),
    ("saved_params", [0] * 8), ("lut_sha256", "0" * 64),
])
def test_metadata_must_match_target_complete_native_format_and_utf8_rules(api, field, value):
    meta = metadata()
    meta[field] = value
    with pytest.raises(tool.RecipeFileError):
        tool.pack(asset(), meta, api)


@pytest.mark.parametrize("field,value", [("scope", 2), ("scope", True), ("samples", 0),
                                          ("clipped", 44), ("delta_e76_milli", [5, 6, 1, 0, 0])])
def test_error_report_is_structurally_checked_but_not_promoted_to_camera_measurement(api, field, value):
    meta = metadata()
    meta["report"][field] = value
    with pytest.raises(tool.RecipeFileError):
        tool.pack(asset(), meta, api)


def test_ajr1_is_inspectable_but_cannot_be_packed_for_new_import(api):
    info = tool.inspect(asset(native=False), api)
    assert info["format"] == "AJR1" and info["supported_for_sd_import"] is False
    with pytest.raises(tool.RecipeFileError, match="AJR2"):
        tool.pack(asset(native=False), metadata(), api)


def test_exported_pure_parameter_document_is_supported_for_reimport(api):
    name = '纯参数'.encode()
    header = bytearray(256)
    header[:8] = b'AFD1\x01\x00\x00\x01'
    struct.pack_into('<I', header, 16, len(name))
    # 纯参数允许初始和保存基底不同；不包含LUT、模型或成像载荷。
    header[88:162] = struct.pack('<BB8b32s32s', 0, 0, 0, 0, 0, 0, 0, 0, 3, 0, bytes(32), bytes(32))
    header[162:236] = struct.pack('<BB8b32s32s', 18, 0, 1, 0, 0, 0, 0, 0, 3, 0, bytes(32), bytes(32))
    struct.pack_into('<I', header, 236, 1)
    info = tool.inspect(bytes(header) + name, api)
    assert info['kind'] == 0 and info['supported_for_sd_import'] is True
    assert info['camera_verified'] is False and 'report' not in info


@pytest.mark.parametrize("offset", [32, 128 + 300, 128 + 292, 128 + 600])
def test_ajr2_rejects_incompatible_cp_bad_seed_tone_and_grid_even_with_recomputed_sha(api, offset):
    raw = bytearray(asset())
    if offset == 128 + 292:
        struct.pack_into("<h", raw, offset, 1025)
    elif offset == 128 + 600:
        raw[offset] = 64
    else:
        raw[offset] ^= 1
    raw[96:128] = bytes(32)
    raw[96:128] = hashlib.sha256(raw).digest()
    with pytest.raises(tool.RecipeFileError, match="原生格式校验拒绝"):
        tool.pack(bytes(raw), metadata(), api)


@pytest.mark.parametrize("raw", [b'{"a":1,"a":2}', b'{"value":NaN}', b'{"value":Infinity}'])
def test_json_does_not_silently_accept_duplicate_or_nonfinite_metadata(raw):
    with pytest.raises(tool.RecipeFileError):
        tool.load_metadata(raw)


def run_cli(*args):
    return subprocess.run([sys.executable, "-B", str(TOOL), *map(str, args)],
                          capture_output=True, text=True)


def test_cli_pack_inspect_and_existing_output_preserved(tmp_path):
    source, meta_file, output = tmp_path / "fit.ajr", tmp_path / "fit.json", tmp_path / "暖光.a7filter"
    source.write_bytes(asset())
    meta_file.write_text(json.dumps(metadata(), ensure_ascii=False), encoding="utf-8")
    result = run_cli("pack", "--asset", source, "--metadata", meta_file, "--output", output)
    assert result.returncode == 0, result.stderr
    before = output.read_bytes()
    assert json.loads(result.stdout)["supported_for_sd_import"] is True
    result = run_cli("inspect", output)
    assert result.returncode == 0 and json.loads(result.stdout)["report_applies_to_saved"] is False
    result = run_cli("pack", "--asset", source, "--metadata", meta_file, "--output", output)
    assert result.returncode == 1 and output.read_bytes() == before
    assert source.read_bytes() == asset()


def test_invalid_cli_metadata_and_link_input_never_create_output(tmp_path):
    source, meta_file, output = tmp_path / "fit.ajr", tmp_path / "fit.json", tmp_path / "bad.a7filter"
    source.write_bytes(asset())
    invalid = copy.deepcopy(metadata())
    invalid["model_sha256"] = "de" * 32
    meta_file.write_text(json.dumps(invalid), encoding="utf-8")
    result = run_cli("pack", "--asset", source, "--metadata", meta_file, "--output", output)
    assert result.returncode == 1 and not output.exists()
    link = tmp_path / "link.ajr"
    link.symlink_to(source)
    with pytest.raises(OSError):
        tool.read_regular(link, 1943)
