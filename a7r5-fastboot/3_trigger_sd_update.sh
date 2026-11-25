#!/usr/bin/env bash
# 步骤 3 包装脚本：一键读取当前 nflasha2、写入 MODE5 触发标志并重启进入 SD 卡强制升级
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
if [[ "${1:-}" == --check-only ]]; then
  shift
  exec /bin/sh "$REPO_ROOT/scripts/usb_preflight.sh" fastboot "$@"
fi

if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON="$REPO_ROOT/.venv/bin/python"
else
  PYTHON="python3"
fi

exec "$PYTHON" -B "$SCRIPT_DIR/3_trigger_sd_update.py" "$@"
