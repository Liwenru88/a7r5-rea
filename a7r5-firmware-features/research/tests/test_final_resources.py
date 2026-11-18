"""最终 USR 资源门禁的破坏性样本；不用生成器自己的读回代替验收。"""
from pathlib import Path
import struct
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import resource_audit as audit


def bank(label=b'Normal', tag=0x1e00a000):
    return b'uxc\x07' + bytes(6) + struct.pack('<HIH', 5, 0x1001, 0) + bytes(2) + struct.pack('<I', tag) + label + b'\0'


@pytest.mark.parametrize('raw,reason', [
    (bank(b'\xff'), 'UTF'), (bank(tag=0x1e00a001), '标识'),
    (bank()[:16], '索引'), (bank()[:-1], '终止'),
])
def test_invalid_text_records_are_rejected(raw, reason):
    with pytest.raises(ValueError, match=reason):
        audit.text_bank(raw)


def test_language_pair_and_module_ownership_are_enforced():
    with pytest.raises(ValueError, match='横竖'):
        audit.language_pairs({'string_english_horizontal.uxc'}, {'english'})
    audit.language_pairs({'string_english_horizontal.uxc', 'string_english_vertical.uxc'}, {'english'})
    with pytest.raises(ValueError, match='冲突'):
        audit.check_claims([('text', 10, 12, 'one'), ('text', 11, 14, 'two')])
    audit.check_claims([('text', 10, 12, 'one'), ('icon', 10, 12, 'two')])


def literal(data):
    return b'\x0f\0' + struct.pack('<H', len(data)) + data


def test_page_decoder_rejects_long_blocks_and_truncated_or_foreign_dictionary():
    assert audit.pages(literal(bytes(4096)) + literal(bytes(1504))) == [4096, 1504]
    for data in (literal(bytes(5600)), literal(bytes(20))[:-1], b'\xf0\x01\x00\x01', b'\xf0\0'):
        with pytest.raises(ValueError):
            audit.pages(data)


def test_required_resource_is_checked_even_if_other_records_are_valid():
    records = audit.text_bank(bank())
    assert records == {0x0200a000: 'Normal'}
    with pytest.raises(ValueError, match='缺少'):
        audit.required_text(records, {0x0200a001: 'Other'})
    with pytest.raises(ValueError, match='内容'):
        audit.required_text(records, {0x0200a000: 'Other'})


def image():
    stream = literal(bytes(8))
    return (bytes.fromhex('757864070000000008000000') + struct.pack('<I', 0x1001000) + bytes(2) + b'\xff\xff' * 4095
            + struct.pack('<5I', 0x1a000000, 0xc0000000, 2 | (2 << 16), len(stream), 16) + stream)


def test_image_descriptor_checks_are_not_replaced_by_component_hash_checks():
    raw = image()
    assert audit.image_bank(raw)[0x02000000]['blocks'] == [8]
    for at, value in ((16, 0xfffe), (8208, 0x1a000001), (8224, 0xffffffff)):
        damaged = bytearray(raw)
        struct.pack_into('<H' if at == 16 else '<I', damaged, at, value)
        with pytest.raises(ValueError):
            audit.image_bank(damaged)
