"""CP候选只改定长文件，真实分区回读和失败路径不扩大写入。"""
from pathlib import Path
from types import SimpleNamespace
import struct
import sys
import zlib
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'experiments/packaging406'))
import stage_cp as cp

WORK = cp.ROOT/'.local/aspect-guide406-update-20261026-01/work/archive'


@pytest.fixture(scope='module')
def original():
    image = WORK/'0700_part_image/dev/nflasha8'
    checksum = WORK/'0701_part_image_sum/part_image.sum'
    if not image.is_file() or not checksum.is_file():
        pytest.skip('本地固定修改版4.06分区未提供')
    return image.read_bytes(), checksum.read_bytes()


def test_partition_roundtrip_preserves_other_files_and_exact_metadata(original):
    image, _ = original
    raw, extents = cp.independent_cp(image)
    assert len(raw) == cp.CP_BYTES and cp.sha(raw) == cp.CP_SHA
    candidate = bytearray(raw)
    # 跨簇边界，验证不把原文件偏移当分区偏移。
    boundary = extents[0][1]
    candidate[boundary-2:boundary+2] = b'ABCD'
    target, count, actual = cp.patch_image(image, bytes(candidate))
    assert count == 11 and extents == actual
    assert cp.independent_cp(target)[0] == candidate
    assert target[:extents[0][0]] == image[:extents[0][0]]


@pytest.mark.parametrize('damage', ['copies', 'loop', 'short', 'directory'])
def test_independent_reader_rejects_corrupt_fat_metadata(original, damage):
    image = bytearray(original[0])
    sector = 512
    fat_at = struct.unpack_from('<H', image, 14)[0]*sector
    fat_size = struct.unpack_from('<H', image, 22)[0]*sector
    root = fat_at+2*fat_size
    entry = next(i for i in range(root, root+512*32, 32) if image[i:i+11] == b'CPAPP-B BIN')
    cluster = struct.unpack_from('<H', image, entry+26)[0]
    if damage == 'copies':
        image[fat_at+3] ^= 1
    elif damage == 'directory':
        image[entry+11] = 0x10
    else:
        value = cluster if damage == 'loop' else 0xfff
        pos = cluster*3//2
        for start in (fat_at, fat_at+fat_size):
            old = int.from_bytes(image[start+pos:start+pos+2], 'little')
            word = ((old & 0xf) | value << 4) if cluster & 1 else ((old & 0xf000) | value)
            struct.pack_into('<H', image, start+pos, word)
    with pytest.raises(ValueError):
        cp.independent_cp(bytes(image))


def test_sum_changes_only_cp_crc_and_preserves_other_records(original):
    image, checksum = original
    target = bytearray(image)
    target[-1] ^= 1
    new = cp.update_sum(checksum, target)
    before = checksum.splitlines()
    after = new.splitlines()
    assert len(new) == len(checksum)
    changed = [i for i, (a,b) in enumerate(zip(before, after)) if a != b]
    assert len(changed) == 1
    a, b = before[changed[0]].split(b','), after[changed[0]].split(b',')
    assert a[:1]+a[2:] == b[:1]+b[2:]
    assert b[1] == f'{zlib.crc32(target):08x}'.encode()
    with pytest.raises(ValueError, match='校验清单'):
        cp.update_sum(checksum+b'\n', target)


def fake_api(raw):
    candidate = bytearray(raw)
    candidate[24] ^= 1
    candidate = bytes(candidate)
    plan = dict(native_integration=True, capacity_layout_version='capture-color-22-v1',
                patches=[{}]*69, native_hooks=[{}]*51, native_contract_bytes=1280,
                build_receipt_sha256='1'*64)
    def transform(data, supplied, reverse=False):
        assert supplied == plan
        assert data == (candidate if reverse else raw)
        return raw if reverse else candidate
    return SimpleNamespace(create_plan=lambda *_: plan, transform=transform)


@pytest.fixture
def staging(tmp_path, monkeypatch, original):
    image = tmp_path/'source-fat'
    image.write_bytes(original[0])
    checksum = tmp_path/'source.sum'
    checksum.write_bytes(original[1])
    monkeypatch.setattr(cp, 'ROOT', tmp_path)
    api = fake_api(cp.independent_cp(original[0])[0])
    monkeypatch.setattr(cp, 'memory_api', lambda: api)
    return image, checksum, tmp_path/'build', tmp_path/'.local/candidate', api


def test_stage_writes_new_candidate_and_refuses_overwrite(staging):
    image, checksum, build, output, _ = staging
    before = image.read_bytes(), checksum.read_bytes()
    receipt = cp.stage(image, checksum, build, output)
    assert receipt['status'] == 'CP_FAT_STAGED_REVERSED_NOT_INSTALLABLE'
    assert receipt['whole_partition_reverse_equal'] and receipt['independent_cp_readback']
    assert not receipt['DAT_created'] and not receipt['private_key_accessed']
    assert (image.read_bytes(), checksum.read_bytes()) == before
    with pytest.raises(ValueError, match='全新'):
        cp.stage(image, checksum, build, output)


@pytest.mark.parametrize('failure', ['baseline', 'contract', 'linked_output', 'changing_build', 'changing_source'])
def test_stage_failures_never_publish_success_receipt(staging, failure):
    image, checksum, build, output, api = staging
    if failure == 'baseline':
        raw = bytearray(image.read_bytes()); raw[0] ^= 1; image.write_bytes(raw)
    elif failure == 'contract':
        api.create_plan(None, None)['native_contract_bytes'] = 1040
    elif failure == 'linked_output':
        output.parent.mkdir(); (output.parent/'linked').symlink_to(output.parent, target_is_directory=True)
        output = output.parent/'linked/candidate'
    else:
        call = 0
        original = api.create_plan
        def changing(*args):
            nonlocal call
            call += 1
            result = dict(original(*args))
            if call == 2:
                if failure == 'changing_source':
                    raw = bytearray(image.read_bytes()); raw[-1] ^= 1; image.write_bytes(raw)
                else:
                    result['build_receipt_sha256'] = '2'*64
            return result
        api.create_plan = changing
    with pytest.raises(ValueError):
        cp.stage(image, checksum, build, output)
    assert not (output/'verification.json').exists()
