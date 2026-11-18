"""全启动修复测试的夹具：从持久输入确定性再生，不依赖 `.local`。

夹具来源：
- `updater.bin` 取官方 4.00 升级包内的原厂升级器（与 4.24 持久区 `updater.img` 同摘要）；
- `libupdaterbody.so` / `ud_cp_firmup.elf` 从该升级器的 squashfs 中按路径提取；
- `header.bin` 由官方 4.00 明文前缀改写副版本号并重算 CRC32 得到。

全部结果按固定摘要校验，缺失持久输入时抛错而不是静默跳过。
"""
import io
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
UPDATER = (ROOT / 'a7r5-firmware-features/builds/4.24-417-scope-repaired-20261116'
           / 'baseline-inputs/updater.img')
FDAT = (ROOT / 'a7r5-firmware-features/builds/4.24-417-scope-repaired-20261116'
        / 'baseline-inputs/firmware.fdat')

UPDATER_SHA = 'c4b18a82eea52a507fb82b86ad50bab6047070b8908d03c28edcce4a9577d348'
LIBUPDATERBODY_SHA = '6582eba530025d17fab81420050433cd998714c922aa4c16fd4d5cdc5a378ee9'
CP_FIRMUP_SHA = 'ea896626a2503f9ab8b90c9506176ffbab7d3b8081a378734d93d7dd410f2c95'
HEADER_SHA = 'c8a02a9feb4964df6fa509926c920356450f52dbf28ad94ed914a637bc6a2ef5'


def sha256(raw):
    import hashlib
    return hashlib.sha256(raw).hexdigest()


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def updater_image():
    """原厂升级器：1253376 字节，与官方 4.00 包内成员一致。"""
    require(UPDATER.is_file(), '缺少持久输入：' + str(UPDATER))
    raw = UPDATER.read_bytes()
    require(sha256(raw) == UPDATER_SHA, '升级器摘要不符')
    return raw


def _squashfs_member(path):
    sys.path.insert(0, str(ROOT / 'a7r5-firmware-features/native24-combined'
                               '/dependencies/native12-combined/upstream/firmware/r5/src/lib'))
    from fwtool.archive.squashfs import readSquashfs
    for entry in readSquashfs(io.BytesIO(updater_image())):
        if entry.path == path:
            return entry.contents.read()
    raise RuntimeError('升级器内缺少成员：' + path)


def updater_body():
    """升级器主体库 /bodylib/libupdaterbody.so。"""
    raw = _squashfs_member('/bodylib/libupdaterbody.so')
    require(sha256(raw) == LIBUPDATERBODY_SHA, 'libupdaterbody.so 摘要不符')
    return raw


def cp_firmup():
    """CP 固件更新程序 /bin/ud_cp_firmup.elf。"""
    raw = _squashfs_member('/bin/ud_cp_firmup.elf')
    require(sha256(raw) == CP_FIRMUP_SHA, 'ud_cp_firmup.elf 摘要不符')
    return raw


def header():
    """4.19 包的前 512 字节头：官方 4.00 前缀 + 副版本号 0x19 + 重算 CRC32。"""
    require(FDAT.is_file(), '缺少持久输入：' + str(FDAT))
    with FDAT.open('rb') as stream:
        raw = bytearray(stream.read(512))
    raw[32:34] = b'\x19\x04'
    struct.pack_into('<I', raw, 8, zlib.crc32(raw[12:512]))
    result = bytes(raw)
    require(sha256(result) == HEADER_SHA, '头部重建摘要不符')
    return result
