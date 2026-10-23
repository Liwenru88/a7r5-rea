#!/bin/bash
# 重建前关闭本项目所有虚拟器；构建始终在此项目内进行。
set -euo pipefail
cd -- "$(dirname -- "$0")"
export PATH="/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin"
.venv/bin/python -B tools/build-native.py
exec .venv/bin/python -B tools/build-guest.py
