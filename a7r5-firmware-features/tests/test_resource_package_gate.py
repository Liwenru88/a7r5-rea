"""发布门禁必须检查最终解包资源，失败时不能报告验签完成。"""
from pathlib import Path
import struct
import sys
import zlib

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from core import package


def test_readback_resource_failure_prevents_verified_receipt(tmp_path, monkeypatch):
    work = tmp_path / 'work'
    (work / 'format').mkdir(parents=True)
    header = bytes(512)
    (work / 'format/header.bin').write_bytes(header)
    expected_header = bytearray(header)
    expected_header[32:34] = b'\x19\x04'
    struct.pack_into('<I', expected_header, 8, zlib.crc32(expected_header[12:]))
    before = dict(updater_sha256='same', outer='same', iv='same', tail='same', components={}, entries=[])
    plan = {'requested': ['look24']}
    called = []

    def unpack(dat, destination, key):
        (destination / 'format').mkdir(parents=True)
        (destination / 'format/header.bin').write_bytes(expected_header)

    def reject(path, current_plan):
        assert current_plan is plan
        assert path == tmp_path / 'readback/archive' / package.tool.AP_IMAGE
        called.append('final-resource-audit')
        raise ValueError('横竖语言银行损坏')

    monkeypatch.setattr(package.tool, 'unpack', unpack)
    monkeypatch.setattr(package, 'read_json', lambda path: before.copy())
    monkeypatch.setattr(package.resource_audit, 'audit_usr', reject)
    monkeypatch.setattr(package, 'verify_signature', lambda *args: pytest.fail('资源失败后仍试图发布验证回执'))
    with pytest.raises(ValueError, match='横竖语言银行损坏'):
        package.verify_readback(tmp_path / 'candidate', work, before,
                                dict(components={}, archive={}), '4.19', tmp_path, plan=plan)
    assert called == ['final-resource-audit']
