#!/bin/bash
# 无本次有效批准时直接停止，既不调用 sudo，也不观察设备。
set -euo pipefail
cd -- "$(dirname -- "$0")"
python_bin="${A7R5_SSH_PYTHON:-${PWD%/*}/a7r5-qemu/.venv/bin/python}"
test -x "$python_bin" || { echo '请用 A7R5_SSH_PYTHON 指定已核对的 Python。'; exit 2; }
operation="${A7R5_SSH_OPERATION:-$PWD/packages/preflight-once}"
test -f "$operation/approval.json" || { echo '仅离线包：缺少本次实机批准，不启动 sudo、不查询设备。'; exit 2; }
"$python_bin" -B lab.py check-approval --operation "$operation"
sudo -- "$python_bin" -B "$PWD/lab.py" execute-preflight --operation "$operation" --device-io
