#!/bin/zsh
set -eu
SCRIPT_DIR="${0:A:h}"
PROJECT_ROOT="${SCRIPT_DIR:h:h}"
PYTHON_BIN="${A7R5_PYTHON:-${PROJECT_ROOT}/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  print -u2 "未找到 Python 虚拟环境：$PYTHON_BIN"
  exit 1
fi

exec "$PYTHON_BIN" -B "${SCRIPT_DIR}/clean_jiritsu.py" "$@"
