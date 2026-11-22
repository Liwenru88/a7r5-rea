#!/usr/bin/env zsh
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"

if [[ -n "${PYTHON_BIN:-}" ]]; then
  PYTHON="$PYTHON_BIN"
elif [[ -x "$ROOT/.venv/bin/python" ]]; then
  PYTHON="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="$(command -v python3)"
else
  echo "未找到可用的 Python 3 解释器，请设置 PYTHON_BIN 或创建 $ROOT/.venv" >&2
  exit 1
fi

exec "$PYTHON" -B "$ROOT/a7r5-firmware-features/native24-combined/release431/build_431_from_400.py" "$@"
