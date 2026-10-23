"""构建时封存的相机任务；没有远端脚本上传或任意命令参数。"""
import re
from .core import validate_run, CARD_BLOCK

FLASH2 = re.compile(r"(?:[pc]?nflasha(?:[0-9]+)?|nflashaB[0-9]+)\Z")


def inventory2(text, views='both'):
    from .core import validate_inventory
    if views not in ('both', 'plaintext'):
        raise ValueError('未知转存视图')
    parts, excluded = [], []
    for line in text.splitlines():
        fields = line.split()
        if len(fields) != 4 or not fields[0].isdigit(): continue
        major, minor, kib, name = fields
        if not minor.isdigit() or not kib.isdigit(): raise ValueError("分区字段不是整数")
        if FLASH2.fullmatch(name):
            parts.append({"device": name, "major": int(major), "minor": int(minor),
                          "bytes": int(kib)*1024, "image": name+".img",
                          "view": view2(name)})
        elif CARD_BLOCK.fullmatch(name) or re.fullmatch(r"(?:ram[0-9]+|loop[0-9]+)", name):
            excluded.append(name)
        else:
            raise ValueError(f"未归类块设备 {name}；拒绝静默遗漏，不能开始转存")
    if views == 'plaintext':
        parts = [p for p in parts if p['view'] != 'physical']
    value = {"schema": "a7r5-partitions-2", "model": "ILCE-7RM5", "firmware_expected": "4.00",
             "views": views, "partitions": parts, "total_bytes": sum(p["bytes"] for p in parts),
             "coverage": "包含本次所选视图；隐藏区域、OTP 与活跃快照未验证"}
    validate_inventory(value)
    return value


def view2(name):
    return "plaintext" if name.startswith("c") else "boot" if name.startswith("nflashaB") else "physical"


def scripts(run_id, marker, *, root="/tmp/jiritsu", mount=None, test_prelude="", views='both'):
    validate_run(run_id)
    if views not in ('both', 'plaintext'):
        raise ValueError('未知转存视图')
    if not re.fullmatch(r"[0-9a-f]{32}", marker): raise ValueError("卡标记必须是 32 位小写十六进制")
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", root): raise ValueError("任务路径不安全")
    prefix = f"{root}/a7r5-{run_id}"
    mount = mount or f"{prefix}.sd"
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", mount): raise ValueError("挂载路径不安全")
    # 文件均由唯一 run_id 构造；拒绝沿用已有目录/输出。不自动格式化或改挂另一张卡。
    # 显式使用已有BusyBox应用，不安装链接或扩大PATH。
    common = "set -eu\numask 077\n" + 'wc() { /bin/busybox wc "$@"; }\nmd5sum() { /bin/busybox md5sum "$@"; }\ncmp() { /bin/busybox cmp "$@"; }\nreadlink() { /bin/busybox readlink "$@"; }\n' + test_prelude
    prepare = common + f'''card=$1
# 挂卡之前核对四个应用存在；不以函数名可见替代应用支持证据。
A7R5_BB_APPLETS=$(/bin/busybox --list) || exit 52
A7R5_APP_CODE=53
for app in wc md5sum cmp readlink; do
 case "
$A7R5_BB_APPLETS
" in *"
$app
"*) : ;; *) exit "$A7R5_APP_CODE" ;; esac
 A7R5_APP_CODE=$((A7R5_APP_CODE+1))
done
# C任务入口传入固定PATH；若shell实际值不同，拒绝继续，不静默改写。
[ "$PATH" = '/bin:/sbin:/usr/bin:/usr/sbin' ] || exit 57
A7R5_TOOL_CODE=60
for tool in cat dd wc md5sum sync mount umount mkdir cmp ls readlink cp; do
 case "$tool" in
  wc|md5sum|cmp|readlink) A7R5_TOOL_PATH=/bin/busybox ;;
  *) A7R5_TOOL_PATH=/bin/$tool ;;
 esac
 [ -f "$A7R5_TOOL_PATH" ] && [ -x "$A7R5_TOOL_PATH" ] || exit "$A7R5_TOOL_CODE"
 A7R5_TOOL_CODE=$((A7R5_TOOL_CODE+1))
done
while read -r src target fs rest; do
 [ "$src" != "$card" ] || exit 22
done < /proc/mounts
mkdir {mount} || exit 23
mount -t ext2 -o rw,nosuid,nodev,noexec "$card" {mount} || exit 24
matched=0
while read -r src target fs rest; do
 if [ "$src" = "$card" ] && [ "$target" = "{mount}" ] && [ "$fs" = ext2 ]; then matched=$((matched+1)); fi
done < /proc/mounts
[ "$matched" = 1 ] || exit 25
[ "$(cat {mount}/A7R5_CARD_ID)" = '{marker}' ] || exit 26
mkdir {mount}/a7r5-{run_id} || exit 27
cat /proc/partitions > {prefix}.parts
cat /proc/mounts > {prefix}.mounts
ls -l /dev > {prefix}.devices
: > {prefix}.topology
for d in /sys/class/block/*; do
  [ -e "$d" ] || exit 28
  echo "$d" >> {prefix}.topology
  readlink "$d" >> {prefix}.topology || exit 28
  cat "$d/dev" "$d/size" >> {prefix}.topology || exit 28
done
for suffix in parts mounts devices topology sources; do
 [ "$(wc -c < {prefix}.$suffix)" -le 65536 ] || exit 36
 cp {prefix}.$suffix {mount}/a7r5-{run_id}/$suffix.txt || exit 37
done
'''
    dump = common + f'''card=$1
matched=0
while read -r src target fs rest; do
 if [ "$src" = "$card" ] && [ "$target" = "{mount}" ] && [ "$fs" = ext2 ]; then matched=$((matched+1)); fi
done < /proc/mounts
[ "$matched" = 1 ] || exit 40
[ "$(cat {mount}/A7R5_CARD_ID)" = '{marker}' ] || exit 41
cmp -s /proc/partitions {prefix}.parts || exit 42
cd {mount}/a7r5-{run_id}
[ ! -e checksums.md5 ] && [ ! -e COMPLETE ] || exit 43
: > checksums.md5
printf '{{"schema":"a7r5-partitions-2","model":"ILCE-7RM5","firmware_expected":"4.00","views":"{views}","partitions":[' > inventory.json
sep=; total=0; count=0
while read -r name major minor size; do
 case "$name" in c*) view=plaintext;; nflashaB*) view=boot;; *) view=physical;; esac
 printf '%s{{"device":"%s","major":%s,"minor":%s,"bytes":%s,"image":"%s.img","view":"%s"}}' "$sep" "$name" "$major" "$minor" "$size" "$name" "$view" >> inventory.json
 sep=,; count=$((count+1)); total=$((total+size))
done < {prefix}.sources
printf '],"total_bytes":%s}}\\n' "$total" >> inventory.json
while read -r name major minor size; do
 [ ! -e "$name.img" ] || exit 45
 dd if="/dev/$name" of="$name.img" bs=1M 2>"$name.log" || exit 46
 [ "$(wc -c < "$name.img")" -eq "$size" ] || exit 47
 md5sum "$name.img" >> checksums.md5 || exit 48
done < {prefix}.sources
sync || exit 49
printf 'A7R5-DUMP-1 {run_id} %s %s\\n' "$count" "$total" > COMPLETE
sync || exit 50
cd /
umount {mount} || exit 51
'''
    return prepare, dump
