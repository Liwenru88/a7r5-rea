"""回放 AP 当前文件的画幅、像素图标及未知比例放大门，保留原生拒绝。"""
import struct

import pytest
from unicorn import UC_HOOK_CODE
from unicorn import arm64_const as R

from aspect_sizes import SIZES
from build_ap import FIRST_PLAYBACK_ICON, FIRST_PIXEL_ICON
from test_ap import ap_image  # noqa: F401
from test_playback import machine
from test_geometry import DATA, STACK, STOP


@pytest.mark.parametrize('format_byte', [0xf2, 0xf3, 0xf4])
def test_playback_info_and_zoom_use_this_file_dimensions(ap_image, format_byte):
    base = 0x10000000
    cpu = machine(ap_image, base)
    owner, record, output = DATA, DATA + 0x180, DATA + 0x2000
    def reg(i, value): cpu.reg_write(getattr(R, f'UC_ARM64_REG_X{i}'), value)
    def invoke(start, stop, **values):
        cpu.reg_write(R.UC_ARM64_REG_SP, STACK)
        cpu.reg_write(R.UC_ARM64_REG_LR, STOP)
        for i, value in values.items(): reg(int(i[1:]), value)
        cpu.emu_start(base + start, stop, count=2000)
        assert cpu.reg_read(R.UC_ARM64_REG_PC) == stop
        assert cpu.reg_read(R.UC_ARM64_REG_SP) == STACK
    for index, (id, w, h) in enumerate(SIZES):
        cpu.mem_write(record, bytes(0x1000))
        cpu.mem_write(record + format_byte, b'\x01')
        cpu.mem_write(record + 0xb80, b'\x01')
        cpu.mem_write(record + 0xb84, struct.pack('<II', w, h))
        cpu.mem_write(record + (0x14 if format_byte == 0xf3 else 0xc), struct.pack('<II', w, h))
        invoke(0x23de638, STOP, x1=output, x3=record)
        assert struct.unpack('<I', cpu.mem_read(output + 0x3c, 4))[0] == FIRST_PLAYBACK_ICON + id - 4
        invoke(0x23dfa30, base + 0x23dfa28, x0=h, x2=w, x3=record)
        assert cpu.reg_read(R.UC_ARM64_REG_X0) == FIRST_PIXEL_ICON + index
        cpu.mem_write(record + 0x1c, struct.pack('<I', 7))
        invoke(0x30c6f1c, base + 0x30c6f20, x0=7, x19=owner)
        assert cpu.reg_read(R.UC_ARM64_REG_X0) == 0
        cpu.mem_write(record + 0xb84, struct.pack('<I', w + 1))
        invoke(0x30c6f1c, base + 0x30c6f20, x0=7, x19=owner)
        assert cpu.reg_read(R.UC_ARM64_REG_X0) == 8
        if format_byte != 0xf3:
            invoke(0x23dfa30, base + 0x23dfa34, x0=h, x2=w, x3=record)
            assert cpu.reg_read(R.UC_ARM64_REG_X3) == 4320


def test_zoom_private_policy_only_opens_native_zoom_start_descriptor(ap_image):
    base = 0x10000000
    cpu = machine(ap_image, base)
    descriptor, key = base + 0x53db910, DATA + 0x1000
    cpu.mem_map(base + 0x5300000, 0x1000000)
    cpu.mem_write(descriptor + 8, struct.pack('<II', 0xffd, 0x8cc))
    table, fallback = DATA + 0x2000, DATA + 0x3000
    cpu.mem_write(descriptor, struct.pack('<Q', table))
    cpu.mem_write(table + 0x40, struct.pack('<Q', fallback))
    def invoke(value, desc=descriptor):
        cpu.mem_write(key, struct.pack('<I', value))
        cpu.reg_write(R.UC_ARM64_REG_X0, desc)
        cpu.reg_write(R.UC_ARM64_REG_X1, key)
        cpu.reg_write(R.UC_ARM64_REG_SP, STACK)
        cpu.reg_write(R.UC_ARM64_REG_LR, STOP)
        cpu.emu_start(base + 0x249069c, STOP, count=128)
        assert cpu.reg_read(R.UC_ARM64_REG_PC) == STOP
        return cpu.reg_read(R.UC_ARM64_REG_X0)
    assert invoke(0x507a) == 0
    for value in (0x504a, 0x5060, 0x5079):
        assert invoke(value) == fallback
    cpu.mem_write(descriptor + 8, struct.pack('<I', 0xffe))
    assert invoke(0x507a) == fallback


def test_zoom_domain_override_requires_current_file_and_native_unknown_value(ap_image):
    base = 0x10000000
    cpu = machine(ap_image, base)
    record = DATA + 0x1000
    frame = DATA + 0x3000
    locks = []
    def service(at, result, label):
        def hook(core, *_):
            locks.append(label)
            core.reg_write(R.UC_ARM64_REG_X0, result)
            core.reg_write(R.UC_ARM64_REG_PC, core.reg_read(R.UC_ARM64_REG_LR))
        cpu.hook_add(UC_HOOK_CODE, hook, begin=base + at, end=base + at)
    service(0x2e7d208, 0, 'lock')
    service(0x28a0a08, record, 'current')
    service(0x2e7cee4, 0, 'unlock')
    cpu.mem_write(record + 0xf3, b'\x01')
    cpu.mem_write(record + 0x1c, struct.pack('<I', 7))
    cpu.mem_write(record + 0xb80, b'\x01')
    cpu.mem_write(record + 0x14, struct.pack('<II', 9504, 3352))
    cpu.mem_write(STACK + 0x10, struct.pack('<Q', 0xace19))
    for prop, raw, domain, w, expected in ((0x152, 8, 0x5049, 9504, 0x507a),
                                         (0x152, 8, 0x5049, 9505, 0x5049),
                                         (0x151, 8, 0x5049, 9504, 0x5049),
                                         (0x152, 7, 0x5049, 9504, 0x5049),
                                         (0x152, 8, 0x5048, 9504, 0x5048)):
        cpu.mem_write(frame + 0x2c, struct.pack('<I', raw))
        cpu.mem_write(record + 0xb84, struct.pack('<II', w, 3352))
        before = bytes(cpu.mem_read(record, 0xc00))
        for i, value in ((0, domain), (19, prop), (29, frame)):
            cpu.reg_write(getattr(R, f'UC_ARM64_REG_X{i}'), value)
        cpu.reg_write(R.UC_ARM64_REG_SP, STACK)
        cpu.emu_start(base + 0x2492230, base + 0x2492234, count=2000)
        assert cpu.reg_read(R.UC_ARM64_REG_PC) == base + 0x2492234
        assert cpu.reg_read(R.UC_ARM64_REG_X0) == expected
        assert cpu.reg_read(R.UC_ARM64_REG_X19) == 0xace19
        assert bytes(cpu.mem_read(record, 0xc00)) == before
    assert locks == ['lock', 'current', 'unlock'] * 2
