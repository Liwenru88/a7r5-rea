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
    # 与 assets/bridge-verification.json 一致的 Waveshare RP2040-Zero OPEN_DRAIN 通用桥接固件
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


def preflight(root, bootstrap=False):
    pins = dict(ASSET_PINS)
    if bootstrap:
        pins.pop(SDM2)
    elif (root / SDM2).is_file() and (root / "local-backup-sdm2.sha256").is_file():
        local = (root / "local-backup-sdm2.sha256").read_text().strip()
        if len(local) != 64 or any(c not in "0123456789abcdef" for c in local):
            raise ProbeError("本机 SDM2 参考摘要格式错误")
        pins[SDM2] = local
    host_file = root / "host-sha256.local.json"
    if not host_file.is_file():
        host_file = root / "host-sha256.json"
    host_pins = json.loads(host_file.read_text())
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
    return inputs.get(SDM2), records


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
        observed = bytearray()
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
            observed.extend(content)
        self.uart.flush()
        return bytes(observed)


def start_ram(bridge, records, report, sleep=time.sleep, before_reset=None):
    if bridge.command(1) != b"uart_boot 1":
        raise ProbeError("RP2040 桥接版本不符")
    if before_reset is not None:
        report["stage"] = "waiting_for_trigger"
        before_reset()
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


USB_POLL_TIMEOUT = 0.5
USB_CONFIGURATION_TIMEOUT = 15


def probe_usb(root, run, table, report, bridge, launch=run_logged, sleep=time.sleep):
    report["stage"] = "usb_enumeration"
    deadline = time.monotonic() + 15
    while (left := deadline - time.monotonic()) > 0:
        try:
            try:
                result = launch(root / CONFIGURE, ["--check"], run / "usb-presence.log",
                                min(USB_POLL_TIMEOUT, left))
            except subprocess.TimeoutExpired:
                # 仅重试注册表检查；这里不打开或配置设备。
                result = 2
        finally:
            if bridge is not None and "uart_capture_error" not in report:
                try:
                    observed = bridge.poll_uart()
                    if UART_READY in observed:
                        report["uart_ready_observed"] = True
                except (OSError, ProbeError) as exc:
                    report["uart_capture_error"] = str(exc)
        if result == 0:
            break
        if result != 2:
            raise ProbeError(f"USB 枚举检查失败：{result}")
        sleep(0.2)
    else:
        raise ProbeError("15 秒内未枚举 Fastboot")

    report["stage"] = "usb_configuration"
    try:
        result = launch(root / CONFIGURE, [], run / "usb-config.log", USB_CONFIGURATION_TIMEOUT)
    except subprocess.TimeoutExpired as exc:
        # 配置超时后状态未知，不重新配置或重新引导。
        raise ProbeError("USB 配置超时；已停止，未自动重试") from exc
    finally:
        if bridge is not None and "uart_capture_error" not in report:
            try:
                observed = bridge.poll_uart()
                if UART_READY in observed:
                    report["uart_ready_observed"] = True
            except (OSError, ProbeError) as exc:
                report["uart_capture_error"] = str(exc)
    if result != 0:
        raise ProbeError(f"USB 配置失败：{result}；已停止，未自动重试")

    report["stage"] = "partition_listing"
    log = run / "usb-layout.log"
    if launch(root / READER, ["getvar:version", "oem partition"], log, 8) != 0:
        raise ProbeError("Fastboot 协议或分区表查询失败")
    listing = log.read_text(errors="replace")
    version = listing.split("COMMAND oem partition\n", 1)[0].split("COMMAND getvar:version\n", 1)
    if len(version) != 2 or version[1].splitlines() != ["REPLY OKAY0.5"]:
        raise ProbeError("Fastboot 协议未返回 OKAY0.5")
    if table is None:
        (run / "sdm2.layout.txt").write_text(listing)
        report["layout_captured"] = True
    else:
        verify_listing(listing, expected_layout(table))
        report["layout_matches_reference"] = True

    report["stage"] = "sdm2_readback"
    current = run / "sdm2.raw.bin"
    if launch(root / READER, [TABLE_DUMP, "upload:" + str(current)], run / "usb-sdm2.log", 8) != 0:
        raise ProbeError("SDM2 回读失败")
    if table is None:
        (root / SDM2).write_bytes(current.read_bytes())
        (root / "local-backup-sdm2.sha256").write_text(digest(current.read_bytes()) + "\n")
        report["sdm2_reference"] = "captured"
    else:
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


def run_probe(port, run, table, records, opener=open_bridge, launch=run_logged, sleep=time.sleep,
              before_reset=None):
    run.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = dict(stage="bridge_ping", reset_attempted=False, reset_acknowledged=False,
                  records_acknowledged=0, usb_transport_verified=False, layout_matches_reference=False,
                  sdm2_matches_reference=False, same_physical_body_verified=False,
                  persistent_write_commands_sent=False, uart_ready_observed=False)
    uart_log = run / "uart.bin"
    try:
        with opener(port, ROOT) as serial, uart_log.open("xb") as uart:
            bridge = SerialBridge(serial, uart)
            start_ram(bridge, records, report, sleep, before_reset)
            probe_usb(ROOT, run, table, report, bridge, launch, sleep)
    except (KeyboardInterrupt, EOFError):
        report["interrupted_stage"] = report["stage"]
        report["stage"] = "cancelled"
        report["error"] = "操作已取消；若已触发复位，取消不会撤销相机状态变化"
    except Exception as exc:
        report["error"] = str(exc)
    if uart_log.is_file():
        try:
            report["uart_ready_observed"] = UART_READY in uart_log.read_bytes()
        except OSError as exc:
            report.setdefault("uart_capture_error", str(exc))
    (run / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def run_usb_check(run, table, launch=run_logged, sleep=time.sleep):
    """只验证现有 USB 会话，不打开串口，不发送复位或引导记录。"""
    run.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = dict(stage="usb_enumeration", reset_attempted=False, serial_opened=False,
                  persistent_write_commands_sent=False, usb_transport_verified=False,
                  stable_communication_verified=False, layout_matches_reference=False,
                  sdm2_matches_reference=False, same_physical_body_verified=False,
                  stability_samples=0)
    try:
        probe_usb(ROOT, run, table, report, None, launch, sleep)
        report["stage"] = "usb_stability"
        started = time.monotonic()
        # 13 次查询之间等待 12×5 秒，至少观察一分钟，不在失败后重配或重试。
        for index in range(13):
            if index:
                sleep(5)
            log = run / f"stability-version-{index + 1:02d}.log"
            if launch(ROOT / READER, ["getvar:version"], log, 8) != 0:
                raise ProbeError(f"第 {index + 1} 次稳定性查询失败；已停止")
            reply = log.read_text(errors="replace").split("COMMAND getvar:version\n", 1)
            if len(reply) != 2 or reply[1].splitlines() != ["REPLY OKAY0.5"]:
                raise ProbeError(f"第 {index + 1} 次稳定性查询协议回执异常")
            report["stability_samples"] = index + 1
        report["stability_elapsed_seconds"] = time.monotonic() - started
        report["stage"] = "sdm2_repeat_readback"
        repeat = run / "sdm2.repeat.raw.bin"
        if launch(ROOT / READER, [TABLE_DUMP, "upload:" + str(repeat)],
                  run / "usb-sdm2-repeat.log", 8) != 0:
            raise ProbeError("第二次 SDM2 回读失败")
        if repeat.read_bytes() != (run / "sdm2.raw.bin").read_bytes():
            raise ProbeError("两次 SDM2 回读不一致")
        report.update(stage="complete", stable_communication_verified=True,
                      repeated_sdm2_sha256=digest(repeat.read_bytes()))
    except KeyboardInterrupt:
        report["interrupted_stage"] = report["stage"]
        report.update(stage="cancelled", error="USB 检查已取消")
    except Exception as exc:
        report["error"] = str(exc)
    (run / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return report


def wait_for_trigger():
    print("本地校验和 RP2040 检查通过。请保持相机 ON、连接稳定，并确认更新已停止。", flush=True)
    print("仅执行一次复位、RAM 引导及只读诊断；不刷写、不擦除、不自动重试。", flush=True)
    input("准备好后按回车触发；Ctrl+C 取消：")
    print("已触发：正在复位相机并发送 RAM 载荷，请勿拔插。", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action")
    pre = sub.add_parser("preflight", help="仅核对本地文件与引导记录")
    pre.add_argument("--bootstrap", action="store_true",
                     help="首次会话：跳过 SDM2 参考，probe 时把本次回读记录为参考")
    usb_check = sub.add_parser("usb-check", help="检查现有 USB 会话；不复位、不打开串口、不写分区")
    usb_check.add_argument("--output", type=Path, required=True)
    probe = sub.add_parser("probe", help="一次相机复位、RAM 引导和只读探测")
    probe.add_argument("--port", required=True)
    probe.add_argument("--output", type=Path, required=True)
    probe.add_argument("--confirm-reset", action="store_true", required=True)
    probe.add_argument("--bootstrap", action="store_true",
                       help="首次会话：无 SDM2 参考时，把本次回读记录为参考")
    probe.add_argument("--wait-for-enter", action="store_true",
                       help="打开并检查桥接后等待回车，再复位并引导一次；Ctrl+C 取消")
    args = parser.parse_args()
    try:
        bootstrap = bool(getattr(args, "bootstrap", False))
        if bootstrap and args.action == "usb-check":
            raise ProbeError("usb-check 需要已有 SDM2 参考；不要在 bootstrap 会话使用")
        table, records = preflight(ROOT, bootstrap=bootstrap)
        if args.action == "usb-check":
            if sys.platform != "darwin":
                raise ProbeError("需要 macOS USB 工具")
            report = run_usb_check(args.output.resolve(), table)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0 if report["stable_communication_verified"] else 1
        if args.action != "probe":
            print(f"本地校验通过：{len(records)} 条引导记录。")
            return 0
        if sys.platform != "darwin" or re.fullmatch(r"/dev/cu\.usbmodem[0-9A-Za-z]+", args.port) is None:
            raise ProbeError("需要 macOS 上显式指定的 RP2040 USB 串口")
        report = run_probe(args.port, args.output.resolve(), table, records,
                           before_reset=wait_for_trigger if args.wait_for_enter else None)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["usb_transport_verified"] else 1
    except (OSError, ValueError, ProbeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    sys.exit(main())
