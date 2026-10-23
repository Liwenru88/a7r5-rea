#!/bin/bash
# 命令仅在沙箱中的原厂 Linux 客体执行。
set -euo pipefail
cd -- "$(dirname -- "$0")"
exec .venv/bin/python -B tools/shell.py "$@"
