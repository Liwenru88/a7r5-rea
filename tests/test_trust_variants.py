"""信任候选两种模式的离线回归；私有镜像不存在时跳过设备相关用例。"""
import hashlib
import json
import os
import pathlib
import subprocess
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'a7r5-updater-trust/src'))
from partition_sparse import apply_sparse, make_sparse  # noqa: E402

IMAGE = pathlib.Path(os.environ.get('A7R5_TRUST_TEST_IMAGE', ROOT / '.local/verify-20261122/partition1.logical.bin'))
SOURCE_SHA = os.environ.get('A7R5_TRUST_TEST_SOURCE_SHA') or (hashlib.sha256(IMAGE.read_bytes()).hexdigest() if IMAGE.is_file() else '')
BUILD = pathlib.Path(os.environ.get('A7R5_TRUST_TEST_BUILD', ROOT / '.local/verify-20261122/build'))
SECTOR = 512


def test_sparse_synthetic_roundtrip():
    before = bytes(4096)
    after = bytearray(before)
    after[512:1024] = b'\x11' * 512
    sparse = make_sparse(before, bytes(after))
    rebuilt, written = apply_sparse(before, sparse)
    assert rebuilt == bytes(after)
    assert written == [1]


@pytest.mark.skipif(not IMAGE.is_file(), reason='本机 cnflasha1 镜像不在')
def test_build_variants_and_rescue(tmp_path):
    raw = IMAGE.read_bytes()
    for mode, sectors, replaced in (('skip-key', 233, False), ('replace-key', 258, True)):
        out = tmp_path / mode
        subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/build_trust_candidate.py'),
                        '--image', str(IMAGE), '--mode', mode,
                        '--source-sha', SOURCE_SHA, '--output', str(out)],
                       check=True, capture_output=True)
        summary = json.loads((out / 'summary.json').read_text())
        assert summary['sectors'] == sectors
        assert summary['key_replaced'] is replaced
        assert summary['source_sha256'] == hashlib.sha256(raw).hexdigest()
        candidate = (out / 'candidate.bin').read_bytes()
        plan = json.loads((out / 'plan.json').read_text())
        assert len(plan['rows']) == sectors
        assert plan['candidate_sha256'] == hashlib.sha256(candidate).hexdigest()

        applied = bytearray(raw)
        for row in plan['rows']:
            off = row['offset']
            applied[off:off + SECTOR] = candidate[off:off + SECTOR]
        assert bytes(applied) == candidate
        assert hashlib.sha256(candidate).hexdigest() == summary['candidate_sha256']

        if mode == 'skip-key':
            sparse = make_sparse(candidate, raw)
            assert len(sparse) <= 524288
            for cut in (1, 50, 100, sectors):
                partial = bytearray(raw)
                for row in plan['rows'][:cut]:
                    off = row['offset']
                    partial[off:off + SECTOR] = candidate[off:off + SECTOR]
                rebuilt, _ = apply_sparse(bytes(partial), sparse)
                assert rebuilt == raw, cut


def test_journal_accepts_dynamic_sector_count():
    sys.path.insert(0, str(ROOT / 'a7r5-desktop/engine'))
    import trust_operation

    rows = [{'offset': 1000, 'phase': 'initrd'}, {'offset': 1512, 'phase': 'initrd'},
            {'offset': 2024, 'phase': 'checksum'}]
    plan = {'rows': rows}
    run = '0' * 32
    lines = [f'A7R5_TRUST {run} PREIMAGE_VERIFIED completed=0 offset=-1 code=0']
    for index, row in enumerate(rows):
        lines.append(f'A7R5_TRUST {run} WRITE_BEGIN completed={index} offset={row["offset"]} code=0')
        lines.append(f'A7R5_TRUST {run} WRITE_RETURNED completed={index+1} offset={row["offset"]} code=0')
        if index == len(rows) - 1 or row['phase'] != rows[index + 1]['phase']:
            lines.append(f'A7R5_TRUST {run} PHASE_SYNC_RETURNED completed={index+1} offset={row["offset"]} code=0')
    total = len(rows)
    lines += [f'A7R5_TRUST {run} FULL_LOGICAL_READBACK_MATCH completed={total} offset=-1 code=0',
              f'A7R5_TRUST {run} REOPENED_FULL_CAPTURE_MATCH completed={total} offset=-1 code=0',
              f'A7R5_TRUST {run} COMPLETED completed={total} offset=-1 code=0']
    journal = ('\n'.join(lines) + '\n').encode()
    assert trust_operation.validate_journal(journal, run, plan) is True


@pytest.mark.skipif(not (pathlib.Path('/opt/homebrew/opt/llvm/bin/clang').is_file()
                         and pathlib.Path('/opt/homebrew/opt/lld/bin/ld.lld').is_file()),
                    reason='需要 llvm clang 与 ld.lld')
def test_native_payload_compiles_with_dynamic_count(tmp_path):
    sys.path.insert(0, str(ROOT / 'a7r5-desktop/scripts'))
    import prepare

    rows = [{'offset': 0, 'phase': 'initrd'}, {'offset': 512, 'phase': 'initrd'},
            {'offset': 1024, 'phase': 'checksum'}]
    plan = {'rows': rows}
    before = bytes([0x11]) * (len(rows) * SECTOR)
    after = bytes([0x22]) * (len(rows) * SECTOR)
    lib = prepare.trust_sector_library(
        tmp_path / 'lib', '0' * 32, '',
        '00' * 32, '11' * 32, before, after, plan)
    assert b'sectors=3 bytes=1536' in lib
    assert b'sectors=258 bytes=132096' not in lib


@pytest.mark.skipif(not IMAGE.is_file(), reason='本机 cnflasha1 镜像不在')
def test_skip_key_only_touches_verifykey_entries(tmp_path):
    import io
    from elftools.elf.elffile import ELFFile
    from filesystems import FatImage, SquashImage
    import trust_recipe

    out = tmp_path / 'skip'
    subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/build_trust_candidate.py'),
                    '--image', str(IMAGE), '--mode', 'skip-key',
                    '--source-sha', SOURCE_SHA, '--output', str(out)],
                   check=True, capture_output=True)
    raw = IMAGE.read_bytes()
    candidate = (out / 'candidate.bin').read_bytes()
    fat0, fat1 = FatImage(raw), FatImage(candidate)
    sq0 = SquashImage(fat0.read('/boot/initrd.img'))
    sq1 = SquashImage(fat1.read('/boot/initrd.img'))

    # 1) 官方 PEM 原样保留
    assert sq1.read('/etc/VerificationKey.pem') == sq0.read('/etc/VerificationKey.pem')

    # 2) 只有四个库变化
    changed = sorted(p for p in sq0.nodes
                     if sq0.nodes[p]['inode_type'] in (2, 9) and sq1.read(p) != sq0.read(p))
    assert changed == ['/usr/lib/' + name for name in sorted(trust_recipe.TARGETS)]

    # 3) 每个库的差异只落在 verifyKey 入口的 8 字节内，且等于 mov w0,#0; ret
    patch = bytes.fromhex('00008052c0035fd6')
    for name in trust_recipe.TARGETS:
        path = '/usr/lib/' + name
        before, after = sq0.read(path), sq1.read(path)
        offset = trust_recipe.elf_offset(ELFFile(io.BytesIO(before)), trust_recipe.TARGETS[name][0])
        diffs = [i for i, (a, b) in enumerate(zip(before, after)) if a != b]
        assert diffs, name
        assert all(offset <= i < offset + 8 for i in diffs), name
        assert after[offset:offset + 8] == patch, name
        assert before[offset:offset + 8] == bytes.fromhex('fd7bb2a9e00301aa'), name

    # 4) p1chksum 与候选 initrd 自洽
    import hashlib
    sums = fat1.read('/p1chksum').decode()
    expected = (hashlib.md5(fat1.read('/boot/vmlinux.bin')).hexdigest() + '  ./boot/vmlinux.bin\n' +
                hashlib.md5(fat1.read('/boot/initrd.img')).hexdigest() + '  ./boot/initrd.img\n')
    assert sums == expected


@pytest.mark.skipif(not IMAGE.is_file(), reason='本机 cnflasha1 镜像不在')
def test_verify_nflasha1_tool(tmp_path):
    tool = ROOT / 'a7r5-fastboot/rescue/verify_nflasha1.py'
    def run(*args):
        return subprocess.run([sys.executable, '-B', str(tool), *args],
                              capture_output=True, text=True).returncode
    assert run('--image', str(IMAGE), '--expect', SOURCE_SHA) == 0
    assert run('--image', str(IMAGE), '--expect', '0' * 64) == 1

    out = tmp_path / 'skip'
    subprocess.run([sys.executable, '-B', str(ROOT / 'scripts/build_trust_candidate.py'),
                    '--image', str(IMAGE), '--mode', 'skip-key',
                    '--source-sha', SOURCE_SHA, '--output', str(out)],
                   check=True, capture_output=True)
    sparse = tmp_path / 'rescue.sparse'
    subprocess.run([sys.executable, '-B', str(ROOT / 'a7r5-fastboot/rescue/build_rescue_sparse.py'),
                    '--before', str(IMAGE), '--after', str(out / 'candidate.bin'),
                    '--output', str(sparse)], check=True, capture_output=True)
    assert run('--image', str(out / 'candidate.bin'), '--sparse', str(sparse),
               '--expect', SOURCE_SHA) == 0


@pytest.mark.skipif(not IMAGE.is_file(), reason='本机 cnflasha1 镜像不在')
def test_verify_known_partial_accepts_half_written(tmp_path):
    build = BUILD / 'replace-key-258'
    if not (build / 'candidate.bin').is_file():
        pytest.skip('258 构建不在')
    tool = ROOT / 'a7r5-fastboot/rescue/verify_nflasha1.py'
    plan = json.loads((build / 'plan.json').read_text())
    candidate = (build / 'candidate.bin').read_bytes()
    source = IMAGE.read_bytes()
    half = bytearray(source)
    for row in plan['rows'][:10]:
        at = row['offset']; half[at:at + 512] = candidate[at:at + 512]
    half_path = tmp_path / 'half.bin'; half_path.write_bytes(half)
    bad_path = tmp_path / 'bad.bin'
    broken = bytearray(half); broken[0] ^= 1; bad_path.write_bytes(broken)

    def run(image):
        return subprocess.run([sys.executable, '-B', str(tool), '--image', str(image),
                               '--known-partial', '--source', str(IMAGE),
                               '--candidate', str(build / 'candidate.bin'),
                               '--plan', str(build / 'plan.json')],
                              capture_output=True).returncode
    assert run(IMAGE) == 0
    assert run(half_path) == 0
    assert run(build / 'candidate.bin') == 0
    assert run(bad_path) == 1


def test_rescue_writer_requires_data_before_approval():
    writer = ROOT / 'a7r5-fastboot/host/rescue_writer'
    if not writer.is_file():
        pytest.skip('救援写入器不在')
    data = writer.read_bytes()
    assert b'DOWNLOAD OKAY BEFORE DATA' in data
    assert b'data_sent' in data
