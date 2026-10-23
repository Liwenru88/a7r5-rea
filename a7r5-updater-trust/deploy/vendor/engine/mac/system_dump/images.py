"""用 debugfs 读取普通 ext2 镜像文件，不挂载卷，也不读取原始设备。"""

import hashlib
import json
from pathlib import Path
import re
import stat
import subprocess

from .core import validate_inventory, validate_run

E2FS = Path("/opt/homebrew/opt/e2fsprogs/sbin")


def regular_file(path):
    path = Path(path).absolute()
    if path.is_symlink() or not stat.S_ISREG(path.stat().st_mode):
        raise ValueError("本地离线操作只接受普通文件，拒绝链接和设备节点")
    if path.resolve().is_relative_to("/dev"):
        raise ValueError("离线入口禁止访问 /dev")
    return path


def digest(path, algorithm="sha256"):
    hasher = hashlib.new(algorithm)
    with regular_file(path).open("rb") as handle:
        while chunk := handle.read(1 << 20): hasher.update(chunk)
    return hasher.hexdigest()


def read_ext2_superblock(path):
    path = regular_file(path)
    with path.open("rb") as handle:
        handle.seek(1024)
        sb = handle.read(1024)
    if len(sb) != 1024 or sb[56:58] != b"\x53\xef":
        raise ValueError("文件不是可识别的 ext2 镜像")
    # 拒绝被误当作 ext2 的 ext3/ext4；备份本体仍可以另行保留。
    compat = int.from_bytes(sb[92:96], "little")
    incompat = int.from_bytes(sb[96:100], "little")
    readonly = int.from_bytes(sb[100:104], "little")
    if compat & 4 or incompat & ~2 or readonly & ~7:
        raise ValueError("镜像含超出本次 ext2 方案的文件系统特性")
    return {"filesystem": "ext2", "compat": compat, "incompat": incompat,
            "readonly_compat": readonly}


def _dump(image, remote, destination, max_bytes):
    # debugfs 的命令解释器有独立引用规则；相机内路径全部由白名单构造。
    if any(c in str(destination) for c in '\n\r"\\'):
        raise ValueError("输出目录包含 debugfs 不支持的引用字符")
    info = subprocess.run([str(E2FS / "debugfs"), "-R", f"stat {remote}", str(image)],
                          capture_output=True, text=True, timeout=60)
    size = re.search(r"\bSize:\s*(\d+)", info.stdout)
    if (info.returncode or "Type: regular" not in info.stdout or not size
            or int(size[1]) > max_bytes):
        raise ValueError(f"ext2 文件缺失、类型不符或超过长度上限：{remote}")
    result = subprocess.run([str(E2FS / "debugfs"), "-R",
                             f'dump {remote} "{destination}"', str(image)],
                            capture_output=True, text=True, timeout=3600)
    # debugfs 可能在内部命令失败时仍返回 0，必须验证实际产物。
    if result.returncode or not destination.is_file() or destination.is_symlink():
        raise ValueError(f"无法从 ext2 读取 {remote}: {result.stderr.strip()}")


def extract_run(image, destination, run_id):
    image = regular_file(image)
    validate_run(run_id)
    read_ext2_superblock(image)
    destination = Path(destination).absolute()
    if destination.resolve().is_relative_to("/dev"):
        raise ValueError("禁止以设备目录作为输出")
    # 每次写入全新的输出目录；失败会保留现场，不覆盖旧镜像。
    destination.mkdir(parents=True, exist_ok=False)
    root = f"/a7r5-{run_id}"
    for name, maximum in (("inventory.json", 1 << 20), ("COMPLETE", 256), ("checksums.md5", 65536)):
        _dump(image, root + "/" + name, destination / name, maximum)
    if (destination / "inventory.json").stat().st_size > (1 << 20):
        raise ValueError("分区清单超过大小上限")
    inventory = validate_inventory(json.loads((destination / "inventory.json").read_text()))
    marker = (destination / "COMPLETE").read_text()
    expected_marker = f"A7R5-DUMP-1 {run_id} {len(inventory['partitions'])} {inventory['total_bytes']}\n"
    if marker != expected_marker:
        raise ValueError("完成标记与当前会话、分区数量或总长度不符")
    hashes = {}
    for row in (destination / "checksums.md5").read_text().splitlines():
        match = re.fullmatch(r"([0-9a-f]{32})\s+\*?([A-Za-z0-9_.]+)", row)
        if not match or match[2] in hashes: raise ValueError("摘要清单无效或重复")
        hashes[match[2]] = match[1]
    if set(hashes) != {p["image"] for p in inventory["partitions"]}:
        raise ValueError("摘要清单与分区清单不一致")
    results = []
    for item in inventory["partitions"]:
        target = destination / item["image"]
        temporary = destination / (item["image"] + ".partial")
        _dump(image, root + "/" + item["image"], temporary, item["bytes"])
        if temporary.stat().st_size != item["bytes"]:
            raise ValueError(f"{item['image']} 长度不符，保留 .partial")
        md5 = digest(temporary, "md5")
        if md5 != hashes[item["image"]]:
            raise ValueError(f"{item['image']} 与相机记录的 MD5 不符，保留 .partial")
        sha256 = digest(temporary)
        temporary.rename(target)
        results.append({**item, "sha256": sha256, "camera_md5": md5,
                        "transfer_verified": True})
    result = {"schema": "a7r5-transfer-1", "run_id": run_id,
              "source_image": str(image), "source_sha256": digest(image),
              "images": results, "transfer_verified": True,
              "whole_camera_completeness_verified": False,
              "limitations": ["摘要一致只证明取回的数据与清单一致；不证明分区盘点完整或动态分区快照一致。",
                              "尚需逐镜像文件系统检查和独立服务文件/官方样本对比。"]}
    with (destination / "manifest.json").open("x") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    return result
