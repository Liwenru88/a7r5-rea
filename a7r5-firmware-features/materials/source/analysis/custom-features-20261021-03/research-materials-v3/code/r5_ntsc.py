"""A7R5 4.00 派生 AP 的两处目标 NTSC 提示补丁；仅本机普通文件。"""
from __future__ import annotations

import hashlib
import struct

AP_SHA = '8ee4d5876b7e127df39f8f820b9d21834c300ff895e02ca522636ed4733efc4b'
AP_BYTES = 97368304
# 由本机 A7R5 的 NPAL 日志引用和启动分支重新定位，未套用 A7C II 地址。
WINDOWS = ((0x20c99a4, 0x20c99c0), (0x20c9ea4, 0x20c9ecc))
BEFORE = bytes.fromhex('226f8052')  # mov w2,#0x379


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def branch(at, target):
    distance = target - at
    if distance % 4 or not -(1 << 27) <= distance < (1 << 27):
        raise ValueError('分支目标越界或未对齐')
    return struct.pack('<I', 0x14000000 | ((distance // 4) & 0x3ffffff))


def patch(raw):
    if len(raw) != AP_BYTES or sha(raw) != AP_SHA:
        raise ValueError('仅接受已构建并用于自定义 4.04 的精确 A7R5 AP')
    result = bytearray(raw)
    rows = []
    for at, target in WINDOWS:
        if raw[at:at + 4] != BEFORE:
            raise ValueError('NTSC 提示指令前像不符')
        after = branch(at, target)
        result[at:at + 4] = after
        rows.append({'offset': at, 'target': target, 'before': BEFORE.hex(),
                     'after': after.hex(), 'purpose': '仅在已选中 0x379 后进入原生后续分支'})
    inverse = bytearray(result)
    for row in rows:
        at = row['offset']
        inverse[at:at + 4] = bytes.fromhex(row['before'])
    if inverse != raw:
        raise ValueError('反向重建不一致')
    return bytes(result), {'model': 'ILCE-7RM5', 'firmware_base': '4.00',
        'custom_ap_baseline': '4.04 FL23', 'source_sha256': sha(raw),
        'target_sha256': sha(result), 'bytes': len(raw), 'patches': rows,
        'inverse_verified': True, 'camera_verified': False,
        'ntsc_message_id': '0x379', 'pal_message_id': '0x381',
        'changes_video_system_setting': False}


def replay(raw, *, path, region, current, default, reset, boot, display, other):
    """执行真实启动条件指令；锁和属性 getter 明确替代，不执行整机启动。"""
    from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE, UC_HOOK_MEM_WRITE
    from unicorn import arm64_const as reg
    u = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    u.mem_map(0x20c9000, 0x2000)
    u.mem_write(0x20c9000, raw[0x20c9000:0x20cb000])
    u.mem_map(0x70000000, 0x10000)
    fp = 0x70004000
    u.reg_write(reg.UC_ARM64_REG_X29, fp)
    u.reg_write(reg.UC_ARM64_REG_SP, fp)
    for offset, value in [(0xc8, region), (0xcc, current), (0xd0, default),
                          (0xbc, reset), (0xb0, boot)]:
        u.mem_write(fp + offset, struct.pack('<I', value))
    for index, value in [(19, fp + 0xe0), (20, fp + 0xd0),
                         (21, 0x70008000), (24, 0x390), (26, other), (28, other)]:
        u.reg_write(getattr(reg, 'UC_ARM64_REG_X' + str(index)), value)
    display_ptr = 0x70009000
    u.mem_write(display_ptr, struct.pack('<I', display))
    calls = {0x20c9960: None, 0x20c9964: display_ptr, 0x20c9970: None,
             0x20c9e6c: None, 0x20c9e70: display_ptr, 0x20c9e7c: None}
    fallback = 0x20c99c0 if path == 0 else 0x20c9ecc
    commits = {0x20c96e4, 0x20c9ba0}
    outcome, trace, writes = {}, [], []

    def code(emu, address, size, _):
        trace.append(address)
        if address == fallback:
            outcome['kind'] = 'native_continue'
            emu.emu_stop()
        elif address in commits:
            outcome.update(kind='selection', message_id=emu.reg_read(reg.UC_ARM64_REG_X2))
            emu.emu_stop()
        elif address == 0x20c9988 or address == 0x20c9e94:
            outcome['kind'] = 'invalid_enum_diagnostic'
            emu.emu_stop()
        elif address in calls:
            if calls[address] is not None:
                emu.reg_write(reg.UC_ARM64_REG_X0, calls[address])
            emu.reg_write(reg.UC_ARM64_REG_PC, address + 4)

    u.hook_add(UC_HOOK_CODE, code)
    u.hook_add(UC_HOOK_MEM_WRITE, lambda _, access, address, size, value, data: writes.append((address, size)))
    u.emu_start(0x20c9938 if path == 0 else 0x20c9e48, 0x20ca000, count=160)
    if not outcome or writes:
        raise AssertionError('启动窗口未正常收敛，或发生了预期外内存写入')
    registers = [u.reg_read(getattr(reg, 'UC_ARM64_REG_X' + str(i))) for i in range(29)]
    return outcome, trace, registers


def validate(before, after):
    import itertools
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
    decoder = Cs(CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN)
    for at, target in WINDOWS:
        instruction = list(decoder.disasm(after[at:at + 4], at))
        if len(instruction) != 1 or instruction[0].mnemonic != 'b' or instruction[0].op_str != f'#{target:#x}':
            raise AssertionError('独立反汇编与分支编码不一致')
    counts = {'native_cases': 0, 'ntsc_removed': 0, 'non_ntsc_trace_registers_identical': 0}
    for values in itertools.product(range(2), range(2), range(3), range(2), range(2), range(4), range(2), range(2)):
        keys = ('path', 'region', 'current', 'default', 'reset', 'boot', 'display', 'other')
        params = dict(zip(keys, values))
        old = replay(before, **params)
        new = replay(after, **params)
        counts['native_cases'] += 1
        if old[0].get('message_id') == 0x379:
            if new[0] != {'kind': 'native_continue'}:
                raise AssertionError('目标 NTSC 提示未进入原生后续分支')
            counts['ntsc_removed'] += 1
        else:
            if old != new:
                raise AssertionError('非 NTSC 路径发生变化：' + str(params))
            counts['non_ntsc_trace_registers_identical'] += 1
    if not counts['ntsc_removed']:
        raise AssertionError('测试没有实际触及目标提示')
    return dict(counts, full_boot_executed=False, ui_rendered=False, external_calls='显式替代锁、getter及解锁',
                camera_io=False)
