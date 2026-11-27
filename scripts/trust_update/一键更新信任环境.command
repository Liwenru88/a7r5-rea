#!/bin/zsh
# 一键：自动转存机内 cnflasha1 镜像 → 现场计算写入计划 → 更新信任环境 → 恢复普通 MSC。
# 用法：
#   ./一键更新信任环境.command                     # 默认 libjit，全自动
#   ./一键更新信任环境.command kit                 # kit 引擎（零写入 /tmp/jiritsu/）
#   ./一键更新信任环境.command --capture-only      # 只转存镜像到 .local/，不写入
#   ./一键更新信任环境.command --preimage 镜像路径  # 跳过转存，离线复用已有镜像
#   ./一键更新信任环境.command --check-only --firmware-version 4.00   # 只读预检
set -eu
SCRIPT_DIR="${0:A:h}"
PROJECT_ROOT="${SCRIPT_DIR:h:h}"

if [[ "${1:-}" == --check-only ]]; then
  shift
  exec /bin/sh "$PROJECT_ROOT/scripts/usb_preflight.sh" msc "$@"
fi

ENGINE=libjit
case "${1:-}" in
  libjit|kit)
    ENGINE="$1"
    shift
    ;;
esac

for arg in "$@"; do
  if [[ "$arg" == --check-only ]]; then
    print -u2 -- '--check-only 必须放在第一个参数：./一键更新信任环境.command --check-only --firmware-version 4.00'
    exit 2
  fi
done

PYTHON_BIN="${A7R5_PYTHON:-${PROJECT_ROOT}/.venv/bin/python}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  print -u2 "未找到 Python 虚拟环境：$PYTHON_BIN"
  exit 1
fi

exec "$PYTHON_BIN" -B "${SCRIPT_DIR}/update_trust.py" --engine "$ENGINE" "$@"