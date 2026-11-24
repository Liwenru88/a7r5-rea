#!/bin/zsh
set -eu
SCRIPT_DIR="${0:A:h}"
PROJECT_ROOT="${SCRIPT_DIR:h:h}"

if [[ "${1:-}" == --check-only ]]; then
  shift
  PYTHON_BIN="${A7R5_PYTHON:-$(command -v python3 || true)}"
  if [[ -z "${A7R5_PYTHON:-}" && ( -z "$PYTHON_BIN" || "$PYTHON_BIN" == /usr/bin/python3 ) ]]; then
    # Finder 的 PATH 可能没有用户安装的 Python。
    for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3; do
      if [[ -x "$candidate" ]]; then
        PYTHON_BIN="$candidate"
        break
      fi
    done
  fi
  if [[ ! -f "$PYTHON_BIN" || ! -x "$PYTHON_BIN" ]]; then
    print -u2 '未找到可用的 Python 3，请安装后重试，或用 A7R5_PYTHON 指定解释器路径。'
    exit 1
  fi
  exec "$PYTHON_BIN" -E -S -B "${SCRIPT_DIR}/preflight.py" "$@"
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

exec "$PYTHON_BIN" -B "${SCRIPT_DIR}/update_trust.py" --engine "$ENGINE"
