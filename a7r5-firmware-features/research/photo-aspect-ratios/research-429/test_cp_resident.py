"""验证 4.29 常驻 CP 纵横比补丁，包含 lateMMU 卸载 [0, 0x128000) 后的全钩子 Unicorn 仿真。"""
import hashlib
from pathlib import Path
import struct
import sys

import pytest
from unicorn import Uc, UC_ARCH_ARM, UC_MODE_ARM, UC_MODE_THUMB
from unicorn import arm_const as R

HERE = Path(__file__).resolve().parent
FEATURES = HERE.parents[1]
sys.path.insert(0, str(HERE))
import cp_resident

CP_428 = FEATURES / 'builds/4.28-427-af-debounce-20261117/verify-runtime-20261117/runtime/cpapp-b.bin'
BASE = 0x108000
STOP = 0x1100000


@pytest.fixture(scope='module')
def patched_cp(tmp_path_factory):
    work = tmp_path_factory.mktemp('cp429')
    raw = CP_428.read_bytes()
    src_sha = hashlib.sha256(raw).hexdigest()
    elf = cp_resident.compile_resident_cp(work / 'compile')
    candidate, proof = cp_resident.apply_resident_cp(raw, elf, source_sha=src_sha)
    return raw, candidate, proof


def test_resident_cp_builds_within_text_safe_zone(patched_cp):
    raw, candidate, proof = patched_cp
    assert len(candidate) == len(raw)
    assert proof['code_bytes'] <= proof['code_capacity']
    assert proof['inverse_exact'] is True
    assert proof['late_mmu_safe'] is True


def test_tail_curves_boot_copy_and_late_mmu_unmap_survives_all_hooks(patched_cp):
    raw, candidate, proof = patched_cp
    cpu = Uc(UC_ARCH_ARM, UC_MODE_ARM)
    # 映射 0x100000..0x1b00000
    cpu.mem_map(0x100000, 0x1a00000)
    cpu.mem_write(BASE, candidate)

    # 1. 验证 matrix_boot_copy (0x108f8c) 将 4608 字节（含 0xbefb80/0xbefdc0 曲线）搬迁到 0x1a39b80..0x1a3ad80
    cpu.mem_write(0x1a30000, struct.pack('<II', 0x1a30000, 0x1a30000))
    cpu.reg_write(R.UC_ARM_REG_R4, 0x1a30000)
    cpu.reg_write(R.UC_ARM_REG_SP, 0x1a30000)
    cpu.reg_write(R.UC_ARM_REG_LR, STOP)
    cpu.emu_start(0x108f8c | 1, STOP, count=200000)
    assert cpu.reg_read(R.UC_ARM_REG_PC) == STOP
    assert bytes(cpu.mem_read(0x1a39b80, 1152)) == raw[0xbefb80 - BASE:0xbf0000 - BASE]
    assert bytes(cpu.mem_read(0x1a3a000, 3456)) == raw[0x11d4000 - BASE:0x11d4000 - BASE + 3456]

    # 2. 模拟 A7R5 CP lateMMU 完成：彻底卸载 [0x100000, 0x128000)！
    cpu.mem_unmap(0x100000, 0x28000)

    # 验证未卸载区 [0x128000, ...) 上的钩子仍可正常执行
    # 设置 POOL (0x1112c54), GFW (0x157aa10), MANAGER (0x163f3c8)
    TASK_BASE = 0x1b00000
    cpu.mem_map(TASK_BASE, 0x10000)
    cpu.mem_write(0x1112c54 + 4, struct.pack('<I', 2))
    cpu.mem_write(0x1112c54 + 0x10, struct.pack('<I', TASK_BASE))

    # 2a. 测试 select_hook (0x33f322): 发送 0xe5 (2.35:1) -> GFW+0xcc 写入 2，state 写入 9
    cpu.reg_write(R.UC_ARM_REG_R5, 0x157aa10)
    cpu.reg_write(R.UC_ARM_REG_R1, 0xe5)
    cpu.reg_write(R.UC_ARM_REG_LR, 0x33f326 | 1)
    cpu.emu_start(0x33f322 | 1, 0x33f326, count=5000)
    assert cpu.reg_read(R.UC_ARM_REG_PC) == 0x33f326
    assert struct.unpack('<I', cpu.mem_read(0x157aa10 + 0xcc, 4))[0] == 2
    assert (struct.unpack('<I', cpu.mem_read(cp_resident.STATE_VA, 4))[0] & 0xf) == 9

    # 2b. 测试 snapshot_hook (0xadf128)
    cpu.mem_write(0x163f3c8, struct.pack('<I', 0x42))  # request id
    cpu.reg_write(R.UC_ARM_REG_R0, 0x163f3f0)
    cpu.reg_write(R.UC_ARM_REG_R1, 0x157aa10)
    cpu.reg_write(R.UC_ARM_REG_R2, 0xdbc)
    cpu.mem_write(0x1a30000 + 4, struct.pack('<I', 0xaf153b))
    cpu.reg_write(R.UC_ARM_REG_R7, 0x1a30000)
    cpu.reg_write(R.UC_ARM_REG_LR, 0xadf12c | 1)
    cpu.emu_start(0xadf128 | 1, 0xadf12c, count=10000)
    assert cpu.reg_read(R.UC_ARM_REG_PC) == 0xadf12c
    assert struct.unpack('<I', cpu.mem_read(cp_resident.STATE_VA + 8, 4))[0] == 9

    # 2c. 测试 capture_copy (0xadd846) 绑定 task[0]
    cpu.mem_write(TASK_BASE + 0x24, struct.pack('<I', 2))
    cpu.mem_write(TASK_BASE + 0x5ae8, struct.pack('<I', 0x42))
    cpu.mem_write(TASK_BASE + 0x5980, struct.pack('<I', 1))  # JPEG
    cpu.reg_write(R.UC_ARM_REG_R0, TASK_BASE + 0x20)
    cpu.reg_write(R.UC_ARM_REG_R1, 0x163f3f0)
    cpu.reg_write(R.UC_ARM_REG_LR, 0xadd84a | 1)
    cpu.emu_start(0xadd846 | 1, 0xadd84a, count=10000)
    assert cpu.reg_read(R.UC_ARM_REG_PC) == 0xadd84a
    assert cpu.mem_read(cp_resident.STATE_VA + 16, 1)[0] == 9

    # 2d. 测试 jpeg_hook (0x473562): 9504x6336 -> 9504x4048 (2.35:1)
    src_geo = struct.pack('<6H', 9600, 6336, 9504, 6336, 0, 0)
    cpu.mem_write(TASK_BASE + 0x5f78, src_geo)
    dst_geo = TASK_BASE + 0x8000
    cpu.reg_write(R.UC_ARM_REG_R0, dst_geo)
    cpu.reg_write(R.UC_ARM_REG_R1, TASK_BASE + 0x5f78)
    cpu.reg_write(R.UC_ARM_REG_R2, 12)
    cpu.reg_write(R.UC_ARM_REG_R4, TASK_BASE)
    cpu.reg_write(R.UC_ARM_REG_LR, 0x473566 | 1)
    cpu.emu_start(0x473562 | 1, 0x473566, count=20000)
    assert cpu.reg_read(R.UC_ARM_REG_PC) == 0x473566
    cw, ch, w, h, x, y = struct.unpack('<6H', cpu.mem_read(dst_geo, 12))
    assert (w, h) == (9504, 4048)

    # 2e. 测试 pool_reset_hook (0x4614a4)
    cpu.reg_write(R.UC_ARM_REG_R9, 0x1112c54)
    cpu.reg_write(R.UC_ARM_REG_R0, TASK_BASE + 0x9000)
    cpu.reg_write(R.UC_ARM_REG_LR, 0x4614a8 | 1)
    cpu.emu_start(0x4614a4 | 1, 0x4614a8, count=5000)
    assert cpu.reg_read(R.UC_ARM_REG_PC) == 0x4614a8
    assert cpu.mem_read(cp_resident.STATE_VA + 16, 1)[0] == 0
