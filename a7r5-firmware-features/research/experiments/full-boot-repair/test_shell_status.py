import io
from pathlib import Path
import struct
import os

import pytest
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM, UC_HOOK_CODE
from unicorn import arm64_const as R

from shell_status import repair_status
from fixtures import updater_body

ROOT = Path(__file__).resolve().parents[3]
STACK, STOP, DATA = 0x3000000, 0x3008000, 0x3009000


def execute(raw, wait_status, errno):
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.mem_map(0, 0x40000)
    elf = ELFFile(io.BytesIO(raw))
    for segment in elf.iter_segments():
        if segment['p_type'] == 'PT_LOAD':
            cpu.mem_write(segment['p_vaddr'], segment.data())
    cpu.mem_map(STACK, 0x10000)
    cpu.mem_write(DATA, struct.pack('<I', errno))
    cpu.mem_write(STACK, struct.pack('<QQ', STACK, STOP))
    for register, value in ((0, wait_status & ((1 << 64)-1)), (29, STACK), (30, STOP)):
        cpu.reg_write(getattr(R, f'UC_ARM64_REG_X{register}'), value)
    cpu.reg_write(R.UC_ARM64_REG_SP, STACK)
    thrown = []
    def service(core, address, _size, _user):
        if address == 0x10700:
            thrown.append(True)
            core.emu_stop()
        elif address in (0x103d0, 0xfd80, 0x10930, 0x10770):
            value = DATA if address == 0x103d0 else DATA + 0x100 if address == 0xfd80 else 0
            core.reg_write(R.UC_ARM64_REG_X0, value)
            core.reg_write(R.UC_ARM64_REG_PC, core.reg_read(R.UC_ARM64_REG_LR))
    cpu.hook_add(UC_HOOK_CODE, service)
    cpu.emu_start(0x189a0, STOP, count=10000)
    if thrown:
        return 'exception'
    assert cpu.reg_read(R.UC_ARM64_REG_PC) == STOP
    return cpu.reg_read(R.UC_ARM64_REG_X0)


@pytest.mark.parametrize('wait_status,errno,expected', [
    (0, 0, 0), (0, 10, 0), (7 << 8, 0, 7), (7 << 8, 10, 7),
    (255 << 8, 10, 255), (-1, 10, 'exception'), (15, 0, 'exception'),
])
def test_native_shell_caller_preserves_error_status(wait_status, errno, expected):
    candidate = repair_status(updater_body())
    if path := os.environ.get('A7R5_SHELL_STATUS_LIBRARY'):
        captured = Path(path).read_bytes()
        assert captured == candidate
        candidate = captured
    assert execute(candidate, wait_status, errno) == expected
