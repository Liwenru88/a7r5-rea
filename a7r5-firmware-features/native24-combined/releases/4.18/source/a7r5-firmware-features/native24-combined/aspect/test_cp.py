"""执行已补丁的原生 CP 入口，区分任务数据夹具与实际固件指令。"""

import os
from pathlib import Path
import struct

import pytest
from unicorn import Uc, UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM
from unicorn import arm_const as ARM, arm64_const as ARM64

from build_cp import BASE, apply_cp, compile_cp, digest
from test_avcam import BASE as AV_BASE, CONTEXT as AV_CONTEXT, images, machine as avcam_machine, stock_avcam
from test_geometry import CASES, DATA, GEOMETRY, ROOT, STACK


POOL = 0x1112c54
MANAGER = 0x163f3c8
GFW = 0x157aa10
STATE = 0x1a3ad80
PACKET = DATA
TASK = DATA + 0x10000
TASK2 = TASK + 0x6688
FULL = GEOMETRY.pack(9600, 6344, 9504, 6336, 0, 0)
SCENE = GEOMETRY.pack(1664, 1080, 1616, 1080, 0, 0)


@pytest.fixture(scope='module')
def component(tmp_path_factory):
    path = Path(os.environ.get('A7R5_ASPECT_CP_INPUT',
        ROOT/'a7r5-qemu/runs/a7r5-lens-af-2qHo9T/default/cpapp-b.bin'))
    if not path.is_file():
        pytest.skip('需要已核对的 native24 整合 CP 输入')
    stock = path.read_bytes()
    elf = compile_cp(tmp_path_factory.mktemp('aspect-cp'))
    raw, receipt = apply_cp(stock, elf)
    reverse = bytearray(raw)
    for row in receipt['patches']:
        at, before = row['offset'], bytes.fromhex(row['before'])
        assert raw[at:at + len(before)].hex() == row['after']
        reverse[at:at + len(before)] = before
    assert reverse == stock
    with pytest.raises(ValueError, match='完整前像'):
        apply_cp(raw, elf)
    return raw, receipt


@pytest.fixture
def cp(component):
    raw, _ = component
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.mem_map(0x100000, 0x1b00000)
    cpu.mem_write(BASE, raw)
    cpu.mem_map(DATA, 0x50000)
    cpu.mem_write(POOL + 4, struct.pack('<I', 2))
    cpu.mem_write(POOL + 0x10, struct.pack('<II', TASK, 2*0x6688))
    return cpu


def run(cpu, start, stop, **registers):
    cpu.reg_write(ARM.UC_ARM_REG_SP, STACK)
    for key, value in registers.items():
        cpu.reg_write(getattr(ARM, f'UC_ARM_REG_{key.upper()}'), value)
    cpu.ctl_flush_tb()
    cpu.emu_start(start | 1, stop, count=30000)
    assert cpu.reg_read(ARM.UC_ARM_REG_PC) == stop
    assert cpu.reg_read(ARM.UC_ARM_REG_SP) == STACK


def bind(cpu, task, wire, request, caller=0xaf153b, primary=1, secondary=2):
    run(cpu, 0x33f322, 0x33f326, r1=wire, r5=GFW)
    cpu.mem_write(MANAGER, struct.pack('<I', request))
    cpu.mem_write(STACK + 0x404, struct.pack('<I', caller))
    run(cpu, 0xadf11e, 0xadf12c, r4=MANAGER, r6=GFW, r7=STACK + 0x400)
    cpu.mem_write(task + 0x5ae8, struct.pack('<I', request))
    run(cpu, 0xadd840, 0xadd84a, r4=task, r6=MANAGER + 0x28)
    cpu.mem_write(task + 0x5980, struct.pack('<I', primary))
    cpu.mem_write(task + 0x5988, struct.pack('<I', secondary))


def jpeg_geometry(cpu, task):
    cpu.mem_write(task + 0x5f78, FULL)
    run(cpu, 0x473554, 0x473566, r4=task, r5=0, r11=STACK + 0x30)
    assert bytes(cpu.mem_read(task + 0x5f78, len(FULL))) == FULL
    return GEOMETRY.unpack(cpu.mem_read(STACK + 0x40, len(FULL)))[2:4]


def test_original_boot_maps_executable_page_without_moving_page_table(cp, component):
    cp.mem_map(0x3e42000, 4096)
    cp.mem_write(STATE, bytes([0xcc])*512)
    cp.reg_write(ARM.UC_ARM_REG_SP, STACK)
    cp.emu_start(0x108398, 0x108728, count=5000000)
    assert cp.reg_read(ARM.UC_ARM_REG_PC) == 0x108728
    assert bytes(cp.mem_read(STATE, 512)) == bytes(512)
    for section in component[1]['sections']:
        assert digest(bytes(cp.mem_read(section['address'], section['bytes']))) == section['sha256']
    root = struct.unpack('<I', cp.mem_read(0x108f1c, 4))[0]
    page = 0x118000
    l1 = struct.unpack('<I', cp.mem_read(root+(page>>20)*4, 4))[0]
    assert l1 & 3 == 1
    l2 = struct.unpack('<I', cp.mem_read((l1&~1023)+((page>>12)&255)*4, 4))[0]
    assert l2 & 3 == 2 and (l2 & ~4095) == page


def test_requests_keep_their_ratios_across_selection_changes_and_reuse(cp):
    bind(cp, TASK, 0xe4, 47)
    bind(cp, TASK2, 0xe5, 48)
    assert jpeg_geometry(cp, TASK) == (9504, 4976)
    assert jpeg_geometry(cp, TASK2) == (9504, 4048)

    # 即便稍后菜单回到原厂比例，两张已绑定照片保持各自拍摄比例。
    run(cp, 0x33f322, 0x33f326, r1=3, r5=GFW)
    assert struct.unpack('<I', cp.mem_read(GFW + 0xcc, 4))[0] == 3
    assert jpeg_geometry(cp, TASK) == (9504, 4976)
    assert jpeg_geometry(cp, TASK2) == (9504, 4048)

    freed = []
    def native_free(cpu, at, _size, _user):
        if at == 0xae0992:
            freed.append(bytes(cpu.mem_read(STATE + 16, 2)))
            cpu.reg_write(ARM.UC_ARM_REG_PC, cpu.reg_read(ARM.UC_ARM_REG_LR))
    cp.hook_add(UC_HOOK_CODE, native_free, begin=0xae0992, end=0xae0992)
    run(cp, 0xae08da, 0xae08de, r0=POOL, r1=TASK)
    assert freed == [b'\x00\x09']
    assert jpeg_geometry(cp, TASK) == (9504, 6336)
    # 原生临时任务入口会调用相同复制函数，但不锁存自定义选择。
    bind(cp, TASK, 0xe4, 49, caller=0x4a2ab3)
    assert jpeg_geometry(cp, TASK) == (9504, 6336)
    bind(cp, TASK, 0xe4, 50, primary=2, secondary=0)
    assert jpeg_geometry(cp, TASK) == (9504, 6336)


def test_native_jpeg_requests_crop_main_scene_and_keep_thumbnail_canvas(cp):
    for ratio, wh, _ in CASES:
        bind(cp, TASK, 0xe0 + ratio - 4, 89 + ratio)
        assert jpeg_geometry(cp, TASK) == wh
    cp.mem_write(TASK+0x5fdc, SCENE)
    run(cp, 0x4729ee, 0x472a12, r4=TASK)
    assert GEOMETRY.unpack(cp.mem_read(STACK+0x38, GEOMETRY.size))[2:4] == (1616, 688)
    assert bytes(cp.mem_read(TASK+0x5fdc, GEOMETRY.size)) == SCENE

    pin = struct.Struct('<10H')
    cp.mem_write(STACK+0x70, pin.pack(1664, 1080, 0, 0, 1616, 1080, 0, 0, 1616, 1080))
    cp.mem_write(STACK+0xf8, pin.pack(160, 120, 0, 0, 160, 120, 0, 0, 160, 120))
    cp.mem_write(STACK+0x12c, bytes([0xc7])*0x20)
    run(cp, 0x46e07e, 0x46e082, r0=STACK+0x12c, r1=0x20, r4=TASK)
    assert pin.unpack(cp.mem_read(STACK+0x70, pin.size)) == (1664, 1080, 0, 196, 1616, 688, 0, 0, 1616, 688)
    assert pin.unpack(cp.mem_read(STACK+0xf8, pin.size)) == (160, 120, 0, 0, 160, 120, 0, 26, 160, 68)
    assert bytes(cp.mem_read(STACK+0x12c, 0x20)) == bytes(0x20)


def test_native_heif_notify_copies_only_heif_and_preserves_raw(cp, images):
    avcam = avcam_machine(images[1])
    def heif_packet(ratio, primary, broken=False):
        bind(cp, TASK, 0xe0 + ratio - 4, 57 + ratio,
             primary=4 if primary else 2, secondary=2 if primary else 4)
        data = bytearray([0x9d]*0x468)
        struct.pack_into('<II', data, 0, 2, 4)
        struct.pack_into('<IxxHH', data, 0x1b0, 4 if primary else 2, 9504, 6336)
        struct.pack_into('<IxxHH', data, 0x1bc, 2 if primary else 4, 9504, 6336)
        data[0x2b4:0x2c0] = FULL
        data[0x2d4:0x2e0] = SCENE
        data[0x2f4:0x300] = bytes(12) if broken else SCENE
        cp.mem_write(PACKET, bytes(data))
        cp.mem_write(TASK + 0x5b3c, bytes(data[0x1e8:0x444]))
        run(cp, 0xae78ae, 0xae78b2, r0=PACKET+0x1e8, r1=TASK+0x5b3c, r2=0x25c, r4=TASK)
        assert bytes(cp.mem_read(TASK+0x5b3c, 0x25c)) == data[0x1e8:0x444]
        return data, bytes(cp.mem_read(PACKET, 0x468))

    for ratio, wh, _ in CASES:
        for primary in (True, False):
            before, after = heif_packet(ratio, primary)
            field = 0x1b6 if primary else 0x1c2
            assert struct.unpack_from('<HH', after, field) == wh
            assert GEOMETRY.unpack_from(after, 0x2b4)[2:4] == wh
            changed = {i for i, (a,b) in enumerate(zip(before, after)) if a != b}
            expected = set(range(field, field + 4))
            for at in (0x2b4, 0x2d4, 0x2f4):
                expected.update(range(at + 4, at + 12))
            assert changed and changed <= expected
            # 将这份 CP 实际生成的消息交给 AVCAM 原生接收器。
            avcam.mem_write(PACKET, after)
            avcam.mem_write(AV_CONTEXT+0x81c, struct.pack('<I', 1))
            for i, value in ((19, AV_CONTEXT), (20, PACKET), (21, AV_CONTEXT+0x3bc)):
                avcam.reg_write(getattr(ARM64, f'UC_ARM64_REG_X{i}'), value)
            avcam.emu_start(AV_BASE+0x1f3c10, AV_BASE+0x1f3c4c, count=1000)
            assert avcam.reg_read(ARM64.UC_ARM64_REG_PC) == AV_BASE+0x1f3c4c
            assert bytes(avcam.mem_read(AV_CONTEXT+0x3bc, 36)) == b''.join(
                after[at:at+12] for at in (0x2b4, 0x2d4, 0x2f4))
    before, after = heif_packet(9, True, broken=True)
    assert before == after
