#!/bin/bash
# 只打开已验收的独立客户端；失败不自动切换后端。
set -euo pipefail
cd -- "$(dirname -- "$0")"
test -x 'dist/A7R5 Emulator Expanded.app/Contents/MacOS/A7R5Emulator' || { echo '缺少新版应用包，请查看 README.md。'; exit 2; }
# 直接启动已验证的包内入口，避免系统服务激活旧包或等待首次注册。
# 忽略终端挂断信号；关闭启动终端不会终止 GUI，仍由客户端正常回收 QEMU。
app_log_base="$HOME/Library/Application Support/A7R5 Emulator"
test ! -L "$app_log_base" || { echo '日志目录不能是符号链接。'; exit 2; }
mkdir -p "$app_log_base"
app_log_dir="$(/usr/bin/mktemp -d "$app_log_base/desktop-launch.XXXXXX")"
/usr/bin/nohup "$PWD/dist/A7R5 Emulator Expanded.app/Contents/MacOS/A7R5Emulator" "$@" > "$app_log_dir/console.log" 2>&1 < /dev/null &
app_pid=$!
printf '%s\n' "$app_pid" > "$app_log_dir/gui.pid"
printf '已启动新版客户端，PID=%s\n启动日志：%s\n请在客户端中正常退出模拟器。\n' "$app_pid" "$app_log_dir/console.log"
