#!/bin/bash
# 从原厂解包输入构建新目录中的非安装组件，保留全部历史现场。
set -euo pipefail
if [ "$#" -ne 2 ]; then
  printf '%s\n' '用法：bash build-components.sh 原厂4.00解包目录 新的.local输出目录'
  exit 2
fi
repo="$(cd "$(dirname "$0")/../../.." && pwd)"
stock="$(cd "$1" && pwd)"
work="$2"
py="$repo/.venv/bin/python"
datpy="$repo/a7r5-dat-tool/.venv/bin/python"
cd "$repo"
"$py" -B - "$repo" "$work" <<'PY'
from pathlib import Path
import sys
repo, work = map(Path, sys.argv[1:])
if work.exists() or not work.resolve().is_relative_to(repo / '.local'):
    raise SystemExit('输出必须是 .local 中不存在的新目录')
work.mkdir(parents=True)
PY
"$py" -B a7r5-firmware-features/native24-combined/build.py \
  --stock "$stock" --fl23 --factory-six --custom-sound --output "$work/native24"
"$py" -B a7r5-firmware-features/native24-combined/build_capture.py \
  --stock "$stock" --runtime "$work/native24" --lens-af --aspect --output "$work/capture-v2"
"$py" -B a7r5-firmware-features/native24-combined/build.py \
  --stock "$stock" --output "$work/look24-single"
"$py" -B a7r5-firmware-features/native24-combined/build_capture.py \
  --stock "$stock" --aspect --output "$work/aspect-standalone"
"$datpy" -B a7r5-firmware-features/specs/4.19-operation-fixes/build_component_view.py \
  --native24 "$work/native24" --capture "$work/capture-v2" --output "$work/combined-components"
"$py" -B - "$stock" "$work" <<'PY'
import hashlib
from pathlib import Path
import sys
sys.path.insert(0, 'a7r5-dat-tool')
from a7r5dat.ext2read import Ext2
stock, work = map(Path, sys.argv[1:])
fs = Ext2(stock / 'archive/0700_part_image/dev/nflasha15')
try:
    raw = fs.read_inode(fs.walk('/lib/libstdc++.so.6.0.22'))
finally:
    fs.mm.close(); fs.f.close()
if hashlib.sha256(raw).hexdigest() != '28f2d082aea5206c42ba15664f39e2eaf7febed8f6264305e7e16aa44c878389':
    raise SystemExit('原生注册树所需 libstdc++ 身份不符')
with (work / 'libstdc++.so.6.0.22').open('xb') as stream:
    stream.write(raw)
PY
printf '%s\n' "组件目录：$work（未生成 DAT）"
