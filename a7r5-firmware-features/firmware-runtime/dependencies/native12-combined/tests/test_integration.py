"""真实固件的独立CPU指令合同；不模拟设备服务或ISP像素。"""
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import sys
import subprocess
import ctypes

import pytest
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM, UC_ARCH_ARM64, UC_MODE_ARM, UC_MODE_THUMB, UC_HOOK_CODE
from unicorn import arm_const as arm
from unicorn import arm64_const as a64

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))
import patches


@pytest.fixture(scope='session')
def images(tmp_path_factory):
    baseline = Path(os.environ.get('A7R5_NATIVE12_BASELINE', HERE/'build/baseline'))
    ap = (baseline/'patched/appFw.so').read_bytes()
    cp = (baseline/'patched/cpapp-b.bin').read_bytes()
    work = tmp_path_factory.mktemp('combined-native')
    final_ap, ap_report = patches.ap_patch(ap)
    final_cp, cp_report = patches.cp_patch(cp, work)
    return ap, cp, final_ap, final_cp, ap_report, cp_report


@pytest.mark.parametrize('case', ['overlap', 'preimage', 'bounds'])
def test_patch_contract_rejects_unsafe_plan(case):
    plan = patches.PatchSet(bytes(16))
    plan.put(0, bytes(4), b'ABCD', 'first')
    with pytest.raises(ValueError):
        if case == 'overlap':
            plan.put(2, bytes(4), b'EFGH', 'second')
        elif case == 'preimage':
            plan.put(8, b'wrong', b'RIGHT', 'wrong')
        else:
            plan.put(14, bytes(4), b'EFGH', 'bounds')


@pytest.mark.parametrize('kind', ['AP', 'CP'])
def test_unknown_complete_preimage_is_rejected(kind, tmp_path):
    with pytest.raises(ValueError, match='完整前像'):
        (patches.ap_patch(b'unknown') if kind == 'AP' else patches.cp_patch(b'unknown', tmp_path))
    assert list(tmp_path.iterdir()) == []


def test_marker_uses_active_relocated_program_headers(images):
    before, _, after, _, report, _ = images
    old, new = ELFFile(io.BytesIO(before)), ELFFile(io.BytesIO(after))
    assert old['e_phoff'] != 64
    assert after[64:64+6*56] == before[64:64+6*56]
    for i, (a, b) in enumerate(zip(old.iter_segments(), new.iter_segments())):
        if i == 0:
            assert b['p_filesz'] == b['p_memsz'] == 0x500fc70
        else:
            assert a.header == b.header
    assert report['marker_support_writes'] == 28
    assert report['marker_registrations'] == 3
    # 远端新增的整个菜单模块仅其PHDR中两个长度字段改变。
    phoff = old['e_phoff']
    x, y = bytearray(before[phoff:]), bytearray(after[phoff:])
    y[32:48] = x[32:48]
    assert x == y


def test_fl23_selection_ignores_old_saved_base_and_keeps_native_routes(images):
    ap = images[2]
    path = patches.ROOT/'a7r5-firmware-features/materials/source/analysis/ap-look-selfcontained-20261022-01/offline_cpu.py'
    spec = importlib.util.spec_from_file_location('combined_selection_cpu', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    for route in ('direct', 'bulk', 'notify'):
        for selector, wanted in ((17, 19), (18, 20)):
            for base in (0, 5, 10, 11):
                result = module.run(ap, selector, base, route=route)
                assert result['wire'] == wanted and not result['diagnostic'], (route, selector, base, result)
        for base, wanted in enumerate((0, 3, 2, 1, 16, 15, 17, 18, 5, 13, 19, 20)):
            assert module.run(ap, 0, base, route=route)['wire'] == wanted


def test_ntsc_branches_execute_to_original_continuations(images):
    ap = images[2]
    for at, target in ((0x20c99a4, 0x20c99c0), (0x20c9ea4, 0x20c9ecc)):
        cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        page = at & ~4095
        cpu.mem_map(page, 4096)
        cpu.mem_write(page, ap[page:page+4096])
        cpu.emu_start(at, target, count=1)
        assert cpu.reg_read(a64.UC_ARM64_REG_PC) == target


def test_marker_registration_executes_original_range_validator(images):
    ap = images[2]
    for index, upper in enumerate((1, 5, 15)):
        for value in (-1, 0, upper, upper+1):
            cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
            for page in (0x500f000, 0x2905000):
                cpu.mem_map(page, 4096)
                cpu.mem_write(page, ap[page:page+4096])
            stop = 0x60000000
            cpu.mem_map(stop, 4096)
            cpu.reg_write(a64.UC_ARM64_REG_X0, value & 0xffffffff)
            cpu.reg_write(a64.UC_ARM64_REG_LR, stop)
            cpu.emu_start(0x500fc10+index*32, stop, count=100)
            assert cpu.reg_read(a64.UC_ARM64_REG_X0) == int(0 <= value <= upper)


def test_relocated_gamma_records_keep_every_original_byte(images):
    old, new, report = images[1], images[3], images[5]
    stage = 0x11d4000-patches.BASE
    for row in report['curve_relocations']:
        record = old[row['before']-patches.BASE:row['before']-patches.BASE+576]
        offset = stage+row['after']-0x1a3a000
        assert new[offset:offset+576] == record
        for at in row['pointer_offsets']:
            assert struct.unpack_from('<I', new, at)[0] == row['after']
    # 两个当前远端RX页、消息处理和私有配置应用代码逐字节保持。
    lo, hi = 0x1195080-patches.BASE, 0x1197000-patches.BASE
    assert old[lo:hi] == new[lo:hi]


def test_supplied_twelve_filter_bin_is_accepted_by_unchanged_upstream_codec(tmp_path):
    upstream = Path(os.environ.get('A7R5_NATIVE12_UPSTREAM', HERE/'upstream'))
    source = upstream/'firmware/r5/src/import'
    library = tmp_path/'codec.dylib'
    subprocess.run(['clang', '-shared', '-fPIC', '-Wall', '-Wextra', '-Werror', '-I', str(source),
                    str(source/'r5_stage410_codec.c'), '-o', str(library)], check=True, capture_output=True)
    codec = ctypes.CDLL(str(library))
    codec.r5_decode_look_file.argtypes = [ctypes.c_void_p, ctypes.c_size_t, ctypes.c_void_p]
    codec.r5_decode_look_file.restype = ctypes.c_int
    payload = (upstream/'filters/FUJ_12_v45/R5NATIVE.BIN').read_bytes()
    output = ctypes.create_string_buffer(65536)
    assert len(payload) == 29552
    assert codec.r5_decode_look_file(payload, len(payload), output) == 0
    assert struct.unpack_from('<I', output.raw)[0] == 0xfff
    before = output.raw
    bad = bytearray(payload)
    bad[-8] ^= 1
    assert codec.r5_decode_look_file(bytes(bad), len(bad), output) == 2
    assert output.raw == before


def matrix_result(raw, profile, sector, table):
    cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
    for va, size in ((0x71e000, 0x2000), (0xbef000, 0x1000), (0x1195000, 0x2000)):
        cpu.mem_map(va, size)
        cpu.mem_write(va, raw[va-patches.BASE:va-patches.BASE+size])
    cpu.mem_map(0x1a3a000, 4096)
    cpu.mem_write(0x1a3a000, table)
    cpu.mem_map(0x16b0000, 0x10000)
    data, stack, stop = 0x6000000, 0x6010000, 0x6020000
    for va in (data, stack, stop):
        cpu.mem_map(va, 0x10000)
    cpu.mem_write(data+0x700, struct.pack('<II', data+0x500, data+0x100))
    cpu.mem_write(data+0x2a0, struct.pack('<3H', 1000, 1100, 1200))
    for i, value in enumerate((data, sector, data+0x700, profile)):
        cpu.reg_write(getattr(arm, f'UC_ARM_REG_R{i}'), value)
    cpu.reg_write(arm.UC_ARM_REG_SP, stack+0x8000)
    cpu.reg_write(arm.UC_ARM_REG_LR, stop|1)
    saved = {}
    for i in range(4, 12):
        value = 0x12340000+i
        cpu.reg_write(getattr(arm, f'UC_ARM_REG_R{i}'), value)
        saved[i] = value
    cpu.emu_start(0x71e41f, stop, count=20000)
    assert cpu.reg_read(arm.UC_ARM_REG_PC) == stop
    assert cpu.reg_read(arm.UC_ARM_REG_SP) == stack+0x8000
    for i, value in saved.items():
        assert cpu.reg_read(getattr(arm, f'UC_ARM_REG_R{i}')) == value
    return struct.unpack('<27H', bytes(cpu.mem_read(data, 54)))


def test_all_fl23_matrix_profiles_and_sector_boundary_use_local_coefficients(images):
    cp = images[3]
    table = patches.matrix_bytes()
    for profile in (54, 55, 56, 57):
        for sector in (0, 7, 15, 16):
            selected = sector if sector <= 15 else 0
            expected = []
            for endpoint in range(3):
                at = (profile-54)*576+selected*36+endpoint*12
                a,b,c,d,e,f = struct.unpack_from('<6h', table, at)
                expected.extend(v & 65535 for v in (1000+a+b,-a,-b,-c,1100+c+d,-d,-e,-f,1200+e+f))
            assert matrix_result(cp, profile, sector, table) == tuple(expected)


def test_non_target_matrices_and_embedded_cc1_remain_upstream(images):
    old, new = images[1], images[3]
    table = patches.matrix_bytes()
    for profile in (0, 42, 53, 58):
        assert matrix_result(old, profile, 3, table) == matrix_result(new, profile, 3, table)
    at = 0xbef3ec-patches.BASE
    assert old[at:at+192] == new[at:at+192]
    assert old[0x377601] == new[0x377601] == 0x0f


def test_sound_selector_keeps_non_type1_inhibit_and_callee_state(images):
    raw = images[3]
    for capture in range(4):
        for inhibit in (0, 1):
            cpu = Uc(UC_ARCH_ARM, UC_MODE_THUMB)
            for va, size in ((0x47f000, 4096), (0xbef000, 4096)):
                cpu.mem_map(va, size)
                cpu.mem_write(va, raw[va-patches.BASE:va-patches.BASE+size])
            cpu.mem_map(0x6000000, 0x3000)
            cpu.mem_write(0x6001618, struct.pack('<I', capture))
            cpu.reg_write(arm.UC_ARM_REG_R0, inhibit)
            cpu.reg_write(arm.UC_ARM_REG_R4, 0x6000000)
            cpu.reg_write(arm.UC_ARM_REG_SP, 0x6002800)
            cpu.emu_start(0x47f623, 0x47f62e, count=100)
            assert cpu.reg_read(arm.UC_ARM_REG_PC) == 0x47f62e
            assert cpu.reg_read(arm.UC_ARM_REG_R1) == (3 if not inhibit or capture == 1 else 0)
            assert cpu.reg_read(arm.UC_ARM_REG_R0) == 0x5b00
            assert cpu.reg_read(arm.UC_ARM_REG_R4) == 0x6000000
            assert cpu.reg_read(arm.UC_ARM_REG_SP) == 0x6002800


@pytest.mark.parametrize('state', ['fresh', 'repeat', 'corrupt'])
def test_bootstrap_copy_reentry_integrity_and_native_instruction(images, state):
    raw, report = images[3], images[5]
    table = patches.cp_payload(images[1])
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.mem_map(0x108000, 4096)
    cpu.mem_write(0x108000, raw[:4096])
    cpu.mem_map(0x11d4000, 4096)
    cpu.mem_write(0x11d4000, table if state == 'fresh' else bytes(len(table)))
    cpu.mem_map(0x1a3a000, 4096)
    cpu.mem_write(0x1a3a000, table if state == 'repeat' else bytes(len(table)))
    cpu.mem_map(0x6000000, 0x10000)
    cpu.mem_write(0x6000148, struct.pack('<I', 0x12345678))
    cpu.reg_write(arm.UC_ARM_REG_R4, 0x6000000)
    cpu.reg_write(arm.UC_ARM_REG_SP, 0x6008000)
    cpu.reg_write(arm.UC_ARM_REG_R5, 0x5678)
    invalid = report['compiled']['symbols']['matrix_copy_invalid'] & ~1
    observed = []
    def stop_invalid(u, at, size, data):
        if at == invalid:
            observed.append(at)
            u.emu_stop()
    cpu.hook_add(UC_HOOK_CODE, stop_invalid)
    cpu.emu_start(0x108524, 0x108528, count=100000)
    if state == 'corrupt':
        assert observed == [invalid]
    else:
        assert not observed and cpu.reg_read(arm.UC_ARM_REG_PC) == 0x108528
        assert bytes(cpu.mem_read(0x1a3a000, len(table))) == table
        assert bytes(cpu.mem_read(0x11d4000, len(table))) == bytes(len(table))
        assert cpu.reg_read(arm.UC_ARM_REG_R0) == 0x12345678
        assert cpu.reg_read(arm.UC_ARM_REG_R4) == 0x6000000
        assert cpu.reg_read(arm.UC_ARM_REG_R5) == 0x5678
        assert cpu.reg_read(arm.UC_ARM_REG_SP) == 0x6008000
