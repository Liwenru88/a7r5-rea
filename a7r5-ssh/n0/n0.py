#!/usr/bin/env python3
"""N0 单地址补证：默认离线；显式批准后仅连接一次 TCP 22，不登录。"""
import argparse
import errno
import hashlib
import ipaddress
import json
import math
import os
from pathlib import Path
import re
import shlex
import stat
import sys
import time
import uuid

SOURCE = Path(__file__).resolve()
PACKAGES = SOURCE.parent / "packages"
RISK = "仅一个明确IPv4的TCP22连接及至多256字节标识读取；不发送SSH应用数据、不认证或登录、不扫描。可选ICMP仅在已批准且TCP拒绝或超时时发送一包；不操作USB、相机文件或菜单；一次尝试后保留锁，不重试。"
READINESS = ("camera_screen_normal", "independent_power", "address_current", "same_network",
             "menus_checked", "usb_handling_complete", "no_error_prompt")
LIMITS = dict(port=22, connect_seconds=5, read_seconds=2, total_seconds=12,
              max_banner_bytes=256, ping_process_seconds=3, ping_packets=1)


def regular(path):
    path = Path(path).absolute()
    if path.is_relative_to("/dev") or any(p.is_symlink() for p in (path, *path.parents)):
        raise ValueError("拒绝设备或符号链接路径")
    if not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("仅接受本机普通文件")
    return path


def digest(path):
    with regular(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def save(path, value):
    with Path(path).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def target(address, prefix, source, mode, usb, icmp=False):
    if not isinstance(address, str) or type(prefix) is not int or not 1 <= prefix <= 30:
        raise ValueError("须提供单个标准IPv4和明确的1–30前缀长度")
    ip = ipaddress.IPv4Address(address)
    network = ipaddress.IPv4Network((ip, prefix), strict=False)
    private = tuple(ipaddress.IPv4Network(n) for n in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16"))
    if address != str(ip) or not any(network.subnet_of(n) for n in private):
        raise ValueError("只接受RFC1918内网的数字IPv4，不接受域名、范围或特殊地址")
    if ip in (network.network_address, network.broadcast_address):
        raise ValueError("拒绝该子网的网络地址和广播地址")
    if source not in ("camera-screen", "router-lease"):
        raise ValueError("地址须来自当前机身界面或受控路由器租约")
    if mode not in ("access-point", "wifi-direct"):
        raise ValueError("须明确正常联网角色")
    if usb not in ("disconnected", "mass-storage", "connected-mode-unconfirmed") or type(icmp) is not bool:
        raise ValueError("USB状态或ICMP范围不符")
    return dict(address=address, prefix_length=prefix, address_source=source,
                network_mode=mode, usb_state=usb, icmp_fallback=icmp)


def normalized(value):
    fixed = target(value["address"], value["prefix_length"], value["address_source"],
                   value["network_mode"], value["usb_state"], value["icmp_fallback"])
    if value != fixed:
        raise ValueError("目标字段集合不符")
    return fixed


def directory_checked(directory):
    directory = Path(directory).absolute()
    if directory.parent != PACKAGES or not re.fullmatch(r"[a-z0-9][a-z0-9-]{0,63}", directory.name):
        raise ValueError("仅接受本入口packages内的新一次性目录")
    if any(p.is_symlink() for p in (directory, *directory.parents)):
        raise ValueError("操作目录不能经过符号链接")
    return directory


def prepare(name, value):
    value = normalized(value)
    directory = directory_checked(PACKAGES / name)
    PACKAGES.mkdir(parents=True, exist_ok=True, mode=0o700)
    directory.mkdir(mode=0o700, exist_ok=False)
    python = Path(sys.executable).absolute()
    command = ("#!/bin/bash\n# 不生成批准，不请求管理员权限；缺少批准即停止。\nset -euo pipefail\nexec "
               + shlex.quote(str(python)) + " -I -B " + shlex.quote(str(SOURCE))
               + " run --operation " + shlex.quote(str(directory)) + " --network-io\n")
    launcher = directory / "run-n0.command"
    with launcher.open("x") as stream:
        stream.write(command)
    launcher.chmod(0o700)
    runtime = {str(python.resolve()): digest(python.resolve())}
    if value["icmp_fallback"]:
        runtime["/sbin/ping"] = digest("/sbin/ping")
    plan = dict(schema="a7r5-n0-plan-1", run_id=uuid.uuid4().hex, directory=str(directory),
                source=str(SOURCE), source_sha256=digest(SOURCE), target=value, limits=LIMITS,
                runtime=runtime, launcher_sha256=digest(launcher), risk=RISK,
                camera_protocol_enabled=False, ssh_authentication_enabled=False,
                camera_file_writes_enabled=False, automatic_usb_actions=False)
    save(directory / "plan.json", plan)
    save(directory / "approval-template.json", approval(directory))
    return directory


def check(directory):
    directory = directory_checked(directory)
    plan = json.loads(regular(directory / "plan.json").read_text())
    if directory.stat().st_mode & 0o077:
        raise PermissionError("新操作目录必须仅本机用户可访问")
    value = normalized(plan["target"])
    expected = dict(schema="a7r5-n0-plan-1", run_id=plan["run_id"], directory=str(directory),
                    source=str(SOURCE), source_sha256=digest(SOURCE), target=value, limits=LIMITS,
                    runtime={str(Path(sys.executable).resolve()): digest(Path(sys.executable).resolve())},
                    launcher_sha256=digest(directory / "run-n0.command"), risk=RISK,
                    camera_protocol_enabled=False, ssh_authentication_enabled=False,
                    camera_file_writes_enabled=False, automatic_usb_actions=False)
    if value["icmp_fallback"]:
        expected["runtime"]["/sbin/ping"] = digest("/sbin/ping")
    if plan != expected or not re.fullmatch("[0-9a-f]{32}", plan["run_id"]):
        raise ValueError("目标、来源、脚本、解释器或运行范围已变化")
    return plan


def approval(directory, accepted=False, now=None):
    plan = check(directory)
    issued = time.time() if now is None else now
    return dict(schema="a7r5-n0-approval-1", run_id=plan["run_id"],
                plan_sha256=digest(Path(directory) / "plan.json"), accepted=accepted,
                risk=RISK, readiness={name: accepted for name in READINESS},
                approved_at_unix=issued if accepted else None,
                expires_at_unix=issued + 900 if accepted else None,
                camera_protocol=False, ssh_authentication=False, camera_file_writes=False)


def checked_approval(directory):
    plan = check(directory)
    directory = Path(directory)
    value = json.loads(regular(directory / "approval.json").read_text())
    if value.get("accepted") is not True or any(value.get("readiness", {}).get(n) is not True for n in READINESS):
        raise PermissionError("没有本次明确批准或准备状态不全")
    issued, expires = value.get("approved_at_unix"), value.get("expires_at_unix")
    if any(type(n) not in (int, float) or not math.isfinite(n) for n in (issued, expires)):
        raise PermissionError("缺少本次明确批准和准备状态")
    if value != approval(directory, True, issued) or not issued <= time.time() <= expires:
        raise PermissionError("批准未接受、准备状态不全、目标不符或已超过15分钟")
    if (directory / "ATTEMPT_LOCK").exists() or (directory / "attempt.json").exists() or (directory / "result.json").exists():
        raise FileExistsError("本包已有尝试，不重试、不删除旧锁")
    return plan


def identification(raw):
    # 保留原始十六进制，终端仅显示转义后的JSON，拒绝控制字符。
    for line in raw.splitlines(keepends=True):
        if line.startswith(b"SSH-") and line.endswith(b"\n"):
            if len(line) > 255 or not re.fullmatch(rb"SSH-(2\.0|1\.99)-[!-~]+(?: [ -~]*)?\r\n", line):
                raise ValueError("SSH标识格式不符")
            return line[:-2].decode("ascii")
    if any(c not in (10, 13) and not 32 <= c <= 126 for c in raw):
        raise ValueError("标识含非预期控制字节")
    return None


def probe(plan, result, socket_factory=None, ping_runner=None):
    # 仅在批准、开关和一次性锁全部通过后才加载网络/子进程后端。
    import socket
    import subprocess
    factory = socket.socket if socket_factory is None else socket_factory
    runner = subprocess.run if ping_runner is None else ping_runner
    value = plan["target"]
    deadline = time.monotonic() + LIMITS["total_seconds"]
    started = time.monotonic()
    connection = None
    raw = b""
    try:
        connection = factory(socket.AF_INET, socket.SOCK_STREAM)
        connection.settimeout(min(LIMITS["connect_seconds"], deadline - time.monotonic()))
        result["tcp_connect_attempted"] = True
        try:
            connection.connect((value["address"], 22))
        except (TimeoutError, OSError) as exc:
            code = getattr(exc, "errno", None)
            expected = isinstance(exc, TimeoutError) or code in (errno.ECONNREFUSED, errno.ETIMEDOUT)
            status = "TCP_REFUSED" if code == errno.ECONNREFUSED else "TCP_TIMEOUT" if expected else "CONNECT_FAILED"
            result.update(outcome=status, connect_error=type(exc).__name__, connect_errno=code)
            connection.close()
            connection = None
            if not expected or not value["icmp_fallback"]:
                return
            remaining = min(LIMITS["ping_process_seconds"], deadline - time.monotonic())
            if remaining <= 0:
                result["outcome"] = "DEADLINE_EXCEEDED"
                return
            result["icmp_attempted"] = True
            try:
                ping = runner(["/sbin/ping", "-n", "-c", "1", "-W", "1000", "-t", "2", value["address"]],
                              capture_output=True, timeout=remaining, check=False)
            except subprocess.TimeoutExpired:
                result["outcome"] = "ICMP_PROCESS_TIMEOUT"
                return
            result["icmp_exit_code"] = ping.returncode
            if len(ping.stdout) + len(ping.stderr) > 4096:
                result["outcome"] = "ICMP_OUTPUT_EXCEEDED"
                return
            result["icmp_stdout_hex"] = ping.stdout.hex()
            result["icmp_stderr_hex"] = ping.stderr.hex()
            if ping.returncode == 0:
                result.update(outcome="ICMP_REPLY_" + status, execution_succeeded=True,
                              reachability_supported=True)
            else:
                result["outcome"] = "ICMP_NO_REPLY_" + status
            return
        result.update(tcp_connected=True, reachability_supported=True,
                      outcome="TCP_CONNECTED_NO_IDENTIFICATION", execution_succeeded=True)
        read_deadline = min(deadline, time.monotonic() + LIMITS["read_seconds"])
        while len(raw) < LIMITS["max_banner_bytes"]:
            remaining = read_deadline - time.monotonic()
            if remaining <= 0:
                return
            connection.settimeout(remaining)
            try:
                chunk = connection.recv(LIMITS["max_banner_bytes"] - len(raw))
            except TimeoutError:
                return
            except OSError as exc:
                result.update(outcome="READ_FAILED", execution_succeeded=False,
                              read_error=type(exc).__name__, read_errno=exc.errno)
                return
            if not chunk:
                if raw:
                    result.update(outcome="UNEXPECTED_IDENTIFICATION", execution_succeeded=False)
                return
            raw += chunk
            try:
                banner = identification(raw)
            except ValueError:
                result.update(outcome="UNEXPECTED_IDENTIFICATION", execution_succeeded=False)
                return
            if banner:
                result.update(outcome="TCP_CONNECTED_SSH_IDENTIFICATION", ssh_identification=banner)
                return
        result.update(outcome="UNEXPECTED_IDENTIFICATION", execution_succeeded=False)
    finally:
        result["banner_raw_hex"] = raw.hex()
        result["network_elapsed_seconds"] = round(time.monotonic() - started, 6)
        if connection is not None:
            connection.close()


def execute(directory, network_io=False, *, socket_factory=None, ping_runner=None):
    if not network_io:
        raise PermissionError("默认离线；缺少显式联网开关")
    directory = Path(directory).absolute()
    plan = checked_approval(directory)
    if sys.platform != "darwin":
        raise PermissionError("此入口只支持已核对的macOS参数")
    (directory / "ATTEMPT_LOCK").mkdir(mode=0o700)
    result = dict(schema="a7r5-n0-result-1", run_id=plan["run_id"], target=plan["target"],
                  plan_sha256=digest(directory / "plan.json"), approval_sha256=digest(directory / "approval.json"),
                  started_at_unix=time.time(), execution_succeeded=False, reachability_supported=False,
                  outcome="NOT_STARTED", tcp_connect_attempted=False, tcp_connected=False,
                  icmp_attempted=False, banner_raw_hex="", application_bytes_sent=0,
                  ssh_authentication_attempted=False, ssh_login_verified=False,
                  camera_identity_cryptographically_verified=False, camera_file_writes=False,
                  usb_actions=False, screen_confirmation_pending=True, acceptance_complete=False)
    save(directory / "attempt.json", dict(run_id=plan["run_id"], plan_sha256=result["plan_sha256"],
                                         approval_sha256=result["approval_sha256"], started_at_unix=result["started_at_unix"]))
    try:
        probe(plan, result, socket_factory, ping_runner)
    except (Exception, KeyboardInterrupt) as exc:
        result.update(outcome="STOPPED", execution_succeeded=False, error_type=type(exc).__name__,
                      error=str(exc)[:240])
    result["completed_at_unix"] = time.time()
    save(directory / "result.json", result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("prepare", help="只准备本机材料，不联网")
    p.add_argument("--name", required=True)
    p.add_argument("--address", required=True)
    p.add_argument("--prefix-length", required=True, type=int)
    p.add_argument("--address-source", required=True, choices=("camera-screen", "router-lease"))
    p.add_argument("--network-mode", required=True, choices=("access-point", "wifi-direct"))
    p.add_argument("--usb-state", required=True, choices=("disconnected", "mass-storage", "connected-mode-unconfirmed"))
    p.add_argument("--icmp-fallback", action="store_true")
    for command in ("check", "run"):
        p = sub.add_parser(command)
        p.add_argument("--operation", required=True, type=Path)
        if command == "run":
            p.add_argument("--network-io", action="store_true")
    args = parser.parse_args()
    if args.action == "prepare":
        value = target(args.address, args.prefix_length, args.address_source, args.network_mode, args.usb_state, args.icmp_fallback)
        output = {"prepared": str(prepare(args.name, value)), "network_executed": False}
    elif args.action == "check":
        output = check(args.operation)
    else:
        output = execute(args.operation, args.network_io)
    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 3 if args.action == "run" and not output["execution_succeeded"] else 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (Exception, KeyboardInterrupt) as exc:
        print("停止：" + type(exc).__name__ + ": " + str(exc), file=sys.stderr)
        raise SystemExit(2)
