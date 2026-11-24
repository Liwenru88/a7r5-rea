"""稳定性外部结果回归；不把控制面与文件夹具当成硬件验收。"""
import struct
import zlib

import pytest

from replay import Replay, recipe


class FaultReplay(Replay):
    def __init__(self, files=None, cards=None):
        self.armed = self.drop_rollback = self.fail_forward = False
        self.first_refresh_failed = self.publication_failed = self.published_target = False
        self.fail_rollback_storage = self.uncertain_publication = False
        self.drop_target_ack = False
        self.chunk = 1024
        super().__init__(files={'R5NATIVE.BIN': recipe()} if files is None else files, cards=cards)

    def refresh(self, ap):
        if self.armed and self.fail_forward and not self.first_refresh_failed:
            self.first_refresh_failed = True
            self.trace.append(['injected_forward_E4_timeout'])
            return 0
        return super().refresh(ap)

    def send(self, ap):
        packet = ap.read(ap.arg(1), ap.arg(2))
        slot = struct.unpack_from('<I', packet, 12)[0] if packet[0] == 0xea else None
        if self.armed and self.drop_rollback and slot == 13:
            self.trace.append(['injected_rollback_packet_loss', 13])
            return 0
        if self.armed and self.drop_target_ack and slot == 24:
            self.drop_target_ack = False
            assert self.cp.consume(packet)
            self.trace.append(['injected_ACK_loss_after_CP_acceptance', 24])
            return 0
        return super().send(ap)

    def rename(self, ap):
        source, target = ap.string(ap.arg(1)), ap.string(ap.arg(3))
        result = super().rename(ap)
        if self.armed and target == 'R5FILTER.BIN' and struct.unpack_from('<I', self.files[target], 12)[0] == 24:
            self.published_target = True
        return result

    def sync(self, ap):
        if self.uncertain_publication and self.published_target and ap.arg(0) == 9 and not self.publication_failed:
            self.publication_failed = True
            return self.error(5)
        return super().sync(ap)

    def openat(self, ap):
        if (self.fail_rollback_storage and self.publication_failed and
                ap.string(ap.arg(1)) == 'R5FILTER.NEW' and ap.arg(2) == 0x80c1):
            return self.error(5)
        return super().openat(ap)

    def card_read(self, ap):
        _, raw, pos, _ = self.handles[ap.arg(0)]
        data = bytes(raw[pos:pos + min(ap.arg(2), self.chunk)])
        ap.write(ap.arg(1), data)
        self.handles[ap.arg(0)][2] += len(data)
        ap.write(ap.arg(3), struct.pack('<Q', len(data)))
        return 0


def selected13():
    r = FaultReplay()
    r.boot()
    r.choose(13)
    r.service()
    assert r.selected() == (13, 13, 13)
    return r


def test_failed_rollback_is_explicit_and_any_native_choice_can_follow_recovery():
    r = selected13()
    r.armed = r.fail_forward = r.drop_rollback = True
    r.choose(24)
    r.service()
    assert r.selected() == (13, 24, 13)
    assert r.ap.call('r5_filter_command_state') == 5
    assert r.ap.call('r5_filter_pending') == 0
    r.choose(18)
    r.service()
    assert r.selected()[0] == 13
    r.drop_rollback = r.fail_forward = False
    r.native_target(0x84d)
    r.ms += 1000
    r.service()
    r.service()
    assert r.selected() == (0, 0, 0) and r.native == 1
    assert r.ap.call('r5_filter_command_state') == 2
    r.record('stable-rollback-recovery')


def test_lost_forward_ack_still_attempts_rollback():
    r = selected13()
    r.armed = r.drop_target_ack = True
    r.choose(24)
    r.service()
    assert r.selected() == (13, 13, 13)
    assert r.ap.call('r5_filter_command_state') == 3
    r.record('stable-lost-forward-ack')


def test_uncertain_selection_and_failed_rollback_recovers_prior_on_restart():
    r = selected13()
    r.armed = r.uncertain_publication = r.fail_rollback_storage = True
    r.choose(24)
    r.service()
    assert r.selected() == (13, 13, 24)
    assert r.ap.call('r5_filter_command_state') == 5
    assert 'R5RECOV.BIN' in r.files
    restarted = FaultReplay(files=r.files)
    restarted.boot()
    assert restarted.selected() == (13, 13, 13)
    assert 'R5RECOV.BIN' not in restarted.files
    restarted.record('stable-publication-restart')


@pytest.mark.parametrize('chunk', [512, 37])
def test_24_slot_short_read_progress(chunk):
    r = FaultReplay(files={}, cards={'A:/R5NATIVE.BIN': recipe()})
    r.chunk = chunk
    r.boot()
    assert r.ap.call('r5_filter_available_mask') & 0xffffffff == 0xffffff
    assert r.files['R5NATIVE.BIN'] == recipe() and not r.handles
    r.record(f'stable-short-read-{chunk}')


@pytest.mark.parametrize('candidate', [recipe(), b''])
def test_cold_unchanged_or_zero_byte_candidate_preserves_library_and_selection(candidate):
    first = selected13()
    r = FaultReplay(files=first.files, cards={'A:/R5NATIVE.BIN': candidate})
    r.boot()
    assert r.selected() == (13, 13, 13)
    assert r.files['R5NATIVE.BIN'] == recipe()
    assert not [row for row in r.trace if row == ['publish', 'R5NATIVE.BIN']]
    r.record('stable-unchanged' if candidate else 'stable-zero-byte')


def changed_recipe():
    value = bytearray(recipe())
    at = 128 + 12 * 2452
    value[at + 4:at + 28] = b'REPLACEMENT13'.ljust(24, b'\0')
    value[at + 28:at + 92] = b'REPLACEMENT13'.ljust(64, b'\0')
    struct.pack_into('<I', value, 112, 0)
    struct.pack_into('<I', value, 112, zlib.crc32(value))
    return bytes(value)


@pytest.mark.parametrize('manual_native', [False, True])
def test_new_library_identity_does_not_reinterpret_saved_slot(manual_native):
    first = selected13()
    assert first.files['R5FILTER.BIN'][:8] == b'R5SEL6\0\0'
    r = FaultReplay(files=first.files, cards={'A:/R5NATIVE.BIN': changed_recipe()})
    r.native = 18
    r.boot()
    if manual_native:
        r.native_target(0x853)
    r.service()
    assert r.selected() == (0, 0, 0)
    assert r.native == (18 if manual_native else 0)
    assert 'R5PREV.BIN' in r.files
    r.record('stable-library-identity-manual' if manual_native else 'stable-library-identity')


def test_retained_cp_resource_failure_restores_prior_library():
    first = selected13()
    r = FaultReplay(files=first.files, cards={'A:/R5NATIVE.BIN': changed_recipe()})
    r.cp = first.cp
    r.boot()
    assert r.selected() == (13, 13, 13)
    assert r.files['R5NATIVE.BIN'] == recipe()
    assert r.ap.call('r5_filter_available_mask') & 0xffffffff == 0xffffff
    assert r.cp.heap_allocations == [947000]
    r.record('stable-resource-fallback')


def test_pipeline_resource_fault_blocks_success_and_preserves_immutable_views():
    r = selected13()
    bank = r.cp.words(0x1a39448, 1)[0]
    old = r.cp.read(bank + 81352, 1620)
    root, state, raw = 0x3120000, 0x3122000, 0x3123000
    r.cp.write(root + 0x2f, bytes([8]))
    r.cp.write(state + 0x184, struct.pack('<IBB', raw, 1, 0))
    source = bytes(i % 127 for i in range(1215))
    for i in range(32):
        r.cp.write(raw, bytes([i]) + source[1:])
        packed = r.cp.call('r5_grid422_restore', bank, root, state)
        assert bool(packed) == (i < 31)
    assert r.cp.words(bank + 81244 + 12, 1)[0] == 5
    r.choose(24)
    r.service()
    assert r.ap.call('r5_filter_command_state') == 5
    assert r.selected()[0] == 13 and r.selected()[2] == 13
    assert r.cp.read(bank + 81352, 1620) == old
    r.cp.write(raw, source)
    assert r.cp.call('r5_grid422_restore', bank, root, state)
    r.native_target(0x84c)
    r.ms += 1000
    r.service()
    r.service()
    assert r.selected() == (0, 0, 0)
    r.record('stable-pipeline-resource-fault')


class RestoreReplay(FaultReplay):
    def __init__(self, files):
        self.fail_restore = True
        super().__init__(files=files)

    def refresh(self, ap):
        if self.fail_restore and self.cp.words(0x1a39464, 1)[0] == 13:
            self.trace.append(['injected_custom_restore_E4_timeout'])
            return 0
        return super().refresh(ap)


def test_automatic_restore_has_terminal_status_and_explicit_retry():
    first = selected13()
    r = RestoreReplay(first.files)
    r.boot()
    for _ in range(32):
        r.ms += 1000
        r.service()
    assert r.selected() == (0, 0, 13)
    assert r.ap.call('r5_filter_command_state') == 6
    assert r.ap.call('r5_filter_pending') == 0
    assert 1 <= r.selection_packets().count(13) <= 30
    before = len(r.selection_packets())
    r.ms += 100000
    r.service()
    assert len(r.selection_packets()) == before
    r.fail_restore = False
    r.native_target(0x853)
    r.service()
    assert r.selected() == (0, 0, 0) and r.native == 18
    r.choose(13)
    r.service()
    assert r.selected() == (13, 13, 13)
    r.record('stable-startup-terminal-retry')


def test_power_epoch_change_recovers_prior_committed_selection():
    r = selected13()
    r.choose(24)
    def power_cycle():
        r.on_refresh = None
        event = r.ap.DATA + 0x7b000
        for value in (0x920143, 0x92015a):
            r.ap.write(event, struct.pack('<I', value))
            r.ap.call('r5_stage421_power', event)
    r.on_refresh = power_cycle
    r.service()
    assert r.ap.call('r5_filter_command_state') == 5
    assert r.ap.call('r5_session_prepare') == 1
    r.ap.call('r5_stage411_child', r.ap.symbols['r5_stage411_state'], count=30000000)
    r.ap.call('r5_session_finish')
    assert r.selected() == (13, 13, 13)
    assert r.ap.call('r5_filter_pending') == 0
    assert r.cp.heap_allocations == [947000] and not r.handles
    r.record('stable-epoch-recovery')


def test_corrupt_recovery_record_is_repaired_in_background():
    first = selected13()
    files = dict(first.files, **{'R5RECOV.BIN': bytes(24)})
    r = FaultReplay(files=files)
    r.boot()
    assert r.ap.call('r5_filter_recovery_required') == 0
    assert r.selected() == (0, 0, 0)
    assert 'R5RECOV.BIN' not in r.files
    r.record('stable-invalid-journal-recovery')


@pytest.mark.parametrize('slot', [12, 13])
def test_legacy_selection_is_restored_then_bound_to_library(slot):
    record = b'R5SEL4\0\0' if slot <= 12 else b'R5SEL5\0\0'
    record += struct.pack('<3I', 1 if slot <= 12 else 2, slot, 0) + bytes(4)
    record = record[:20] + struct.pack('<I', zlib.crc32(record))
    r = FaultReplay(files={'R5NATIVE.BIN': recipe(), 'R5FILTER.BIN': record})
    r.boot()
    assert r.selected() == (slot, slot, slot)
    assert r.files['R5FILTER.BIN'][:8] == b'R5SEL6\0\0'
    assert struct.unpack_from('<I', r.files['R5FILTER.BIN'], 16)[0] == struct.unpack_from('<I', recipe(), 112)[0]
    r.record(f'stable-legacy-sidecar-{slot}')


class DelayedPrimaryReplay(FaultReplay):
    def __init__(self, ready_ms):
        self.ready_ms = ready_ms
        self.primary_ready = False
        super().__init__(files={}, cards={'A:/R5NATIVE.BIN': recipe(), 'B:/R5NATIVE.BIN': changed_recipe()})

    def sleep(self, ap):
        result = super().sleep(ap)
        if not self.primary_ready and self.ms >= self.ready_ms:
            self.primary_ready = True
            # 回调排队后在外层恢复执行，避免重入Unicorn改写外层指令预算。
            ap.pending.extend([('r5_stage411_completed', (0,)), ('r5_stage411_media', (0, 0, ord('A')))])
        return result

    def boot(self):
        self.ap.call('r5_session_cold')
        assert self.ap.call('r5_session_prepare') == 1
        self.ap.call('r5_stage411_initial', 1, 1)
        self.ap.call('r5_stage411_completed', 1)
        self.ap.call('r5_stage411_media', 1, 0, ord('B'))
        self.ap.call('r5_stage411_child', self.ap.symbols['r5_stage411_state'], count=30000000)
        self.ap.call('r5_session_finish')
        assert not self.handles


@pytest.mark.parametrize('ready_ms,primary', [(1000, True), (3000, False)])
def test_primary_card_priority_has_bounded_fallback(ready_ms, primary):
    r = DelayedPrimaryReplay(ready_ms)
    r.boot()
    assert r.files['R5NATIVE.BIN'] == (recipe() if primary else changed_recipe())
    opens = [e[1] for e in r.trace if e[0] == 'card_open']
    assert opens[0] == ('A:/R5NATIVE.BIN' if primary else 'B:/R5NATIVE.BIN')
    r.record(f'stable-card-priority-{ready_ms}')


def test_invalid_primary_does_not_hide_valid_secondary():
    r = FaultReplay(files={}, cards={'A:/R5NATIVE.BIN': b'', 'B:/R5NATIVE.BIN': recipe()})
    r.boot()
    assert r.files['R5NATIVE.BIN'] == recipe()
    assert [e[1] for e in r.trace if e[0] == 'card_open'] == ['A:/R5NATIVE.BIN', 'B:/R5NATIVE.BIN']
    r.record('stable-invalid-primary-secondary')


def test_transient_initial_heap_failure_can_retry_without_leaking():
    class TransientHeapReplay(FaultReplay):
        failed_once = False
        def send(self, ap):
            packet = ap.read(ap.arg(1), ap.arg(2))
            if not self.failed_once and packet[0] == 0xe8:
                self.failed_once = True
                self.cp.heap_used = 1048576
                result = super().send(ap)
                self.cp.heap_used = 0
                return result
            return super().send(ap)
    r = TransientHeapReplay()
    r.boot()
    assert r.failed_once and r.cp.heap_allocations == [947000]
    assert r.ap.call('r5_filter_available_mask') & 0xffffffff == 0xffffff
    r.choose(24)
    r.service()
    assert r.selected() == (24, 24, 24)
    r.record('stable-transient-initial-heap')


def test_startup_both_e4_paths_late_ready_recovers_saved_filter():
    first = selected13()
    r = FaultReplay(files=first.files)
    r.fail_refresh = True
    r.boot()
    assert r.ap.call('r5_filter_command_state') == 5
    assert r.selected()[2] == 13
    r.fail_refresh = False
    r.ms += 1000
    r.service()
    r.service()
    assert r.selected() == (13, 13, 13)
    assert r.ap.call('r5_filter_pending') == 0
    r.record('stable-startup-late-ready')


def test_startup_transaction_queues_last_ui_intent_without_overwriting_it():
    r = FaultReplay()
    def rotate():
        r.on_refresh = None
        for slot in (13, 17, 24):
            r.choose(slot)
    r.on_refresh = rotate
    r.boot()
    r.service()
    r.service()
    assert r.selected() == (24, 24, 24)
    assert 13 not in r.selection_packets() and 17 not in r.selection_packets()
    r.record('stable-startup-last-intent')


def test_native_e4_orphan_blocks_new_objects_and_wrong_completion():
    class BlockedNativeReplay(FaultReplay):
        block_native = False
        constructed = 0
        def refresh(self, ap):
            if not self.block_native:
                return super().refresh(ap)
            self.constructed += 1
            self.object = ap.DATA + 0x79000 + 16*self.constructed
            ap.pending.append(('r5_filter_refresh_construct425', (self.object, ap.arg(0)+16)))
            return 0
    r = BlockedNativeReplay()
    r.boot()
    r.choose(13)
    r.service()
    r.block_native = True
    r.choose(24)
    r.service()
    assert r.constructed == 1 and r.ap.call('r5_filter_native_inflight') == 1
    assert r.ap.call('r5_filter_command_state') == 5
    r.native_target(0x84c)
    r.service()
    assert r.constructed == 1
    r.ap.call('r5_filter_refresh_execute425', r.object + 0x1000)
    assert r.ap.call('r5_filter_native_inflight') == 1
    r.ap.call('r5_filter_refresh_execute425', r.object)
    assert r.ap.call('r5_filter_native_inflight') == 0
    r.block_native = False
    r.native_target(0x84d)
    r.ms += 1000
    r.service()
    r.service()
    assert r.selected() == (0, 0, 0) and r.native == 1
    r.record('stable-native-e4-orphan')
