"""验证容器往返、校验联动及失败边界，不操作设备。"""
import io
import json
import os
from pathlib import Path
import struct
import sys
import tarfile
import zlib

import pytest
from Cryptodome.PublicKey import RSA

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from a7r5dat import tool
from a7r5dat.codec import decode_frames, decrypt_to, header_info, sha, verify_signature


def plaintext(names=('0100_config/value',), link=None):
    archive = io.BytesIO()
    with tarfile.open(fileobj=archive, mode='w', format=tarfile.USTAR_FORMAT) as tar:
        for name in names:
            m = tarfile.TarInfo(name)
            m.size = 3
            tar.addfile(m, io.BytesIO(b'one'))
        if link:
            m = tarfile.TarInfo(link[0]); m.type = link[2]; m.linkname = link[1]
            tar.addfile(m)
    body = archive.getvalue()
    header = bytearray(512)
    header[:8] = b'UDTRFIRM'; header[16] = ord('U'); header[20] = ord('N'); header[33] = 4
    struct.pack_into('<II', header, 36, 0x11030080, 0)
    struct.pack_into('<III', header, 48, 1024, len(body), 2)
    header[64] = ord('U'); struct.pack_into('<II', header, 68, 512, 512)
    header[80] = ord('P'); struct.pack_into('<II', header, 84, 512, 0)
    struct.pack_into('<I', header, 8, zlib.crc32(header[12:]))
    return bytes(header)+bytes(512)+body


def envelope():
    return dict(iv=tool.encode(bytes(range(16))), outer=[dict(kind=k, data=tool.encode(b'\0'*4))
                                                      for k in ['DATV', 'PROV', 'UDID']])


@pytest.fixture(scope='session', autouse=True)
def temporary_signing_identity(tmp_path_factory):
    """测试使用临时身份，不读取本地真实研究私钥。"""
    previous = tool.HOME
    home = tmp_path_factory.mktemp('dat-test-identity')
    keys = home/'keys'
    keys.mkdir()
    key = RSA.generate(2048)
    private = keys/'research-signing-private.pem'
    private.write_bytes(key.export_key())
    private.chmod(0o600)
    (keys/'research-public.pem').write_bytes(key.public_key().export_key())
    tool.HOME = home
    try:
        yield
    finally:
        tool.HOME = previous


@pytest.fixture
def signing():
    return tool.signing_key(tool.HOME/'keys/research-signing-private.pem', tool.HOME/'keys/research-public.pem')


@pytest.mark.parametrize('size', [1, 1020, 1021, 4096*1020+1])
def test_frame_boundaries_roundtrip(tmp_path, signing, size):
    raw = bytes((i*17)&255 for i in range(size))
    out = tmp_path/'signed.DAT'
    tool.encrypt(io.BytesIO(raw), len(raw), envelope(), signing, out)
    verify_signature(out, signing.public_key().export_key())
    clear = io.BytesIO(); facts = decrypt_to(out, clear)
    assert clear.getvalue() == raw and facts['plaintext_bytes'] == size


def test_tampered_signature_even_with_valid_outer_crc(tmp_path, signing):
    p = tmp_path/'signed.DAT'; raw = plaintext()
    tool.encrypt(io.BytesIO(raw), len(raw), envelope(), signing, p)
    data = bytearray(p.read_bytes()); data[100] ^= 1
    struct.pack_into('>I', data, len(data)-4, zlib.crc32(data[:-12])); p.write_bytes(data)
    with pytest.raises(ValueError):
        verify_signature(p, signing.public_key().export_key())


def test_invalid_frame_rejected():
    with pytest.raises(ValueError, match='帧加和'):
        decode_frames(b'\1'+bytes(1023), False)


@pytest.mark.parametrize('name', ['../outside', '/outside', 'a/../outside', 'C:/outside', 'a\\outside'])
def test_archive_path_rejected(tmp_path, name):
    raw = plaintext((name,)); dest = tmp_path/'out'; dest.mkdir()
    with pytest.raises(ValueError):
        tool.read_archive(io.BytesIO(raw), len(raw), dest)
    assert not list(dest.rglob('*'))


@pytest.mark.parametrize('link', [('evil', '../../outside', tarfile.SYMTYPE),
                                 ('evil', '0100_config/value', tarfile.LNKTYPE)])
def test_links_never_materialized(tmp_path, link):
    raw = plaintext((), link=link); dest = tmp_path/'out'; dest.mkdir()
    with pytest.raises(ValueError):
        tool.read_archive(io.BytesIO(raw), len(raw), dest)
    assert not list(dest.rglob('*'))


def test_factory_link_kept_as_metadata(tmp_path):
    raw = plaintext((), link=('0800_appli/tmp/mtab', '../proc/mounts', tarfile.SYMTYPE))
    dest = tmp_path/'out'; dest.mkdir()
    _, _, _, entries, _ = tool.read_archive(io.BytesIO(raw), len(raw), dest)
    assert entries[0]['link'] == '../proc/mounts' and not list(dest.rglob('*'))


def test_checksum_updated_and_bad_baseline_rejected():
    name = '0701_part_image_sum/part_image.sum'; target = '0700_part_image/dev/nflasha8'
    old, new = b'one', b'two'
    text = f'0,{zlib.crc32(old):08x},00000003,0,0,0,root,root,-1,-1,dev/nflasha8,\n'.encode()
    before = {target: dict(size=3, crc32=f'{zlib.crc32(old):08x}')}
    after = {target: dict(bytes=3, crc32=f'{zlib.crc32(new):08x}')}
    result = tool.checksum_updates(name, text, before, after)
    assert result.split(b',')[1] == f'{zlib.crc32(new):08x}'.encode()
    with pytest.raises(ValueError, match='原校验'):
        tool.checksum_updates(name, result, before, after)


def test_private_public_mismatch_and_key_permissions(tmp_path):
    private = tool.HOME/'keys/research-signing-private.pem'
    wrong = tmp_path/'wrong.pem'; wrong.write_bytes(RSA.generate(2048).public_key().export_key())
    with pytest.raises(ValueError, match='不配对'):
        tool.signing_key(private, wrong)
    if os.name != 'nt':
        p = tmp_path/'private.pem'; p.write_bytes(private.read_bytes()); p.chmod(0o644)
        with pytest.raises(ValueError, match='0600'):
            tool.signing_key(p, tool.HOME/'keys/research-public.pem')


def test_existing_output_untouched(tmp_path):
    work = tmp_path/'work'; work.mkdir(); out = tmp_path/'BODYDATA.DAT'; out.write_bytes(b'keep')
    with pytest.raises(ValueError, match='拒绝覆盖'):
        tool.pack(work, out)
    assert out.read_bytes() == b'keep'


def test_raw_image_and_component_conflict(tmp_path):
    work = tmp_path/'work'; (work/'archive/0700_part_image/dev').mkdir(parents=True)
    (work/'archive'/tool.AP_IMAGE).write_bytes(b'two')
    (work/'components/usr/lib').mkdir(parents=True)
    (work/'components/usr/lib/appFw.so').write_bytes(b'two')
    manifest = dict(entries=[dict(name=tool.AP_IMAGE,type='0',size=3,sha256=sha(b'one'))],
                    components={'usr/lib/appFw.so':dict(image=tool.AP_IMAGE,path='/lib/appFw.so',sha256=sha(b'one'))})
    with pytest.raises(ValueError, match='同时修改'):
        tool.collect(work, manifest, tmp_path)


def make_workspace(tmp_path):
    work = tmp_path/'work'; work.mkdir()
    for n in ['archive', 'components', 'format']:
        (work/n).mkdir()
    raw = plaintext()
    h, u, info, entries, tail = tool.read_archive(io.BytesIO(raw), len(raw), work/'archive')
    (work/'format/header.bin').write_bytes(h); (work/'format/updater.bin').write_bytes(u)
    m = dict(schema=1,source={'sha256':sha(raw)},header=info,header_sha256=sha(h),updater_sha256=sha(u),
             decryption={'plaintext_bytes':len(raw)},entries=entries,tail=tool.encode(tail),components={},**envelope())
    (work/'manifest.json').write_text(json.dumps(m))
    return work


def test_pack_modified_member_version_and_failure_not_published(tmp_path, monkeypatch):
    work = make_workspace(tmp_path)
    (work/'archive/0100_config/value').write_bytes(b'two')
    out = tmp_path/'ok.DAT'; result = tool.pack(work, out, version='4.06')
    assert result['changed_archive_members'] == ['0100_config/value']
    clear = io.BytesIO(); facts = decrypt_to(out, clear)
    clear.seek(0); assert header_info(clear.read(512), facts['plaintext_bytes'])['minor'] == 6
    target = tmp_path/'failed.DAT'
    def fail(*a, **kw):
        raise ValueError('独立回读失败')
    monkeypatch.setattr(tool, 'decoded_chunks', fail)
    with pytest.raises(ValueError, match='回读失败'):
        tool.pack(work, target)
    assert not target.exists() and not target.with_suffix('.DAT.json').exists()


def test_workspace_symlink_rejected(tmp_path):
    work = make_workspace(tmp_path)
    (work/'components/link').symlink_to(work/'archive', target_is_directory=True)
    with pytest.raises(ValueError, match='符号链接'):
        tool.pack(work, tmp_path/'bad.DAT')
