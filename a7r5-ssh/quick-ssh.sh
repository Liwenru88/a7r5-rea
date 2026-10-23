#!/bin/zsh
set -eu
TASK_DIR="${0:A:h}"
exec "$TASK_DIR/../.venv/bin/python" -B "$TASK_DIR/libjit-ssh-on-demand/quick_ssh.py" "$@"
