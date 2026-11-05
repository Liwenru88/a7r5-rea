"""固定五文件导出：普通记录不变，墓碑仅允许规范AFD1且CRC有效。"""
from pathlib import Path
import importlib.util
import struct
import zlib

import pytest

HERE=Path(__file__).resolve().parent
ROOT=HERE.parents[3]


def load(path,name):
    spec=importlib.util.spec_from_file_location(name,path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


NEW=load(HERE/'guest/record_export.py','ui406_new_record_parser_test')
OLD=load(ROOT/'.local/fixed-custom-filters/continuation29-exporter/parse_export.py','ui406_old_record_parser_test')


def record(payload,slot=20,generation=2):
    header=bytearray(32);header[:8]=b'A7F1\1\0'+bytes([slot,0])
    struct.pack_into('<QII',header,8,generation,len(payload),zlib.crc32(payload))
    struct.pack_into('<I',header,24,zlib.crc32(header))
    return bytes(header)+payload


def document(name='自定义C07'):
    text=name.encode();payload=bytearray(256+len(text));payload[:8]=b'AFD1\1\0\0\1'
    struct.pack_into('<I',payload,16,len(text));struct.pack_into('<I',payload,236,1)
    payload[96]=payload[170]=3;payload[256:]=text
    return bytes(payload)


def marker():
    data=bytearray(96);data[:8]=b'A7STORE1';struct.pack_into('<4I',data,8,1,262463,0,20)
    data[24:56]=bytes.fromhex('3cb87fd41de7bf6693375bac66d780556d87e1f73270cadb1a8f02eb8c0f24c2')
    return bytes(data)


def exported(last):
    raw={'STORE.ID':marker(),'C07_A.rec':record(document(),7,3),'C07_B.rec':record(document(),7,2),
         'C20_A.rec':record(document('自定义C20'),20,1),'C20_B.rec':last}
    lines=['AF_EXPORT_BEGIN v=1 files=5 root='+NEW.ROOT]
    for name,data in raw.items():
        if data is None:
            lines.append('AF_EXPORT_ABSENT name=C20_B.rec required=0');continue
        lines.append(f'AF_EXPORT_FILE name={name} bytes={len(data)}')
        for offset in range(0,len(data),64):lines.append(f'AF_EXPORT_HEX offset={offset:08x} data={data[offset:offset+64].hex()}')
        lines.append(f'AF_EXPORT_END name={name} bytes={len(data)}')
    lines.append(f'AF_EXPORT_DONE files=5 present={sum(v is not None for v in raw.values())} bytes={sum(len(v) for v in raw.values() if v is not None)} status=0')
    return '\n'.join(lines)+'\n'


def test_normal_record_export_output_remains_exactly_compatible():
    for last in (None,record(document('普通滤镜'),20,2)):
        text=exported(last)
        assert NEW.verify(text)==OLD.verify(text)


def test_canonical_tombstone_requires_complete_record_and_preserves_slot_generation():
    tombstone=b'AFD1\1\0\0\1'+bytes(248)
    raw,report=NEW.verify(exported(record(tombstone,20,2)))
    assert len(raw['C20_B.rec'])==288
    assert report['C20_B.rec']['tombstone'] is True
    assert report['C20_B.rec']['slot']==20 and report['C20_B.rec']['generation']==2
    assert report['C20_B.rec']['crc_verified'] is True
    assert all(key not in report['C20_B.rec'] for key in ('name','initial','saved','absent'))
    with pytest.raises(ValueError):OLD.verify(exported(record(tombstone)))


def test_empty_or_noncanonical_present_zero_is_rejected_even_after_crc_is_repaired():
    canonical=b'AFD1\1\0\0\1'+bytes(248)
    candidates=[b'',canonical+b'\0',canonical[:-1],b'AFD1\2\0\0\1'+bytes(248)]
    for offset in (8,16,88,162,236,240,255):
        bad=bytearray(canonical);bad[offset]=1;candidates.append(bytes(bad))
    for payload in candidates:
        with pytest.raises(ValueError):NEW.decode('C20_B.rec',record(payload))
    with pytest.raises(ValueError):NEW.verify(exported(b''))
    bad=bytearray(document());struct.pack_into('<I',bad,236,0)
    with pytest.raises(ValueError):NEW.verify(exported(record(bytes(bad))))


def test_bad_header_or_payload_crc_never_becomes_a_tombstone():
    canonical=record(b'AFD1\1\0\0\1'+bytes(248))
    for offset in (24,32,96,287):
        bad=bytearray(canonical);bad[offset]^=1
        with pytest.raises(ValueError):NEW.verify(exported(bytes(bad)))


def test_manifest_parser_is_fixed_by_path_and_hash_with_legacy_fallback():
    # 只执行实际辅助函数，避免测试为了导出解析启动任何VM或引入Qt。
    import ast
    import hashlib
    path=HERE/'guest/probe_menu.py';tree=ast.parse(path.read_text())
    functions=[node for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in ('digest','record_parser')]
    assert len(functions)==2
    namespace={'Path':Path,'hashlib':hashlib,'importlib':importlib,'ROOT':ROOT,'__file__':str(path)}
    exec(compile(ast.Module(body=functions,type_ignores=[]),str(path),'exec'),namespace)
    choose=namespace['record_parser'];target=HERE/'guest/record_export.py'
    identity={'path':str(target),'sha256':hashlib.sha256(target.read_bytes()).hexdigest()}
    parser,selected=choose({'record_parser':identity});assert selected==identity
    parser.verify(exported(record(b'AFD1\1\0\0\1'+bytes(248))))
    with pytest.raises(ValueError):choose({'record_parser':{'path':str(target),'sha256':'0'*64}})
    with pytest.raises(ValueError):choose({'record_parser':{'path':'/tmp/arbitrary_parser.py','sha256':identity['sha256']}})
    with pytest.raises(ValueError):choose({'record_parser':{'path':str(target)}})
    legacy,selected=choose({});assert selected['path']==str(ROOT/'.local/fixed-custom-filters/continuation29-exporter/parse_export.py')
    assert legacy.verify(exported(None))==OLD.verify(exported(None))
    with pytest.raises(ValueError):legacy.verify(exported(record(b'AFD1\1\0\0\1'+bytes(248))))
