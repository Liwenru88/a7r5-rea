#!/bin/sh
set -eu
tool_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
cd "$tool_dir"
runtime=${A7R5_DAT_PYTHON:-}
if [ -z "$runtime" ]; then
    for candidate in python3.14 python3.13 python3.12 python3; do
        if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; raise SystemExit(sys.version_info < (3,12))'; then
            runtime=$candidate
            break
        fi
    done
fi
if [ -z "$runtime" ]; then
    printf '%s\n' '需要 Python 3.12 或更新版本；本包实际验收环境为 Python 3.14 / macOS arm64。' >&2
    exit 1
fi
"$runtime" -c 'import sys; raise SystemExit(sys.version_info < (3,12))'
if command -v uv >/dev/null 2>&1; then
    if [ ! -d .venv ]; then uv venv --python "$runtime" .venv; fi
    uv pip install --python .venv/bin/python -r requirements-lock.txt
else
    if [ ! -d .venv ]; then "$runtime" -m venv .venv; fi
    .venv/bin/python -m pip install -r requirements-lock.txt
fi
if [ -f keys/research-signing-private.pem ]; then
    chmod 600 keys/research-signing-private.pem
fi
printf '%s\n' '依赖已就绪。运行 ./dattool --help 查看本地离线命令。'
