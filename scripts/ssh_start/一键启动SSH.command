#!/bin/zsh
set -eu
SCRIPT_DIR="${0:A:h}"
PROJECT_ROOT="${SCRIPT_DIR:h:h}"
if [[ "${1:-}" == --check-only ]]; then
  shift
  exec /bin/sh "$PROJECT_ROOT/scripts/usb_preflight.sh" msc "$@"
fi

ENGINE="${1:-libjit}"
if (( $# > 1 )) || [[ "$ENGINE" != libjit && "$ENGINE" != kit ]]; then
  print -u2 '请使用 --check-only 进行只读预检，或仅传入 libjit / kit。'
  exit 2
fi

PYTHON_BIN="${A7R5_PYTHON:-${PROJECT_ROOT}/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  print -u2 "未找到 Python 虚拟环境：$PYTHON_BIN"
  exit 1
fi

exec "$PYTHON_BIN" -B "${SCRIPT_DIR}/start_ssh.py" --engine "$ENGINE"
