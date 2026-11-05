"""附加滤镜八项独立读写、身份保存及原生打包的可观察契约。"""
import hashlib
import struct
import zlib

import pytest
from unicorn import UC_HOOK_CODE, arm_const as ARM

from replay import Replay, recipe
from test_stability import FaultReplay


BASE = (0, 0, 0, 0, 0, 4, 3, 1)
IDS = (0x4030, 0x40f3, 0x40f4, 0x40f5, 0x4031, 0x4032, 0x40f6, 0x40f7)
OFFSETS = (0x1cc, 0x6dc, 0x6e8, 0x6f4, 0x1d8, 0x1e4, 0x700, 0x70c)
FIELDS = (0xa44, 0xa46, 0xa45, 0xa47, 0xa48, 0xd2e, 0xd2f, 0xd30)


def full_packet():
    out = bytearray(0x960)
    for prop, at, value in zip(IDS, OFFSETS, BASE):
        struct.pack_into('<BBHII', out, at, 5, 0, prop, 0x11223344, value & 255)
    return bytes(out)


class ParameterReplay(FaultReplay):
    """E4外部执行为夹具；原AP叠加及原CP任务／上下文执行真实机器码。"""
    def __init__(self, files=None, cards=None):
        self.parameter_packets = []
        self.fail_tune_publish = False
        super().__init__(files=files, cards=cards)
        self.native_message_sizes = {}
        self.ap.stub(0x355882c, self.native_send)
        self.ap.stub(0x16dafc0, self.native_transport)
        self.ap.stub('r5_osal_msg_size', lambda a:self.native_message_sizes.get(a.arg(0),self.message_size))
        self.native_lock = False
        def semaphore(cpu, at, size, _):
            if at not in (0x5b8f58, 0x5b8d6c, 0x5b8910):
                return
            assert cpu.reg_read(ARM.UC_ARM_REG_R0) == 0x24
            if at == 0x5b8910:
                assert self.native_lock
                self.native_lock = False
            else:
                assert not self.native_lock
                self.native_lock = True
            cpu.reg_write(ARM.UC_ARM_REG_R0, 0)
            cpu.reg_write(ARM.UC_ARM_REG_PC, cpu.reg_read(ARM.UC_ARM_REG_LR))
        self.cp.cpu.hook_add(UC_HOOK_CODE, semaphore)
        self.cp.cpu.reg_write(ARM.UC_ARM_REG_C1_C0_2, 0xf << 20)
        self.cp.cpu.reg_write(ARM.UC_ARM_REG_FPEXC, 1 << 30)

    def native_send(self, ap):
        assert ap.arg(0) == 0x90030001 and ap.arg(2) in (12, 0x960)
        pointer=ap.DATA+0x8a000
        ap.write(pointer,ap.read(ap.arg(1),ap.arg(2)))
        self.native_message_sizes[pointer]=ap.arg(2)
        ap.pending.append(('n12_tune_transport_send',(ap.arg(0),pointer)))
        # 高层发送器没有发送状态返回契约，不能把清理后的寄存器当成功码。
        return 0x1c0ffee

    def native_transport(self, ap):
        assert ap.arg(0)==0x90030001
        size=self.native_message_sizes[ap.arg(1)]
        packet = ap.read(ap.arg(1), size)
        self.parameter_packets.append(packet)
        records=[packet] if len(packet)==12 else [packet[at:at+12] for at in OFFSETS]
        for body in records:
            ptr = self.cp.PACKET
            self.cp.write(ptr - 12, struct.pack('<I', 0x80020002))
            self.cp.write(ptr, body)
            self.cp.packet_size = 12
            self.cp.write(self.cp.STACK + 0xe000, struct.pack('<I', ptr))
            self.cp.cpu.reg_write(ARM.UC_ARM_REG_SP, self.cp.STACK + 0xe000)
            self.cp.cpu.reg_write(ARM.UC_ARM_REG_LR, self.cp.STOP | 1)
            self.cp.cpu.reg_write(ARM.UC_ARM_REG_R4, 0x90030001)
            self.cp.cpu.reg_write(ARM.UC_ARM_REG_R11, 0x7a0020)
            self.cp.cpu.emu_start(0x496019, 0x49606e, count=100000)
            assert self.cp.cpu.reg_read(ARM.UC_ARM_REG_PC) == 0x49606e
            assert self.cp.words(0x172e1c0, 1)[0] == 0x80020002 and not self.native_lock
        self.trace.append(['native_eight_CP_fields', self.cp_values()])
        return 0

    def cp_values(self):
        return tuple(struct.unpack('b', self.cp.read(0x157aa10 + p, 1))[0] for p in FIELDS)

    def cp_consumption(self, values):
        """原刷新、上下文、锐度和颜色窗口；帧元数据为显式零夹具。"""
        m = self.cp
        def register(name, value=None):
            at = getattr(ARM, 'UC_ARM_REG_' + name.upper())
            if value is not None:
                m.cpu.reg_write(at, value)
            return m.cpu.reg_read(at)
        def window(start, end, *args):
            for i, value in enumerate(args):
                register('r' + str(i), value)
            register('sp', m.STACK + 0xe000)
            register('lr', m.STOP | 1)
            m.cpu.emu_start(start | 1, end, count=2000000)
            assert register('pc') == end
        register('r4', 0x164eef0)
        window(0x4b8d88, 0x4b8dc4)
        window(0x4baa9e, 0x4baaba)
        root, context = 0x1653c68, 0x192b070
        assert tuple(struct.unpack('b', m.read(root + p, 1))[0] for p in FIELDS) == values
        m.call(0xafd2db, root, context)
        assert m.words(context, 1)[0] == root
        work = m.BANK + 0x60000
        m.write(work + 0x2000, struct.pack('<5I', 0x60daa5, 0, 0x4bf3e1, 0, 0))
        window(0x9071cc, 0x9071fa, context, work + 0x2000, 6)
        window(0x9053f8, 0x905446, work + 0x5000, 0x157c278)
        wire = m.words(root + 0xa40, 1)[0]
        assert m.read(work + 0x5020, 6) == struct.pack('<I2B', wire, values[5], values[6])
        m.write(m.STACK + 0xe024, struct.pack('<I', context))
        m.write(work + 0x6104, struct.pack('<I', work + 0x500))
        register('fp', work + 0x5000)
        register('sl', work + 0x6000)
        window(0x240da8, 0x240df0)
        assert register('r8') == root
        window(0x24119a, 0x241280)
        assert m.read(work + 0x5030, 1) == bytes([values[4] & 255])
        assert m.read(work + 0x5033, 1) == bytes([values[0] & 255])
        self.trace.append(['native_CP_snapshot_context_sharpness_color', list(values),
                           '完整成像算法和真实帧元数据未执行'])

    def refresh(self, ap):
        if not self.fail_refresh and not (self.armed and self.fail_forward and not self.first_refresh_failed):
            context = ap.cpu.context_save()
            if self.on_refresh:
                callback = self.on_refresh
                self.on_refresh = None
                callback()
            pointer = ap.DATA + 0x88000
            ap.write(pointer, full_packet())
            # 高层清理值只验证原样透传，完成判定由真实SND_MSG观察点负责。
            assert ap.call('n12_tune_send', 0x90030001, pointer, 0x960, 0, 0, 0) == 0x1c0ffee
            ap.cpu.context_restore(context)
        return super().refresh(ap)

    def rename(self, ap):
        if self.fail_tune_publish and ap.string(ap.arg(1)) == 'R5TUNE.NEW':
            self.fail_tune_publish = False
            self.trace.append(['injected_tune_rename_failure'])
            return self.error(5)
        return super().rename(ap)


def edit_vector(r, values, slot=13):
    display_custom(r, slot)
    for i, value in enumerate(values):
        assert r.ap.call('r5_tune_edit', slot, i, value) == 0
    r.choose(slot)
    for _ in range(3):
        r.service()


def parameters(r, slot=13):
    result = []
    for i in range(8):
        at = r.ap.DATA + 0x90000
        assert r.ap.call('r5_tune_value', slot, i, at) == 0
        result.append(struct.unpack('<i', r.ap.read(at, 4))[0])
    return tuple(result)


def recolor(raw, *, rename=False, swap=False, changed=False):
    out = bytearray(raw)
    at = 128 + 12 * 2452
    if rename:
        out[at + 4:at + 28] = b'RENAMED'.ljust(24, b'\0')
        out[at + 28:at + 92] = b'Renamed same recipe'.ljust(64, b'\0')
    if changed:
        value = struct.unpack_from('<h', out, at + 92)[0]
        struct.pack_into('<h', out, at + 92, value + 1)
    if swap:
        a, b = bytes(out[at + 4:at + 2452]), bytes(out[at + 2456:at + 4904])
        out[at + 4:at + 2452], out[at + 2456:at + 4904] = b, a
    struct.pack_into('<I', out, 112, 0)
    struct.pack_into('<I', out, 112, zlib.crc32(out))
    return bytes(out)


def test_recipe_identity_matches_independent_sha_and_excludes_name_and_slot():
    r = ParameterReplay()
    r.boot()
    look = r.ap.DATA + 0xa0000
    digest = look + 0x1000
    raw = recipe()[128 + 12 * 2452:128 + 13 * 2452]
    r.ap.write(look, raw[4:2447] + b'\0')
    r.ap.call('r5_tune_identity', look, digest)
    expected = hashlib.sha256(b'R5COLOR1' + raw[92:2447]).digest()
    assert r.ap.read(digest, 32) == expected
    r.ap.write(look, b'changed name'.ljust(88, b'\0'))
    r.ap.call('r5_tune_identity', look, digest)
    assert r.ap.read(digest, 32) == expected


def test_eight_values_reach_original_cp_and_survive_restart_without_bin_changes():
    r = ParameterReplay()
    r.boot()
    values = (-3, 4, -5, 2, 6, 7, 4, 8)
    edit_vector(r, values)
    assert r.selected() == (13, 13, 13)
    assert r.cp_values() == values and r.ap.call('r5_filter_command_state') == 2
    r.cp_consumption(values)
    assert r.files['R5NATIVE.BIN'] == recipe() and 'R5TUNE.BIN' in r.files
    restart = ParameterReplay(files=r.files)
    restart.boot()
    assert parameters(restart) == values and restart.cp_values() == values
    assert restart.files['R5NATIVE.BIN'] == recipe()
    r.record('parameters-native-eight-and-save')
    restart.record('parameters-restart')


@pytest.mark.parametrize('kind', ['same', 'renamed', 'moved', 'new'])
def test_import_uses_recipe_identity_for_saved_microadjustments(kind):
    r = ParameterReplay()
    r.boot()
    values = (2, 3, -2, 1, 4, 6, 4, 2)
    edit_vector(r, values)
    new = recolor(recipe(), rename=kind == 'renamed', swap=kind == 'moved', changed=kind == 'new')
    restored = ParameterReplay(files=r.files, cards={'A:/R5NATIVE.BIN': new})
    restored.boot()
    slot = 14 if kind == 'moved' else 13
    display_custom(restored, slot)
    assert parameters(restored, slot) == (BASE if kind == 'new' else values)
    assert restored.files['R5NATIVE.BIN'] == new
    restored.record('parameters-import-' + kind)


def test_tune_publish_failure_restores_ap_cp_and_saved_parameters():
    r = ParameterReplay()
    r.boot()
    old = (1, 2, 3, 1, 2, 4, 3, 1)
    edit_vector(r, old)
    r.fail_tune_publish = True
    edit_vector(r, (3, 4, 5, 2, 4, 6, 4, 2))
    assert r.cp_values() == old
    assert r.ap.call('r5_filter_command_state') == 3
    restarted = ParameterReplay(files=r.files)
    restarted.boot()
    assert parameters(restarted) == old
    restarted.record('parameters-save-failure-rollback')


def test_parameter_snapshot_stays_fixed_and_last_working_values_follow():
    r = ParameterReplay()
    r.boot()
    first = (1, 1, 1, 1, 1, 5, 3, 2)
    edit_vector(r, first)
    second = (2, 2, 2, 2, 2, 6, 4, 3)
    last = (3, 3, 3, 3, 3, 7, 5, 4)
    display_custom(r)
    for i, value in enumerate(second):
        assert r.ap.call('r5_tune_edit', 13, i, value) == 0
    r.choose(13)
    def rotate():
        for i, value in enumerate(last):
            assert r.ap.call('r5_tune_edit', 13, i, value) == 0
        r.choose(13)
    r.on_refresh = rotate
    r.service()
    assert r.cp_values() == second
    r.service()
    assert r.cp_values() == last and parameters(r) == last
    assert 'R5TUNE.BIN' in r.files
    r.record('parameters-snapshot-and-last')


def test_reset_is_independent_and_malformed_packet_never_partially_overlays():
    r = ParameterReplay()
    r.boot()
    edit_vector(r, (2, 3, 4, 2, 4, 7, 5, 4))
    original = bytearray(full_packet())
    original[OFFSETS[-1] + 2] ^= 1
    ptr = r.ap.DATA + 0x88000
    r.ap.write(ptr, original)
    assert r.ap.call('r5_tune_overlay', ptr, len(original)) != 0
    assert r.ap.read(ptr, len(original)) == original
    assert r.ap.call('r5_tune_reset', 13) == 0
    r.choose(13)
    r.service()
    assert parameters(r) == BASE and r.cp_values() == BASE
    assert r.files['R5NATIVE.BIN'] == recipe()
    r.record('parameters-reset-and-packet-rejection')


def test_corrupt_tune_file_is_preserved_and_not_silently_overwritten():
    broken = b'bad microadjustments'
    r = ParameterReplay(files={'R5NATIVE.BIN': recipe(), 'R5TUNE.BIN': broken})
    r.boot()
    assert r.ap.call('r5_tune_status') == 2
    display_custom(r)
    assert r.ap.call('r5_tune_edit', 13, 0, 3) != 0
    assert r.files['R5TUNE.BIN'] == broken and r.files['R5NATIVE.BIN'] == recipe()
    r.record('parameters-corrupt-file')


def test_interrupted_parameter_commit_restores_old_identity_and_values():
    class InterruptedReplay(ParameterReplay):
        armed_capture = False
        interrupted = None

        def rename(self, ap):
            tune = ap.string(ap.arg(1)) == 'R5TUNE.NEW'
            result = super().rename(ap)
            if self.armed_capture and tune and self.interrupted is None:
                self.interrupted = dict(self.files)
            return result

    r = InterruptedReplay()
    r.boot()
    old = (1, 2, 3, 1, 2, 4, 3, 1)
    edit_vector(r, old)
    r.armed_capture = True
    edit_vector(r, (3, 4, 5, 2, 4, 6, 4, 2))
    assert r.interrupted and 'R5RECOV.BIN' in r.interrupted and 'R5TREC.BIN' in r.interrupted
    restarted = ParameterReplay(files=r.interrupted)
    restarted.boot()
    assert restarted.selected() == (13, 13, 13) and parameters(restarted) == old
    assert restarted.cp_values() == old
    assert 'R5RECOV.BIN' not in restarted.files and 'R5TREC.BIN' not in restarted.files
    restarted.record('parameters-interrupted-commit')


def display_custom(r, slot=13):
    r.mid = 0x160f + slot
    model, output = r.ap.DATA + 0x80000, r.ap.DATA + 0x82000
    r.ap.write(model, bytes(0x1100))
    r.ap.write(model + 0x20, struct.pack('<I', 18 + slot))
    for i, value in enumerate(BASE):
        r.ap.write(model + 0x50 + 0x1f8 * i, struct.pack('<i', value))
        r.ap.write(model + 0xa8 + 0x1f8 * i, struct.pack('<i', value))
    r.ap.call('n12_display', 0, output, 0, model)
    values = tuple(struct.unpack('<i', r.ap.read(output + 0x38 + i * 12, 4))[0] for i in range(8))
    ids = tuple(r.ap.words(output + 0x34 + i * 12, 1)[0] for i in range(8))
    return values, ids


def test_custom_eight_parameters_are_visible_and_independent():
    r = Replay(files={'R5NATIVE.BIN': recipe()})
    r.boot()
    r.choose(13)
    r.service()
    values, ids = display_custom(r)
    assert ids == tuple(range(8))
    assert values == BASE
    obj = r.ap.DATA + 0x83000
    r.ap.write(obj + 0x3b18, struct.pack('<I', r.mid))
    assert r.ap.call('n12_inhibited', obj) == 0
    option = [1]
    r.ap.stub(0x220b4e0, lambda a: option[0])
    for i in range(8):
        option[0] = i + 1
        assert r.ap.call('n12_parameter_value', obj) & 0xffffffff == BASE[i] & 0xffffffff
        r.ap.call('n12_step_' + str(i), obj, 0)
        assert r.ap.call('n12_parameter_value', obj) & 0xffffffff == (BASE[i] + 1) & 0xffffffff
        assert r.ap.call('n12_parameter_default', obj) & 0xffffffff == BASE[i] & 0xffffffff
    values, ids = display_custom(r, 14)
    assert values == BASE and ids == tuple(range(8))
    r.record('parameters-eight-model')


def test_new_recipe_defaults_do_not_inherit_factory_st_working_adjustments():
    r = Replay(files={'R5NATIVE.BIN': recipe()})
    r.boot()
    r.mid = 0x161c
    model, output = r.ap.DATA + 0x80000, r.ap.DATA + 0x82000
    r.ap.write(model, bytes(0x1100))
    r.ap.write(model + 0x20, struct.pack('<I', 31))
    for i, value in enumerate(BASE):
        r.ap.write(model + 0x50 + 0x1f8 * i, struct.pack('<i', value + 1))
        r.ap.write(model + 0xa8 + 0x1f8 * i, struct.pack('<i', value))
    before = r.ap.read(model, 0x1100)
    r.ap.call('n12_display', 0, output, 0, model)
    assert parameters(r) == BASE
    assert r.ap.read(model, 0x1100) == before
    r.record('parameters-stock-default-isolation')


def test_missing_selection_gets_a_valid_baseline_before_paired_journals():
    r = ParameterReplay()
    r.boot()
    r.files.pop('R5FILTER.BIN', None)
    display_custom(r)
    r.choose(13)
    r.fail_refresh = True
    r.service()
    # 未完成E4的两份日志仍携带同一份合法选择，重启可恢复。
    if 'R5TREC.BIN' in r.files:
        assert r.files['R5TREC.BIN'][32:56] == r.files['R5RECOV.BIN']
        assert r.files['R5RECOV.BIN'][:8] == b'R5SEL6\0\0'
    restarted = ParameterReplay(files=r.files)
    restarted.boot()
    assert restarted.ap.call('r5_tune_status') == 0
    assert restarted.selected() == (0, 0, 0)
    restarted.record('parameters-missing-selection-baseline')
