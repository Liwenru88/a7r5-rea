#!/usr/bin/env python3
"""A7R V 内存引导及只读探测。默认仅检查本地材料。"""

import argparse
import hashlib
import json
import re
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PAYLOAD = "assets/fastboot.bin"
SDM2 = "assets/local-backup-sdm2.raw.bin"
WHEEL = "assets/pyserial-3.5-py2.py3-none-any.whl"
BRIDGE = "assets/uart_boot.ino.uf2"
CONFIGURE = "host/configure_fastboot_usb"
READER = "host/read_fastboot_usb"
ASSET_PINS = {
    PAYLOAD: "330ac322bd0e40a7bb4974f69a2667e7d59a25e59c1322339690f30a3ceadbdc",
    SDM2: "1c2c4b0548a49a3ec25ef4b5f09540ca78c4432cc0419e0c07e626ff2f77d7e6",
    WHEEL: "c4451db6ba391ca6ca299fb3ec7bae67a5c55dde170964c7a14ceefec02f2cf0",
    BRIDGE: "40554314f62bc5c22d6d22246b42988a79bb8f9a5089942fda7fbfb85e1d4dcd",
}
RECORDS_SHA = "3604be189345d85deb701d22f145b8b7a28d606186ec287751a677ccbb9c2ebb"
TABLE_DUMP = "oem partition dump nflasha 0 0x80"
ROM_DUMP = "oem dumpbrom"
UART_READY = b"[mira] fastboot ready"
MAX_BRIDGE_FRAME = 4096


class ProbeError(RuntimeError):
    pass


def digest(data):
    return hashlib.sha256(data).hexdigest()


def boot_records(payload):
    # 记录布局及 SRAM 地址来自 David 的公开脚本，由 Erlla 实现独立比对。
    def frame(kind, value, data=b""):
        body = struct.pack("<IHI", 10 + len(data), kind, value) + data
        return body + struct.pack("<I", zlib.crc32(body))

    start = 0xFE020000
    yield frame(0x123, 0)
    for offset in range(0, len(payload), 512):
        yield frame(1, start + offset, payload[offset:offset + 512])
    token = struct.pack("<I", 0xDEADBEEF)
    yield frame(1, 0xFE02F398, token + struct.pack("<I", zlib.crc32(token) ^ 0xFFFFFFFF))
    yield frame(0xFFFF, start)
    yield frame(0, 0xDEADBEEF)
    yield frame(0x123, 0)


def preflight(root):
    pins = dict(ASSET_PINS)
    host_pins = json.loads((root / "host-sha256.json").read_text())
    if set(host_pins) != {CONFIGURE, READER}:
        raise ProbeError("Mac 工具清单不完整")
    pins.update(host_pins)
    inputs = {}
    for name, expected in pins.items():
        data = (root / name).read_bytes()
        if digest(data) != expected:
            raise ProbeError(f"文件校验失败：{name}")
        inputs[name] = data
    records = tuple(boot_records(inputs[PAYLOAD]))
    if len(records) != 64 or digest(b"".join(records)) != RECORDS_SHA:
        raise ProbeError("BootROM 引导记录与公开参考不一致")
    return inputs[SDM2], records


class SerialBridge:
    def __init__(self, serial, uart):
        self.serial = serial
        self.uart = uart
        self.pending_uart = bytearray()

    def receive(self, size, deadline):
        data = bytearray()
        while len(data) < size:
            left = deadline - time.monotonic()
            if left <= 0:
                raise ProbeError("RP2040 应答超时或不完整")
            self.serial.timeout = left
            data.extend(self.serial.read(size - len(data)))
        return bytes(data)

    def command(self, code, data=b""):
        packet = struct.pack("<BH", code, len(data)) + data
        if self.serial.write(packet) != len(packet):
            raise ProbeError("RP2040 串口写入不完整")
        deadline = time.monotonic() + 1.0
        while True:
            event, length = struct.unpack("<BH", self.receive(3, deadline))
            if length > MAX_BRIDGE_FRAME:
                raise ProbeError("RP2040 应答长度异常")
            content = self.receive(length, deadline)
            if event == 0x81:
                if code != 1 and content:
                    raise ProbeError("RP2040 ACK 携带非预期内容")
                return content
            if event == 0x82:
                raise ProbeError(f"RP2040 返回错误：{content!r}")
            if event != 0x83:
                raise ProbeError(f"RP2040 返回未知事件：{event:#x}")
            self.uart.write(content)
            self.uart.flush()

    def poll_uart(self):
        # USB 轮询有自己的时限。串口只取当前可读的数据，跨轮询保留未完成的帧。
        self.serial.timeout = 0
        self.pending_uart.extend(self.serial.read(65536))
        while len(self.pending_uart) >= 3:
            event, length = struct.unpack_from("<BH", self.pending_uart)
            if length > MAX_BRIDGE_FRAME:
                raise ProbeError("RP2040 异步应答长度异常")
            end = 3 + length
            if len(self.pending_uart) < end:
                break
            content = bytes(self.pending_uart[3:end])
            del self.pending_uart[:end]
            if event == 0x82:
                raise ProbeError(f"RP2040 异步错误：{content!r}")
            if event != 0x83:
                raise ProbeError(f"RP2040 返回非预期的异步事件：{event:#x}")
            self.uart.write(content)
        self.uart.flush()


def start_ram(bridge, records, report, sleep=time.sleep):
    if bridge.command(1) != b"uart_boot 1":
        raise ProbeError("RP2040 桥接版本不符")
    report["stage"] = "reset"
    report["reset_attempted"] = True
    bridge.command(2)
    report["reset_acknowledged"] = True
    bridge.command(3, b"\x01")
    sleep(0.5)
    report["stage"] = "boot_records"
    for record in records:
        bridge.command(4, record)
        report["records_acknowledged"] += 1
        sleep(0.0144)
    bridge.command(3, b"\x00")
    bridge.command(5, struct.pack("<I", 115200))


def expected_layout(table):
    if len(table) != 65536 or not table.startswith(b"82462.00"):
        raise ProbeError("SDM2 参考的长度或标记错误")
    count = struct.unpack_from("<I", table, 8)[0]
    if not 1 <= count <= 64:
        raise ProbeError("SDM2 分区项数异常")
    kinds = {4: "ext2", 5: "fat", 6: "wbi2"}
    partitions = {}
    for index in range(count):
        start, size, kind, flags = struct.unpack_from("<4I", table, 32 + index * 16)
        if flags & 1:
            partitions[index + 1] = (start, size, kinds.get(kind, "?"))
    return partitions


def verify_listing(listing, expected):
    actual = {}
    for line in listing.splitlines():
        match = re.fullmatch(r"REPLY INFOnflasha([0-9]+)\s+([0-9a-fA-F]{8})\s+([0-9a-fA-F]{8})\s+(\S+)", line)
        if match is None:
            continue
        index, start, size, kind = match.groups()
        number = int(index)
        if number in actual:
            raise ProbeError("Fastboot 分区表重复")
        actual[number] = (int(start, 16), int(size, 16), kind)
    if actual != expected:
        raise ProbeError("Fastboot 分区布局与 R5 历史参考不符")


def run_logged(executable, args, log, timeout):
    with log.open("ab") as out:
        result = subprocess.run([str(executable), *args], stdout=out, stderr=subprocess.STDOUT,
                                timeout=timeout, check=False)
    return result.returncode


def probe_usb(root, run, table, report, bridge, launch=run_logged, sleep=time.sleep):
    report["stage"] = "usb_enumeration"
    deadline = time.monotonic() + 15
    while (left := deadline - time.monotonic()) > 0:
        try:
            result = launch(root / CONFIGURE, [], run / "usb-config.log", min(3, left))
        finally:
            if "uart_capture_error" not in report:
                try:
                    bridge.poll_uart()
                except (OSError, ProbeError) as exc:
                    report["uart_capture_error"] = str(exc)
        if result == 0:
            break
        if result != 2:
            raise ProbeError(f"USB 配置失败：{result}")
        sleep(0.2)
    else:
        raise ProbeError("15 秒内未枚举 Fastboot")

    report["stage"] = "partition_listing"
    log = run / "usb-layout.log"
    if launch(root / READER, ["getvar:version", "oem partition"], log, 8) != 0:
        raise ProbeError("Fastboot 协议或分区表查询失败")
    listing = log.read_text(errors="replace")
    version = listing.split("COMMAND oem partition\n", 1)[0].split("COMMAND getvar:version\n", 1)
    if len(version) != 2 or version[1].splitlines() != ["REPLY OKAY0.5"]:
        raise ProbeError("Fastboot 协议未返回 OKAY0.5")
    verify_listing(listing, expected_layout(table))
    report["layout_matches_reference"] = True

    report["stage"] = "sdm2_readback"
    current = run / "sdm2.raw.bin"
    if launch(root / READER, [TABLE_DUMP, "upload:" + str(current)], run / "usb-sdm2.log", 8) != 0:
        raise ProbeError("SDM2 回读失败")
    if current.read_bytes() != table:
        raise ProbeError("SDM2 原始数据与历史参考不符")
    report["sdm2_matches_reference"] = True

    report["stage"] = "ap_bootrom_readback"
    rom = run / "ap-bootrom.bin"
    if launch(root / READER, [ROM_DUMP, "upload:" + str(rom)], run / "usb-rom.log", 8) != 0:
        raise ProbeError("AP BootROM 回读失败")
    data = rom.read_bytes()
    if len(data) != 49152:
        raise ProbeError("AP BootROM 回读长度错误")
    report.update(stage="complete", usb_transport_verified=True, ap_bootrom_sha256=digest(data))


def open_bridge(port, root):
    sys.path.insert(0, str(root / WHEEL))
    import serial
    from serial.tools import list_ports

    matching = [p for p in list_ports.comports() if p.device == port and p.vid == 0x2E8A]
    if len(matching) != 1:
        raise ProbeError("没有找到指定的 RP2040 串口")
    return serial.Serial(port, 115200, timeout=1.0, write_timeout=1.0, exclusive=True)


def run_probe(port, run, table, records, opener=open_bridge, launch=run_logged, sleep=time.sleep):
    run.mkdir(mode=0o700, exist_ok=False)
    report = dict(stage="bridge_ping", reset_attempted=False, reset_acknowledged=False,
                  records_acknowledged=0, usb_transport_verified=False, layout_matches_reference=False,
                  sdm2_matches_reference=False, same_physical_body_verified=False,
                  persistent_write_commands_sent=False, uart_ready_observed=False)
    uart_log = run / "uart.bin"
    try:
        with opener(port, ROOT) as serial, uart_log.open("xb") as uart:
            bridge = SerialBridge(serial, uart)
            start_ram(bridge, records, report, sleep)
            probe_usb(ROOT, run, table, report, bridge, launch, sleep)
    except Exception as exc:
        report["error"] = str(exc)
    if uart_log.is_file():
        try:
            report["uart_ready_observed"] = UART_READY in uart_log.read_bytes()
        except OSError as exc:
            report.setdefault("uart_capture_error", str(exc))
    (run / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action")
    sub.add_parser("preflight", help="仅核对本地文件与引导记录")
    probe = sub.add_parser("probe", help="一次相机复位、RAM 引导和只读探测")
    probe.add_argument("--port", required=True)
    probe.add_argument("--output", type=Path, required=True)
    probe.add_argument("--confirm-reset", action="store_true", required=True)
    args = parser.parse_args()
    try:
        table, records = preflight(ROOT)
        if args.action != "probe":
            print(f"本地校验通过：{len(records)} 条引导记录。")
            return 0
        if sys.platform != "darwin" or re.fullmatch(r"/dev/cu\.usbmodem[0-9A-Za-z]+", args.port) is None:
            raise ProbeError("需要 macOS 上显式指定的 RP2040 USB 串口")
        report = run_probe(args.port, args.output.resolve(), table, records)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["usb_transport_verified"] else 1
    except (OSError, ValueError, ProbeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    sys.exit(main())
