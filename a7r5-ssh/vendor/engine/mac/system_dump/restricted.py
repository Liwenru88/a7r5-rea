"""一次性受限部署协议；导入和准备均不打开 USB，不提供任意命令通道。"""
import hashlib
import json
import os
from pathlib import Path
import struct
import time
import uuid

from .core import MIB, validate_run
from .preflight import BASELINE_VERSION_SHA256, wire_path
from .session import FileResultError
from .usb_adapter import HEADER

neutral = b"\n" * 512
MAX_ARTIFACT = 128 * 1024
MAX_METADATA = 64 * 1024


class WorkerFailure(RuntimeError):
    def __init__(self, phase, code):
        self.unmounted = phase in ("FAILED_UNMOUNTED", "EXPIRED_UNMOUNTED")
        super().__init__(f"工作进程 {phase}，退出码 {code}；未完成转存")


def validate_mounts(text, card, prefix):
    rows = [line.split() for line in text.splitlines()]
    def mounted(path, source, filesystem):
        matches = [row for row in rows if len(row) >= 4 and row[1] == path]
        return len(matches) == 1 and matches[0][:3] == [source, path, filesystem]
    if (not mounted("/tmp/jiritsu", "/dev/nflasha6", "vfat")
            or not mounted("/etc", "/dev/nflasha10", "vfat")
            or not mounted("/tmp", "/dev/nflasha10", "vfat")
            or not mounted(prefix+".sd", card, "ext2")):
        raise ValueError("运行时挂载映射与审查假设不符；停止，不猜测或改挂另一张卡")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def save_json(path, value):
    # 先刷盘临时文件，再替换状态，保证 DEBUG 之前留下尝试记录。
    temporary = path.with_suffix(".new")
    with temporary.open("w") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def layout128(capacity_bytes, sector_bytes=512):
    if type(capacity_bytes) is not int or sector_bytes != 512:
        raise ValueError("本方案仅适配实测的 512 字节逻辑扇区")
    if not 16_000_000_000 <= capacity_bytes <= (2 << 40):
        raise ValueError("本方案要求至少 16 GB，且不超过 MBR 边界")
    first = 2048
    second = first + (8 << 30) // 512
    end = capacity_bytes // MIB * (MIB // 512)
    if end - second < (4 << 30) // 512:
        raise ValueError("ext2 区不足 4 GiB")
    return {"scheme": "MBR", "sector_bytes": 512, "capacity_bytes": capacity_bytes,
            "execution_enabled": False,
            "partitions": [
                {"number": 1, "type": "0x07", "filesystem": "exFAT", "label": "A7R5CAM",
                 "start_lba": first, "end_lba_exclusive": second, "bytes": 8 << 30},
                {"number": 2, "type": "0x83", "filesystem": "ext2", "label": "A7R5DUMP",
                 "start_lba": second, "end_lba_exclusive": end, "bytes": (end-second)*512}],
            "pending": ["真实整卡身份、容量、512 字节扇区及读卡器", "单独确认清空整卡后才可格式化"]}


def approve(value, bundle_sha):
    required = ("camera_writes", "debug_once", "unknown_preload_overwrite",
                "neutral_file_residue", "card_dump_writes", "failure_recovery_limits")
    if (not isinstance(value, dict) or value.get("schema") != "a7r5-dump-approval-1"
            or value.get("bundle_sha256") != bundle_sha
            or any(value.get(k) is not True for k in required)):
        raise PermissionError("缺少绑定本次材料的明确实机批准；未知预加载覆盖必须单独接受")
    return value


class RestrictedChannel:
    """选路径与操作在同一调用绑定；只接受本次固定读/写字节。"""
    def __init__(self, driver, writes, reads, log):
        self.driver, self.writes, self.reads, self.log = driver, dict(writes), dict(reads), log
        self.sequence, self.usable, self.debug_attempted = 1, True, False
        self.remaining = 20000

    def exchange(self, body, limit):
        if not self.usable or self.remaining <= 0 or self.sequence > 65535:
            raise PermissionError("通道已失败或请求上限耗尽")
        self.usable = False
        self.remaining -= 1
        self.driver.write(HEADER.pack(len(body), 0x40, self.sequence, 0, 0, 0, 0) + body)
        raw = self.driver.read(HEADER.size)
        self.log("dump_response_header", raw_hex=raw.hex(), sequence=self.sequence, limit=limit)
        if len(raw) != HEADER.size: raise ValueError("响应头长度错误")
        size, function, sequence, version, micon, offset, status = HEADER.unpack(raw)
        if function != 0x40 or sequence != self.sequence or not 4 <= size <= limit or status:
            raise ValueError("响应头功能、序号、长度或状态错误")
        content = bytearray()
        while len(content) < size:
            chunk = self.driver.read(min(size-len(content), 4096))
            if not chunk or len(chunk) > size-len(content): raise ValueError("响应体边界错误")
            content.extend(chunk)
        if size % 512 == 0 and self.driver.read(512) != b"": raise ValueError("缺少空边界包")
        self.sequence += 1
        self.usable = True
        result, = struct.unpack_from("<I", content)
        self.log("dump_result", result=f"0x{result:08x}", bytes=size-4)
        if result: raise FileResultError(result)
        return bytes(content[4:])

    def select(self, path):
        self.exchange(struct.pack("<HH", 0x1001, 0x0f) + b"\0" + wire_path(path) + b"\0", 4)

    def read(self, path, limit):
        if path not in self.reads or not 0 <= limit <= self.reads[path]:
            raise PermissionError("读取超出本次固定路径/长度")
        self.select(path)
        return self.exchange(struct.pack("<HH", 0x1001, 0x11) + b"\0\xff\0", limit+4)

    def put(self, path, data):
        if path not in self.writes or data not in self.writes[path] or len(data) > MAX_ARTIFACT:
            raise PermissionError("写入路径或完整字节不在本次批准材料内")
        self.select(path)
        self.exchange(struct.pack("<HH", 0x1001, 0x10) + b"\0\xff\0" + data, 4)

    def debug(self):
        if self.debug_attempted: raise PermissionError("DEBUG 不允许重发")
        self.debug_attempted = True
        return self.exchange(struct.pack("<HH", 0x1001, 5) + b"\0\0\0", 4)


class Deployment:
    def __init__(self, channel, run_id, payload, output, accept_unknown=False):
        validate_run(run_id)
        if not 0 < len(payload) <= MAX_ARTIFACT: raise ValueError("载荷超过受限上限")
        self.channel, self.run_id, self.payload, self.output = channel, run_id, payload, Path(output)
        self.prefix = f"/tmp/jiritsu/a7r5-{run_id}"
        self.arm_bytes = (self.prefix + ".so\n").encode()
        self.accept_unknown = accept_unknown
        self.safe_to_stop = True
        self.state = {"run_id": run_id, "debug_attempted": False, "armed": False,
                      "preload_baseline": "unread", "original_restored": False}

    def persist(self):
        save_json(self.output / "deployment.json", self.state)

    def arm(self):
        # 基线检查在任何上传之前；除明确服务码 6 外的异常均向上传播。
        version = self.channel.read("/version.txt", 4096)
        if sha(version) != BASELINE_VERSION_SHA256: raise ValueError("版本对照不符")
        try:
            baseline = self.channel.read("/etc/ld.so.preload", 4096)
        except FileResultError as exc:
            self.state["preload_baseline"] = "unknown"
            self.persist()
            if exc.result != 0x10000006 or not self.accept_unknown: raise
        else:
            self.state["preload_baseline"] = "read"
            (self.output / "preload-before.bin").write_bytes(baseline)
            if baseline not in (b"", neutral):
                raise PermissionError("出现未批准的预加载内容；停止，不能以未知覆盖授权替代审查")
        self.persist()
        self.state["payload_write_attempted"] = True
        self.persist()
        self.channel.put(self.prefix + ".so", self.payload)
        if self.channel.read(self.prefix + ".so", MAX_ARTIFACT) != self.payload:
            raise ValueError("载荷完整读回不符；不写预加载")
        self.state["arm_write_attempted"] = True
        self.safe_to_stop = False
        self.persist()
        self.channel.put("/etc/ld.so.preload", self.arm_bytes)
        if self.channel.read("/etc/ld.so.preload", 4096) != self.arm_bytes:
            raise ValueError("预加载读回不符；不触发 DEBUG，保留未清理状态")
        self.state["armed"] = True
        self.persist()

    def trigger(self):
        if not self.state["armed"] or self.state["debug_attempted"]:
            raise PermissionError("尚未完整武装或 DEBUG 已尝试")
        self.state["debug_attempted"] = True
        self.persist()
        self.channel.debug()

    def disarm_before_debug(self):
        # 仅在通道完整、DEBUG 未尝试且读到本次精确条目时允许一次中和。
        if self.state["debug_attempted"] or not self.channel.usable:
            raise PermissionError("不能在 DEBUG 后或失步通道上盲目清理")
        if self.channel.read("/etc/ld.so.preload", 4096) != self.arm_bytes:
            raise PermissionError("不覆盖未知的现状")
        self.channel.put("/etc/ld.so.preload", neutral)
        if self.channel.read("/etc/ld.so.preload", 4096) != neutral: raise ValueError("中和读回失败")
        self.safe_to_stop = True
        self.state["neutral_verified"] = True
        self.persist()


class DumpOperation:
    """两阶段认证之后使用的固定流程；只有完整卸载回执允许自动退出服务。"""
    def __init__(self, bundle, payload, accept_unknown, *, channel_factory=None):
        self.bundle, self.payload, self.accept_unknown = bundle, payload, accept_unknown
        self.channel_factory = channel_factory
        self.safe_to_stop = True
        self.deployment = None

    @property
    def safe_to_stop(self):
        deploy = getattr(self, "deployment", None)
        return deploy.safe_to_stop if deploy is not None else self._safe_to_stop

    @safe_to_stop.setter
    def safe_to_stop(self, value):
        self._safe_to_stop = value
        deploy = getattr(self, "deployment", None)
        if deploy is not None: deploy.safe_to_stop = value

    def __call__(self, driver, output, log, report):
        from .tasks import inventory2
        run_id, marker = self.bundle["run_id"], self.bundle["card_marker"]
        prefix = f"/tmp/jiritsu/a7r5-{run_id}"
        arm = (prefix + ".so\n").encode()
        go = f"A7R5_GO {run_id} {marker}\n".encode()
        abort = f"A7R5_ABORT {run_id} {marker}\n".encode()
        writes = {prefix+".so": (self.payload,), "/etc/ld.so.preload": (arm, neutral), prefix+".go": (go, abort)}
        reads = {prefix+".so": MAX_ARTIFACT, "/etc/ld.so.preload": 4096, "/version.txt": 4096,
                 prefix+".state": 512, **{prefix+"."+s: MAX_METADATA for s in ("parts", "mounts", "devices", "topology", "sources")}}
        channel = (self.channel_factory or RestrictedChannel)(driver, writes, reads, log)
        deploy = self.deployment = Deployment(channel, run_id, self.payload, output, self.accept_unknown)
        ready, go_attempted = False, False
        try:
            # 在任何写请求之前把可能的写入影响记录到报告，失败不伪称未写。
            report["camera_file_write_commands_possible"] = True
            deploy.arm()
            self.safe_to_stop = False
            report["camera_file_write_commands_sent"] = True
            report["preload_written"] = True
            report["debug_commands_sent"] = True  # 表示尝试，不表示相机已执行。
            deploy.trigger()
            phase, card = self.wait(channel, prefix, run_id, {"READY"}, output, log, 70,
                                    self.bundle.get('expected_card_device'))
            ready = True
            if channel.read("/etc/ld.so.preload", 4096) != neutral:
                raise ValueError("没有正面预加载中和证据，不发送开始令牌")
            evidence = {}
            for suffix in ("parts", "mounts", "devices", "topology", "sources"):
                raw = channel.read(prefix+"."+suffix, MAX_METADATA)
                if not raw: raise ValueError(f"盘点证据为空：{suffix}")
                (output / (suffix+".txt")).write_bytes(raw)
                evidence[suffix] = raw.decode("ascii", errors="strict")
            validate_mounts(evidence["mounts"], card, prefix)
            inventory = inventory2(evidence["parts"], views=self.bundle['dump_views'])
            # 新材料将预期完整集合一并封存；范围不符不能发送GO。
            pinned = self.bundle.get('expected_inventory')
            if pinned is None or any(inventory[key] != pinned[key]
                    for key in ('schema', 'model', 'firmware_expected', 'views', 'partitions', 'total_bytes')):
                raise ValueError('本次所选分区集合或容量与封存模式不符；不发送GO')
            expected = "".join(f"{p['device']} {p['major']} {p['minor']} {p['bytes']}\n" for p in inventory["partitions"])
            if evidence["sources"] != expected: raise ValueError("设备端选择与主机独立盘点不符")
            # 保存完整拓扑，自动完成标记仍不能等同于全机覆盖证明。
            save_json(output/"inventory-expected.json", inventory)
            go_attempted = True
            deploy.state["go_attempted"] = True
            deploy.persist()
            channel.put(prefix+".go", go)
            report["dump_start_token_sent"] = True
            self.wait(channel, prefix, run_id, {"DONE"}, output, log, 7300, card)
            if channel.read("/etc/ld.so.preload", 4096) != neutral: raise ValueError("最终中和读回不符")
            report["card_unmounted_verified"] = True
            report["worker_done_receipt"] = True
            report["preload_neutral_verified"] = True
            report["whole_camera_completeness_verified"] = False
            self.safe_to_stop = deploy.safe_to_stop = True
        except Exception as failure:
            self.safe_to_stop = deploy.safe_to_stop
            if not deploy.state["debug_attempted"] and not deploy.safe_to_stop and channel.usable:
                try:
                    deploy.disarm_before_debug()
                    self.safe_to_stop = deploy.safe_to_stop
                except Exception as exc:
                    log("pre_debug_disarm_failed", message=str(exc))
            elif channel.usable and (isinstance(failure, WorkerFailure) and failure.unmounted or ready and not go_attempted):
                try:
                    if channel.read("/etc/ld.so.preload", 4096) != neutral:
                        raise ValueError("失败后中和读回不符")
                    if not isinstance(failure, WorkerFailure):
                        channel.put(prefix+".go", abort)
                        self.wait(channel, prefix, run_id, {"ABORTED_UNMOUNTED"}, output, log, 15, card)
                    self.safe_to_stop = deploy.safe_to_stop = True
                    report["card_unmounted_verified"] = True
                    report["preload_neutral_verified"] = True
                    report["dump_aborted"] = True
                except Exception as exc:
                    log("pre_dump_abort_failed", message=str(exc))
            raise
        finally:
            report["camera_file_write_commands_sent"] = bool(deploy.state.get("payload_write_attempted"))
            report["preload_written"] = bool(deploy.state.get("arm_write_attempted"))
            report["debug_commands_sent"] = bool(deploy.state["debug_attempted"])
            report["deployment_state"] = deploy.state
            report["automatic_service_exit_permitted"] = self.safe_to_stop

    @staticmethod
    def wait(channel, prefix, run_id, accepted, output, log, seconds, expected_card=None):
        import re
        deadline = time.monotonic() + seconds
        last = None
        while time.monotonic() < deadline:
            try: raw = channel.read(prefix+".state", 512)
            except FileResultError as exc:
                # 状态尚未创建仅允许有界轮询；6 永远不是文件不存在的证明。
                if exc.result != 0x10000006: raise
                time.sleep(1)
                continue
            record = re.fullmatch(rb"A7R5-STATE-1 ([0-9a-f]{8,32}) (READY|RUNNING|DONE|FAILED|EXPIRED|FAILED_UNMOUNTED|EXPIRED_UNMOUNTED|ABORTED_UNMOUNTED) ([0-9]+) (/dev/mmc[ab][1-4]|-) uid=([0-9]+) euid=([0-9]+) errno=([0-9]+)\n", raw)
            if not record or record[1].decode() != run_id: raise ValueError("旧状态、错误会话或不完整回执")
            phase, code, card = record[2].decode(), int(record[3]), record[4].decode()
            if phase not in ("FAILED", "EXPIRED") and (record[5] != b"0" or record[6] != b"0"):
                raise PermissionError("工作进程没有报告 UID/EUID 均为 root")
            if expected_card is not None and card != expected_card: raise ValueError("输出设备在会话中改变")
            if raw != last:
                log("worker_state", raw_hex=raw.hex(), phase=phase, code=code, card=card)
                (output/"worker-last-state.txt").write_bytes(raw)
                last = raw
            if phase in ("FAILED", "EXPIRED", "FAILED_UNMOUNTED", "EXPIRED_UNMOUNTED") or code:
                raise WorkerFailure(phase, code)
            if phase in accepted: return phase, card
            time.sleep(1)
        raise TimeoutError("工作进程轮询超时；任务可能仍写卡，不自动退出服务或断电")


def run_dump_session(bundle_path, approval_path, output):
    from .bundle import load_bundle
    from .images import regular_file
    from .session import run_session
    value, digest = load_bundle(bundle_path)
    approval = approve(json.loads(regular_file(approval_path).read_bytes()), digest)
    if (approval.get("card_verified_uuid") != value["card_uuid"]
            or approval.get("card_verified_partition_bytes") != value["card_partition_bytes"]
            or approval.get("card_verified_capacity_bytes") != value["layout"]["capacity_bytes"]):
        raise PermissionError("尚未核对真实备用卡及本次 UUID、容量和分区几何")
    output = Path(output).absolute()
    if output.resolve().is_relative_to("/dev"): raise ValueError("证据输出不能位于设备目录")
    if output.exists(): raise FileExistsError("不复用历史输出")
    # 一次性锁在任何 USB 初始化之前创建；失败也不自动删除或再试。
    (Path(bundle_path)/"ATTEMPT_LOCK").mkdir(mode=0o700)
    operation = DumpOperation(value, regular_file(Path(bundle_path)/"a7r5_worker.arm64.so").read_bytes(), True)
    return run_session(output, "libusb", _operation=operation)
