#!/usr/bin/env python3
"""步骤 3：一键触发 A7R V SD 卡强制升级（无需校验本地 BODYDATA.DAT，自动完成激活、读取、打补丁、刷入与重启）。"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
RECOVERY_DIR = SCRIPT_DIR / "r5-fastboot-recovery"
sys.path.insert(0, str(RECOVERY_DIR))
sys.path.insert(0, str(RECOVERY_DIR / "vendor/fwtool.py-a7iv"))

from patch_r5_slot_settings import apply_sparse, make_sparse
from sd_trigger_offline import make_trigger

CONFIGURE_BIN = SCRIPT_DIR / "host/configure_fastboot_usb"
READER_BIN = SCRIPT_DIR / "host/read_fastboot_usb"
WRITER_BUILDER = RECOVERY_DIR / "build_current_4_19_writer.py"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def run_cmd(cmd: list[str], log_path: Path | None = None) -> str:
    print(f"  $ {' '.join(cmd)}", flush=True)
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    output = (proc.stdout or "") + (proc.stderr or "")
    if log_path is not None:
        log_path.write_text(output, encoding="utf-8")
    if output.strip():
        print(output.rstrip(), flush=True)
    if proc.returncode != 0 or "REPLY FAIL" in output:
        raise RuntimeError(f"命令执行失败 (exit={proc.returncode}): {' '.join(cmd)}")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="可选：指定输出目录（默认自动创建 a7r5-fastboot/runs/sd-force-update-时间戳）",
    )
    parser.add_argument(
        "--no-reboot",
        action="store_true",
        help="刷入并回读确认后不自动发送 reboot 命令",
    )
    args = parser.parse_args()

    ts = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
    out_dir = (args.output or (SCRIPT_DIR / "runs" / f"sd-force-update-{ts}")).resolve()
    out_dir.mkdir(mode=0o700, parents=True, exist_ok=False)

    print("============================================================")
    print("[Step 3] 触发 A7R V SD 卡强制升级 (MODE5)")
    print(f"  - 工作目录: {out_dir}")
    print("  - 请确保包含 BODYDATA.DAT 的 SD 卡已插入相机 Slot 1")
    print("============================================================")

    # 1. 激活 Fastboot USB 接口
    print("\n[1/5] 激活并检查 Fastboot USB 接口...")
    run_cmd([str(CONFIGURE_BIN)], out_dir / "01_configure.log")

    # 2. 读取当前机身的 nflasha2 (20 MiB)
    before_img = out_dir / "nflasha2.before.logical.img"
    print("\n[2/5] 读取当前机身 nflasha2 设置区 (20 MiB)...")
    run_cmd(
        [
            str(READER_BIN),
            "getvar:version",
            "oem partition dump nflasha2",
            f"upload:{before_img}",
        ],
        out_dir / "02_read_before.log",
    )

    before_data = before_img.read_bytes()
    before_sha = sha256_bytes(before_data)

    # 3. 内存生成 MODE5 触发补丁（不校验外部 BODYDATA.DAT）
    print("\n[3/5] 生成 MODE5 强制升级稀疏补丁 (dat4 -> 0.00, 创建 mode/mode5)...")
    after_data, plan = make_trigger(before_data)
    sparse_data = make_sparse(before_data, after_data)
    rebuilt, written_sectors = apply_sparse(before_data, sparse_data)
    if rebuilt != after_data or written_sectors != plan["changed_sectors"]:
        raise RuntimeError("Sparse 稀疏补丁自检不一致，已中止")

    after_sha = sha256_bytes(after_data)
    sparse_sha = sha256_bytes(sparse_data)

    after_img = out_dir / "nflasha2.candidate.logical.img"
    sparse_img = out_dir / "trigger.sparse.img"
    after_img.write_bytes(after_data)
    sparse_img.write_bytes(sparse_data)

    print(f"  - 当前机身版本 : {plan['current_version']} -> 临时门禁 {plan['temporary_gate']}")
    print(f"  - 变更扇区数量 : {len(plan['changed_sectors'])} 个扇区 ({plan['changed_bytes']} 字节)")
    print(f"  - Sparse SHA256: {sparse_sha}")

    # 4. 编译单次 Writer 并刷入 nflasha2
    writer_dir = out_dir / "writer"
    print("\n[4/5] 编译绑定当前 Sparse 的写入程序并刷入 nflasha2...")
    run_cmd(
        [
            sys.executable,
            "-B",
            str(WRITER_BUILDER),
            "--sparse",
            str(sparse_img),
            "--expected-sparse-sha256",
            sparse_sha,
            "--output",
            str(writer_dir),
        ],
        out_dir / "03_build_writer.log",
    )
    writer_bin = writer_dir / "current_4_19_writer"
    write_out = run_cmd(
        [str(writer_bin), f"download:{sparse_img}", "flash:nflasha2"],
        out_dir / "04_write.log",
    )
    expected_ack = f"wrote {len(plan['changed_sectors'])} sectors to nflasha2"
    if expected_ack not in write_out:
        raise RuntimeError(f"未收到预期的扇区写入确认: {expected_ack}")

    # 5. 回读核对并发送 reboot
    verify_img = out_dir / "nflasha2.after.logical.img"
    print("\n[5/5] 回读验证 nflasha2 写入结果...")
    run_cmd(
        [
            str(READER_BIN),
            "oem partition dump nflasha2",
            f"upload:{verify_img}",
        ],
        out_dir / "05_read_after.log",
    )
    verify_sha = sha256_bytes(verify_img.read_bytes())
    if verify_sha != after_sha:
        raise RuntimeError(
            f"写后回读 SHA-256 ({verify_sha}) 与目标候选 ({after_sha}) 不一致，已阻止重启！"
        )
    print(f"  - 写后回读校验通过: {verify_sha}")

    rebooted = False
    if not args.no_reboot:
        print("\n[Reboot] 正在发送 reboot 指令，相机将重启并从 SD 卡启动强制升级...")
        run_cmd([str(READER_BIN), "reboot"], out_dir / "06_reboot.log")
        rebooted = True
    else:
        print("\n[跳过重启] 已指定 --no-reboot，如需重启请执行: a7r5-fastboot/host/read_fastboot_usb reboot")

    summary = {
        "timestamp": ts,
        "output_dir": str(out_dir),
        "previous_version": plan["current_version"],
        "changed_sectors": plan["changed_sectors"],
        "changed_bytes": plan["changed_bytes"],
        "before_sha256": before_sha,
        "candidate_sha256": after_sha,
        "after_sha256": verify_sha,
        "sparse_sha256": sparse_sha,
        "readback_matched": True,
        "reboot_sent": rebooted,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print("\n============================================================")
    print("SD 卡强制升级触发完成！等待相机指示灯闪烁并完成升级即可。")
    print(f"摘要已保存至: {out_dir / 'summary.json'}")
    print("============================================================")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"\n[错误中止] {exc}", file=sys.stderr)
        raise SystemExit(1)
