#!/bin/sh
# 准备 Python 依赖并检查快捷脚本所需的本机工具；不安装系统软件、不启动应用或操作相机。
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

# 检查快捷脚本所需的 macOS 原生依赖，缺失时给出明确安装命令。
missing_brew=""
check_any() {
    for candidate in "$@"; do
        if [ -f "$candidate" ]; then
            return 0
        fi
    done
    return 1
}

if ! check_any "${A7R5_LIBUSB:-/nonexistent}" \
    /opt/homebrew/opt/libusb/lib/libusb-1.0.dylib \
    /usr/local/opt/libusb/lib/libusb-1.0.dylib; then
    missing_brew="$missing_brew libusb"
fi
if ! check_any "${A7R5_CLANG:-/nonexistent}" \
    /opt/homebrew/opt/llvm/bin/clang \
    /usr/local/opt/llvm/bin/clang; then
    missing_brew="$missing_brew llvm"
fi
if ! check_any "${A7R5_LLD:-/nonexistent}" \
    /opt/homebrew/opt/lld/bin/ld.lld \
    /usr/local/opt/lld/bin/ld.lld; then
    missing_brew="$missing_brew lld"
fi
if ! check_any "${A7R5_OPENSSL:-/nonexistent}" \
    /opt/homebrew/opt/openssl/bin/openssl \
    /opt/homebrew/opt/openssl@3/bin/openssl \
    /usr/local/opt/openssl/bin/openssl \
    /usr/local/opt/openssl@3/bin/openssl; then
    missing_brew="$missing_brew openssl@3"
fi

printf '%s\n' 'Python 虚拟环境已准备完成。'
if [ -n "$missing_brew" ]; then
    printf '提示：快捷脚本还需要以下 Homebrew 依赖，请先安装：\n  brew install%s\n' "$missing_brew"
else
    printf '%s\n' '快捷脚本所需的本机依赖（libusb / llvm / lld / openssl）均已就绪。'
fi
if [ "$(uname -m)" != "arm64" ]; then
    printf '%s\n' '提示：当前非 Apple Silicon 架构，使用 Fastboot 前请从 a7r5-fastboot/native/ 重新编译 host/ USB 工具。'
fi
