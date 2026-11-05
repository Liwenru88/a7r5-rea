#!/usr/bin/env python3
"""将已有AJR2拟合结果封装成完整AFD1；只执行宿主校验，不训练或连接相机。"""
from __future__ import annotations

import argparse
import contextlib
import ctypes
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import struct
import subprocess
import sys
import tempfile


HOME = Path(__file__).resolve().parents[1]
NATIVE = HOME / "native"
METADATA_SCHEMA = "a7r5-recipe-file/1"
ASSET_SCHEMA = 0x314A4641
ASSET_BYTES = 1943
SECTOR_BYTES = 2483
DOCUMENT_MAX = 256 + 63 + SECTOR_BYTES
METADATA_MAX = 65536
_SOURCES = (
    "af_slots.c", "af_document.c", "af_sha256.c", "af_joint.c",
    "af_joint_asset.c", "af_import.c", "af_joint_fit.c", "af_joint_report.c",
    "af_grid.c", "af_grid_fit.c", "af_cube.c",
)
_BRIDGE = r'''
#include "af_import.h"
int recipe_file_asset(const void *raw,size_t bytes){
    AfJointAsset value;return af_joint_asset_decode(raw,bytes,&value);
}
int recipe_file_document(const void *raw,size_t bytes){
    AfDocument document;AfJointAsset asset;
    int result=af_document_decode(raw,bytes,AF_JOINT_ASSET_SCHEMA,&document);
    if(result)return result;
    if(document.present!=1)return AF_INVALID;
    return document.initial.kind?af_import_asset(&document,&asset):AF_OK;
}
'''


class RecipeFileError(ValueError):
    """格式、兼容性或宿主校验错误。"""


def read_regular(path: Path, maximum: int) -> bytes:
    """只读取有界普通文件，拒绝设备、链接和读取期间变化。"""
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(fd, "rb") as stream:
        before = os.fstat(stream.fileno())
        if not stat.S_ISREG(before.st_mode) or not 0 < before.st_size <= maximum:
            raise RecipeFileError("输入必须是大小在限制内的普通文件")
        value = stream.read(maximum + 1)
        after = os.fstat(stream.fileno())
        if (len(value) != before.st_size or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns):
            raise RecipeFileError("输入在读取期间发生变化")
    return value


@contextlib.contextmanager
def native_codec():
    """仅将当前校验源码编译为本机共享库，不执行ARM客体。"""
    compiler = shutil.which("clang")
    if not compiler:
        raise RecipeFileError("需要宿主clang以执行与机内相同的原生格式校验")
    with tempfile.TemporaryDirectory(prefix="a7r5-recipe-codec-") as folder:
        root = Path(folder)
        bridge, library = root / "codec.c", root / "codec.so"
        bridge.write_text(_BRIDGE, encoding="utf-8")
        command = [compiler, "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                   "-shared", "-fPIC", "-I" + str(NATIVE), str(bridge),
                   *[str(NATIVE / name) for name in _SOURCES], "-o", str(library)]
        result = subprocess.run(command, capture_output=True, text=True, check=False)
        if result.returncode:
            raise RecipeFileError("宿主校验器编译失败：" + result.stderr.strip())
        api = ctypes.CDLL(str(library))
        for name in ("recipe_file_asset", "recipe_file_document"):
            getattr(api, name).argtypes = [ctypes.c_void_p, ctypes.c_size_t]
            getattr(api, name).restype = ctypes.c_int
        yield api


def _check(api, function: str, data: bytes) -> None:
    raw = ctypes.create_string_buffer(data)
    status = getattr(api, function)(raw, len(data))
    if status:
        raise RecipeFileError(f"原生格式校验拒绝：{function}，状态{status}")


def _keys(value, names: set[str], description: str) -> None:
    if type(value) is not dict or set(value) != names:
        raise RecipeFileError(description + "字段缺失或含未知字段")


def _digest(value, field: str) -> bytes:
    if (type(value) is not str or len(value) != 64
            or any(ch not in "0123456789abcdef" for ch in value)):
        raise RecipeFileError(field + "必须为64位小写十六进制SHA256")
    answer = bytes.fromhex(value)
    if not any(answer):
        raise RecipeFileError(field + "不能全零")
    return answer


def _integer(value, lower: int, upper: int, field: str) -> int:
    if type(value) is not int or not lower <= value <= upper:
        raise RecipeFileError(field + "必须是范围内整数")
    return value


def _params(value, field: str) -> list[int]:
    if type(value) is not list or len(value) != 8:
        raise RecipeFileError(field + "必须包含完整八项参数")
    return [_integer(v, -128, 127, field) for v in value]


def load_metadata(data: bytes) -> dict:
    def pairs(items):
        answer = {}
        for key, value in items:
            if key in answer:
                raise RecipeFileError("元数据有重复键：" + key)
            answer[key] = value
        return answer

    def nonfinite(value):
        raise RecipeFileError("元数据不接受NaN或Infinity：" + value)

    if not 0 < len(data) <= METADATA_MAX:
        raise RecipeFileError("元数据超过64KiB限制")
    return json.loads(data, object_pairs_hook=pairs, parse_constant=nonfinite)


def pack(asset: bytes, metadata: dict, api) -> bytes:
    """保留全部AJR2原字节，构造AFD1后由当前C双层解码器验收。"""
    _check(api, "recipe_file_asset", asset)
    if asset[:5] not in (b"AJR2\x02", b"AJR3\x03"):
        raise RecipeFileError("SD参数导入仅接受AJR2/AJR3；AJR1只可检查，不能伪装转换")
    converter = 3 if asset[:4] == b"AJR3" else 2
    _keys(metadata, {"schema", "target_cp_sha256", "base", "name", "lut_sha256",
                     "model_sha256", "initial_params", "saved_params", "report"}, "元数据")
    if metadata["schema"] != METADATA_SCHEMA:
        raise RecipeFileError("不支持的元数据schema")
    cp = bytes((ctypes.c_uint8 * 32).in_dll(api, "af_joint_cp_sha256"))
    if _digest(metadata["target_cp_sha256"], "target_cp_sha256") != cp:
        raise RecipeFileError("元数据目标CP与当前修改版4.06不匹配")
    base = _integer(metadata["base"], 0, 31, "base")
    if base != struct.unpack_from("<I", asset, 16)[0]:
        raise RecipeFileError("元数据基底与AJR2不一致")
    if _digest(metadata["model_sha256"], "model_sha256") != asset[64:96]:
        raise RecipeFileError("元数据模型与AJR2不一致")
    name = metadata["name"]
    if type(name) is not str:
        raise RecipeFileError("name必须为UTF-8名称")
    encoded_name = name.encode("utf-8")
    if not 1 <= len(encoded_name) <= 63:
        raise RecipeFileError("name必须占1～63个UTF-8字节，不静默截断")
    initial = _params(metadata["initial_params"], "initial_params")
    saved = _params(metadata["saved_params"], "saved_params")
    report = metadata["report"]
    _keys(report, {"samples", "clipped", "delta_e76_milli", "scope"}, "报告")
    samples = _integer(report["samples"], 1, 0xFFFFFFFF, "samples")
    clipped = _integer(report["clipped"], 0, samples, "clipped")
    if type(report["scope"]) is not int or report["scope"] != 1:
        raise RecipeFileError("scope必须为1，仅表示外部提供的模型预测误差")
    delta = report["delta_e76_milli"]
    if type(delta) is not list or len(delta) != 5:
        raise RecipeFileError("delta_e76_milli必须为五项色差统计")
    delta = [_integer(v, 0, 0xFFFFFFFF, "delta_e76_milli") for v in delta]
    lut = _digest(metadata["lut_sha256"], "lut_sha256")
    payload = hashlib.sha256(asset).digest()
    header = bytearray(256)
    header[:8] = b"AFD1\x01\x00\x00\x01"
    struct.pack_into("<6I", header, 8, ASSET_SCHEMA, converter, len(encoded_name), len(asset), samples, clipped)
    struct.pack_into("<6I", header, 32, *delta, 1)
    header[56:88] = asset[64:96]
    header[88:162] = struct.pack("<BB8b32s32s", base, 1, *initial, payload, lut)
    header[162:236] = struct.pack("<BB8b32s32s", base, 1, *saved, payload, lut)
    struct.pack_into("<I", header, 236, 1)
    answer = bytes(header) + encoded_name + asset
    _check(api, "recipe_file_document", answer)
    return answer


def inspect(data: bytes, api) -> dict:
    """输出来源声明与兼容性，不将模型预测报告升级为实机结论。"""
    answer = {"bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(),
              "camera_verified": False}
    if data[:3] == b"AJR":
        _check(api, "recipe_file_asset", data)
        answer.update(format=data[:4].decode("ascii"), base=struct.unpack_from("<I", data, 16)[0],
                      target_cp_sha256=data[32:64].hex(), model_sha256=data[64:96].hex(),
                      supported_for_sd_import=False,
                      reason="需要完整AFD1封装；AJR1不受本次参数导入支持")
        return answer
    _check(api, "recipe_file_document", data)
    name_bytes, image_bytes = struct.unpack_from("<2I", data, 16)
    initial, saved = data[88:162], data[162:236]
    asset = data[256 + name_bytes:]
    converter = struct.unpack_from("<I", data, 12)[0]
    supported = bool(initial[1] == 0 or (initial[1] == 1 and
                     ((image_bytes == ASSET_BYTES and asset[:5] == b"AJR2\x02" and converter == 2) or
                      (image_bytes == SECTOR_BYTES and asset[:5] == b"AJR3\x03" and converter == 3))))
    answer.update(format="AFD1", name=data[256:256 + name_bytes].decode("utf-8"),
                  base=initial[0], kind=initial[1], initial_params=list(struct.unpack_from("<8b", initial, 2)),
                  saved_params=list(struct.unpack_from("<8b", saved, 2)),
                  lut_sha256=initial[42:74].hex(), payload_sha256=initial[10:42].hex(),
                  supported_for_sd_import=supported)
    if initial[1]:
        samples, clipped = struct.unpack_from("<2I", data, 24)
        answer.update(target_cp_sha256=asset[32:64].hex(), model_sha256=data[56:88].hex(),
                      report={"samples": samples, "clipped": clipped,
                              "delta_e76_milli": list(struct.unpack_from("<5I", data, 32)),
                              "scope": struct.unpack_from("<I", data, 52)[0],
                              "source": "文件提供者声明的模型预测，非认证或本机实测"},
                      report_applies_to_saved=initial == saved)
    return answer


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    command = commands.add_parser("pack", help="封装已有AJR2配方；不重新拟合")
    command.add_argument("--asset", type=Path, required=True)
    command.add_argument("--metadata", type=Path, required=True)
    command.add_argument("--output", type=Path, required=True)
    command = commands.add_parser("inspect", help="校验并查看AFD1或AJR1/AJR2")
    command.add_argument("file", type=Path)
    args = parser.parse_args(argv)
    try:
        with native_codec() as api:
            if args.command == "inspect":
                result = inspect(read_regular(args.file, DOCUMENT_MAX), api)
            else:
                if args.output.suffix.lower() != ".a7filter":
                    raise RecipeFileError("输出扩展名必须为.a7filter")
                data = pack(read_regular(args.asset, SECTOR_BYTES),
                            load_metadata(read_regular(args.metadata, METADATA_MAX)), api)
                result = inspect(data, api)
                fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                result["output"] = str(args.output)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (RecipeFileError, OSError, UnicodeError, json.JSONDecodeError) as error:
        print("配方文件处理失败：" + str(error), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
