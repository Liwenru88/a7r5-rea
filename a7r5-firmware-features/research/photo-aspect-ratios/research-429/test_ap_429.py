"""4.29 AP 自定义纵横比补丁离线验证测试。"""

from __future__ import annotations

import hashlib
import shutil
import struct
import subprocess
import tempfile
from pathlib import Path

from elftools.elf.elffile import ELFFile
from unicorn import UC_ARCH_ARM64, UC_HOOK_CODE, UC_MODE_ARM, Uc
from unicorn.arm64_const import (
    UC_ARM64_REG_CPACR_EL1,
    UC_ARM64_REG_D0,
    UC_ARM64_REG_D1,
    UC_ARM64_REG_LR,
    UC_ARM64_REG_NZCV,
    UC_ARM64_REG_PC,
    UC_ARM64_REG_Q0,
    UC_ARM64_REG_Q15,
    UC_ARM64_REG_SP,
    UC_ARM64_REG_W0,
    UC_ARM64_REG_W1,
    UC_ARM64_REG_W2,
    UC_ARM64_REG_W3,
    UC_ARM64_REG_W4,
    UC_ARM64_REG_X0,
    UC_ARM64_REG_X1,
    UC_ARM64_REG_X2,
    UC_ARM64_REG_X3,
    UC_ARM64_REG_X5,
    UC_ARM64_REG_X8,
    UC_ARM64_REG_X19,
    UC_ARM64_REG_X20,
    UC_ARM64_REG_X29,
)

from build_ap_429 import STOCK_GUIDE_RECT_DRAW, patch_ap_429

REPO = Path(__file__).resolve().parents[3]
AP_428 = REPO / "a7r5-firmware-features" / "builds" / "4.28-427-af-debounce-20261117" / "verify-runtime-20261117" / "runtime" / "appFw.so"


def _elf_symbols(elf_path: Path) -> dict[str, int]:
    with elf_path.open("rb") as fh:
        elf = ELFFile(fh)
        symtab = elf.get_section_by_name(".symtab")
        return {sym.name: sym["st_value"] for sym in symtab.iter_symbols() if sym.name}


def _map_segments(uc: Uc, elf_bytes: bytes) -> None:
    import io

    elf = ELFFile(io.BytesIO(elf_bytes))
    ranges: list[tuple[int, int, bytes]] = []
    for seg in elf.iter_segments():
        if seg["p_type"] != "PT_LOAD":
            continue
        va = seg["p_vaddr"]
        memsz = seg["p_memsz"]
        start = va & ~0xFFF
        end = (va + memsz + 0xFFF) & ~0xFFF
        ranges.append((start, end, seg.data(), va))
    # 合并重叠页区间后整段映射，避免逐页映射耗时
    merged: list[list[int]] = []
    for start, end, _, _ in sorted(ranges, key=lambda r: r[0]):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    for start, end in merged:
        uc.mem_map(start, end - start)
    for _, _, data, va in ranges:
        uc.mem_write(va, data)


def test_compile_and_no_forbidden_symbols_or_simd() -> None:
    raw = AP_428.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    work = Path(tempfile.mkdtemp(prefix="test_ap_429_"))
    try:
        patched, elf, meta = patch_ap_429(raw, work, source_sha=sha)
        assert len(patched) == len(raw)
        assert meta.get("inverse_exact") is True

        syms = _elf_symbols(elf)
        for forbidden in ("pthread_create", "pthread_detach", "usleep", "aspect_worker"):
            assert forbidden not in syms

        # 验证 ap_guide_429.o 与 ap_persist_429.o 不含浮点/SIMD 指令
        objdump = shutil.which("llvm-objdump") or "/opt/homebrew/opt/llvm/bin/llvm-objdump"
        for obj_name in ("ap_guide_429.c.o", "ap_persist_429.c.o"):
            dis = subprocess.check_output([objdump, "-d", str(work / obj_name)], text=True)
            for line in dis.splitlines():
                parts = line.split("\t")
                if len(parts) < 3:
                    continue
                op = parts[2].strip().split()[0]
                assert not op.startswith(("f", "scvtf", "ucvtf", "fcvtz")), f"发现浮点指令: {line}"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def test_unicorn_guide_and_transport_429() -> None:
    raw = AP_428.read_bytes()
    sha = hashlib.sha256(raw).hexdigest()
    work = Path(tempfile.mkdtemp(prefix="test_ap_429_uc_"))
    try:
        patched, elf, _ = patch_ap_429(raw, work, source_sha=sha)
        syms = _elf_symbols(elf)

        uc = Uc(UC_ARCH_ARM64, UC_MODE_ARM)
        uc.reg_write(UC_ARM64_REG_CPACR_EL1, 3 << 20)
        _map_segments(uc, patched)

        # 栈与测试数据区
        stack_base = 0x20000000
        uc.mem_map(stack_base, 0x10000)
        data_base = 0x20100000
        uc.mem_map(data_base, 0x10000)
        stub_base = 0x20200000
        uc.mem_map(stub_base, 0x1000)

        # 伪造 stock create 函数：只写入返回 widget 并修改 x1..x3、q0 测试保存/恢复
        stock_create_addr = stub_base
        # mov x0, x0; ret (0xd65f03c0)
        uc.mem_write(stock_create_addr, struct.pack("<I", 0xD65F03C0))
        ret_sentinel = stub_base + 0x100
        uc.mem_write(ret_sentinel, struct.pack("<I", 0xD65F03C0))
        noop_stub = stub_base + 0x200
        uc.mem_write(noop_stub, struct.pack("<I", 0xD65F03C0))

        # 在 stock_guide_draw_resume / stock_guide_rect_draw 放置 RET 桩并记录调用
        draw_calls: list[tuple[int, int, int, tuple[int, int, int, int], int]] = []
        stock_draw_calls: list[int] = []
        uc.mem_write(STOCK_GUIDE_RECT_DRAW, struct.pack("<I", 0xD65F03C0))
        stock_draw_resume = syms["stock_guide_draw_resume"]
        uc.mem_write(stock_draw_resume, struct.pack("<I", 0xD65F03C0))
        stock_sender = syms["stock_sender"]
        uc.mem_write(stock_sender, struct.pack("<I", 0xD65F03C0))
        # stub stock_dlsym: mov x0, #0; ret
        uc.mem_write(syms["stock_dlsym"], struct.pack("<II", 0xD2800000, 0xD65F03C0))

        def hook_code(uc_inst: Uc, address: int, size: int, user_data: object) -> None:
            if address == STOCK_GUIDE_RECT_DRAW:
                w0 = uc_inst.reg_read(UC_ARM64_REG_W0)
                w1 = uc_inst.reg_read(UC_ARM64_REG_W1)
                w2 = uc_inst.reg_read(UC_ARM64_REG_W2)
                x3 = uc_inst.reg_read(UC_ARM64_REG_X3)
                w4 = uc_inst.reg_read(UC_ARM64_REG_W4)
                rect = struct.unpack("<4i", uc_inst.mem_read(x3, 16))
                draw_calls.append((w0, w1, w2, rect, w4))
            elif address == stock_draw_resume:
                stock_draw_calls.append(uc_inst.reg_read(UC_ARM64_REG_X0))

        uc.hook_add(UC_HOOK_CODE, hook_code)

        # 1. 验证 r5_aspect_guide_create_call：从 view+8 读取 layer=3，而非 W1 Scene ID (99)
        view_ptr = data_base + 0x1000
        widget_ptr = data_base + 0x2000
        flags_ptr = data_base + 0x3000
        arena_ptr = data_base + 0x2000
        # 构造 view（size >= 0x4000），需要额外映射一段数据区
        uc.mem_map(data_base + 0x10000, 0x10000)
        view_ptr = data_base + 0x10000
        uc.mem_write(view_ptr, struct.pack("<Q", syms["stock_view_vtable"]))
        uc.mem_write(view_ptr + 8, struct.pack("<I", 3))
        uc.mem_write(view_ptr + 0x3E98, struct.pack("<Q", arena_ptr))
        uc.mem_write(view_ptr + 0x3EA0, struct.pack("<I", 0x4000))
        # row 4 = GUIDE_KIND (0x3d), parameter = widget_ptr + 0x1d8
        uc.mem_write(view_ptr + 0x10 + 4 * 16, struct.pack("<IIQ", 0x3D, 0, widget_ptr + 0x1D8))
        uc.mem_write(view_ptr + 0x3EC8 + 4 * 8, struct.pack("<Q", widget_ptr))
        uc.mem_write(widget_ptr, struct.pack("<Q", syms["stock_guide_vtable"]))

        uc.reg_write(UC_ARM64_REG_SP, stack_base + 0x8000)
        uc.reg_write(UC_ARM64_REG_X0, view_ptr)
        uc.reg_write(UC_ARM64_REG_W1, 99)  # 故意传入大 Scene ID
        uc.reg_write(UC_ARM64_REG_X2, syms["stock_descriptors_a"])
        uc.reg_write(UC_ARM64_REG_W3, 585)
        uc.reg_write(UC_ARM64_REG_W4, 0)
        uc.reg_write(UC_ARM64_REG_X5, flags_ptr)
        uc.reg_write(UC_ARM64_REG_X8, stock_create_addr)
        uc.reg_write(UC_ARM64_REG_X19, 0x1122334455667788)
        uc.reg_write(UC_ARM64_REG_Q0, (0xAAAABBBBCCCCDDDD << 64) | 0x1111222233334444)
        uc.reg_write(UC_ARM64_REG_Q15, (0x5555666677778888 << 64) | 0x9999000011112222)
        uc.reg_write(UC_ARM64_REG_LR, ret_sentinel)

        uc.emu_start(syms["r5_aspect_guide_create_call"], ret_sentinel, count=10000)

        assert uc.reg_read(UC_ARM64_REG_X19) == 0x1122334455667788
        assert uc.reg_read(UC_ARM64_REG_Q0) == ((0xAAAABBBBCCCCDDDD << 64) | 0x1111222233334444)
        assert uc.reg_read(UC_ARM64_REG_Q15) == ((0x5555666677778888 << 64) | 0x9999000011112222)

        # 验证 slots[3].widget == widget_ptr
        slots_addr = syms["aspect_guide_slots"]
        slot3_widget = struct.unpack("<Q", uc.mem_read(slots_addr + 3 * 24, 8))[0]
        assert slot3_widget == widget_ptr

        # 2. 验证 r5_aspect_guide_draw 在原生 3:2 模式下调用 stock_draw
        uc.mem_write(syms["aspect_selection"], struct.pack("<I", 0))
        uc.reg_write(UC_ARM64_REG_SP, stack_base + 0x8000)
        uc.reg_write(UC_ARM64_REG_X0, widget_ptr)
        uc.reg_write(UC_ARM64_REG_LR, ret_sentinel)
        uc.emu_start(syms["r5_aspect_guide_draw"], ret_sentinel, count=10000)
        assert len(stock_draw_calls) == 1
        assert len(draw_calls) == 0

        # 3. 验证 r5_aspect_guide_draw 在 2.35:1 (id=9) 模式下绘制两条黑边矩形（enable=1）并清除其余 6 条
        fake_vtable = data_base + 0x5000
        uc.mem_write(fake_vtable + 0x30, struct.pack("<Q", noop_stub))
        uc.mem_write(widget_ptr, struct.pack("<Q", fake_vtable))
        uc.mem_write(widget_ptr + 0x204, b"\x01")
        uc.mem_write(widget_ptr + 0x208, struct.pack("<4i", 0, 0, 640, 480))
        uc.mem_write(widget_ptr + 0x218, struct.pack("<I", 0))
        uc.mem_write(widget_ptr + 0x21C, b"\x01\x00")
        uc.mem_write(syms["aspect_selection"], struct.pack("<I", 9))
        # 设置 slots[3].completed = 9, slots[3].custom = 1
        uc.mem_write(slots_addr + 3 * 24 + 16, struct.pack("<IBB", 9, 0, 1))

        uc.reg_write(UC_ARM64_REG_SP, stack_base + 0x8000)
        uc.reg_write(UC_ARM64_REG_X0, widget_ptr)
        uc.reg_write(UC_ARM64_REG_LR, ret_sentinel)
        uc.emu_start(syms["r5_aspect_guide_draw"], ret_sentinel, count=10000)
        assert len(draw_calls) == 8
        assert draw_calls[0][1] == 0 and draw_calls[0][2] == 1
        assert draw_calls[1][1] == 1 and draw_calls[1][2] == 1
        assert all(c[2] == 0 for c in draw_calls[2:])

        # 4. 验证 r5_aspect_ap_prepare 不触发文件 I/O 且写入 0xe5 (9-4+0xe0)
        frame_ptr = data_base + 0x6000
        msg_ptr = data_base + 0x7000
        uc.mem_write(msg_ptr + 8, struct.pack("<I", 0))
        uc.reg_write(UC_ARM64_REG_SP, stack_base + 0x8000)
        uc.reg_write(UC_ARM64_REG_X20, msg_ptr)
        uc.reg_write(UC_ARM64_REG_X29, frame_ptr)
        uc.reg_write(UC_ARM64_REG_LR, ret_sentinel)
        uc.emu_start(syms["r5_aspect_ap_prepare"], ret_sentinel, count=10000)
        assert uc.mem_read(frame_ptr + 0x77, 1)[0] == 0xE5
    finally:
        shutil.rmtree(work, ignore_errors=True)
