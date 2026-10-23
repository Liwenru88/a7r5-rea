#!/bin/zsh
set -eu
TASK_DIR="${0:A:h}"
if [[ -x "${TASK_DIR}/../.venv/bin/python" ]]; then
  TASK_DEFAULT_PY="${TASK_DIR}/../.venv/bin/python"
else
  TASK_DEFAULT_PY="${TASK_DIR}/../../.venv/bin/python"
fi
TASK_PY="${A7R5_PYTHON:-${TASK_DEFAULT_PY}}"
exec "$TASK_PY" -B "$TASK_DIR/deploy.py" "$@"
