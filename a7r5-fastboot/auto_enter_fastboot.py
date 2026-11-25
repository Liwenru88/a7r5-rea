#!/usr/bin/env python3
"""自动循环触发 A7R V RAM Fastboot，直至 USB 接口成功激活并验证 getvar:version (OKAY0.5)。"""

from __future__ import annotations

import argparse
import datetime as dt
import getpass
import json
import os
import signal
import subprocess
import sys
import threading
import time
from pathlib import Path

import r5_fastboot as r5
from manual_fastboot import find_rp2040_port, poll_uart_until_exit

SCRIPT_DIR = Path(__file__).resolve().parent
CONFIGURE_BIN = SCRIPT_DIR / "host/configure_fastboot_usb"
READER_BIN = SCRIPT_DIR / "host/read_fastboot_usb"


def release_stale_holders(port: str) -> list[int]:
    """仅终止当前用户残留的 manual_fastboot.py 或 auto_enter_fastboot.py 进程。"""
    result = subprocess.run(
        ["/usr/sbin/lsof", "-t", port],
        capture_output=True,
        text=True,
        check=False,
    )
    pids: list[int] = []
    for line in result.stdout.splitlines():
        try:
            pid = int(line.strip())
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        cmd = subprocess.run(
            ["/bin/ps", "-p", str(pid), "-o", "user=,command="],
            capture_output=True,
            text=True,
            check=False,
        ).stdout.strip()
        fields = cmd.split(None, 1)
        if len(fields) != 2 or fields[0] != getpass.getuser():
            raise r5.ProbeError(f"串口被非当前用户进程占用，未自动终止：PID {pid}")
        if not any(k in fields[1] for k in ("manual_fastboot.py", "auto_enter_fastboot.py")):
            raise r5.ProbeError(f"串口被其他程序占用，未自动终止：PID {pid} ({fields[1]})")
        os.kill(pid, signal.SIGTERM)
        pids.append(pid)
    if pids:
        time.sleep(0.5)
    return pids


def open_rp2040(port: str | None = None):
    target_port = port or find_rp2040_port()
    try:
        return r5.open_bridge(target_port, r5.ROOT), target_port, []
    except OSError as exc:
        if exc.errno != 35:
            raise
        released = release_stale_holders(target_port)
        return r5.open_bridge(target_port, r5.ROOT), target_port, released


def wait_for_uart_ready(bridge: r5.SerialBridge, timeout_sec: float = 2.2) -> tuple[bool, bytes]:
    deadline = time.monotonic() + timeout_sec
    collected = bytearray()
    while time.monotonic() < deadline:
        chunk = bridge.poll_uart()
        if chunk:
            collected.extend(chunk)
            if r5.UART_READY in collected:
                return True, bytes(collected)
        else:
            time.sleep(0.03)
    return (r5.UART_READY in collected), bytes(collected)


def verify_usb_active(bridge: r5.SerialBridge) -> tuple[bool, str]:
    """等待 USB 18d1:4ee0 出现，执行 configure_fastboot_usb 并验证 getvar:version == OKAY0.5。"""
    # 1. 等待 IOUSB 树出现 18d1:4ee0（最多 3.0 秒）
    deadline = time.monotonic() + 3.0
    present = False
    while time.monotonic() < deadline:
        bridge.poll_uart()
        try:
            res = subprocess.run(
                [str(CONFIGURE_BIN), "--check"],
                capture_output=True,
                text=True,
                timeout=0.6,
                check=False,
            )
            if res.returncode == 0:
                present = True
                break
        except subprocess.TimeoutExpired:
            pass
        time.sleep(0.2)

    if not present:
        return False, "IOUSB 未枚举出 18d1:4ee0"

    # 给 macOS 内核 0.25s 完成描述符读取与驱动匹配
    time.sleep(0.25)
    bridge.poll_uart()

    # 2. 尝试激活 USB Configuration (限时 4.5 秒，若卡住说明 EP0 挂死)
    try:
        cfg = subprocess.run(
            [str(CONFIGURE_BIN)],
            capture_output=True,
            text=True,
            timeout=4.5,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "configure_fastboot_usb 超时 (EP0 无响应)"

    cfg_out = (cfg.stdout or "") + (cfg.stderr or "")
    if cfg.returncode != 0:
        first_err = cfg_out.strip().splitlines()[-1] if cfg_out.strip() else f"exit={cfg.returncode}"
        return False, f"USB 配置未就绪 ({first_err})"

    # 3. 立即用 getvar:version 验证 Bulk 读写通道真正可用
    try:
        ver = subprocess.run(
            [str(READER_BIN), "getvar:version"],
            capture_output=True,
            text=True,
            timeout=4.0,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return False, "getvar:version 读取超时"

    ver_out = (ver.stdout or "") + (ver.stderr or "")
    if ver.returncode == 0 and "REPLY OKAY0.5" in ver_out:
        return True, "REPLY OKAY0.5"
    return False, f"getvar:version 校验未通过 ({ver_out.strip()})"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", help="指定 RP2040 串口（默认自动查找 0x2E8A）")
    parser.add_argument("--output", type=Path, help="输出目录（默认自动创建）")
    parser.add_argument(
        "--max-attempts",
        type=int,
        default=15,
        help="最大自动重试次数（默认 15 次）",
    )
    parser.add_argument(
        "--now",
        action="store_true",
        help="无需等待第一次回车，启动后立即开始自动触发重试",
    )
    args = parser.parse_args()

    if sys.platform != "darwin":
        raise SystemExit("需要在 macOS 上运行")

    _, records = r5.preflight(r5.ROOT, bootstrap=True)
    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = (args.output or (SCRIPT_DIR / "runs" / f"auto-fastboot-{ts}")).resolve()
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=False)

    serial_conn, actual_port, released = open_rp2040(args.port)
    print(f"已连接 RP2040 串口: {actual_port}")
    if released:
        print(f"已自动释放旧会话 PID: {released}")

    if not args.now:
        print("按一次回车后，脚本将自动循环触发复位并检测 USB 通信，直到相机红灯熄灭且 USB 激活成功。")
        input("准备好后按回车开始（Ctrl+C 取消）：")

    uart_log_path = out_dir / "uart.bin"
    attempts_log: list[dict] = []
    success_attempt = None

    try:
        with uart_log_path.open("xb") as uart_file:
            bridge = r5.SerialBridge(serial_conn, uart_file)

            for attempt in range(1, args.max_attempts + 1):
                print(f"\n--- [第 {attempt}/{args.max_attempts} 次尝试] 正在触发复位并注入 64 帧 SRAM 载荷 ---", flush=True)
                attempt_info = {
                    "attempt": attempt,
                    "uart_ready": False,
                    "usb_verified": False,
                    "detail": "",
                }
                try:
                    # 清理串口残留缓冲
                    serial_conn.reset_input_buffer()
                    serial_conn.reset_output_buffer()
                    bridge.pending_uart.clear()

                    step_report = {"records_acknowledged": 0}
                    r5.start_ram(bridge, records, step_report)
                except (OSError, r5.ProbeError) as exc:
                    attempt_info["detail"] = f"串口触发异常: {exc}"
                    attempts_log.append(attempt_info)
                    print(f"  ⚠️ {attempt_info['detail']}，1 秒后尝试重连 RP2040...", flush=True)
                    try:
                        serial_conn.close()
                    except OSError:
                        pass
                    time.sleep(1.0)
                    serial_conn, actual_port, _ = open_rp2040(args.port)
                    bridge.serial = serial_conn
                    continue

                uart_ok, uart_bytes = wait_for_uart_ready(bridge, timeout_sec=2.2)
                attempt_info["uart_ready"] = uart_ok
                if not uart_ok:
                    delay = round(0.7 + (attempt % 3) * 0.45, 2)
                    attempt_info["detail"] = f"未收到完整 [mira] fastboot ready (收到 {len(uart_bytes)} 字节)"
                    attempts_log.append(attempt_info)
                    print(
                        f"  ⏳ {attempt_info['detail']}，可能撞上相机重启周期；错相等待 {delay}s 后自动重试...",
                        flush=True,
                    )
                    time.sleep(delay)
                    continue

                print("  ✓ 已捕获 [mira] fastboot ready，正在检测并激活 Fastboot USB 接口...", flush=True)
                usb_ok, usb_detail = verify_usb_active(bridge)
                attempt_info["usb_verified"] = usb_ok
                attempt_info["detail"] = usb_detail
                attempts_log.append(attempt_info)

                if usb_ok:
                    success_attempt = attempt
                    print("\a", end="", flush=True)
                    print("\n============================================================", flush=True)
                    print(f"✅ 第 {attempt} 次尝试成功！Fastboot USB 已激活且读写通道验证正常 ({usb_detail})。")
                    print("   此时相机红灯应已闪烁一下后彻底熄灭。")
                    print("   请保持本终端开启，在另一终端运行 ./a7r5-fastboot/2_activate_usb.sh 或 ./a7r5-fastboot/3_trigger_sd_update.sh")
                    print("============================================================", flush=True)
                    break

                delay = round(0.8 + (attempt % 3) * 0.45, 2)
                print(
                    f"  ❌ USB 未能激活 ({usb_detail}) —— 相机处于红灯持续闪烁/EP0 挂死状态；错相等待 {delay}s 后自动重试...",
                    flush=True,
                )
                time.sleep(delay)

            if success_attempt is None:
                print(f"\n❌ 已达最大尝试次数 ({args.max_attempts} 次) 仍未激活 USB，请检查 Multi→USB-A 线缆连接或插拔重连。", flush=True)
                return 1

            # 保持 UART 监听直到用户按回车退出
            stop_event = threading.Event()
            report_state = {"uart_ready_observed": True}

            def reconnect_serial():
                conn, _, _ = open_rp2040(args.port)
                return conn

            poller = threading.Thread(
                target=poll_uart_until_exit,
                args=(bridge, stop_event, report_state, reconnect_serial),
                name="uart-poller",
                daemon=True,
            )
            poller.start()
            try:
                input("\n操作全部完成后，回到本终端按回车退出（或按 Ctrl+C）：")
            except (KeyboardInterrupt, EOFError):
                pass
            finally:
                stop_event.set()
                poller.join(timeout=1.0)
    finally:
        try:
            serial_conn.close()
        except OSError:
            pass
        summary = {
            "timestamp": ts,
            "port": actual_port,
            "success_attempt": success_attempt,
            "total_attempts": len(attempts_log),
            "attempts": attempts_log,
        }
        (out_dir / "report.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except KeyboardInterrupt:
        print("\n已手动取消。", file=sys.stderr)
        raise SystemExit(130)
