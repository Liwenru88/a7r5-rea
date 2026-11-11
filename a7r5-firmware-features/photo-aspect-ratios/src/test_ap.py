"""回放原生 0x402d 消息的比例序列化，底层发送服务为夹具。"""

import io
import json
import os
from pathlib import Path
import struct

from elftools.elf.elffile import ELFFile
import pytest
from unicorn import Uc, UC_ARCH_ARM64, UC_HOOK_CODE, UC_MODE_ARM
from unicorn import arm64_const as R

from build_ap import DESCRIPTOR, FIRST_ICON, FIRST_ROW, SELECTION, STOCK_ROWS, apply_ap, compile_ap, digest
from test_geometry import DATA, ROOT, STACK, STOP

if folder := os.environ.get('A7R5_ASPECT_CAPTURE'):
    SELECTION = json.loads((Path(folder) / 'build.json').read_text())['AP']['selection']


class BoundAP(bytes):
    def __new__(cls, raw, symbols):
        result = super().__new__(cls, raw)
        result.symbols = symbols
        return result


@pytest.fixture(scope='module')
def ap_image(tmp_path_factory):
    path = Path(os.environ.get('A7R5_ASPECT_AP_INPUT',
        ROOT/'a7r5-qemu/runs/a7r5-lens-af-2qHo9T/default/appFw.so'))
    if not path.is_file():
        pytest.skip('需要已核对的 native24 整合 AP 输入')
    raw = path.read_bytes()
    if folder := os.environ.get('A7R5_ASPECT_CAPTURE'):
        folder = Path(folder)
        proof = json.loads((folder / 'build.json').read_text())['AP']
        candidate = (folder / 'appFw.so').read_bytes()
        assert digest(candidate) == proof['target_sha256'] and digest(raw) == proof['source_sha256']
    else:
        candidate, proof = apply_ap(raw, compile_ap(tmp_path_factory.mktemp('aspect-ap'), raw))
    reverse = bytearray(candidate[:len(raw)])
    for row in proof['patches']:
        offset, before = row['offset'], bytes.fromhex(row['before'])
        assert candidate[offset:offset + len(before)].hex() == row['after']
        reverse[offset:offset + len(before)] = before
    assert reverse == raw and len(candidate) >= len(raw)
    if folder := os.environ.get('A7R5_OPTIONAL_AP_READBACK'):
        folder = Path(folder)
        name = 'usr/lib/appFw.so'
        row = json.loads((folder / 'manifest.json').read_text())['components'][name]
        candidate = (folder / 'components' / name).read_bytes()
        assert len(candidate) == row['bytes'] and digest(candidate) == row['sha256']
    return BoundAP(candidate, proof['symbols'])


@pytest.mark.parametrize('base', [0, 0x10000000])
def test_native_402d_freezes_private_wire_once(ap_image, base):
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.mem_map(base, 0x9000000)
    for segment in ELFFile(io.BytesIO(ap_image)).iter_segments():
        if segment['p_type'] == 'PT_LOAD' and segment['p_filesz']:
            cpu.mem_write(base + segment['p_vaddr'], segment.data())
    if base:
        cpu.mem_map(DATA, 0x30000)
    frame = STACK + 0x1000
    sent = []

    def write(registers):
        for i, value in registers.items():
            cpu.reg_write(getattr(R, f'UC_ARM64_REG_X{i}'), value)

    def sender(core, _address, _size, _user):
        assert core.reg_read(R.UC_ARM64_REG_X0) == 0x90030001
        assert core.reg_read(R.UC_ARM64_REG_X2) == 24
        at = core.reg_read(R.UC_ARM64_REG_X1)
        sent.append(bytes(core.mem_read(at, 24)))
        core.reg_write(R.UC_ARM64_REG_PC, core.reg_read(R.UC_ARM64_REG_LR))

    original = base + 0x355882c
    cpu.hook_add(UC_HOOK_CODE, sender, begin=original, end=original)
    cases = [(0, id, 2, 0xe0 + id - 4) for id in range(4, 10)]
    cases += [(0, 0, 2, 2), (0, 10, 2, 2), (1, 9, 1, 1), (2, 9, 0, 0), (3, 9, 3, 3)]
    for native_id, private, stock_wire, expected in cases:
        cpu.mem_write(base + SELECTION, struct.pack('<I', 0x123400 | private))
        # 本用例已注入显式选择；启动读盘另由真实文件／线程边界用例验证。
        cpu.mem_write(base + SELECTION + 0x1a0, struct.pack('<I', 1))
        cpu.mem_write(DATA, struct.pack('<III', 0, 0, native_id))
        cpu.mem_write(frame, bytes(0x400))
        header = struct.pack('<BxH', 5, 0x402d)
        cpu.mem_write(frame + 0x88, header)
        cpu.reg_write(R.UC_ARM64_REG_SP, frame)
        write({0: 0, 16: 0x1616, 17: 0x1717, 20: DATA, 29: frame})
        cpu.ctl_flush_tb()
        cpu.emu_start(base+0x3565f78, base+0x3565fac, count=150)
        assert cpu.reg_read(R.UC_ARM64_REG_PC) == base+0x3565fac
        assert cpu.mem_read(frame+0x90, 1) == bytes([stock_wire])
        assert cpu.reg_read(R.UC_ARM64_REG_X16) == 0x1616
        assert cpu.reg_read(R.UC_ARM64_REG_X17) == 0x1717

        # 发送前菜单更改，不得污染本条已冻结的消息。
        cpu.mem_write(base + SELECTION, struct.pack('<I', 8 if private != 8 else 9))
        write({0: 0x90030001, 1: frame + 0x88, 2: 24, 3: 0x402d, 4: frame+0x220, 5: 12})
        cpu.ctl_flush_tb()
        cpu.emu_start(base+0x3566a44, base+0x3566a48, count=150)
        assert cpu.reg_read(R.UC_ARM64_REG_PC) == base+0x3566a48
        assert cpu.reg_read(R.UC_ARM64_REG_SP) == frame
        assert sent[-1] == header + bytes(4) + bytes([expected]) + bytes(15)


def test_leaf_round_trip_keeps_private_values_out_of_stock_property(ap_image):
    base = 0x10000000
    core = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    core.mem_map(base, 0x9000000)
    core.mem_map(DATA, 0x30000)
    elf = ELFFile(io.BytesIO(ap_image))
    for segment in elf.iter_segments():
        if segment['p_type'] == 'PT_LOAD' and segment['p_filesz']:
            core.mem_write(base+segment['p_vaddr'], segment.data())
    descriptor = base+DESCRIPTOR
    for at, info, addend in struct.iter_unpack('<QQq', elf.get_section_by_name('.rela.dyn').data()):
        if DESCRIPTOR+0x58 <= at <= DESCRIPTOR+0x88:
            assert info == 1027
            core.mem_write(base+at, struct.pack('<Q', base+addend))

    def word(at):
        return struct.unpack('<I', core.mem_read(at, 4))[0]

    def pointer(at):
        return struct.unpack('<Q', core.mem_read(at, 8))[0]

    assert word(descriptor+0x54) == 10
    rows = pointer(descriptor+0x58)
    assert core.mem_read(rows, 512) == core.mem_read(base+STOCK_ROWS, 512)
    get, set_, commit = (pointer(descriptor+i) for i in (0x78, 0x80, 0x88))
    native = 0
    committed = []

    def hook(cpu, address, _size, _user):
        nonlocal native
        argument = cpu.reg_read(R.UC_ARM64_REG_X0)
        if address == base+0x1c448dc:
            cpu.reg_write(R.UC_ARM64_REG_X0, native)
        elif address == base+0x1c61d14:
            assert 0 <= argument < 4
            native = argument
        else:
            committed.append((argument, word(base+SELECTION) & 0xff))
        cpu.reg_write(R.UC_ARM64_REG_PC, cpu.reg_read(R.UC_ARM64_REG_LR))

    for at in (0x1c448dc, 0x1c61d14, 0x1c93d88, 0x1bd9410):
        core.hook_add(UC_HOOK_CODE, hook, begin=base+at, end=base+at)

    def unavailable_files(cpu, *_):
        cpu.reg_write(R.UC_ARM64_REG_X0, 0)
        cpu.reg_write(R.UC_ARM64_REG_PC, cpu.reg_read(R.UC_ARM64_REG_LR))
    core.hook_add(UC_HOOK_CODE, unavailable_files, begin=base+0x16dac90, end=base+0x16dac90)
    # 本用例只执行菜单契约；补齐新增状态通知的原生模型边界。
    for at in (0x2e7d208, 0x2e7cee4, 0x252ca34, 0x252d80c):
        core.hook_add(UC_HOOK_CODE, unavailable_files, begin=base+at, end=base+at)

    def available(cpu, *_):
        sp = cpu.reg_read(R.UC_ARM64_REG_SP)
        x29, lr = struct.unpack('<QQ', cpu.mem_read(sp, 16))
        cpu.reg_write(R.UC_ARM64_REG_X29, x29)
        cpu.reg_write(R.UC_ARM64_REG_SP, sp+0x20)
        cpu.reg_write(R.UC_ARM64_REG_X0, 1)
        cpu.reg_write(R.UC_ARM64_REG_PC, lr)
    core.hook_add(UC_HOOK_CODE, available, begin=base+0x1bd5418, end=base+0x1bd5418)

    def call(address, argument=0, argument2=0, end=STOP):
        core.reg_write(R.UC_ARM64_REG_X0, argument)
        core.reg_write(R.UC_ARM64_REG_X1, argument2)
        core.reg_write(R.UC_ARM64_REG_LR, end)
        core.reg_write(R.UC_ARM64_REG_SP, STACK)
        core.emu_start(address, end, count=3000)
        assert core.reg_read(R.UC_ARM64_REG_PC) == end
        assert core.reg_read(R.UC_ARM64_REG_SP) == STACK
        return core.reg_read(R.UC_ARM64_REG_X0)

    for index in (*range(4, 10), *range(4)):
        row = rows+128*index
        alias, setting = word(row), word(row+0x34)
        assert (alias, setting) == ((FIRST_ROW+index-4 if index >= 4 else 126+index), index)
        call(set_, setting)
        assert call(get) == index
        assert native == (0 if index >= 4 else index)
        if index >= 4:
            # 原厂确认路径先查询行级拦截回调；此项必须落到父菜单提交。
            selector = struct.unpack('<H', core.mem_read(row+0x74, 2))[0]
            assert selector == 0x1086 and call(base+0x1c5ff04, selector) == 0
            assert call(base+0x1bd5414, alias) == 1
            assert call(base+0x1bd18e8, 0, alias) == FIRST_ICON+2*(index-4)
            assert call(base+0x1bd19e8, 0, alias) == FIRST_ICON+2*(index-4)+1
        call(commit, alias)
        assert committed[-1] == ((126, index) if index >= 4 else (126+index, 0))
        core.mem_write(base+SELECTION, bytes(4))
        call(base+0x21e1cd4, alias, end=base+0x21e1cd8)
        assert committed[-1] == ((126, index) if index >= 4 else (126+index, 0))
    call(set_, 9)
    call(set_, 10)
    assert call(get) == 9
    call(base+0x21e1cd4, 126, end=base+0x21e1cd8)
    assert committed[-1] == (126, 0) and call(get) == 0
    call(set_, 9)
    earlier = word(base+SELECTION)
    call(set_, 0)
    assert call(get) == 0 and word(base+SELECTION) & 0xff == 0
    call(set_, 9)
    assert call(get) == 9 and word(base+SELECTION) != earlier
