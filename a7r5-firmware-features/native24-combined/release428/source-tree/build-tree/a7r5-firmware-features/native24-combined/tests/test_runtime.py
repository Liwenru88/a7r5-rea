"""24槽实际机器码、原注册树、冷启动／恢复及失败闭环。"""
import hashlib
import importlib.util
import inspect
import io
import json
from pathlib import Path
import re
import struct
import zlib

import pytest
from elftools.elf.elffile import ELFFile
from unicorn import arm_const as A

from replay import BUILD, FEATURE, Replay, candidate, cp_raw, old_cp, receipt, recipe


def probe(version=2, magic=0x33503552, mask=0xffffff):
    data = struct.pack('<4B6I', 0xe8, version, 1, 32, magic, 77, 0, mask, 0, 0)
    return data + struct.pack('<I', zlib.crc32(data))


def test_baseline_rejects_new_capability_before_allocating():
    cp = old_cp()
    cp.receiver_services()
    assert cp.consume(probe()) is None and cp.heap_allocations == []


def test_current_build_layouts_and_strict_inverse():
    assert receipt['CP_heap_bytes'] == 947000 and receipt['CP_code_bytes'] <= 7568
    assert receipt['AP_bss_bytes'] <= 327680 and receipt['unified']['custom_count'] == 24
    assert all(row['exit_code'] == 0 for row in receipt['commands'])
    elf = ELFFile(io.BytesIO(candidate[0]))
    loads = [s for s in elf.iter_segments() if s['p_type'] == 'PT_LOAD']
    assert elf['e_phnum'] == 10 and all(s['p_flags'] in (4, 5, 6) for s in loads)
    for i, left in enumerate(loads):
        assert all(max(left['p_vaddr'], right['p_vaddr']) >= min(left['p_vaddr'] + left['p_memsz'], right['p_vaddr'] + right['p_memsz']) for right in loads[:i])
    assert receipt['local_AP']['inverse_exact'] and receipt['local_CP']['inverse_exact']
    stack = json.loads((BUILD / 'stack-usage.json').read_text())
    sizes = [int(line.split('\t')[1]) for text in stack.values() for line in text.splitlines()]
    assert sizes and max(sizes) < 16384
    assert receipt['stack_budget']['conservative_sum'] < 32768


def test_actual_native_registry_enumerates_and_navigates_all43_rows():
    # 原树／枚举／导航函数执行真实机器码，资格和分配仍是已有明确夹具。
    import test_unified_look as original
    def machine(value):
        ap, state = original.machine(value)
        state['mask'] = 0xffffff
        return ap, state
    text = inspect.getsource(original.test_original_registry_enumerates_and_navigates_unified_rows)
    text = re.sub(r'\b31\b', '43', text).replace('0x161c', '0x1628').replace('==5603', '==5615')
    context = dict(original.__dict__, machine=machine)
    exec(compile(text, 'native24-native-registry-contract', 'exec'), context)
    context['test_original_registry_enumerates_and_navigates_unified_rows'](candidate)


def assert_color(replay, slot):
    cp = replay.cp
    bank = cp.words(0x1a39448, 1)[0]
    view = cp.words(0x1a39458, 1)[0]
    assert view == bank + 79600 + slot * 24
    table = cp.words(view + 12, 1)[0]
    assert cp.read(table, 51 * 28) == cp.read(0x107e968, 51 * 28)
    record = recipe()[128 + (slot - 1) * 2452:128 + slot * 2452]
    curve = record[716:1232]
    wires = (0, 3, 2, 1, 16, 15, 19, 20, 17, 18, 5, 13)
    for base in range(12):
        for movie in (0, 1):
            row = 51 + base * 2 + movie
            channels = (6,) if movie else (0, 6)
            for channel in channels:
                pointer = cp.words(table + row * 28 + channel * 4, 1)[0]
                assert cp.read(pointer, 516) == curve
                native_row = cp.words(0x107eefc + wires[base] * 8 + movie * 4, 1)[0]
                native_record = cp.words(0x107e968 + native_row * 28 + channel * 4, 1)[0]
                assert cp.read(pointer + 516, 60) == cp.read(native_record + 516, 60)
    order = struct.unpack('<405H', cp.read(0xe8c1d8, 810))
    for level in range(8):
        expected = [0] * 405
        for point in range(405):
            packed = 0
            for channel in range(3):
                value = record[1232 + channel * 405 + point]
                if value >= 128:
                    value -= 256
                if level < 7:
                    value = value * (level + 1) >> 3
                packed |= (value & 127) << (22 - channel * 10)
            expected[order[point]] = packed
        assert cp.words(bank + 81352 + (slot - 1) * 12960 + level * 1620, 405) == tuple(expected)
    root, env, work = 0x3120000, 0x3121000, 0x3122000
    cp.write(work, struct.pack('<II', root, env))
    for wire, actual in ((0, 0), (19, 54), (20, 55)):
        cp.write(root + 0x2e, bytes([wire]))
        cp.write(env + 0x25, bytes([actual]))
        assert cp.call('r5_native418_available', work, actual) == 1
        assert cp.call('r5_native418_cc1', 0x123456, work, actual) == bank + 64 + (slot - 1) * 2392 + 32


def test_all24_transactions_names_colors_and_st_fl23_roundtrips():
    replay = Replay(cards={'A:/R5NATIVE.BIN': recipe()})
    replay.boot()
    assert replay.ap.call('r5_filter_available_mask') & 0xffffffff == 0xffffff
    assert replay.cp.heap_allocations == [947000]
    assert replay.selected() == (0, 0, 0)
    for slot in range(1, 25):
        replay.choose(slot)
        replay.service()
        assert replay.selected() == (slot, slot, slot)
        assert replay.ap.call('r5_filter_command_state') == 2
        title = replay.ap.call('n12_title_name', 0x160f + slot)
        assert title == 0x02ff4601 + slot - 1
        full = recipe()[128 + (slot - 1) * 2452 + 28:128 + (slot - 1) * 2452 + 92].split(b'\0', 1)[0].decode()
        assert replay.ap.string(replay.ap.call('r5_filter_menu_text', title)) == full
        assert_color(replay, slot)
        for mid, selector in ((0x84c, 0), (0x852, 17), (0x853, 18)) if slot in (13, 24) else ((0x84c, 0),):
            replay.native_target(mid)
            replay.service()
            assert replay.selected() == (0, 0, 0) and replay.ap.call('n12_current') == selector
            if mid != 0x853 and slot in (13, 24):
                replay.choose(slot)
                replay.service()
                assert replay.selected() == (slot, slot, slot)
    assert replay.cp.heap_allocations == [947000] and not replay.handles
    replay.record('all24-roundtrips')


def test_all11_gamma_getters_preserve_registers_flags_and_native_fallback():
    replay = Replay(files={'R5NATIVE.BIN': recipe()})
    replay.boot()
    cp = replay.cp
    bank = cp.words(0x1a39448, 1)[0]
    gates = json.loads((BUILD / 'work/gamma/getter_build423/gates.json').read_text())['records']
    assert len(gates) == 11
    for slot in (None, -1, 0, 24):
        view = 0 if slot is None else 0x3120000 if slot == -1 else bank + 79600 + slot * 24
        cp.write(0x1a39458, struct.pack('<I', view))
        for gate in gates:
            wanted = int(gate['original_pointer'], 16) if slot in (None, -1) else cp.words(view + gate['custom_bank_offset'], 1)[0]
            for flags in (0, 0xf8000000):
                saved = {n: 0x12340000 + n for n in range(13)}
                for n, value in saved.items():
                    cp.cpu.reg_write(getattr(A, 'UC_ARM_REG_R' + str(n)), value)
                cp.cpu.reg_write(A.UC_ARM_REG_SP, cp.STACK + 0x8000)
                cp.cpu.reg_write(A.UC_ARM_REG_LR, cp.STOP | 1)
                cp.cpu.reg_write(A.UC_ARM_REG_CPSR, (cp.cpu.reg_read(A.UC_ARM_REG_CPSR) & ~0xf8000000) | flags)
                resume = int(gate['resume'], 16)
                cp.cpu.emu_start(int(gate['site'], 16) | 1, resume, count=1000)
                assert cp.cpu.reg_read(A.UC_ARM_REG_PC) == resume
                assert cp.cpu.reg_read(A.UC_ARM_REG_SP) == cp.STACK + 0x8000
                assert cp.cpu.reg_read(A.UC_ARM_REG_LR) == cp.STOP | 1
                assert cp.cpu.reg_read(A.UC_ARM_REG_CPSR) & 0xf8000000 == flags
                for n, value in saved.items():
                    assert cp.cpu.reg_read(getattr(A, 'UC_ARM_REG_R' + str(n))) == (wanted if n == gate['register'] else value)


def test_rapid_high_slots_and_failure_preserve_ap_cp_file_then_retry():
    replay = Replay(files={'R5NATIVE.BIN': recipe()})
    replay.boot()
    before = len(replay.selection_packets())
    replay.choose(13)
    def rotate():
        replay.on_refresh = None
        for slot in (14, 17, 23, 24):
            replay.choose(slot)
    replay.on_refresh = rotate
    replay.service()
    assert replay.selected() == (13, 13, 13)
    replay.service()
    assert replay.selected() == (24, 24, 24)
    assert replay.selection_packets()[before:] == [13, 13, 24, 24]
    replay.fail_refresh = True
    replay.choose(17)
    replay.service()
    assert replay.selected() == (24, 24, 24) and replay.ap.call('r5_filter_command_state') == 5
    replay.fail_refresh = False
    replay.native_target(0x84c)
    replay.ms += 1000
    replay.service()
    replay.service()
    assert replay.selected() == (0, 0, 0)
    replay.choose(18)
    replay.service()
    assert replay.selected() == (18, 18, 18)
    replay.record('rapid-and-failure')


@pytest.mark.parametrize('slot', [0, 13, 24])
def test_cold_without_sd_and_resume_reuse_actual_new_bank(slot):
    first = Replay(cards={'A:/R5NATIVE.BIN': recipe()})
    first.boot()
    if slot:
        first.choose(slot)
        first.service()
    assert first.selected() == (slot, slot, slot)
    second = Replay(files=first.files, native_selector=1)
    second.boot()
    assert second.selected() == (slot, slot, slot)
    assert not any(row[0] == 'card_open' for row in second.trace)
    if not slot:
        assert second.ap.call('n12_current') == 1
    second.cards = {'A:/R5NATIVE.BIN': b''}
    event = second.ap.DATA + 0x7b000
    for value in (0x920143, 0x92015a):
        second.ap.write(event, struct.pack('<I', value))
        second.ap.call('r5_stage421_power', event)
    assert second.ap.call('r5_session_prepare') == 1
    second.ap.call('r5_stage411_child', second.ap.symbols['r5_stage411_state'], count=30000000)
    second.ap.call('r5_session_finish')
    assert second.selected() == (slot, slot, slot) and second.cp.heap_allocations == [947000]
    assert second.files['R5NATIVE.BIN'] == recipe() and not second.handles
    second.record(f'restart-resume-{slot}')


def test_legacy_v4_input_and_both_directions_of_protocol_mismatch():
    old_recipe = (FEATURE / 'upstream/filters/FUJ_12_v45/R5NATIVE.BIN').read_bytes()
    replay = Replay(files={'R5NATIVE.BIN': old_recipe})
    assert replay.cp.consume(probe(1, 0x32503552, 0xfff)) is None
    assert replay.cp.heap_allocations == []
    replay.boot()
    assert replay.ap.call('r5_filter_available_mask') & 0xffffffff == 0xfff
    replay.choose(12)
    replay.service()
    assert replay.selected() == (12, 12, 12)
    replay.choose(24)
    replay.service()
    assert replay.selected() == (12, 12, 12)
    replay.record('legacy-v4')
    mismatched = Replay(files={'R5NATIVE.BIN': old_recipe})
    mismatched.cp = old_cp()
    mismatched.cp.receiver_services()
    mismatched.boot()
    assert mismatched.ap.call('r5_filter_available_mask') & 0xffffffff == 0
    assert mismatched.cp.heap_allocations == []
    mismatched.record('mismatched-old-cp')


def test_resource_failure_does_not_publish_or_overwrite():
    replay = Replay(files={'R5NATIVE.BIN': recipe()})
    replay.cp.receiver_services = None
    # 重新创建受限的同一服务边界；未测量任何实体堆。
    from runtime_support import CP
    replay.cp = CP(cp_raw)
    replay.cp.receiver_services(budget=947000 - 1)
    replay.boot()
    assert replay.ap.call('r5_filter_available_mask') & 0xffffffff == 0
    assert replay.cp.heap_allocations == [] and replay.selected()[2] is None
    replay.record('insufficient-shared-heap')


def test_new_generation_resource_rejection_preserves_published_bank_and_view():
    first = Replay(files={'R5NATIVE.BIN': recipe()})
    first.boot()
    first.choose(24)
    first.service()
    cp = first.cp
    bank = cp.words(0x1a39448, 1)[0]
    view = cp.words(0x1a39458, 1)[0]
    before = hashlib.sha256(cp.read(bank, 81244) + cp.read(bank + 81344, 947000 - 81344)).hexdigest()
    changed = bytearray(recipe())
    changed[128 + 23 * 2452 + 4] = ord('X')
    struct.pack_into('<I', changed, 112, 0)
    struct.pack_into('<I', changed, 112, zlib.crc32(changed))
    second = Replay(files=first.files, cards={'A:/R5NATIVE.BIN': bytes(changed)})
    second.cp = cp
    second.boot()
    assert second.ap.call('r5_filter_available_mask') & 0xffffffff == 0xffffff
    assert cp.words(0x1a39448, 1)[0] == bank and cp.words(0x1a39458, 1)[0] == view
    assert hashlib.sha256(cp.read(bank, 81244) + cp.read(bank + 81344, 947000 - 81344)).hexdigest() == before
    assert cp.heap_allocations == [947000] and second.ap.call('r5_filter_selected') == 24
    assert second.files['R5NATIVE.BIN'] == recipe()
    second.record('retained-bank-resource-rejection')


def test_high_slot_persistence_failure_rolls_back_cp_and_preserves_saved_selection():
    replay = Replay(files={'R5NATIVE.BIN': recipe()})
    replay.boot()
    replay.choose(13)
    replay.service()
    saved = replay.files['R5FILTER.BIN']
    replay.fail_selection_rename = True
    replay.choose(24)
    replay.service()
    assert replay.ap.call('r5_filter_command_state') == 3
    assert replay.selected() == (13, 13, 13) and replay.files['R5FILTER.BIN'] == saved
    assert 'R5FILTER.NEW' not in replay.files and not replay.handles
    replay.choose(18)
    replay.service()
    replay.choose(24)
    replay.service()
    assert replay.selected() == (24, 24, 24) and replay.ap.call('r5_filter_command_state') == 2
    replay.record('high-slot-persistence-failure')


@pytest.mark.parametrize('check', [
    'test_fl23_selection_ignores_old_saved_base_and_keeps_native_routes',
    'test_ntsc_branches_execute_to_original_continuations',
    'test_marker_registration_executes_original_range_validator',
    'test_sound_selector_keeps_non_type1_inhibit_and_callee_state',
])
def test_current_components_preserve_local_patches(check):
    import test_integration
    images = (None, None, candidate[0], cp_raw, receipt['local_AP'], receipt['local_CP'])
    getattr(test_integration, check)(images)
