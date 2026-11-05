"""使用冻结的第三方逐块解码器，独立检查原厂资源的4KiB分块契约。"""
import io
import os
from pathlib import Path
import types
import ctypes
import hashlib
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[3]
BUILD = Path(os.environ['A7R5_NATIVE24_BUILD'])


def load(path, name):
    # 冻结快照不接受新增字节码缓存，直接编译到内存。
    module = types.ModuleType(name)
    module.__file__ = str(path)
    exec(compile(path.read_text(), str(path), 'exec'), module.__dict__)
    return module


def blocks(stream):
    decoder = load(ROOT / 'a7r5-firmware-features/native12-combined/upstream/firmware/r5/src/lib/fwtool/lz77/__init__.py', 'frozen_fwtool_pages')
    source = io.BytesIO(stream)
    result = []
    while source.tell() < len(stream):
        result.append(decoder.inflateLz77(source))
    assert source.tell() == len(stream)
    return result


def resources():
    icons = load(BUILD / 'unified-tools/unified_icons.py', 'page_contract_icons')
    for name in ('image_00_23_IPSX.uxc', 'image_00_32_IPSX.uxc'):
        raw = (BUILD / name).read_bytes()
        _, _, _, records, _ = icons.layout(raw)
        for index, (at, flags, *_) in records.items():
            _, size, offset = icons.payload_fields(raw, at, flags)
            yield icons, name, index, raw[at + 4 + offset:at + 4 + offset + size]


def test_added_icons_have_independent_4k_blocks():
    count = 0
    for icons, name, index, stream in resources():
        if index < icons.COUNT:
            continue
        decoded = blocks(stream)
        assert list(map(len, decoded)) == [4096, 1504], f'{name}:{index:#x}: 新图标跨越4KiB块边界'
        assert b''.join(decoded) == icons.icon_pixels((index-icons.COUNT)//2+1, bool((index-icons.COUNT)&1))
        count += 1
    assert count == 96


def test_original_resources_establish_page_profile():
    """正向样本取全部原厂载荷，避免只按新增编码器自己的规则验收。"""
    count = 0
    for icons, name, index, stream in resources():
        if index >= icons.COUNT:
            continue
        sizes = list(map(len, blocks(stream)))
        assert sizes and 0 < sizes[-1] <= 4096, (name, index, sizes)
        assert all(size == 4096 for size in sizes[:-1]), (name, index, sizes)
        count += 1
    assert count == 7022


@pytest.fixture(scope='module')
def cpu_decoder(tmp_path_factory):
    output = tmp_path_factory.mktemp('page-decoder') / 'decoder.dylib'
    subprocess.run(['clang', '-shared', '-fPIC', '-O2', '-Wall', '-Werror',
                    str(ROOT / 'a7r5-qemu/source/guest/sony-lz77.c'), '-o', str(output)], check=True)
    library = ctypes.CDLL(str(output))
    for name in ('sony_lz77_decode', 'sony_lz77_decode_pages'):
        fn = getattr(library, name)
        fn.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong]
        fn.restype = ctypes.c_int
    return library


@pytest.mark.parametrize('folder,sha', [
    ('2026-11-03-tabs-01', 'a65afbdb43e4eca063baacdd77f822890b521c509ec383eacfaa8abe20971bc5'),
    ('2026-11-03-incident413-fix-01', '7adc49cf46a99802e8e68e06455d813730ff0f32c4efe96f76bd80161e442b2c'),
])
def test_qemu_page_gate_rejects_both_released_long_blocks(cpu_decoder, folder, sha):
    old = Path(__file__).resolve().parents[1] / 'verification' / folder / 'components'
    # 读取封存的同一份失败资源，避免依赖会被清理的临时构建目录。
    icons = load(BUILD / 'unified-tools/unified_icons.py', 'old_page_icons')
    raw = (old / 'image_00_32_IPSX.uxc').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == sha
    at, _, _, size, offset = icons.layout(raw)[3][icons.COUNT + 1]
    stream = raw[at + 4 + offset:at + 4 + offset + size]
    # 此断言记录旧QEMU为什么会放行；新增门禁必须拒绝同一份输入。
    assert cpu_decoder.sony_lz77_decode(stream, len(stream), None, 5600) == 0
    output = ctypes.create_string_buffer(b'\xa5' * 5600, 5600)
    assert cpu_decoder.sony_lz77_decode_pages(stream, len(stream), output, 5600) != 0
    assert output.raw == b'\xa5' * 5600


def test_qemu_page_gate_accepts_original_and_fixed_resources(cpu_decoder):
    count = 0
    for _, _, _, stream in resources():
        size = sum(map(len, blocks(stream)))
        assert cpu_decoder.sony_lz77_decode_pages(stream, len(stream), None, size) == 0
        count += 1
    assert count == 7118
