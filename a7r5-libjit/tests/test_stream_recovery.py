"""恢复契约：未确认旧响应结束前零OUT，任何失败都不开放STOP。"""
from collections import deque
import hashlib
import json
from pathlib import Path
import struct
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/'recovery'))
import recovery_flow as recovery
from transport import HEADER

from references import loader_path
LOADER = loader_path(ROOT).read_bytes()
EXPECTED = b'\0'*4+LOADER
OLD = ROOT/'packages/libjit-info-20261021-01'
CONFIG = json.loads((OLD/'config.json').read_text())
VERSION = (OLD/'result/session/version.bin').read_bytes()
PRELOAD = bytes.fromhex(CONFIG['preload_baselines'][1][1])


class Pending:
    def __init__(self, offset=32768, fault=None, short=False):
        self.queue = deque()
        self.writes = []
        self.short = short
        self.fault = fault
        self.gets = 0
        for start in range(offset, len(EXPECTED), 32768):
            block = EXPECTED[start:start+32768]
            self.queue.append(block)
            if len(block) % 512 == 0:
                self.queue.append(b'')
        if fault == 'mismatch': self.queue[0] = b'not-a-library'
        if fault == 'unexpected-zlp': self.queue.appendleft(b'')
        if fault == 'missing-zlp': del self.queue[1]
        if fault == 'nonempty-zlp': self.queue[1] = b'foreign'
        if fault == 'empty-queue': self.queue.clear()
        if fault == 'truncated': self.queue.pop()
        self.old_reads = 0

    def read(self, n):
        if not self.queue:
            raise TimeoutError('synthetic empty endpoint')
        self.old_reads += int(not self.writes)
        raw = self.queue.popleft()
        count = min(503, n) if self.short and n != 12 else n
        result = raw[:count]
        if raw[count:]: self.queue.appendleft(raw[count:])
        return result

    def write(self, packet):
        # 独立端点队列断言：任何残留尚未消费时不能有OUT。
        assert not self.queue
        self.writes.append(packet)
        size, func, seq, *meta = HEADER.unpack_from(packet)
        body = packet[12:]
        assert size == len(body) and func == 64 and not any(meta)
        group, cmd = struct.unpack_from('<HH', body)
        assert group == 4097 and cmd in (15, 17)
        data = b''
        if cmd == 15:
            self.path = body[5:-1]
        else:
            self.gets += 1
            data = VERSION if self.path.endswith(b'/version.txt') else PRELOAD
            if self.fault == 'version' and self.gets == 1: data = b'wrong-version'
            if self.fault == 'preload' and self.gets == 2: data = b'unknown-preload'
            if self.fault == 'preload-changed' and self.gets == 4: data = b'\n'*512
        response = b'\0'*4+data
        header = HEADER.pack(len(response), 64, seq, 3, 0, 0, 0)
        if self.fault == 'sequence': header = HEADER.pack(len(response), 64, seq+1, 3, 0, 0, 0)
        if self.fault == 'status': header = HEADER.pack(len(response), 64, seq, 3, 0, 0, 1)
        if self.fault == 'metadata': header = HEADER.pack(len(response), 64, seq, 2, 0, 0, 0)
        if self.fault == 'short-header': header = b'bad'
        self.queue.extend([header, response])
        return len(packet)-1 if self.fault == 'short-write' else len(packet)


@pytest.mark.parametrize('offset', list(range(0, 233420, 32768)))
@pytest.mark.parametrize('short', [False, True])
def test_real_library_suffix_uniquely_matches_before_any_out(offset, short):
    driver = Pending(offset, short=short)
    proof = recovery.drain_known_response(driver, EXPECTED, lambda *a, **k: None)
    assert proof['start_offset'] == offset and proof['bytes'] == 233420-offset
    assert proof['sha256'] == hashlib.sha256(EXPECTED[offset:]).hexdigest()
    assert not driver.queue and not driver.writes


@pytest.mark.parametrize('fault', ['mismatch', 'unexpected-zlp', 'missing-zlp', 'nonempty-zlp', 'empty-queue', 'truncated'])
def test_drain_failure_never_sends_out_or_opens_gate(tmp_path, fault):
    driver = Pending(fault=fault)
    with pytest.raises((ValueError, TimeoutError)):
        recovery.recover_stream(driver, tmp_path, lambda *a, **k: None, CONFIG, EXPECTED)
    assert not driver.writes and not (tmp_path/'read-gates.json').exists()


def test_ambiguous_zero_suffix_is_rejected_instead_of_reading_past_end():
    driver = Pending(229376)
    driver.queue = deque([b'\0'*4044])
    with pytest.raises(ValueError, match='歧义'):
        recovery.drain_known_response(driver, b'\0'*233420, lambda *a, **k: None)
    assert not driver.writes


def test_drain_time_and_call_budgets_are_bounded():
    ticks = iter([0, 61])
    with pytest.raises(TimeoutError):
        recovery.drain_known_response(Pending(), EXPECTED, lambda *a, **k: None, clock=lambda: next(ticks))
    class OneByte(Pending):
        def read(self, n): return super().read(min(n, 1))
    with pytest.raises(TimeoutError):
        recovery.drain_known_response(OneByte(), EXPECTED, lambda *a, **k: None)


def test_drain_then_exact_four_reads_has_only_eight_requests(tmp_path):
    driver = Pending(short=True)
    proof = recovery.recover_stream(driver, tmp_path, lambda *a, **k: None, CONFIG, EXPECTED)
    assert proof['gate_passed'] and proof['protocol_requests'] == len(driver.writes) == 8
    assert [HEADER.unpack_from(p)[2] for p in driver.writes] == list(range(5, 13))
    assert (tmp_path/'preload-a.bin').read_bytes() == (tmp_path/'preload-b.bin').read_bytes() == PRELOAD


@pytest.mark.parametrize('fault', ['version', 'preload', 'preload-changed', 'sequence', 'status', 'metadata', 'short-header', 'short-write'])
def test_read_gate_failure_does_not_complete(tmp_path, fault):
    driver = Pending(fault=fault)
    with pytest.raises((ValueError, OSError)):
        recovery.recover_stream(driver, tmp_path, lambda *a, **k: None, CONFIG, EXPECTED)
    assert not (tmp_path/'read-gates.json').exists() and len(driver.writes) <= 8


def test_fixed_operation_rejects_write_debug_reordered_read(tmp_path):
    operation = recovery.FixedOperation(tmp_path)
    for cmd in [5, 16, 17]:
        body = struct.pack('<HH', 4097, cmd)+b'\0\xff\0'
        packet = HEADER.pack(len(body), 64, 5, 0, 0, 0, 0)+body
        operation.permitted_packet = packet
        with pytest.raises(PermissionError): operation.guard_packet(packet)
    assert operation.index == 0


class Device:
    bus = 0
    port_numbers = [1]
    idProduct = 822
    def __init__(self, fault=None):
        self.pending = Pending(fault=fault)
        self.stop = []
        self.fault = fault
        values = CONFIG['interfaces']['interface-2.json']
        self.interface = Interface(values)
    def get_active_configuration(self): return {(0, 0): self.interface}
    def is_kernel_driver_active(self, _): return self.fault == 'active-driver'
    def read(self, ep, n, timeout):
        assert ep == 129 and 0 < timeout <= 5000
        return self.pending.read(n)
    def write(self, ep, raw, timeout):
        assert ep == 2
        return self.pending.write(raw)
    def ctrl_transfer(self, *args, **kwargs):
        assert args == recovery.STOP
        self.stop.append(args)
        if self.fault == 'stop-pipe': raise OSError('synthetic pipe')


class Interface(list):
    bInterfaceNumber = 0
    bAlternateSetting = 0
    bInterfaceClass = 255
    bInterfaceSubClass = 0
    bInterfaceProtocol = 0
    def __init__(self, value):
        super().__init__([SimpleNamespace(bEndpointAddress=row['address'], bmAttributes=row['attributes'],
                                        wMaxPacketSize=row['max_packet'], bInterval=row['interval'])
                          for row in value['endpoints']])


@pytest.mark.parametrize('fault', [None, 'stop-pipe', 'mismatch', 'preload', 'active-driver', 'fingerprint'])
def test_single_claim_and_stop_only_after_all_gates(tmp_path, monkeypatch, fault):
    dev = Device(fault)
    if fault == 'fingerprint': dev.interface.reverse()
    actions = []
    core = SimpleNamespace(find=lambda **kwargs: [dev])
    util = SimpleNamespace(claim_interface=lambda *a: actions.append('claim'),
                           release_interface=lambda *a: actions.append('release'),
                           dispose_resources=lambda *a: actions.append('dispose'))
    monkeypatch.setattr(recovery, 'usb_runtime', lambda _: (core, util, None))
    local = tmp_path/'bundle'; (local/'evidence').mkdir(parents=True)
    (local/'evidence/libJiritsu.so').write_bytes(LOADER)
    monkeypatch.setattr(recovery, 'HERE', local)
    out = tmp_path/'out'; out.mkdir()
    report = dict(gate_passed=False, stop_attempts=0)
    if fault in [None, 'stop-pipe']:
        recovery.service_attempt(dict(config=CONFIG), out, lambda *a, **k: None, report)
        assert report['gate_passed'] and report['stop_attempts'] == len(dev.stop) == 1
    else:
        with pytest.raises((ValueError, PermissionError)):
            recovery.service_attempt(dict(config=CONFIG), out, lambda *a, **k: None, report)
        assert not report['gate_passed'] and report['stop_attempts'] == len(dev.stop) == 0
    assert actions.count('claim') <= 1 and actions.count('dispose') == 1
    if fault in ['mismatch', 'active-driver', 'fingerprint']: assert not dev.pending.writes


@pytest.mark.parametrize('kind', ['ordinary', 'transition', 'absent'])
def test_nonservice_branch_never_opens_usb(tmp_path, kind):
    def forbidden(*a): raise AssertionError('不能打开USB')
    report = {}
    if kind == 'absent':
        with pytest.raises(ValueError):
            recovery.dispatch(dict(kind=kind), {}, tmp_path, lambda *a, **k: None, report, forbidden, forbidden)
    else:
        recovery.dispatch(dict(kind=kind), {}, tmp_path, lambda *a, **k: None, report,
                          forbidden, lambda: dict(recovered=True))
        assert report['host_recovery_verified']


def test_no_approval_blocks_before_snapshot_or_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(recovery, 'HERE', tmp_path)
    with pytest.raises(PermissionError): recovery.execute(True)
    assert not (tmp_path/'ATTEMPT_LOCK').exists()


@pytest.mark.parametrize('fault', ['material', 'dependency', 'approval', 'old-lock', 'moved', 'symlink'])
def test_immutable_package_and_approval_reject_changes(tmp_path, monkeypatch, fault):
    bundle = tmp_path/'bundle'; bundle.mkdir()
    source = bundle/'source.py'; source.write_text('original')
    dependency = tmp_path/'dependency'; dependency.write_bytes(b'dependency')
    manifest = dict(schema='a7r5-libjit-stream-recovery-1', run_id=recovery.RUN, risk=recovery.RISK,
                    directory=str(bundle), files={'source.py': recovery.digest(source.read_bytes())},
                    dependencies={str(dependency): recovery.digest(dependency.read_bytes())})
    recovery.save(bundle/'recovery.json', manifest)
    recovery.save(bundle/'approval.json', dict(accepted=True, risk=recovery.RISK,
                  recovery_sha256=recovery.digest((bundle/'recovery.json').read_bytes())))
    monkeypatch.setattr(recovery, 'HERE', bundle)
    recovery.check(True)
    if fault == 'material': source.write_text('changed')
    if fault == 'dependency': dependency.write_bytes(b'changed')
    if fault == 'approval': (bundle/'approval.json').write_text('{}')
    if fault == 'old-lock': (bundle/'ATTEMPT_LOCK').mkdir()
    if fault == 'moved': monkeypatch.setattr(recovery, 'HERE', tmp_path)
    if fault == 'symlink':
        source.unlink(); source.symlink_to(dependency)
    with pytest.raises((ValueError, PermissionError, FileExistsError, FileNotFoundError)):
        recovery.check(True)
