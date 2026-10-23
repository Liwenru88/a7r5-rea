"""原厂NSS与私有账户视图的SSH集成；无NIC、无相机、无SD直通。"""
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import struct
import sys
import tempfile

import build


def original_passwd():
    image = build.LAB.parent / "a7r5-firmware-images/标准固件_19项/明文分区_17项/cnflasha10.img"
    with image.open("rb") as stream:
        boot = stream.read(512)
        sector = struct.unpack_from("<H", boot, 11)[0]
        reserved = struct.unpack_from("<H", boot, 14)[0]
        roots = struct.unpack_from("<H", boot, 17)[0]
        fat_sectors = struct.unpack_from("<H", boot, 22)[0]
        start = (reserved + boot[16] * fat_sectors) * sector
        cluster_bytes = sector * boot[13]
        data = start + ((roots * 32 + sector - 1) // sector) * sector
        stream.seek(start)
        directory = stream.read(roots * 32)
        found = []
        for i in range(0, len(directory), 32):
            entry = directory[i:i + 32]
            if not entry[0]:
                break
            if entry[0] != 0xe5 and entry[11] != 15 and entry[:11].decode("ascii").strip().lower() == "passwd":
                found.append(entry)
        if len(found) != 1:
            raise ValueError("原始FAT账户文件不唯一")
        entry = found[0]
        cluster = struct.unpack_from("<H", entry, 26)[0]
        size = struct.unpack_from("<I", entry, 28)[0]
        if not 0 < size < cluster_bytes:
            raise ValueError("账户文件超出本次单簇读取范围")
        stream.seek(data + (cluster - 2) * cluster_bytes)
        raw = stream.read(size)
    if hashlib.sha256(raw).hexdigest() != build.PASSWD_SHA:
        raise ValueError("原始账户基线不符")
    return raw

