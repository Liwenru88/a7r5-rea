"""离线验证 stock-absence 258 任务协议（fake channel，不接相机）。"""
import json
import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / 'a7r5-desktop/engine'))
sys.path.insert(0, str(ROOT / 'scripts'))
from transport import FileResultError  # noqa: E402

BUNDLE = pathlib.Path(os.environ.get('A7R5_TRUST_TEST_BUNDLE', ROOT / '.local/verify-20261122/build/bundle-258/07d0a64accee764171f2b2aff2cf41b9'))
MISSING = 0x10000006


class FakeChannel:
    def __init__(self, files):
        self.files = files
        self.puts = []

    def read(self, path, size):
        if path not in self.files:
            raise FileResultError(MISSING, action='read', path=path)
        return self.files[path][:size]

    def put(self, path, data):
        self.puts.append(path)
        self.files[path] = data


def journal(run, plan):
    lines = [f'A7R5_TRUST {run} PREIMAGE_VERIFIED completed=0 offset=-1 code=0']
    rows = plan['rows']
    for i, row in enumerate(rows):
        lines.append(f"A7R5_TRUST {run} WRITE_BEGIN completed={i} offset={row['offset']} code=0")
        lines.append(f"A7R5_TRUST {run} WRITE_RETURNED completed={i + 1} offset={row['offset']} code=0")
        if i == len(rows) - 1 or row['phase'] != rows[i + 1]['phase']:
            lines.append(f"A7R5_TRUST {run} PHASE_SYNC_RETURNED completed={i + 1} offset={row['offset']} code=0")
    for name in ('FULL_LOGICAL_READBACK_MATCH', 'REOPENED_FULL_CAPTURE_MATCH', 'COMPLETED'):
        lines.append(f'A7R5_TRUST {run} {name} completed={len(rows)} offset=-1 code=0')
    return ('\n'.join(lines) + '\n').encode()


@pytest.mark.skipif(not BUNDLE.is_dir(), reason='258 bundle 不在')
def test_stock_operation_fake_channel(tmp_path):
    from stock_trust_operation import Operation

    src = json.loads((BUNDLE / 'config.json').read_text())
    run = src['run_id']
    plan = json.loads((BUNDLE / 'write-plan.json').read_text())
    candidate = (BUNDLE / 'materials/candidate.logical.img').read_bytes()
    begin = src['expected_output_begin'].encode()
    end = src['expected_output_end'].encode()
    output = begin + (f'A7R5_TRUST_STOCK_COMPLETE {src["candidate_sha256"]} sectors=258 bytes=132096 '
                      f'reopened=1 chunks={src["chunks"]} chunk_bytes={src["chunk_bytes"]} preload=absent-v1\n').encode() + end
    prefix = '/tmp_wbshd/a7r5-control-' + run + '/task'
    state = (f'A7R5-JIT-1 {run} DONE 0 uid=0 euid=0 bytes={len(output)} disarmed=1 children=0\n').encode()

    bundle = tmp_path / 'bundle'
    (bundle / 'materials').mkdir(parents=True)
    for name in ('libJit.so', 'ticket.bin', 'write-plan.json', 'source.logical.img', 'candidate.logical.img'):
        (bundle / 'materials' / name).symlink_to(BUNDLE / 'materials' / name)
    config = dict(src, version_sha256=None, loader_sha256=None, loader_bytes=1000)
    version, loader = b'v' * 64, b'l' * 1000
    import hashlib
    config['version_sha256'] = hashlib.sha256(version).hexdigest()
    config['loader_sha256'] = hashlib.sha256(loader).hexdigest()
    (bundle / 'config.json').write_text(json.dumps(config))

    files = {'/version.txt': version, '/usr/lib/libJiritsu.so': loader}

    def on_put(path, data):
        files[path] = data
        if path != '/tmp/jiritsu/libJit.so':
            return
        files[prefix + '.state'] = state
        files[src['journal_path']] = journal(run, plan)
        files[prefix + '.output'] = output
        for i in range(src['chunks']):
            files[src['readback_path'] + f'.part-{i}'] = candidate[i * src['chunk_bytes']:(i + 1) * src['chunk_bytes']]

    class Channel(FakeChannel):
        def put(self, path, data):
            super().put(path, data)
            on_put(path, data)

    fake = Channel(files)
    op = Operation(bundle, channel_factory=lambda *a: fake, clock=lambda: 0.0, sleep=lambda *_: None)
    out = tmp_path / 'out'
    out.mkdir()
    report = {}
    op(None, out, lambda *a, **k: None, report)
    assert op.safe_to_stop is True
    assert report['complete_partition_readback_verified'] is True
    assert fake.puts == [src['ticket_path'], '/tmp/jiritsu/libJit.so']
    assert (out / 'partition1.readback.bin').read_bytes() == candidate
    assert (out / 'trust-native-verified.json').is_file()


def test_bundle_payload_is_real_device_writer():
    payload = (BUNDLE / 'materials/libJit.so').read_bytes()
    run = json.loads((BUNDLE / 'config.json').read_text())['run_id']
    assert b'/dev/cnflasha1' in payload
    assert run.encode() in payload
    assert b'/tmp/a7r5-host/target.bin' not in payload
    assert b'sectors=258 bytes=132096' in payload


def test_launcher_rejects_incomplete_session(tmp_path):
    from types import SimpleNamespace
    import trust_write_258 as launcher

    class Incomplete:
        @staticmethod
        def run_session(output, transport, _operation):
            return {'complete_partition_readback_verified': False, 'protocol_gate_passed': True}

    with pytest.raises(SystemExit):
        launcher.execute(SimpleNamespace(), tmp_path, Incomplete)

    class Complete:
        @staticmethod
        def run_session(output, transport, _operation):
            return {'complete_partition_readback_verified': True, 'protocol_gate_passed': True,
                    'logical_partition_sha256': '00'}

    op = SimpleNamespace()
    report = launcher.execute(op, tmp_path, Complete)
    assert op.output == tmp_path and report['protocol_gate_passed'] is True


REHEARSAL = pathlib.Path(os.environ.get('A7R5_TRUST_TEST_REHEARSAL', ROOT / '.local/verify-20261122/build/bundle-rehearsal/6a182972377280d55e4db71994e9dbd2'))


@pytest.mark.skipif(not REHEARSAL.is_dir(), reason='rehearsal bundle 不在')
def test_rehearsal_zero_write_protocol(tmp_path):
    from stock_trust_operation import Operation

    src = json.loads((REHEARSAL / 'config.json').read_text())
    run = src['run_id']
    plan = json.loads((REHEARSAL / 'materials/write-plan.json').read_text())
    assert plan['rows'] == []
    source = (REHEARSAL / 'materials/source.logical.img').read_bytes()
    begin = src['expected_output_begin'].encode()
    end = src['expected_output_end'].encode()
    output = begin + (f'A7R5_TRUST_STOCK_COMPLETE {src["candidate_sha256"]} sectors=0 bytes=0 '
                      f'reopened=1 chunks={src["chunks"]} chunk_bytes={src["chunk_bytes"]} preload=absent-v1\n').encode() + end
    prefix = '/tmp_wbshd/a7r5-control-' + run + '/task'
    state = (f'A7R5-JIT-1 {run} DONE 0 uid=0 euid=0 bytes={len(output)} disarmed=1 children=0\n').encode()

    bundle = tmp_path / 'bundle'
    (bundle / 'materials').mkdir(parents=True)
    for name in ('libJit.so', 'ticket.bin', 'write-plan.json', 'source.logical.img', 'candidate.logical.img'):
        (bundle / 'materials' / name).symlink_to(REHEARSAL / 'materials' / name)
    import hashlib
    version, loader = b'v' * 64, b'l' * 1000
    config = dict(src, version_sha256=hashlib.sha256(version).hexdigest(),
                  loader_sha256=hashlib.sha256(loader).hexdigest(), loader_bytes=1000)
    (bundle / 'config.json').write_text(json.dumps(config))

    files = {'/version.txt': version, '/usr/lib/libJiritsu.so': loader}

    class Channel(FakeChannel):
        def put(self, path, data):
            super().put(path, data)
            if path != '/tmp/jiritsu/libJit.so':
                return
            files[prefix + '.state'] = state
            files[src['journal_path']] = journal(run, plan)
            files[prefix + '.output'] = output
            for i in range(src['chunks']):
                files[src['readback_path'] + f'.part-{i}'] = source[i * src['chunk_bytes']:(i + 1) * src['chunk_bytes']]

    fake = Channel(files)
    op = Operation(bundle, channel_factory=lambda *a: fake, clock=lambda: 0.0, sleep=lambda *_: None)
    out = tmp_path / 'out'; out.mkdir()
    report = {}
    op(None, out, lambda *a, **k: None, report)
    assert op.safe_to_stop is True
    assert report['complete_partition_readback_verified'] is True
    assert (out / 'partition1.readback.bin').read_bytes() == source
