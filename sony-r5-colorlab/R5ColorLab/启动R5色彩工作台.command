#!/bin/zsh
set -eu
cd "${0:A:h}"
if [[ -n "${R5_COLORLAB_PYTHON:-}" ]]; then
  colorlab_python="$R5_COLORLAB_PYTHON"
elif [[ -x .venv/bin/python ]]; then
  colorlab_python="$PWD/.venv/bin/python"
elif command -v python3 >/dev/null; then
  colorlab_python="$(command -v python3)"
else
  print '请先安装 Python 3.12：https://www.python.org/downloads/'
  read '?按回车关闭…'
  exit 1
fi
"$colorlab_python" launcher.py "$@" || { read '?启动失败，按回车关闭…'; exit 1; }
