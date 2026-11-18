#!/usr/bin/env python3
"""手动触发 A7R V RAM Fastboot，并在进入后保持桥接连接。"""

from __future__ import annotations

import argparse
import getpass
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import r5_fastboot as r5


PORT_PATTERN = re.compile(r"/dev/cu\.usbmodem[0-9A-Za-z]+")


def find_rp2040_port() -> str:
    """Automatically find the unique RP2040 USB serial port."""
    wheel = (r5.ROOT / r5.WHEEL).resolve()
    sys.path.insert(0, str(wheel))
    try:
        from serial.tools import list_ports
    except ImportError as exc:
        raise r5.ProbeError(f"无法加载 pySerial：{exc}") from exc

    candidates = [
        port.device
        for port in list_ports.comports()
        if port.vid == 0x2E8A
        and port.device.startswith("/dev/cu.usbmodem")
    ]
    if len(candidates) == 1:
        return candidates[0]
    if not candidates:
        raise r5.ProbeError("没有自动找到 RP2040 串口，请确认设备已连接并运行桥接固件")
    raise r5.ProbeError(
        "自动找到多个 RP2040 串口，请使用 --port 明确指定：" + ", ".join(candidates)
    )


def release_stale_manual_process(port: str) -> list[int]:
    """Terminate only same-user manual_fastboot.py holders of the port."""
    result = subprocess.run(
        ["/usr/sbin/lsof", "-t", port],
        capture_output=True,
        text=True,
        check=False,
    )
    pids = []
    for line in result.stdout.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        command = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "user=,command="],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        fields = command.split(None, 1)
        if len(fields) != 2 or fields[0] != getpass.getuser():
            raise r5.ProbeError(f"串口被非当前用户进程占用，未自动终止：PID {pid}")
        if "manual_fastboot.py" not in fields[1]:
            raise r5.ProbeError(f"串口被其他程序占用，未自动终止：PID {pid}")
        os.kill(pid, signal.SIGTERM)
        pids.append(pid)
    if pids:
        time.sleep(0.5)
    return pids


def open_bridge_with_optional_release(port: str, auto_release: bool):
    """Open RP2040 exclusively, optionally releasing stale same-user sessions."""
    try:
        return r5.open_bridge(port, r5.ROOT), []
    except OSError as exc:
        if exc.errno != 35 or not auto_release:
            raise
        released = release_stale_manual_process(port)
        return r5.open_bridge(port, r5.ROOT), released


def poll_uart_until_exit(
    bridge: r5.SerialBridge,
    stop: threading.Event,
    report: dict,
    reconnect=None,
) -> None:
    """持续转发 UART；USB 重枚举后只重连监听，不重复引导。"""
    while not stop.is_set():
        try:
            observed = bridge.poll_uart()
            if r5.UART_READY in observed:
                report["uart_ready_observed"] = True
            if not observed:
                time.sleep(0.05)
        except OSError as exc:
            if exc.errno not in (5, 6) or reconnect is None:
                report.setdefault("uart_capture_error", str(exc))
                stop.set()
                continue
            try:
                old_serial = bridge.serial
                old_serial.close()
                new_serial = reconnect()
                bridge.serial = new_serial
                report["serial_reconnected"] = True
                report["serial_reconnect_attempts"] = report.get("serial_reconnect_attempts", 0) + 1
            except (OSError, r5.ProbeError) as reconnect_error:
                report.setdefault("uart_capture_error", str(reconnect_error))
                stop.set()
        except r5.ProbeError as exc:
            report.setdefault("uart_capture_error", str(exc))
            stop.set()


def run_manual(port: str, output: Path, wait_for_enter=input, auto_release: bool = False) -> dict:
    """等待用户确认后只执行一次复位和 RAM 引导，不运行 USB 分析。"""
    table, records = r5.preflight(r5.ROOT)
    del table  # 该入口只需要预检返回的引导记录。

    output.mkdir(mode=0o700, parents=True, exist_ok=False)
    report = {
        "stage": "bridge_ping",
        "reset_attempted": False,
        "reset_acknowledged": False,
        "records_acknowledged": 0,
        "ram_payload_sent": False,
        "fastboot_entry_requested": False,
        "uart_ready_observed": False,
        "usb_analysis_started": False,
        "exit_reason": None,
    }
    uart_log = output / "uart.bin"
    stop = threading.Event()
    poller = None
    reconnected_serials = []

    def reconnect_serial():
        reconnect_port = find_rp2040_port()
        serial, _ = open_bridge_with_optional_release(reconnect_port, auto_release)
        reconnected_serials.append(serial)
        report["serial_reconnect_port"] = reconnect_port
        return serial

    try:
        serial, released_pids = open_bridge_with_optional_release(port, auto_release)
        report["released_stale_pids"] = released_pids
        with serial, uart_log.open("xb") as uart:
            bridge = r5.SerialBridge(serial, uart)
            if bridge.command(1) != b"uart_boot 1":
                raise r5.ProbeError("RP2040 桥接版本不符")

            report["stage"] = "waiting_for_trigger"
            print("本地校验和 RP2040 检查通过。", flush=True)
            print("按回车后将只执行一次相机复位并发送完整 RAM payload。", flush=True)
            print("脚本不会自动执行 USB 分区读取、写入、擦除或重启。", flush=True)
            wait_for_enter("准备好后按回车触发；Ctrl+C 取消：")

            report["fastboot_entry_requested"] = True
            report["stage"] = "reset_and_boot_records"
            r5.start_ram(bridge, records, report)
            report["ram_payload_sent"] = True
            report["stage"] = "fastboot_waiting"
            print("RAM payload 已发送，正在保持连接。", flush=True)
            print("现在可以在其他终端手动分析 Fastboot；完成后回到这里按回车退出。", flush=True)

            poller = threading.Thread(
                target=poll_uart_until_exit,
                args=(bridge, stop, report, reconnect_serial),
                name="uart-poller",
                daemon=True,
            )
            poller.start()
            try:
                wait_for_enter("分析完成后按回车退出；Ctrl+C 也可退出：")
                report["exit_reason"] = "enter"
            except (KeyboardInterrupt, EOFError):
                report["exit_reason"] = "cancelled"
            finally:
                stop.set()
                poller.join(timeout=1.0)

            report["stage"] = "complete"
    except (KeyboardInterrupt, EOFError):
        report["exit_reason"] = "cancelled"
        report["stage"] = "cancelled"
    except Exception as exc:
        report["error"] = str(exc)
        report["stage"] = "failed"
    finally:
        stop.set()
        if poller is not None:
            poller.join(timeout=1.0)
        for reconnected_serial in reconnected_serials:
            try:
                reconnected_serial.close()
            except OSError:
                pass
        if uart_log.is_file():
            try:
                report["uart_ready_observed"] = (
                    report["uart_ready_observed"]
                    or r5.UART_READY in uart_log.read_bytes()
                )
            except OSError as exc:
                report.setdefault("uart_capture_error", str(exc))
        (output / "report.json").write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n"
        )

    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--port",
        help="RP2040 串口；省略时自动查找唯一的 RP2040 串口",
    )
    parser.add_argument("--output", type=Path, required=True, help="新的输出目录")
    parser.add_argument(
        "--auto-release-port",
        action="store_true",
        help="仅自动终止当前用户的旧 manual_fastboot.py 串口占用者",
    )
    parser.add_argument(
        "--confirm-reset",
        action="store_true",
        required=True,
        help="明确确认脚本会触发一次相机复位",
    )
    args = parser.parse_args()

    try:
        if sys.platform != "darwin":
            raise r5.ProbeError("需要在 macOS 上运行")
        port = args.port or find_rp2040_port()
        if PORT_PATTERN.fullmatch(port) is None:
            raise r5.ProbeError("需要 macOS 上的 /dev/cu.usbmodem* RP2040 串口")
        print(f"使用 RP2040 串口：{port}", flush=True)
        report = run_manual(
            port, args.output.resolve(), auto_release=args.auto_release_port
        )
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["stage"] == "complete" else 1
    except (OSError, ValueError, r5.ProbeError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    sys.exit(main())
