#!/bin/sh
set -eu

SCRIPT_DIR="$(CDPATH= cd "$(dirname "$0")" && pwd)"
PYTHON_BIN="${A7R5_PYTHON:-$(command -v python3 || true)}"
if [ -z "${A7R5_PYTHON:-}" ] && { [ -z "$PYTHON_BIN" ] || [ "$PYTHON_BIN" = /usr/bin/python3 ]; }; then
    # Finder 的 PATH 可能没有用户安装的 Python。
    for candidate in /opt/homebrew/bin/python3 /usr/local/bin/python3; do
        if [ -x "$candidate" ]; then
            PYTHON_BIN="$candidate"
            break
        fi
    done
fi
if [ ! -f "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
    printf '%s\n' '未找到可用的 Python 3，请安装后重试，或用 A7R5_PYTHON 指定解释器路径。' >&2
    exit 1
fi
exec "$PYTHON_BIN" -E -S -B "$SCRIPT_DIR/trust_update/preflight.py" "$@"
