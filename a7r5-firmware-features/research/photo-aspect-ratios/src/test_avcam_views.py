"""执行已安装的 AVCAM 局部裁切代码；原生准备/头服务在边界使用夹具。"""
import struct
import json
import os
from pathlib import Path

import pytest
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
from unicorn import arm64_const as R

from aspect_sizes import FULL_SIZES, SIZES, SCENES, THUMBNAILS
from build_avcam import apply_avcam, compile_avcam, digest
from test_avcam import BASE, CONTEXT, machine, stock_avcam  # noqa: F401
from test_geometry import DATA, GEOMETRY, STACK, STOP


@pytest.fixture(scope='module')
def views(stock_avcam, tmp_path_factory):
    if folder := os.environ.get('A7R5_ASPECT_CAPTURE'):
        folder = Path(folder)
        proof = json.loads((folder / 'build.json').read_text())['AVCAM']
        image = (folder / 'AV-CAM.BIN').read_bytes()
        assert digest(image) == proof['target_sha256']
        assert digest(stock_avcam) == proof['source_sha256']
        return image, proof
    image, proof = apply_avcam(stock_avcam, compile_avcam(tmp_path_factory.mktemp('views')))
    return image, proof


@pytest.mark.parametrize('slot', [1, 16])
def test_encoder_entry_uses_argument_slot_without_caller_register_assumption(views, slot):
    image, proof = views
    cpu = machine(image)
    source = DATA + 0x6000
    for register, value in ((0, slot), (1, 2), (2, CONTEXT), (4, source),
                            (21, 0xdeadbeef), (30, STOP)):
        cpu.reg_write(getattr(R, f'UC_ARM64_REG_X{register}'), value)
    cpu.reg_write(R.UC_ARM64_REG_SP, STACK)
    helper = BASE + proof['symbols']['aspect_avcam_heif_encode']
    cpu.emu_start(BASE + 0x200734, helper, count=1000)
    assert cpu.reg_read(R.UC_ARM64_REG_PC) == helper
    assert tuple(cpu.reg_read(getattr(R, f'UC_ARM64_REG_X{i}')) for i in range(4)) == (
        CONTEXT, 2, source, slot)


@pytest.fixture
def local(views):
    image, proof = views
    cpu = machine(image)
    state = {'prepare_error': 0, 'headers': []}
    extra = DATA + 0xa000
    def reg(index): return cpu.reg_read(getattr(R, f'UC_ARM64_REG_X{index}'))
    def service(address, function):
        def hook(core, *_):
            core.reg_write(R.UC_ARM64_REG_X0, function())
            core.reg_write(R.UC_ARM64_REG_PC, core.reg_read(R.UC_ARM64_REG_LR))
        cpu.hook_add(UC_HOOK_CODE, hook, begin=BASE + address, end=BASE + address)
    service(0x206378, lambda: state['prepare_error'])
    def raw_headers():
        cpu.mem_write(reg(2), struct.pack('<19Q', *([0] * 18), extra))
        return 0
    service(0x1f5388, raw_headers)
    def headers():
        cpu.mem_write(reg(3), struct.pack('<6Q', DATA + 0xb000, DATA + 0xb100, 0, 0, 0, 0))
        return 0
    service(0x1f52d4, headers)
    def size():
        state['headers'].append((reg(0), reg(1), reg(2)))
        return 0
    service(0x1f30c8, size)
    service(0x1f377c, size)
    def call(name, *args):
        cpu.mem_write(STACK, struct.pack('<2Q', *(list(args[8:]) + [0, 0])[:2]))
        for i, value in enumerate(args[:8]):
            cpu.reg_write(getattr(R, f'UC_ARM64_REG_X{i}'), value)
        cpu.reg_write(R.UC_ARM64_REG_SP, STACK)
        cpu.reg_write(R.UC_ARM64_REG_LR, STOP)
        cpu.emu_start(BASE + proof['symbols'][name], STOP, count=30000)
        assert cpu.reg_read(R.UC_ARM64_REG_PC) == STOP
        assert cpu.reg_read(R.UC_ARM64_REG_SP) == STACK
        return reg(0)
    return cpu, call, state, extra


def test_heif_each_slot_crops_local_view_and_keeps_shared_raw_dimensions(local):
    cpu, call, state, _ = local
    source = DATA + 0x6000
    for index, (id, w, h) in enumerate(SIZES):
        fw, fh = FULL_SIZES[index % 3]
        for slot, offset, wh_at in ((1, 0xa4, 0x3a4), (16, 0x224, 0x3a8)):
            cpu.mem_write(CONTEXT, bytes(0x1000))
            cpu.mem_write(CONTEXT + 0x440 + offset, struct.pack('<I', 4))
            cpu.mem_write(CONTEXT + 0x440 + wh_at, struct.pack('<HH', w, h))
            shared = bytes([0x5a]) * 0x3c
            cpu.mem_write(CONTEXT + 0x3bc, shared)
            full = GEOMETRY.pack((fw + 127) & ~127, fh + 8, fw, fh, 0, 0)
            cpu.mem_write(source, full)
            assert call('aspect_avcam_heif_prepare', slot, 0, CONTEXT, 0, source, 0, 0, 0, 0, 0) == 0
            assert GEOMETRY.unpack(cpu.mem_read(source, 12))[2:4] == (w, h)
            assert bytes(cpu.mem_read(CONTEXT + 0x3bc, len(shared))) == shared
            state['headers'].clear()
            assert call('aspect_avcam_heif_encode', CONTEXT, 0, source, slot) == 0
            assert [row[1:] for row in state['headers']] == [(w, h)] * 2
            cropped = bytes(cpu.mem_read(source, 12))
            assert call('aspect_avcam_heif_encode', CONTEXT, 0, source, slot) == 0
            assert bytes(cpu.mem_read(source, 12)) == cropped
            invalid = bytearray(cropped)
            struct.pack_into('<H', invalid, 8, 65528)
            cpu.mem_write(source, bytes(invalid))
            assert call('aspect_avcam_heif_encode', CONTEXT, 0, source, slot) == 2
            assert bytes(cpu.mem_read(source, 12)) == invalid
            state['prepare_error'] = 5
            cpu.mem_write(source, full)
            assert call('aspect_avcam_heif_prepare', slot, 0, CONTEXT, 0, source, 0, 0, 0, 0, 0) == 5
            assert bytes(cpu.mem_read(source, 12)) == full
            state['prepare_error'] = 0


def test_raw_only_and_raw_heif_preview_use_emb_wh_without_touching_full_source(local):
    cpu, call, _, extra = local
    source, target = DATA + 0x6000, DATA + 0x7000
    for index, (id, w, h) in enumerate(SIZES):
        for raw_offset, other in ((0xa4, 0), (0xa4, 4), (0x224, 4)):
            cpu.mem_write(CONTEXT, bytes(0x1000))
            cpu.mem_write(CONTEXT + 0x440 + raw_offset, struct.pack('<I', 2))
            cpu.mem_write(CONTEXT + 0x440 + (0x224 if raw_offset == 0xa4 else 0xa4), struct.pack('<I', other))
            cpu.mem_write(CONTEXT + 0x840, struct.pack('<Q', DATA + 0xc000))
            cpu.mem_write(extra, bytes([0x5a]) * 0xb00)
            cpu.mem_write(extra + 0xa50, struct.pack('<II', w, h))
            shared = bytes(cpu.mem_read(CONTEXT, 0x1000))
            header = bytes(cpu.mem_read(extra, 0xb00))
            for mode, full, expected in ((3, FULL_SIZES[index % 3], (w, h)),
                                          (1, (1616, 1080), SCENES[id - 4]),
                                          (2, (320, 212), THUMBNAILS[id - 4])):
                fw, fh = full
                cpu.mem_write(source, GEOMETRY.pack((fw + 127) & ~127, fh + 8, fw, fh, 0, 0))
                cpu.mem_write(target, GEOMETRY.pack((fw + 127) & ~127, fh + 8, fw, fh, 0, 0))
                target_before = bytes(cpu.mem_read(target, 12))
                assert call('aspect_avcam_raw_preview_prepare', 1, mode, CONTEXT, 0,
                            source, 0, target, 0, 0, 0) == 0
                assert GEOMETRY.unpack(cpu.mem_read(source, 12))[2:4] == expected
                if mode != 2:
                    assert GEOMETRY.unpack(cpu.mem_read(target, 12))[2:] == (*expected, 0, 0)
                else:
                    assert bytes(cpu.mem_read(target, 12)) == target_before
                assert bytes(cpu.mem_read(CONTEXT, 0x1000)) == shared
                assert bytes(cpu.mem_read(extra, 0xb00)) == header


def test_snapshot_references_reserve_ram_after_code_and_preserve_native_ram_window(views):
    image, proof = views
    layout = proof['snapshot']
    assert layout['code_end'] <= layout['backup_start'] < layout['backup_end'] <= layout['tail_end'] < 0x1000000
    assert layout['backup_end'] - layout['backup_start'] == layout['ram_end'] - layout['ram_start']
    assert struct.unpack_from('<Q', image, 0x1cc)[0] == 0xffffffc001000000 + layout['tail_end']
    cpu = machine(image)
    for at, register in ((0x2db28, 9), (0x2db58, 20), (0x2dc30, 0), (0x2dc50, 0), (0x2e22c, 1)):
        cpu.emu_start(BASE + at, BASE + at + 8, count=2)
        assert cpu.reg_read(getattr(R, f'UC_ARM64_REG_X{register}')) == BASE + layout['backup_start']


def test_native_snapshot_save_restore_keeps_complete_ram_and_code(views, stock_avcam):
    # 执行原生控制流；只在日志、地址翻译和 DMA 硬件边界提供替身。
    high = 0xffffffc001000000
    dma = 0xfffffffff1058030
    ram_start, ram_end = 0xba7fc0, 0xc5b378
    length = ram_end - ram_start
    for image in (stock_avcam, views[0]):
        cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        cpu.mem_map(high, 0x1000000)
        cpu.mem_write(high, image)
        cpu.mem_map(DATA, 0x30000)
        cpu.mem_map(dma & ~4095, 4096)
        backup = struct.unpack_from('<Q', image, 0x32d9b0)[0]
        assert struct.unpack_from('<Q', image, 0x32d9b8)[0] - backup == length
        code_before = bytes(cpu.mem_read(high + 0xc5b380, len(image) - 0xc5b380)) if len(image) > 0xc5b380 else b''
        transfers = []
        def service(core, address, _size, _user):
            relative = address - high
            if relative in (0x126e8, 0x2ef10, 0x2f528):
                value = core.reg_read(R.UC_ARM64_REG_X0) & 0xffffffff if relative == 0x2f528 else 0
                core.reg_write(R.UC_ARM64_REG_X0, value)
                core.reg_write(R.UC_ARM64_REG_PC, core.reg_read(R.UC_ARM64_REG_LR))
        def dma_write(core, _access, address, _size, value, _user):
            if address != dma + 0x1a0 or value != 1:
                return
            source, destination, command = (struct.unpack('<I', core.mem_read(dma + offset, 4))[0]
                                            for offset in (0x190, 0x194, 0x19c))
            count = ((command & 0xfff) or 4096) * 4
            source += 0xffffffc000000000
            destination += 0xffffffc000000000
            assert high + ram_start <= source < source + count <= high + ram_end
            assert backup <= destination < destination + count <= backup + length
            core.mem_write(destination, bytes(core.mem_read(source, count)))
            transfers.append(count)
        cpu.hook_add(UC_HOOK_CODE, service)
        cpu.hook_add(UC_HOOK_MEM_WRITE, dma_write)
        for seed in (17, 91):
            pattern = bytes((i + seed) & 255 for i in range(length))
            cpu.mem_write(high + ram_start, pattern)
            cpu.mem_write(backup - 8, b'\x7d' * 8)
            cpu.mem_write(backup + length, b'\x6c' * 32)
            for register, value in ((19, high + ram_start), (22, high + 0xbcc000),
                                    (26, DATA + 0x4000)):
                cpu.reg_write(getattr(R, f'UC_ARM64_REG_X{register}'), value)
            cpu.reg_write(R.UC_ARM64_REG_SP, STACK)
            transfers.clear()
            cpu.emu_start(high + 0x2db28, high + 0x2dd78, count=500000)
            assert cpu.reg_read(R.UC_ARM64_REG_PC) == high + 0x2dd78
            assert sum(transfers) == length
            saved = bytes(cpu.mem_read(backup, length))
            native_log = 0xbcc978 - ram_start
            assert saved[:native_log] == pattern[:native_log]
            assert saved[native_log + 4:] == pattern[native_log + 4:]
            cpu.mem_write(high + ram_start, b'\xa5' * length)
            cpu.emu_start(high + 0x2e218, high + 0x2e238, count=500000)
            assert cpu.reg_read(R.UC_ARM64_REG_PC) == high + 0x2e238
            assert bytes(cpu.mem_read(high + ram_start, length)) == saved
            assert bytes(cpu.mem_read(backup - 8, 8)) == b'\x7d' * 8
            assert bytes(cpu.mem_read(backup + length, 32)) == b'\x6c' * 32
            if code_before:
                assert bytes(cpu.mem_read(high + 0xc5b380, len(code_before))) == code_before
