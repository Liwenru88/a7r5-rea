#!/bin/zsh
set -eu
TASK_DIR="${0:A:h}"
exec "$TASK_DIR/quick-ssh.sh" start --execute "$@"
