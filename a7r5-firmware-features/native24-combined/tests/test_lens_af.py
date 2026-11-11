"""A7R5 镜头能力补丁的真实 Thumb 调用点与包数据回放。"""
from hashlib import sha256
import importlib.util
import json
import os
from pathlib import Path
import struct

from unicorn import arm_const as R

from replay import CP, cp_raw, receipt
import patches

spec = importlib.util.spec_from_file_location(
    'native24_lens_af', Path(__file__).resolve().parents[2] / 'lens-af-compat/src/lens_af.py')
lens_af = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lens_af)


def execute(cp, start, stop, registers):
    cp.cpu.reg_write(R.UC_ARM_REG_SP, cp.STACK + 0x8000)
    for register, value in registers.items():
        cp.cpu.reg_write(register, value)
    # 同一入口有两种停止边界，避免复用跨过本次停止地址的翻译块。
    cp.cpu.ctl_flush_tb()
    cp.cpu.emu_start(start | 1, stop, count=1024)
    assert cp.cpu.reg_read(R.UC_ARM_REG_PC) == stop


def test_lens_af_scoped_consumers_and_lens_reports(tmp_path):
    proof = receipt.get('lens_AF')
    patched = cp_raw
    if folder := os.environ.get('A7R5_CAPTURE_AF_BUILD'):
        folder = Path(folder)
        build = json.loads((folder / 'build.json').read_text())
        patched = (folder / 'cpapp-b.bin').read_bytes()
        proof = build['CP_lens_af']
        expected = build.get('CP_aspect', {}).get('target_sha256', lens_af.STOCK_SHA256)
        assert sha256(patched).hexdigest() == build['CP_sha256'] == proof['target_sha256']
    elif not proof:
        # 默认构建也回放实验补丁，仅改测试内存。
        patched, proof = lens_af.apply_lens_af(cp_raw, patches, tmp_path)
        expected = lens_af.SOURCE_SHA256
    else:
        expected = lens_af.SOURCE_SHA256
    raw = bytearray(patched)
    for row in proof['patches']:
        at = row['offset']
        before = bytes.fromhex(row['before'])
        assert raw[at:at + len(before)].hex() == row['after']
        raw[at:at + len(before)] = before
    assert sha256(raw).hexdigest() == proof['source_sha256'] == expected
    stock, candidate = CP(bytes(raw)), CP(patched)
    classifier, getter = 0xa6bca0, 0xa6bce2
    config_byte, flag_byte = 0x119e357, 0x19ce5b1
    cases = ((0xc530, 0, 1, 0), (0xd123, 0, 1, 0),
             (0x8050, 0, 0, 0), (0xffff, 0, 0, 0),
             (0xc530, 1, 1, 1), (0xc530, 2, 0, 0))
    for lens_id, config, native, adapted in cases:
        for cp in (stock, candidate):
            cp.write(config_byte, bytes([config]))
            cp.call(classifier | 1, lens_id)
            # 分类器及任何未改的消费者仍看到原兼容标志。
            assert cp.read(flag_byte, 1) == bytes([native])
            assert cp.call(getter | 1) == native
            for address, _, _ in lens_af.CALLS:
                registers = {R.UC_ARM_REG_R1: 0x11111111, R.UC_ARM_REG_R2: 0x22222222,
                             R.UC_ARM_REG_APSR: 0xa0000000}
                execute(cp, address, address + 4, registers)
                assert cp.cpu.reg_read(R.UC_ARM_REG_R0) == (native if cp is stock else adapted)
                assert cp.cpu.reg_read(R.UC_ARM_REG_APSR) & 0xf0000000 == 0xa0000000
                assert cp.cpu.reg_read(R.UC_ARM_REG_R1) == 0x11111111
                assert cp.cpu.reg_read(R.UC_ARM_REG_R2) == 0x22222222
                assert cp.cpu.reg_read(R.UC_ARM_REG_SP) == cp.STACK + 0x8000

    # 在镜头已声明能力的情况下，三条原包分支保留数据，强制兼容仍过滤。
    for cp, config, filtered in ((stock, 0, True), (candidate, 0, False), (candidate, 1, True)):
        cp.write(config_byte, bytes([config]))
        cp.call(classifier | 1, 0xc530)
        for (address, _, _), stop in zip(lens_af.CALLS[:3], (0x3f4dbe, 0x3f3ffa, 0x3f47c4)):
            packet = bytearray([0xff] * 64)
            struct.pack_into('<H', packet, 0x0a, 0xc530)
            cp.write(cp.PACKET, packet)
            execute(cp, address, stop, {R.UC_ARM_REG_R4: cp.PACKET})
            after = cp.read(cp.PACKET, len(packet))
            assert (after != packet) == filtered
            if address == 0x3f47b6:
                assert after[0x21:0x23] == (b'\x01\x0c' if filtered else b'\xff\xff')
                assert after[0x32] & 0x30 == (0 if filtered else 0x30)

        # 真实发布分支读取缓存中的上报位。逐位验证，避免把未上报能力发布成可用。
        cached_lens = cp.PACKET + 0x100
        cached_lens_ptr = cp.PACKET + 0x300
        cp.write(cached_lens_ptr, struct.pack('<I', cached_lens))
        for reported in (0, 1 << 12, 1 << 15, 1 << 21, 1 << 28, 1 << 29):
            cp.write(cp.PACKET, bytes(16))
            cp.write(cached_lens + 0x15a, struct.pack('<II', reported, 0))
            registers = {R.UC_ARM_REG_R4: cp.PACKET, R.UC_ARM_REG_R9: cached_lens_ptr,
                         R.UC_ARM_REG_R8: 0}
            execute(cp, 0xa64db4, 0xa64ec6, registers)
            execute(cp, 0xa64f48, 0xa64fb6, registers)
            expected = 0 if filtered else {0: 0, 1 << 12: 4, 1 << 15: 8, 1 << 21: 16,
                                           1 << 28: 2 << 8, 1 << 29: 4 << 8}[reported]
            assert cp.read(cp.PACKET + 3, 1) + cp.read(cp.PACKET + 10, 1) == struct.pack('<H', expected)
    candidate.write(config_byte, b'\0')
    candidate.write(flag_byte, b'\x02')
    for address, _, _ in lens_af.CALLS:
        execute(candidate, address, address + 4, {})
        assert candidate.cpu.reg_read(R.UC_ARM_REG_R0) == 2
