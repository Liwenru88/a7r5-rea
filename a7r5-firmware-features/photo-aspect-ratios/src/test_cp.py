"""执行已补丁的原生 CP 入口，区分任务数据夹具与实际固件指令。"""

import json
import os
from pathlib import Path
import struct

import pytest
from unicorn import Uc, UC_ARCH_ARM, UC_HOOK_CODE, UC_MODE_ARM
from unicorn import arm_const as ARM, arm64_const as ARM64

from build_cp import BASE, STOCK, apply_cp, compile_cp, digest
from test_avcam import BASE as AV_BASE, CONTEXT as AV_CONTEXT, images, machine as avcam_machine, stock_avcam
from test_geometry import CASES, DATA, ENCODE_SIZES, GEOMETRY, ROOT, STACK


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
    lens = None
    if folder := os.environ.get('A7R5_ASPECT_CAPTURE'):
        folder = Path(folder)
        build = json.loads((folder / 'build.json').read_text())
        receipt = build['CP_aspect']
        lens = build.get('CP_lens_af')
        raw = (folder / 'cpapp-b.bin').read_bytes()
        assert digest(raw) == build['CP_sha256']
    else:
        elf = compile_cp(tmp_path_factory.mktemp('aspect-cp'), stock=digest(stock) == STOCK)
        raw, receipt = apply_cp(stock, elf)
    reverse = bytearray(raw)
    for proof in ([lens, receipt] if lens else [receipt]):
        assert digest(reverse) == proof['target_sha256']
        for row in proof['patches']:
            at, before = row['offset'], bytes.fromhex(row['before'])
            assert reverse[at:at + len(before)].hex() == row['after']
            reverse[at:at + len(before)] = before
        assert digest(reverse) == proof['source_sha256']
    assert reverse == stock
    with pytest.raises(ValueError, match='完整前像'):
        apply_cp(raw, b'')
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


def jpeg_geometry(cpu, task, geometry=FULL):
    cpu.mem_write(task + 0x5f78, geometry)
    run(cpu, 0x473554, 0x473566, r4=task, r5=0, r11=STACK + 0x30)
    assert bytes(cpu.mem_read(task + 0x5f78, len(geometry))) == geometry
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
    assert jpeg_geometry(cp, TASK) == (9504, 4976)


def test_native_capture_clone_inherits_frozen_ratio_and_clears_reused_destination(cp):
    bind(cp, TASK, 0xe5, 47)
    bind(cp, TASK2, 0xe4, 48)

    def clone(source, destination):
        payload = bytes(cp.mem_read(source + 0x20, 0x1ec))
        run(cp, 0xaddd4e, 0xaddd5e, r8=source, r11=destination + 4)
        assert bytes(cp.mem_read(destination + 0x20, len(payload))) == payload
        assert cp.reg_read(ARM.UC_ARM_REG_R0) == destination + 0x20

    # 当前菜单与源任务的比例不同，复制时仍继承源任务。
    clone(TASK, TASK2)
    assert jpeg_geometry(cp, TASK2) == (9504, 4048)

    # 普通 3:2 的原生比例值和自定义任务的基底值相同。
    bind(cp, TASK, 2, 49)
    clone(TASK, TASK2)
    assert jpeg_geometry(cp, TASK2) == (9504, 6336)


def test_native_jpeg_requests_crop_main_scene_and_keep_thumbnail_canvas(cp):
    for (width, height), sizes in ENCODE_SIZES.items():
        geometry = GEOMETRY.pack((width + 127) & ~127, height + 8, width, height, 0, 0)
        for index, size in enumerate(sizes):
            bind(cp, TASK, 0xe0 + index, 89 + index)
            assert jpeg_geometry(cp, TASK, geometry) == size
    # 场景图和缩略图仍采用与 L 主图一致的最后一档。
    jpeg_geometry(cp, TASK)
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


def test_native_heif_copy_keeps_shared_yc_and_notifies_only_heif_slot(cp, images, component):
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
        assert bytes(cp.mem_read(PACKET, 0x468)) == data
        cp.mem_write(TASK + 0x5f78, FULL)
        # 原生复制不再裁共享区域；Notify 仅更新格式 4 的输出尺寸。
        helper = component[1]['symbols']['r5_cp_notify_jpeg']
        for field, kind in ((0x1b6, 4 if primary else 2), (0x1c2, 2 if primary else 4)):
            run(cp, helper, DATA + 0x48000, r0=PACKET+field, r1=TASK, r2=kind, lr=(DATA+0x48000)|1)
        return data, bytes(cp.mem_read(PACKET, 0x468))

    for ratio, wh, _ in CASES:
        for primary in (True, False):
            before, after = heif_packet(ratio, primary)
            field = 0x1b6 if primary else 0x1c2
            assert struct.unpack_from('<HH', after, field) == wh
            assert GEOMETRY.unpack_from(after, 0x2b4)[2:4] == (9504, 6336)
            changed = {i for i, (a,b) in enumerate(zip(before, after)) if a != b}
            expected = set(range(field, field + 4))
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
    assert before[0x2b4:] == after[0x2b4:]


def test_raw_emb_header_uses_frozen_task_and_changes_only_jpeg_dimensions(cp):
    header = DATA + 0x28000
    stop = DATA + 0x48000
    calls = []
    def native_header(cpu, *_):
        calls.append((cpu.reg_read(ARM.UC_ARM_REG_R0), cpu.reg_read(ARM.UC_ARM_REG_R1),
                      cpu.reg_read(ARM.UC_ARM_REG_R2)))
        cpu.reg_write(ARM.UC_ARM_REG_R0, 0xabc)
        cpu.reg_write(ARM.UC_ARM_REG_PC, cpu.reg_read(ARM.UC_ARM_REG_LR))
    cp.hook_add(UC_HOOK_CODE, native_header, begin=0xade83c, end=0xade83c)
    for id, wh, _ in CASES:
        bind(cp, TASK, 0xe0 + id - 4, 200 + id, primary=2, secondary=0)
        cp.mem_write(TASK + 0x234, struct.pack('<HH', 9504, 6336))
        original = bytes([0x5a]) * 0x15000
        cp.mem_write(header, original)
        run(cp, 0x48a00a, 0x48a00e, r0=PACKET, r1=header, r2=TASK)
        result = bytes(cp.mem_read(header, len(original)))
        expected = bytearray(original)
        struct.pack_into('<II', expected, 0x14a2c, *wh)
        assert result == expected
        assert cp.reg_read(ARM.UC_ARM_REG_R0) == 0xabc
    assert calls == [(PACKET, header, TASK)] * 6


def test_custom_aspect_keeps_native_focus_domain_and_full_source_task_unchanged(cp):
    # 实时取景仍是原厂完整源上的遮罩，AF/MF 不接收私有枚举或缩放后的任务坐标。
    for id, _, _ in CASES:
        for primary, secondary in ((1, 2), (2, 0), (4, 2)):
            bind(cp, TASK, 0xe0 + id - 4, 300 + id, primary=primary, secondary=secondary)
            cp.mem_write(TASK + 0x5f78, FULL)
            cp.mem_write(TASK + 0x5fdc, SCENE)
            before = bytes(cp.mem_read(TASK, 0x6688))
            jpeg_geometry(cp, TASK)
            assert bytes(cp.mem_read(TASK, 0x6688)) == before
            assert struct.unpack('<I', cp.mem_read(GFW + 0xcc, 4))[0] == 2
            assert struct.unpack('<I', cp.mem_read(TASK + 0x24, 4))[0] == 2


def test_full_native_raw_header_producer_matches_except_eight_emb_dimension_bytes(cp):
    header = DATA + 0x28000
    stop = DATA + 0x48000
    seen = []
    def external(core, pc, *_):
        if pc in (0xade83c, 0xadd162, 0x45b0c0, 0x45acbc): seen.append(pc)
        if pc == 0x4e9304:
            # 附加参数服务返回空；完整 RAW 头和尺寸仍由原生函数生成。
            core.mem_write(core.reg_read(ARM.UC_ARM_REG_R1), bytes(2))
            core.reg_write(ARM.UC_ARM_REG_R0, 0)
            core.reg_write(ARM.UC_ARM_REG_PC, core.reg_read(ARM.UC_ARM_REG_LR))
        if pc == 0xb0de92: raise AssertionError('原生 RAW 头进入诊断拒绝')
    cp.hook_add(UC_HOOK_CODE, external)
    from aspect_sizes import crop
    for id, _, _ in CASES:
        for full in ENCODE_SIZES:
            for formats in ((2, 0), (1, 2), (2, 4), (4, 2)):
                for raw_type in (0, 3):
                    cp.mem_write(TASK, bytes(0x6688))
                    bind(cp, TASK, 0xe0 + id - 4, 400 + id, primary=formats[0], secondary=formats[1])
                    for offset in (0x30, 0x234): cp.mem_write(TASK + offset, struct.pack('<HH', *full))
                    cp.mem_write(TASK + 0x6072, struct.pack('<HH', 32, 20))
                    cp.mem_write(TASK + 0x38, struct.pack('<I', 1))
                    cp.mem_write(TASK + 0x726, b'\x0e')
                    cp.mem_write(TASK + (0x5984 if formats[0] == 2 else 0x598c),
                                 bytes((raw_type, 0 if raw_type == 0 else 2)))
                    # 当前菜单已经改变，本张头仍使用任务锁存的旧比例。
                    run(cp, 0x33f322, 0x33f326, r1=3, r5=GFW)
                    ptr = header + int(bool(raw_type))
                    task_before = bytes(cp.mem_read(TASK, 0x6688))
                    cp.mem_write(header, bytes([0xa5]) * 0x18000)
                    run(cp, 0xade83c, stop, r0=TASK + 0x5b3c, r1=ptr, r2=TASK, lr=stop | 1)
                    native_result = cp.reg_read(ARM.UC_ARM_REG_R0)
                    native = bytes(cp.mem_read(ptr, 0x15000))
                    cp.mem_write(header, bytes([0xa5]) * 0x18000)
                    seen.clear()
                    run(cp, 0x48a00a, 0x48a00e, r0=TASK + 0x5b3c, r1=ptr, r2=TASK)
                    after = bytes(cp.mem_read(ptr, 0x15000))
                    assert cp.reg_read(ARM.UC_ARM_REG_R0) == native_result
                    assert seen == [0xade83c, 0xadd162, 0x45b0c0, 0x45acbc]
                    assert after[:0x14a2c] == native[:0x14a2c] and after[0x14a34:] == native[0x14a34:]
                    assert struct.unpack_from('<II', after, 0x14a2c) == crop(id, full)
                    assert bytes(cp.mem_read(TASK, 0x6688)) == task_before
                    assert bytes(cp.mem_read(ptr + 0x15000, 16)) == bytes([0xa5]) * 16
