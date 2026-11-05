"""在Unicorn内执行当前AP原始AArch64解码／编码函数；无操作系统或设备替身。"""
import hashlib
import io
import json
from pathlib import Path
import struct
import zlib

import pytest
from elftools.elf.elffile import ELFFile
from unicorn import Uc, UC_ARCH_ARM64, UC_MODE_ARM
from unicorn import arm64_const as A

from test_native24 import ROOT, REPO, entries, load_codec


@pytest.fixture(scope='module')
def image():
    candidate = json.loads((REPO/'a7r5-firmware-features/native24-combined/current-candidate.json').read_text())
    build = REPO/candidate['build']
    raw = (build/'appFw.so').read_bytes()
    assert hashlib.sha256(raw).hexdigest() == candidate['AP_sha256']
    audit = json.loads((build/'work/import/module_audit.json').read_text())
    return raw, audit['symbols']


@pytest.mark.parametrize('slots', [[], list(range(1, 13)), [1, 13, 24], list(range(1, 25))])
def test_actual_ap_accepts_generated_bin_and_rejects_corruption(image, slots):
    raw, symbols = image
    cpu = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
    cpu.mem_map(0, 0x9200000)
    for segment in ELFFile(io.BytesIO(raw)).iter_segments():
        if segment['p_type'] == 'PT_LOAD': cpu.mem_write(segment['p_vaddr'], segment.data())
    stop, stack, source, target, output = 0x60000000, 0x60018000, 0x60100000, 0x60200000, 0x60300000
    cpu.mem_map(stop, 0x400000)

    def call(name, *args):
        for i, value in enumerate(args): cpu.reg_write(getattr(A, f'UC_ARM64_REG_X{i}'), value)
        cpu.reg_write(A.UC_ARM64_REG_SP, stack)
        cpu.reg_write(A.UC_ARM64_REG_LR, stop)
        # 纯文件编解码没有外部硬件调用，不安装成功返回或内存复制桩。
        cpu.emu_start(symbols[name], stop, count=50_000_000)
        assert cpu.reg_read(A.UC_ARM64_REG_PC) == stop
        assert cpu.reg_read(A.UC_ARM64_REG_SP) == stack
        return cpu.reg_read(A.UC_ARM64_REG_X0)

    codec = load_codec(ROOT/'R5ColorLab/compilers/custom_filter_v4.py')
    data = codec.pack(codec.config(entries(codec, slots)))
    cpu.mem_write(source, data)
    assert call('r5_decode_look_file', source, len(data), target) == 0
    assert struct.unpack('<I', bytes(cpu.mem_read(target, 4)))[0] == sum(1 << (s-1) for s in slots)
    assert call('r5_encode_look_file', target, output, 58976) == len(data)
    assert bytes(cpu.mem_read(output, len(data))) == data
    damaged = bytearray(data)
    if slots: damaged[-1] = 1
    else: damaged[116] = 1
    struct.pack_into('<I', damaged, 112, 0)
    struct.pack_into('<I', damaged, 112, zlib.crc32(damaged))
    cpu.mem_write(source, bytes(damaged))
    before = bytes(cpu.mem_read(target, 58660))
    assert call('r5_decode_look_file', source, len(damaged), target) == 2
    assert bytes(cpu.mem_read(target, 58660)) == before
