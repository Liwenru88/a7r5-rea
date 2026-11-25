#!/usr/bin/env bash
# 步骤 2：激活 Fastboot USB 接口并验证读写通信（默认读取分区表、SDM2 与当前 nflasha2 版本）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ "${1:-}" == --check-only ]]; then
  shift
  exec /bin/sh "$REPO_ROOT/scripts/usb_preflight.sh" fastboot "$@"
fi
if [[ "${1:-}" == --help || "${1:-}" == -h ]]; then
  printf '%s\n' '用法：2_activate_usb.sh [--quick | --check-only [--usb-snapshot 文件] | --help]'
  exit 0
fi
if (( $# > 1 )) || { (( $# == 1 )) && [[ "$1" != --quick ]]; }; then
  printf '%s\n' '参数无效，请运行 2_activate_usb.sh --help。' >&2
  exit 2
fi

CONFIGURE="$SCRIPT_DIR/host/configure_fastboot_usb"
READER="$SCRIPT_DIR/host/read_fastboot_usb"

if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
else
  PYTHON="python3"
fi

QUICK_ONLY=0
if [[ "${1:-}" == "--quick" ]]; then
  QUICK_ONLY=1
  shift
fi

echo "============================================================"
echo "[Step 2] 检查并激活 Sony Fastboot USB 接口 (18d1:4ee0)"
echo "============================================================"
"$CONFIGURE"

OUT_DIR="$SCRIPT_DIR/runs/usb-comm-$(date +%Y%m%d-%H%M%S)"
mkdir -m 700 -p "$OUT_DIR"

echo ""
echo "[1/2] 验证 Fastboot 0.5 协议与分区表..."
"$READER" "getvar:version" "oem partition" | tee "$OUT_DIR/partition.log"

if [[ "$QUICK_ONLY" -eq 1 ]]; then
  echo ""
  echo "Fastboot USB 激活与基础通信验证完成（--quick 模式）。日志保存在: $OUT_DIR"
  exit 0
fi

echo ""
echo "[2/2] 读取当前 SDM2 (64 KiB) 与 nflasha2 设置区 (20 MiB)..."
"$READER" \
  "oem partition dump nflasha 0 0x80" "upload:$OUT_DIR/sdm2.raw.bin" \
  "oem partition dump nflasha2" "upload:$OUT_DIR/nflasha2.logical.img" \
  | tee "$OUT_DIR/readback.log"

"$PYTHON" -B - "$OUT_DIR/nflasha2.logical.img" <<'PY'
import hashlib, sys
from pathlib import Path

img_path = Path(sys.argv[1])
rec_dir = img_path.resolve().parents[2] / "r5-fastboot-recovery"
sys.path.insert(0, str(rec_dir))
sys.path.insert(0, str(rec_dir / "vendor/fwtool.py-a7iv"))
from build_r5_partition1 import FatImage

data = img_path.read_bytes()
sha = hashlib.sha256(data).hexdigest()
fs = FatImage(data)
dat4 = fs.read("/updater/dat4")
ver = f"{dat4[1]:02x}.{dat4[0]:02x}" if len(dat4) == 2 else repr(dat4)
flags = [k for k in sorted(fs.entries) if k.startswith("/updater/") and k != "/updater/dat4"]
print("\n------------------------------------------------------------")
print(f"nflasha2 SHA-256 : {sha}")
print(f"当前记录固件版本 : {ver} (raw dat4={dat4.hex()})")
print(f"当前 updater 标志: {', '.join(flags) if flags else '无'}")
print(f"输出目录         : {img_path.parent}")
print("------------------------------------------------------------")
PY
