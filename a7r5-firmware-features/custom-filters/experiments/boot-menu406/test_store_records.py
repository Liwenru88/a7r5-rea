"""只读记录导出契约：完整字节、中文名称与拒绝损坏／截断，不启动客体。"""
import importlib.util
from pathlib import Path
import struct
import zlib

import pytest

SPEC = importlib.util.spec_from_file_location('boot_menu_store_records', Path(__file__).with_name('store_records.py'))
STORE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(STORE)


def files():
    marker = bytearray(96)
    marker[:8] = b'A7STORE1'
    struct.pack_into('<4I', marker, 8, 1, 262463, 0, 20)
    marker[24:56] = bytes.fromhex('3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2')
    name = '电脑参数示例'.encode()
    document = bytearray(256 + len(name))
    document[:8] = b'AFD1\1\0\0\1'
    struct.pack_into('<I', document, 16, len(name))
    struct.pack_into('<I', document, 236, 1)
    document[96] = document[170] = 3
    document[164] = 2  # 保存值与创建值独立。
    document[256:] = name
    header = bytearray(32)
    header[:8] = b'A7F1\1\0\x14\0'
    struct.pack_into('<QII', header, 8, 2, len(document), zlib.crc32(document))
    struct.pack_into('<I', header, 24, zlib.crc32(header))
    return {'STORE.ID': bytes(marker), 'C20_B.rec': bytes(header + document)}


def transcript(data):
    lines = ['AF_STORE_BEGIN v=1 root=/setting/A7LOOKS1']
    for name in STORE.NAMES:
        if name not in data:
            lines.append(f'AF_STORE_ABSENT name={name}')
            continue
        raw = data[name]
        lines.append(f'AF_STORE_FILE name={name} bytes={len(raw)}')
        lines += [f'AF_STORE_HEX offset={at:08x} data={raw[at:at+64].hex()}' for at in range(0, len(raw), 64)]
        lines.append(f'AF_STORE_END name={name} bytes={len(raw)}')
    lines.append(f'AF_STORE_DONE files={len(data)} bytes={sum(map(len,data.values()))} status=0')
    return '\n'.join(lines)


def test_export_preserves_actual_bytes_and_saved_snapshot(tmp_path):
    source = files()
    report = STORE.export(transcript(source) + '\nAF_STORE_RC=0', tmp_path/'valid')
    record = report['files']['C20_B.rec']
    assert record['name'] == '电脑参数示例' and record['generation'] == 2
    assert record['initial']['parameters'][0] == 0
    assert record['saved']['parameters'][0] == 2
    assert (tmp_path/'valid/C20_B.rec').read_bytes() == source['C20_B.rec']
    assert len(report['absent']) == 39


@pytest.mark.parametrize('damage', ['truncate', 'crc', 'duplicate', 'exit_error', 'duplicate_exit'])
def test_incomplete_or_corrupted_export_never_creates_recovery_files(tmp_path, damage):
    source = files()
    if damage == 'crc':
        raw = bytearray(source['C20_B.rec']);raw[-1] ^= 1
        source['C20_B.rec'] = bytes(raw)
    text = transcript(source)
    if damage == 'truncate':
        text = text.rsplit('\n', 1)[0]
    if damage == 'duplicate':
        text += '\nAF_STORE_BEGIN v=1 root=/setting/A7LOOKS1'
    if damage == 'exit_error':
        text += '\nAF_STORE_RC=9'
    if damage == 'duplicate_exit':
        text += '\nAF_STORE_RC=0\nAF_STORE_RC=0'
    with pytest.raises(ValueError):
        STORE.export(text, tmp_path/'rejected')
    assert not (tmp_path/'rejected').exists()
