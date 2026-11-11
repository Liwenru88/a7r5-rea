"""回放真实 AP 遮罩调用，核对原生矩形和控件生命周期。"""

import io
import struct

import pytest
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_HOOK_CODE, UC_MODE_ARM
from unicorn import arm64_const as R

from test_ap import SELECTION, ap_image  # noqa: F401


@pytest.fixture
def replay(ap_image):
    base = 0x10000000
    work = 0x60000000
    core = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    core.mem_map(base, 0x9000000)
    core.mem_map(work, 0x400000)
    for segment in ELFFile(io.BytesIO(ap_image)).iter_segments():
        if segment['p_type'] == 'PT_LOAD' and segment['p_filesz']:
            core.mem_write(base + segment['p_vaddr'], segment.data())
    stop, stack = work + 0x3e0000, work + 0x3f0000

    def reg(i, value=None):
        r = getattr(R, f'UC_ARM64_REG_X{i}')
        if value is None:
            return core.reg_read(r)
        core.reg_write(r, value)

    def get(address, fmt='I'):
        return struct.unpack('<'+fmt, core.mem_read(address, struct.calcsize('<'+fmt)))[0]

    def put(address, value, fmt='I'):
        core.mem_write(address, struct.pack('<'+fmt, value))

    def execute(at, *args, end=None):
        for i, value in enumerate(args):
            reg(i, value)
        core.reg_write(R.UC_ARM64_REG_SP, stack)
        core.reg_write(R.UC_ARM64_REG_LR, stop)
        until = end if end is not None else stop
        core.emu_start(base+at, until, count=200000)
        assert core.reg_read(R.UC_ARM64_REG_PC) == until
        assert core.reg_read(R.UC_ARM64_REG_SP) == stack
        return reg(0)

    def hook(address, call):
        def run(*_):
            result = call()
            if result is not None:
                reg(0, result)
            core.reg_write(R.UC_ARM64_REG_PC, core.reg_read(R.UC_ARM64_REG_LR))
        core.hook_add(UC_HOOK_CODE, run, begin=address, end=address)

    return core, base, work, reg, get, put, execute, hook


@pytest.mark.parametrize('create,rotate,produce,table,count,row,portrait', [
    (0x1d9ba18, 0x1d1574c, 0x1d9bb74, 0x4125d78, 585, 4, False),
    (0x1e179e0, 0x1d15664, 0x1e17b1c, 0x4039480, 442, 3, True),
])
def test_guide_native_masks_follow_selection_and_recreated_view(
        replay, create, rotate, produce, table, count, row, portrait):
    core, base, work, reg, get, put, execute, hook = replay
    view, flags, frame, factory = (work + n for n in (0, 0x30000, 0x40000, 0x60000))
    arena, widget2 = work+0x80000, work+0x82000
    sprites, sprite_vtable = work+0x90000, work+0x92000
    widget = arena
    put(view, base+0x5783098, 'Q')
    put(view+0x3e98, arena, 'Q')
    put(view+0x3ea0, 0x200000)
    pattern = bytearray(i%3 != 0 for i in range(count))
    pattern[row] = 1
    core.mem_write(flags, bytes(pattern))
    initial_flag = 1
    seen_flags = []
    paints = {}
    shown = []
    original_draw = []
    destroyed = []
    heap = work+0x2d0000

    def allocate():
        nonlocal heap
        start = heap
        heap += (reg(0)+15)&~15
        assert heap < work+0x350000
        return start

    def unit_divisor():
        assert core.reg_read(R.UC_ARM64_REG_S0) == 0x3f800000
        return reg(0)

    def memset():
        core.mem_write(reg(0), bytes([reg(1)&255])*reg(2))
        return reg(0)

    def no_rehash():
        assert reg(2)+reg(3) <= reg(1)
        reg(1, 0)
        return 0

    hook(base+0x23da254, unit_divisor)
    # 夹具用较大的桶表代替 libstdc++ 的同等哈希容量策略。
    hook(base+0x16d9b00, lambda: 2*reg(1)+1)
    hook(base+0x16dacb0, no_rehash)
    hook(base+0x16d95f0, memset)
    hook(base+0x16dc130, allocate)
    hook(base+0x16d9870, lambda: None)

    def fake_factory():
        seen_flags.append(get(flags+row, 'B'))
        if get(flags+row, 'B') == 0:
            put(view+0x3ec8+8*row, widget, 'Q')
            put(view+0x10+16*row, 0x3d)
            put(view+0x18+16*row, widget+0x1d8, 'Q')
            put(widget, base+0x57836a0, 'Q')

    def paint():
        index = (reg(0)-sprites)//0x100
        parameter = reg(0)+0x20
        rect = struct.unpack('<4i', core.mem_read(parameter+0x18, 16))
        paints[index] = get(parameter+0x2c, 'B'), rect

    hook(factory, fake_factory)
    for off, callback in ((0x140, lambda: reg(0)+0x20), (0x148, lambda: None), (0x150, paint)):
        call = factory+off
        put(sprite_vtable+off, call, 'Q')
        hook(call, callback)
    hook(base+0x182e13c, lambda: original_draw.append(reg(0)))
    hook(base+0x182e1b0, lambda: destroyed.append(reg(0)))
    # 夹具跳过销毁和原厂绘制的设备调用，并撤销被重放的原厂入口压栈。
    def undo_native_prologue(cpu, *_):
        address = cpu.reg_read(R.UC_ARM64_REG_SP)
        saved = struct.unpack('<2Q', core.mem_read(address, 16))
        cpu.reg_write(R.UC_ARM64_REG_SP, address+32)
        cpu.reg_write(R.UC_ARM64_REG_X29, saved[0])
    for at in (0x182e13c, 0x182e1b0):
        core.hook_add(UC_HOOK_CODE, undo_native_prologue, begin=base+at, end=base+at)
    # 原厂控制函数为虚调用。仅替换夹具里的显示／隐藏出口。
    put(base+0x57836a0+0x30, factory+4, 'Q')
    put(base+0x57836a0+0x190, base+0x182cb74, 'Q')
    put(base+0x57836a0+0x1a0, base+0x182cb8c, 'Q')
    hook(factory+4, lambda: shown.append(reg(1)))

    def create_at(at):
        execute(at, view, 0, base+table, count, 0, flags, 0, 0, factory, end=base+at+4)

    cursor = work+0xb0000
    sizes = {}
    for i, disabled in enumerate(pattern):
        type_id = get(base+table+52*i)
        disabled = bool(disabled and i != row)
        key = type_id, disabled
        if key not in sizes:
            factories = 0x50210e0 if disabled else 0x5020be8
            constructor = get(base+factories+8*type_id, 'Q')
            put(cursor, 0)
            # 原厂工厂用空基址做容量探测，不构造对象。
            execute(constructor, 0x400000, 0, cursor, cursor+16, cursor+32)
            sizes[key] = get(cursor)
            assert sizes[key] > 0 and sizes[key] % 128 == 0
    capacity = sum(sizes[(get(base+table+52*i), bool(flag and i != row))]
                   for i, flag in enumerate(pattern))
    put(view+0x3ea0, capacity)
    create_at(create)
    assert seen_flags == [1]  # 容量不足时保持原厂禁用标志。
    put(view+0x3ea0, capacity+128)
    create_at(create)
    assert seen_flags == [1, 0] and get(flags+row, 'B') == initial_flag

    def prepare():
        put(widget+0x204, 1, 'B')
        put(widget+0x21c, 1, 'B')
        put(widget+0x1d4, int(portrait))
        put(widget+0x218, 1)
        put(widget+0x220, 1)
        put(widget+0x224, 12)
        core.mem_write(widget+0x208, struct.pack('<4i', 20, 40, 600, 400))
        for i in range(8):
            sprite = sprites+i*0x100
            put(sprite, sprite_vtable, 'Q')
            put(widget+0x1a68+i*8, sprite, 'Q')

    def produce_frame():
        execute(produce, 0, widget+0x1d8, 0, frame, end=base+produce+4)

    put(frame, 1)  # 原厂屏蔽这一路，须只对当前登记对象打开。
    put(frame+0x24d8, 2)
    for offset, value in zip((0x2500, 0x2520, 0x2540, 0x2560), (20, 40, 600, 400)):
        put(frame+offset, value)
    # 保留前置的原厂标志，使未登记控件在短路路径清除可见。
    put(frame+0x25a0, 1)
    put(base+SELECTION, 0x109)
    prepare()
    execute(0x182e138, widget)
    assert shown == [3] and not paints
    produce_frame()
    assert get(widget+0x21c, 'B') == 1
    old_style = get(widget+0x224)
    execute(0x182e138, widget)
    assert shown[-1] == 2 and len(paints) == 8 and get(widget+0x224) == old_style
    assert paints[2][0] == paints[3][0] == 1
    expected = ((368, 20, 72, 600), (40, 20, 72, 600)) if portrait else (
        (20, 40, 600, 72), (20, 368, 600, 72))
    assert (paints[2][1], paints[3][1]) == expected
    assert tuple(struct.unpack('<4i', core.mem_read(widget+0x208, 16))) == (20, 40, 600, 400)

    # 只补静态型号列 16；曝光/输出/其他模式列仍服从原厂拒绝。
    presenter = work + 0x100000
    family = count == 442
    cap = 0x2156e70 if family else 0x2146224
    column = 0x478c0 if family else 0x4ff14
    snapshot = presenter + (0x15b0 if family else 0x1780)
    put(snapshot + 0x24d8, 2)
    put(presenter + (0x1e0 if family else 0x270), view + 0x10, 'Q')
    allowed = [0]
    hook(base + cap + 4, lambda: allowed[0])
    for value, result in ((15, 0), (16, 1), (17, 0)):
        put(presenter + column, value)
        assert execute(cap, presenter, row) == result
    allowed[0] = 1
    assert execute(cap, presenter, row) == 1
    allowed[0] = 0

    # 所有六档均执行原厂遮罩与方向变换；源坐标不被覆盖，边界留在画布内。
    from fractions import Fraction
    from aspect_sizes import RATIOS
    for id in range(4, 10):
        put(base + SELECTION, 0x100 | id)
        prepare()
        produce_frame()
        paints.clear()
        execute(0x182e138, widget)
        proportion = Fraction(*RATIOS[id])
        fmt = get(widget + 0x218)
        pixel = (Fraction(4, 3), Fraction(3, 2), Fraction(16, 9), Fraction(4, 3))[fmt]
        effective = proportion * Fraction(4, 3) / pixel
        horizontal = effective >= Fraction(3, 2)
        thickness = (400 - 600 / effective) / 2 if horizontal else (600 - 400 * effective) / 2
        active = [rect for index, (visible, rect) in paints.items()
                  if index < 4 and visible and rect[2] and rect[3]]
        assert len(active) == 2
        for x, y, w, h in active:
            assert x >= 0 and y >= 0 and w > 0 and h > 0
            assert x + w <= (480 if portrait else 640)
            assert y + h <= (640 if portrait else 480)
            actual = w if horizontal == portrait else h
            assert abs(Fraction(actual) - thickness) <= 1
        assert tuple(struct.unpack('<4i', core.mem_read(widget + 0x208, 16))) == (20, 40, 600, 400)
    put(base + SELECTION, 0x109)

    # 同一比例在重选后序号不同，绘制不能用上一次快照。
    put(base+SELECTION, 0x309)
    paints.clear()
    execute(0x182e138, widget)
    assert shown[-1] == 3 and not paints
    execute(0x182e1ac, widget)
    assert destroyed == [widget]
    widget = widget2
    create_at(rotate)
    assert seen_flags[-1] == 0 and get(flags+row, 'B') == initial_flag
    prepare()
    execute(0x182e138, widget)
    assert shown[-1] == 3 and not paints
    produce_frame()
    execute(0x182e138, widget)
    assert shown[-1] == 2 and len(paints) == 8
    put(frame+0x24d8, 4)  # 录像保持原厂分支。
    paints.clear()
    produce_frame()
    execute(0x182e138, widget)
    assert shown[-1] == 3 and not paints
    execute(0x182e138, arena)
    assert original_draw == [arena]
    put(flags+row, 0, 'B')
    create_at(rotate)
    produce_frame()
    execute(0x182e138, widget)
    assert original_draw == [arena, widget]
