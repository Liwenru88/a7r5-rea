"""固定公开Edit捕获的只读参数入口；不提供相机访问或sRGB域桥。"""
from dataclasses import dataclass, field
import hashlib
import math
import os
from pathlib import Path
import stat
import struct


REPOSITORY = 'Hearts-Ace/sony-a7r5-custom-firmware'
COMMIT = '8b563d46f800679abd3f215950cb541fc81da2a6'
CONTEXT = 4
# 只接受公开Edit上下文4，不能拿其他场景的同长度表静默替换。
FILES = (
    ('1304-color-build-runtime-4.bin', 670656,
     '082d904742375cf85c04b181e79353a5864026c56e9a55ee25c3a8ee777bf60e'),
    ('1305-color-build-raw-4.bin', 5120,
     '986cbbf413a72d196e4ba64d2ca08503c66706338beed7267acd5c69fb2b1acc'),
    ('1306-color-build-settings-4.bin', 768,
     '3724592c0560014db0acf6f5cdd39b1ebb8d152b69654668044ac0995c66fd98'),
)


@dataclass(frozen=True)
class EditParameters:
    """已选择的整数算子参数；字段完整不表示机身ISP或颜色域已认证。"""
    gamma: bytes
    cc1: tuple[int, ...]
    luma: tuple[int, ...]
    keep_chroma_unclipped: bool
    y_gamma: bytes
    level: int
    white: int
    pivot: int
    gain: float
    gamma_axis: tuple[int, ...]
    gamma_values: tuple[int, ...]
    matrix_payload: bytes


def _signed16(value):
    return (value + 32768) % 65536 - 32768


def decode_parameters(runtime: bytes, raw: bytes, settings: bytes) -> EditParameters:
    """显式解码参数，不校验来源，也不授予AfJointModel/机身应用能力。"""
    if (not all(type(v) is bytes for v in (runtime, raw, settings))
            or len(runtime) != 670656 or len(raw) != 5120 or len(settings) != 768):
        raise ValueError('Edit参考参数长度或字节类型不符')
    mode = struct.unpack_from('<i', settings, 0x1e8)[0]
    if mode == 1 and raw[0x1c]:
        cc1 = struct.unpack_from('<8h', raw, 0xddc)
    else:
        base = struct.unpack_from('<8h', raw, 0xdec)
        if mode in (0, 2, 3, 4, 5, 6, 7):
            delta = struct.unpack_from('<8h', raw, 0xe1c if mode == 7 else 0xe0c)
        elif mode == 1:
            planes = struct.unpack_from('<32h', raw, 0xdfc)
            weights = struct.unpack_from('<4h', raw, 0xe44)
            delta = tuple(sum(planes[8*j+i] * weights[j] for j in range(4)) >> 10
                          for i in range(8))
        else:
            raise ValueError('Edit参考未支持的CC1选择模式')
        cc1 = tuple(_signed16(a+b) for a, b in zip(base, delta))
    clipping = struct.unpack_from('<i', settings, 0x248)[0]
    if clipping not in (0, 1):
        raise ValueError('Edit参考色度门控不是布尔值')
    level = struct.unpack_from('<h', settings, 0x2ac)[0]
    white = struct.unpack_from('<h', settings, 0x2b0)[0]
    quarter = level // 4 if level >= 0 else -((-level) // 4)
    gain = struct.unpack_from('<f', runtime, 0x91964)[0]
    if not math.isfinite(gain) or gain <= 0 or 512-white+quarter == 0:
        raise ValueError('Edit参考明度参数无效')
    return EditParameters(
        gamma=runtime[0x18f6:0x218f6], cc1=cc1,
        luma=struct.unpack_from('<3h', runtime, 0x218f6),
        keep_chroma_unclipped=bool(clipping),
        y_gamma=runtime[0x318fc:0x418fc], level=level, white=white,
        pivot=struct.unpack_from('<h', runtime, 0x91962)[0], gain=gain,
        gamma_axis=struct.unpack_from('<128i', raw, 0x5d8),
        gamma_values=struct.unpack_from('<128i', raw, 0x7d8),
        matrix_payload=raw[0xae:0xae+276])


def _read_locked(path: Path, size: int, digest: str) -> bytes:
    flags = os.O_RDONLY | os.O_NONBLOCK | getattr(os, 'O_NOFOLLOW', 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_size != size:
            raise ValueError('公开Edit捕获不是规定大小的普通文件：' + path.name)
        with os.fdopen(fd, 'rb', closefd=False) as handle:
            raw = handle.read(size+1)
        if len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
            raise ValueError('公开Edit捕获摘要不符：' + path.name)
        return raw
    finally:
        os.close(fd)


@dataclass(frozen=True)
class EditSnapshot:
    runtime: bytes
    raw: bytes
    settings: bytes
    parameters: EditParameters = field(init=False)

    def __post_init__(self):
        for raw, (_, size, digest) in zip((self.runtime, self.raw, self.settings), FILES):
            if type(raw) is not bytes or len(raw) != size or hashlib.sha256(raw).hexdigest() != digest:
                raise ValueError('EditSnapshot不能声明未经固定摘要验证的来源')
        # 参数仅由已验证字节生成，调用者不能传入自定义比较对象冒充相等。
        object.__setattr__(self, 'parameters', decode_parameters(self.runtime, self.raw, self.settings))

    def provenance(self) -> dict:
        return dict(repository=REPOSITORY, commit=COMMIT, context=CONTEXT,
                    files=[dict(name=n, bytes=s, sha256=h) for n, s, h in FILES],
                    input_domain='Edit post-SSCS/pre-matrix integer RGB',
                    output_domain='Edit color-subchain integer RGB; not final JPG',
                    source_hashes_verified=True, camera_io=False,
                    observations='passive synthetic native Edit rendering; not camera capture',
                    current_cp_calibration_verified=False,
                    srgb_bridge_verified=False, camera_apply_allowed=False)


def load_edit_snapshot(folder: Path) -> EditSnapshot:
    """仅本地按摘要读取；不下载、不执行脚本、不搜寻设备或默认替代模型。"""
    data = tuple(_read_locked(Path(folder)/name, size, digest)
                 for name, size, digest in FILES)
    return EditSnapshot(*data)
