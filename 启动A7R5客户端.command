#!/bin/bash
# 双击或从终端运行；只构建开发运行缓存，不生成安装包。
set -eu
project_dir="$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)"
python_bin="$project_dir/.venv/bin/python"
if [ ! -x "$python_bin" ]; then
    echo "缺少项目 Python 环境，请先按 docs/build-inputs.md 准备开发环境。"
    if [ -t 0 ]; then read -r -p "按回车关闭…" _; fi
    exit 1
fi
if "$python_bin" -B "$project_dir/a7r5-desktop/scripts/dev.py" "$@"; then
    exit 0
else
    result=$?
    if [ -t 0 ]; then read -r -p "启动失败，按回车关闭…" _; fi
    exit "$result"
fi
