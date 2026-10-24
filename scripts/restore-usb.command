#!/bin/zsh
set -eu
TASK_DIR="${0:A:h}"
TASK_PY="${A7R5_PYTHON:-${TASK_DIR}/../.venv/bin/python}"
if [[ ! -x "$TASK_PY" ]]; then
  print -u2 -- "未找到Python环境：$TASK_PY；请设置A7R5_PYTHON。"
  exit 2
fi
if [[ "${1:-}" == '--check' || "${1:-}" == '--help' || "${1:-}" == '-h' ]]; then
  exec "$TASK_PY" -B "$TASK_DIR/restore_usb.py" "$@"
fi
print -- '将退出当前相机服务模式；请勿在任务或传输进行时运行。只发送一次STOP，不重试。'
if (( EUID == 0 )); then
  exec "$TASK_PY" -B "$TASK_DIR/restore_usb.py" --execute "$@"
fi
exec sudo "$TASK_PY" -B "$TASK_DIR/restore_usb.py" --execute "$@"
