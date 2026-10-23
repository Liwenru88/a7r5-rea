"""目标配置、分区盘点及待审批的转存指令；本模块不执行设备操作。"""

import json
import re

MODEL = "ILCE-7RM5"
FIRMWARE = "4.00"
NORMAL_PID = 0x0E0A
SERVICE_PID = 0x0336
VID = 0x054C
FLASH = re.compile(r"(?:[pc]nflasha[0-9]+|nflashaB[0-9]+)\Z")
RUN = re.compile(r"[0-9a-f]{8,32}\Z")
MIB = 1 << 20
# 只支持已知的两组卡块设备；未验证的设备族不自动扩大。
CARD_PARTITION = re.compile(r"mmc[ab][1-4]\Z")
CARD_BLOCK = re.compile(r"mmc[ab](?:[1-4])?\Z")


def validate_run(run_id):
    if not isinstance(run_id, str) or not RUN.fullmatch(run_id):
        raise ValueError("会话标识必须是 8 至 32 位小写十六进制")
    return run_id


def parse_partitions(text, views="both"):
    if views not in ("both", "plaintext"):
        raise ValueError("视图必须是 both 或 plaintext")
    found = {}
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 4 or not fields[0].isdigit():
            continue
        major, minor, kib, name = fields
        if not FLASH.fullmatch(name):
            continue
        if name in found or not minor.isdigit() or not kib.isdigit() or int(kib) <= 0:
            raise ValueError("闪存分区记录重复或长度无效")
        found[name] = {"device": name, "bytes": int(kib) * 1024,
                       "major": int(major), "minor": int(minor),
                       "image": name + ".img",
                       "view": "plaintext" if name.startswith("c") else
                               "physical" if name.startswith("p") else "boot"}
    if not found:
        raise ValueError("没有发现闪存分区，不能生成整机转存计划")
    if views == "plaintext":
        for name, item in found.items():
            if name.startswith("p"):
                peer = found.get("c" + name[1:])
                if not peer or peer["bytes"] != item["bytes"]:
                    raise ValueError(f"{name} 缺少长度一致的明文视图")
    selected = [p for p in found.values() if views == "both" or p["view"] != "physical"]
    result = {"schema": "a7r5-partitions-1", "model": MODEL,
              "firmware_expected": FIRMWARE, "views": views,
              "partitions": selected, "total_bytes": sum(p["bytes"] for p in selected),
              "coverage": "仅覆盖本次 /proc/partitions 中符合设备命名的闪存分区；"
                          "不含整个块设备、隐藏区域或已证明的全机覆盖保证"}
    validate_inventory(result)
    return result


def validate_inventory(value):
    if not isinstance(value, dict) or value.get("schema") not in ("a7r5-partitions-1", "a7r5-partitions-2"):
        raise ValueError("分区清单版本无效")
    if (value.get("model") != MODEL or value.get("firmware_expected") != FIRMWARE
            or value.get("views") not in ("both", "plaintext")):
        raise ValueError("清单机型或视图无效")
    parts = value.get("partitions")
    if not isinstance(parts, list) or not 1 <= len(parts) <= 128:
        raise ValueError("分区数量无效")
    devices, images = set(), set()
    version2 = value["schema"] == "a7r5-partitions-2"
    total = 0
    for item in parts:
        if not isinstance(item, dict): raise ValueError("分区记录必须是对象")
        device, name, size = item.get("device"), item.get("image"), item.get("bytes")
        from .tasks import FLASH2, view2
        pattern = FLASH2 if version2 else FLASH
        if not isinstance(device, str) or not pattern.fullmatch(device):
            raise ValueError("源设备不是允许的闪存分区")
        expected_view = view2(device) if version2 else "plaintext" if device.startswith("c") else "physical" if device.startswith("p") else "boot"
        if name != device + ".img" or item.get("view") != expected_view:
            raise ValueError("镜像名称或视图与源设备不一致")
        if device in devices or name in images:
            raise ValueError("重复的分区或镜像")
        if type(size) is not int or not 0 < size <= (1 << 40) or size % 512:
            raise ValueError("分区长度无效")
        if value["views"] == "plaintext" and expected_view == "physical":
            raise ValueError("明文计划不能混入物理视图")
        devices.add(device)
        images.add(name)
        total += size
    if type(value.get("total_bytes")) is not int or value["total_bytes"] != total:
        raise ValueError("清单总长度与分区不一致")
    return value


def card_layout(capacity_bytes, dump_bytes):
    if type(capacity_bytes) is not int or type(dump_bytes) is not int or dump_bytes <= 0:
        raise ValueError("容量必须是正整数")
    reserve = max(128 * MIB, (dump_bytes + 9) // 10)
    dump_area = ((dump_bytes + reserve + MIB - 1) // MIB) * MIB
    camera_area = ((capacity_bytes - MIB - dump_area) // MIB) * MIB
    if camera_area < 1024 * MIB:
        raise ValueError("备用卡不足以容纳镜像、余量和 1 GiB 相机分区")
    if capacity_bytes > (2 << 40):
        raise ValueError("容量超出本工具 MBR 方案边界")
    return {"scheme": "MBR", "partition_types": ["0x07", "0x83"],
            "camera_filesystem": "exFAT", "dump_filesystem": "ext2",
            "camera_bytes": camera_area, "dump_bytes": dump_area,
            "required_image_bytes": dump_bytes, "capacity_bytes": capacity_bytes,
            "execution_enabled": False,
            "note": "仅为容量方案；尚需确认真实卡设备、扇区大小和盘符后审批格式化。"}


def build_dump_script(inventory, run_id, card_device):
    validate_inventory(inventory)
    validate_run(run_id)
    if not isinstance(card_device, str) or not card_device.startswith('/dev/') or not CARD_PARTITION.fullmatch(card_device[5:]):
        raise ValueError("必须指定经实机盘点确认的 mmca/mmcb 1至4卡分区")
    mount = "/tmp/a7r5-sd"
    folder = f"{mount}/a7r5-{run_id}"
    total = inventory["total_bytes"]
    required_kib = (total + max(total // 10, 128 * MIB) + 1023) // 1024
    # 指令文本仅用于审阅。调用者不应把生成成功当作设备执行授权。
    rows = ["set -eu", "umask 077",
            "for tool in cat dd wc md5sum sync mount umount df mkdir; do command -v \"$tool\" >/dev/null || exit 20; done",
            f"mkdir -p {mount}", f"mount -t ext2 {card_device} {mount}",
            f"trap 'sync; umount {mount}' 0",
            "matched=0", "while read -r src target fs rest; do",
            f"  if [ \"$src\" = {card_device} ] && [ \"$target\" = {mount} ] && [ \"$fs\" = ext2 ]; then matched=1; fi",
            "done < /proc/mounts", '[ "$matched" = 1 ] || exit 21',
            f"space=$(df -k {mount})", "available=",
            "while read -r src blocks used free rest; do",
            f"  if [ \"$src\" = {card_device} ]; then available=$free; fi",
            "done <<A7R5_SPACE", "$space", "A7R5_SPACE",
            'case "$available" in ""|*[!0-9]*) exit 22;; esac',
            f'[ "$available" -ge {required_kib} ] || exit 23',
            f"mkdir {folder}", f"cd {folder}",
            "cat > inventory.json <<'A7R5_INVENTORY'",
            json.dumps(inventory, ensure_ascii=True, separators=(",", ":")),
            "A7R5_INVENTORY", ": > checksums.md5"]
    for item in inventory["partitions"]:
        source, name, size = item["device"], item["image"], item["bytes"]
        rows += [f"dd if=/dev/{source} of={name} bs=1M 2>{name}.log || exit 30",
                 f"actual=$(wc -c < {name})", f'[ "$actual" -eq {size} ] || exit 31',
                 f"md5sum {name} >> checksums.md5 || exit 32"]
    rows += ["sync || exit 33",
             f"echo 'A7R5-DUMP-1 {run_id} {len(inventory['partitions'])} {total}' > COMPLETE",
             "sync || exit 34", f"cd /", f"umount {mount} || exit 35", "trap - 0",
             f"echo A7R5_UNMOUNTED_{run_id}"]
    return "\n".join(rows) + "\n"
