#!/bin/zsh
set -eu
TASK_DIR="${0:A:h}"
TASK_PY="${A7R5_PYTHON:-${TASK_DIR}/../.venv/bin/python}"
exec "$TASK_PY" -B "$TASK_DIR/exec.py" run "$@"
