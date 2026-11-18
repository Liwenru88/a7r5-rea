"""基于 4.28 appFw.so 构建 4.29 自定义纵横比 AP 代码并应用补丁。"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FEATURES_DIR = HERE.parent.parent
ASPECT_SRC = FEATURES_DIR / "photo-aspect-ratios" / "src"

if str(ASPECT_SRC) not in sys.path:
    sys.path.insert(0, str(ASPECT_SRC))

import build_ap as base_ap  # noqa: E402

CLANG = shutil.which("clang", path="/opt/homebrew/opt/llvm/bin:/usr/bin:/bin") or "/opt/homebrew/opt/llvm/bin/clang"
LD = shutil.which("ld.lld", path="/opt/homebrew/opt/lld/bin:/opt/homebrew/opt/llvm/bin:/usr/bin:/bin") or "/opt/homebrew/opt/lld/bin/ld.lld"

STOCK_GUIDE_RECT_DRAW = 0x182DA28

AP_SOURCES_429 = [
    HERE / "ap_transport_429.S",
    ASPECT_SRC / "ap_menu.S",
    ASPECT_SRC / "ap_menu.c",
    ASPECT_SRC / "ap_state.c",
    HERE / "ap_persist_429.c",
    HERE / "ap_guide_429.S",
    HERE / "ap_guide_429.c",
    ASPECT_SRC / "geometry.c",
    ASPECT_SRC / "playback.S",
    ASPECT_SRC / "ap_zoom.S",
    ASPECT_SRC / "ap_playback_info.S",
]


def _make_linker_script(work: Path, shift: int) -> Path:
    source = (ASPECT_SRC / "ap.ld").read_text(encoding="utf-8")
    if shift:
        source = re.sub(
            r"0x8f[01][0-9a-f]{4}",
            lambda m: hex(int(m[0], 16) + shift),
            source,
        )
    if "stock_guide_rect_draw" not in source:
        source = source.rstrip() + f"\nstock_guide_rect_draw = 0x{STOCK_GUIDE_RECT_DRAW:x};\n"
    out = work / "aspect-ap-429.ld"
    out.write_text(source, encoding="utf-8")
    return out


def compile_ap_429(work: Path, raw: bytes, *, source_sha: str | None = None) -> tuple[bytes, Path]:
    expected_sha = base_ap.SOURCE if source_sha is None else source_sha
    actual_sha = hashlib.sha256(raw).hexdigest()
    if actual_sha != expected_sha:
        raise SystemExit(f"意外的 appFw.so SHA-256: {actual_sha} != {expected_sha}")

    work.mkdir(parents=True, exist_ok=True)
    base_ap.generate(work)
    existing = base_ap.layout(raw, expected_sha)
    shift = existing[5] if existing and len(existing) > 5 else 0
    linker = _make_linker_script(work, shift)

    if existing:
        hooks = [
            f"-Wl,--defsym={key}={hex(value)}"
            for key, value in zip(("prior_register", "prior_icon", "prior_icon_alt"), existing[2:])
        ]
    else:
        hooks = [
            "-DR5_ASPECT_STOCK",
            "-Wl,--defsym=prior_register=0x1c91e94",
            "-Wl,--defsym=prior_icon=r5_aspect_stock_icon",
            "-Wl,--defsym=prior_icon_alt=r5_aspect_stock_icon_alt",
        ]

    row_file = work / "aspect-ap-rows.bin"
    row_file.write_bytes(base_ap.rows(raw))
    assembly = work / "aspect-ap-rows.S"
    assembly.write_text(
        '.section .rodata.rows,"a"\n.balign 8\n'
        ".global r5_aspect_rows\nr5_aspect_rows:\n"
        f".incbin {json.dumps(str(row_file.resolve()))}\n",
        encoding="utf-8",
    )

    elf = work / "aspect-ap-429.elf"
    objs: list[str] = []
    common_flags = [
        CLANG,
        "--target=aarch64-none-elf",
        "-Oz",
        "-ffreestanding",
        "-fno-builtin",
        "-fno-stack-protector",
        "-mno-outline-atomics",
        "-Wall",
        "-Wextra",
        "-Werror",
        "-I",
        str(work),
        "-I",
        str(ASPECT_SRC),
    ]
    for src in [*AP_SOURCES_429, assembly]:
        obj = work / f"{src.name}.o"
        extra: list[str] = []
        if src.suffix == ".c":
            extra.append("-mgeneral-regs-only")
        elif existing is None:
            extra.extend(hooks[:1])
        subprocess.run(
            [*common_flags, *extra, "-c", str(src), "-o", str(obj)],
            check=True,
        )
        objs.append(str(obj))

    subprocess.run(
        [
            CLANG,
            "--target=aarch64-none-elf",
            "-nostdlib",
            f"--ld-path={LD}",
            "-Wl,--build-id=none",
            f"-Wl,-T,{linker}",
            *(h for h in hooks if h.startswith("-Wl,")),
            *objs,
            "-o",
            str(elf),
        ],
        check=True,
    )
    return elf.read_bytes(), elf


def patch_ap_429(raw: bytes, work: Path, *, source_sha: str | None = None) -> tuple[bytes, Path, dict]:
    expected_sha = hashlib.sha256(raw).hexdigest() if source_sha is None else source_sha
    elf_bytes, elf_path = compile_ap_429(work, raw, source_sha=expected_sha)
    patched, meta = base_ap.apply_ap(raw, elf_bytes, source_sha=expected_sha)
    return patched, elf_path, meta
