#!/bin/sh
# 只准备开发依赖；不启动应用、USB 或相机工具。
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$project_dir"
task_python=${A7R5_BUILD_PYTHON:-python3.14}
"$task_python" -c 'import sys; raise SystemExit(sys.version_info[:2] != (3, 14))'
if ! command -v uv >/dev/null 2>&1; then
    printf '%s\n' '需要预先安装 uv；本脚本不会安装系统软件。' >&2
    exit 1
fi
if [ ! -d .venv ]; then uv venv --python "$task_python" .venv; fi
uv pip install --python .venv/bin/python -r requirements-dev.txt
if [ ! -d a7r5-dat-tool/.venv ]; then uv venv --python "$task_python" a7r5-dat-tool/.venv; fi
uv pip install --python a7r5-dat-tool/.venv/bin/python -r a7r5-dat-tool/requirements-dev.txt
printf '%s\n' '源码测试依赖已准备；QEMU/Qt、LLVM、固件及签名身份需按文档单独准备。'
