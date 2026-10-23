"""仅检查本机库、参考文件和 ELF 兼容性，不初始化 USB 上下文。"""

import ctypes
import hashlib
from importlib import metadata
from pathlib import Path
import sys

from .usb_adapter import LIBUSB
from .images import E2FS

ROOT = Path(__file__).resolve().parents[2]
REFERENCE = ROOT / "sources/projects/a7c2-re/report/2026-10-16-system-dump"
PMCA = ROOT / "sources/workspaces/j/work/sony-pmca-re"
FW = ROOT / "sources/workspaces/j/work/a7r5-400-filesystem/firmware.tar_unpacked/0700_part_image/dev"
PINNED = {
    "system_dump_probe.arm64.so": "5a95d422dff2134b055e159f786184b2929553c3416f0a0b8d847aee816bc5f1",
    "a7c2_shell.arm64.so": "d261855eb1ea461a77c7847fefef7e6960d4495433d245a9eeb458eef0b35e6e",
}


def static_payload_check(path, expected):
    from elftools.elf.elffile import ELFFile
    raw = path.read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError(f"参考载荷摘要变化：{path.name}")
    with path.open("rb") as handle:
        elf = ELFFile(handle)
        if (elf.header["e_machine"] != "EM_AARCH64" or elf.header["e_type"] != "ET_DYN"
                or elf.elfclass != 64 or not elf.little_endian):
            raise ValueError("参考载荷不是 AArch64 ELF64 动态库")
        dynamic = elf.get_section_by_name(".dynamic")
        needed = [t.needed for t in dynamic.iter_tags() if t.entry.d_tag == "DT_NEEDED"]
        versions = []
        version_section = elf.get_section_by_name(".gnu.version_r")
        if version_section:
            for _, auxiliary in version_section.iter_versions():
                versions.extend(v.name for v in auxiliary)
        undefined = [s.name for s in elf.get_section_by_name(".dynsym").iter_symbols()
                     if s["st_shndx"] == "SHN_UNDEF" and s.name
                     and s["st_info"]["bind"] != "STB_WEAK"]
    exports = set()
    for name in needed:
        candidates = [FW / "nflasha7_unpacked/lib" / name,
                      FW / "nflasha15_unpacked/lib" / name]
        # Windows 解包未创建固件符号链接，按已知解释器/库实体解析。
        if name == "libc.so.6": candidates.insert(0, FW / "nflasha7_unpacked/lib/libc-2.25.so")
        if name == "libpthread.so.0": candidates.insert(0, FW / "nflasha7_unpacked/lib/libpthread-2.25.so")
        actual = next((p for p in candidates if p.is_file()), None)
        if actual is None: raise ValueError(f"目标样本缺少依赖实体：{name}")
        with actual.open("rb") as handle:
            table = ELFFile(handle).get_section_by_name(".dynsym")
            exports.update(s.name for s in table.iter_symbols() if s["st_shndx"] != "SHN_UNDEF")
    missing = sorted(set(undefined) - exports)
    if missing: raise ValueError(f"目标样本未解析符号：{missing}")
    for version in versions:
        if version.startswith("GLIBC_"):
            numbers = tuple(map(int, version.removeprefix("GLIBC_").split(".")))
            if numbers > (2, 25): raise ValueError(f"载荷需要较新的 {version}")
    return {"file": path.name, "sha256": expected, "bytes": len(raw),
            "needed": needed, "required_versions": sorted(set(versions)),
            "strong_symbols_resolved_by_name": len(undefined),
            "static_check_passed": True, "camera_execution_verified": False,
            "note": "仅校验格式、依赖、符号名称和版本上界；不等价于实际重定位/构造执行或恢复验证。"}


def offline_check():
    # ctypes 只读版本号：不调用 libusb_init、get_backend 或 USB 枚举函数。
    library = ctypes.CDLL(str(LIBUSB))
    class Version(ctypes.Structure):
        _fields_ = [("major", ctypes.c_uint16), ("minor", ctypes.c_uint16),
                    ("micro", ctypes.c_uint16), ("nano", ctypes.c_uint16)]
    library.libusb_get_version.restype = ctypes.POINTER(Version)
    version = library.libusb_get_version().contents
    tools = {name: str(E2FS / name) for name in ("mke2fs", "debugfs", "e2fsck")}
    if not all(Path(p).is_file() for p in tools.values()): raise ValueError("缺少 e2fsprogs 工具")
    packages = {name: metadata.version(name) for name in
                ("pyusb", "pycryptodomex", "capstone", "pyelftools", "pytest")}
    from Cryptodome.Hash import SHA256
    if SHA256.new(b"abc").hexdigest() != hashlib.sha256(b"abc").hexdigest():
        raise ValueError("SHA-256 依赖自检失败")
    sys.path.insert(0, str(PMCA))
    from pmca.usb.sony import SonySenserAuthDevice
    if not hasattr(SonySenserAuthDevice, "authenticate"): raise ValueError("参考认证模块不完整")
    source_files = [PMCA / "pmca/usb/sony.py", PMCA / "pmca/usb/constants.py",
                    REFERENCE / "scripts/jiritsu_card_dump.py",
                    REFERENCE / "scripts/jiritsu_preload_deploy.py"]
    return {"local_ready": True, "usb_enumerated": False, "live_execution_enabled": False,
            "python": sys.executable, "packages": packages,
            "libusb": {"path": str(LIBUSB), "version": f"{version.major}.{version.minor}.{version.micro}"},
            "e2fsprogs_tools": tools,
            "reference_sources": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest()
                                  for p in source_files},
            "payloads": [static_payload_check(REFERENCE / "payload" / name, sha)
                         for name, sha in PINNED.items()]}
