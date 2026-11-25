#!/usr/bin/env bash
# 步骤 1：自动检测 RP2040 串口、自动循环触发 RAM Fastboot 直至 USB 激活成功（红灯闪一下熄灭）
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ "${1:-}" == --check-only ]]; then
  shift
  exec /bin/sh "$REPO_ROOT/scripts/usb_preflight.sh" rp2040 "$@"
fi

if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
else
  PYTHON="python3"
fi

echo "============================================================"
echo "[Step 1] 自动进入 A7R V RAM Fastboot 并验证 USB 激活"
echo "  - 自动查找 RP2040 (0x2E8A) 串口并释放旧会话占用"
echo "  - 若遇相机红灯持续闪烁/USB 不响应，将自动错相重试直至成功"
echo "============================================================"

exec "$PYTHON" -B "$SCRIPT_DIR/auto_enter_fastboot.py" "$@"
