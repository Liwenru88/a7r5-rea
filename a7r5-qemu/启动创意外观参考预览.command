#!/bin/zsh
set -eu
project_dir="${0:A:h}"
cd "$project_dir"
exec "$project_dir/.venv/bin/python" -B "$project_dir/tools/look_launch.py"
