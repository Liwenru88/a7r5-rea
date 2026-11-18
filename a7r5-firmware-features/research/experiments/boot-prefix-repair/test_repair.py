"""用实际 4.19 CP 检查前缀入口及启动前后可观察状态。"""
import hashlib
import os
from pathlib import Path
import struct

import pytest
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm_const as ARM

from repair import repair_cp

ROOT = Path(__file__).resolve().parents[3]
BASE = 0x108000
SOURCE = ROOT / 'a7r5-fastboot/private/cases/recovered-vs-419-20261114/failed419/nflasha8/cpapp-b.bin'
SOURCE_SHA = '745c63742b525f8700142ad310b6f3ec848015aec60044bc19b69cc458d6c441'
CALL = 0x1086d0
PREFIX_LIMIT = BASE + (5 << 20)
NEW = 0x109200


@pytest.fixture(scope='module')
def original():
    raw = Path(os.environ.get('A7R5_CP_REPAIR_SOURCE', SOURCE)).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == SOURCE_SHA
    return raw


def arm_bl_target(raw, address):
    instruction, = struct.unpack_from('<I', raw, address - BASE)
    assert instruction >> 24 == 0xeb
    immediate = instruction & 0xffffff
    if immediate & 0x800000:
        immediate -= 1 << 24
    return address + 8 + 4 * immediate


def test_pre_mmu_helper_is_available_in_boot_prefix(original):
    candidate = repair_cp(original)
    target = arm_bl_target(candidate, CALL)
    assert BASE <= target < PREFIX_LIMIT
    assert target == NEW
    # 原 helper 的两个外部调用仍进入原映射器；内部循环的相对距离保持。
    assert arm_bl_target(candidate, NEW + 4) == 0x109000
    assert arm_bl_target(candidate, NEW + 0x24) == 0x108768
    assert len(candidate) == len(original)
    changed = {i for i, (a, b) in enumerate(zip(original, candidate)) if a != b}
    permitted = set(range(CALL - BASE, CALL - BASE + 4)) | set(range(NEW - BASE, NEW - BASE + 0x50))
    assert changed and changed <= permitted


def replay(raw, mode, stack):
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    cpu.mem_map(0x100000, 0x1b00000)
    cpu.mem_write(BASE, raw)
    cpu.mem_write(0x1a3ad80, b'\xcc' * 512)
    cpu.mem_map(0x3000000, 0x50000)
    cpu.mem_map(0x3e42000, 4096)
    cpu.mem_write(0x3e42000, bytes([mode]))
    # 这是明确提供的 NOR 内存替身，不等同于执行 NOR 硬件驱动。
    cpu.mem_map(0xd0200000, (len(raw) + 4095) & ~4095)
    cpu.mem_write(0xd0200000, raw)
    cpu.reg_write(ARM.UC_ARM_REG_SP, stack)
    minimum = stack
    visited = set()
    def trace(core, address, _size, _user):
        nonlocal minimum
        minimum = min(minimum, core.reg_read(ARM.UC_ARM_REG_SP))
        visited.add(address)
    cpu.hook_add(UC_HOOK_CODE, trace)
    cpu.emu_start(0x108398, 0x108728, count=5000000)
    assert cpu.reg_read(ARM.UC_ARM_REG_PC) == 0x108728
    root, = struct.unpack('<I', cpu.mem_read(0x108f1c, 4))
    assert root == 0x1a3c000
    assert bytes(cpu.mem_read(0x1a3ad80, 512)) == bytes(512)
    state = {
        'registers': tuple(cpu.reg_read(getattr(ARM, 'UC_ARM_REG_' + name))
                           for name in [*(f'R{i}' for i in range(13)), 'SP', 'LR', 'CPSR']),
        'page_tables': bytes(cpu.mem_read(root, 0x8000)),
        'private_runtime': bytes(cpu.mem_read(0x1a3a000, 0x2000)),
    }
    return state, minimum, visited


@pytest.mark.parametrize('mode', [0, 1])
@pytest.mark.parametrize('stack', [0x109f20, 0x3018000])
def test_relocated_helper_preserves_boot_outputs(original, mode, stack):
    before, _, _ = replay(original, mode, stack)
    after, minimum, visited = replay(repair_cp(original), mode, stack)
    assert NEW in visited
    assert 0xbef7c0 not in visited
    assert minimum >= NEW + 0x50 + 0x100
    assert before == after


@pytest.mark.parametrize('bad', [b'', b'\0' * 1024], ids=['empty', 'wrong-image'])
def test_unknown_cp_is_rejected(bad):
    with pytest.raises(ValueError, match='前像'):
        repair_cp(bad)
