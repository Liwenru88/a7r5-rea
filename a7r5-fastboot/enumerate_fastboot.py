#!/usr/bin/env python3
"""只读枚举 macOS 上的 RP2040 和 Sony Fastboot USB 设备。"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

EXPECTED_FASTBOOT = (0x18D1, 0x4EE0)
EXPECTED_RP2040 = 0x2E8A


@dataclass
class CommandResult:
    command: str
    returncode: int | None
    stdout: str
    stderr: str
    error: str | None = None


def run_command(command: list[str], timeout: float = 10.0) -> CommandResult:
    """Run one read-only diagnostic command and capture all output."""
    rendered = " ".join(command)
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            errors="replace",
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        return CommandResult(rendered, None, "", "", str(exc))
    return CommandResult(rendered, result.returncode, result.stdout, result.stderr)


def parse_modems() -> list[str]:
    """Return currently visible modem device paths."""
    result = run_command(["/bin/sh", "-c", "ls -1 /dev/cu.usbmodem* /dev/tty.usbmodem* 2>/dev/null"])
    if result.returncode != 0:
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def parse_serial_ports() -> list[dict[str, object]]:
    """Inspect serial devices using the bundled pySerial wheel when available."""
    wheel_dir = Path(__file__).resolve().parent / "assets"
    wheels = sorted(wheel_dir.glob("pyserial-*.whl"))
    if not wheels:
        return [{"error": f"找不到 {wheel_dir}/pyserial-*.whl"}]

    sys.path.insert(0, str(wheels[0]))
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        return [{"error": f"无法导入 pySerial: {exc}"}]

    ports = []
    for port in list_ports.comports():
        ports.append(
            {
                "device": port.device,
                "description": port.description,
                "hwid": port.hwid,
                "vid": port.vid,
                "pid": port.pid,
                "serial_number": port.serial_number,
                "manufacturer": port.manufacturer,
                "is_expected_rp2040": port.vid == EXPECTED_RP2040,
            }
        )
    return ports


def fastboot_matches_ioreg(ioreg_text: str) -> list[dict[str, str]]:
    """Extract Fastboot device blocks from ioreg output."""
    matches = []
    # ioreg prints each device as a tree node followed by one property block.
    # Split at the next node marker so vendor/product values stay paired.
    blocks = re.findall(
        r"(?s)^[ |]*\+-o .*?(?=^[ |]*\+-o |\Z)",
        ioreg_text,
        flags=re.MULTILINE,
    )
    for block in blocks:
        vendor = re.search(r'"idVendor"\s*=\s*(\d+)', block)
        product = re.search(r'"idProduct"\s*=\s*(\d+)', block)
        if not vendor or not product:
            continue
        vid = int(vendor.group(1))
        pid = int(product.group(1))
        if (vid, pid) != EXPECTED_FASTBOOT:
            continue
        product_name = re.search(r'"USB Product Name"\s*=\s*"([^"]*)"', block)
        serial = re.search(r'"USB Serial Number"\s*=\s*"([^"]*)"', block)
        location = re.search(r'"locationID"\s*=\s*(\d+)', block)
        matches.append(
            {
                "vid": f"0x{vid:04x}",
                "pid": f"0x{pid:04x}",
                "product": product_name.group(1) if product_name else "",
                "serial": serial.group(1) if serial else "",
                "location_id": location.group(1) if location else "",
                "matched": "true",
            }
        )
    return matches


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, help="可选：将 JSON 报告写入新文件")
    args = parser.parse_args()

    if sys.platform != "darwin":
        print("警告：该脚本针对 macOS；当前系统不是 Darwin。", file=sys.stderr)

    usb = run_command(["/usr/sbin/system_profiler", "SPUSBDataType"], timeout=20)
    ioreg = run_command(["/usr/sbin/ioreg", "-p", "IOUSB", "-l", "-w", "0"], timeout=20)
    report = {
        "timestamp_utc": datetime.now(timezone.utc).isoformat(),
        "platform": sys.platform,
        "expected": {
            "fastboot_vid": f"0x{EXPECTED_FASTBOOT[0]:04x}",
            "fastboot_pid": f"0x{EXPECTED_FASTBOOT[1]:04x}",
            "rp2040_vid": f"0x{EXPECTED_RP2040:04x}",
        },
        "modem_devices": parse_modems(),
        "serial_ports": parse_serial_ports(),
        "fastboot_matches_in_ioreg": fastboot_matches_ioreg(ioreg.stdout),
        "commands": [asdict(usb), asdict(ioreg)],
    }
    report["fastboot_usb_seen"] = bool(report["fastboot_matches_in_ioreg"])
    report["rp2040_serial_seen"] = any(
        item.get("is_expected_rp2040") is True
        for item in report["serial_ports"]
        if isinstance(item, dict)
    )

    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(f"报告已写入：{args.output}", file=sys.stderr)

    return 0 if usb.returncode == 0 and ioreg.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
