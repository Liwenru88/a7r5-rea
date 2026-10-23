#!/bin/bash
# 仅启动当前独立项目的原生模拟器。
set -euo pipefail
cd -- "$(dirname -- "$0")"
test "$(uname -sm)" = 'Darwin arm64' || { echo '需要 Apple Silicon Mac。'; exit 2; }
test -x .venv/bin/python || { echo '请先按 README.md 建立项目 Python 环境。'; exit 2; }
exec .venv/bin/python -B client/main.py "$@"
