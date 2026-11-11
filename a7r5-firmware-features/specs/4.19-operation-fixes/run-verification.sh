#!/bin/bash
# 只运行离线回归；回执写入新的临时目录。
set -euo pipefail
if [ "$#" -ne 2 ]; then
  printf '%s\n' '用法：bash run-verification.sh 原厂4.00解包目录 已构建组件目录'
  exit 2
fi
repo="$(cd "$(dirname "$0")/../../.." && pwd)"
stock="$(cd "$1" && pwd)"
work="$(cd "$2" && pwd)"
out="$(mktemp -d "${TMPDIR:-/tmp}/r5-operation-fixes.XXXXXX")"
py="$repo/.venv/bin/python"
datpy="$repo/a7r5-dat-tool/.venv/bin/python"
cd "$repo"
"$datpy" -B - <<'PY'
import hashlib, json, sys
from pathlib import Path
sys.path.insert(0, 'a7r5-firmware-features')
from core.plan import make_plan, read_json
from core.package import source_snapshot
root = Path.cwd()
lock = read_json(root / 'a7r5-firmware-features/specs/4.19-operation-fixes/source-lock.json')
plan = make_plan(read_json(root / 'a7r5-firmware-features/presets/full-4.19.json'))
if plan != lock['module_plan'] or source_snapshot(plan) != lock['firmware_sources']:
    raise SystemExit('固件源码或模块计划已变化；须重新构建、审查并更新本轮验证锁')
for name, expected in lock['test_and_reproduction_sources'].items():
    if hashlib.sha256((root / name).read_bytes()).hexdigest() != expected:
        raise SystemExit('回归工具已变化：' + name)
PY
export A7R5_NATIVE24_BUILD="$work/native24"
export A7R5_COMPONENT_CAPTURE="$work/combined-components"
export A7R5_LOOK24_REPAIR_BUILD="$work/look24-single"
export A7R5_NATIVE12_STD="$work/libstdc++.so.6.0.22"
export A7R5_ASPECT_AP_INPUT="$work/native24/appFw.so"
export A7R5_ASPECT_CP_INPUT="$work/native24/cpapp-b.bin"
export A7R5_ASPECT_CAPTURE="$work/capture-v2"
export A7R5_ASPECT_NATIVE24_IMAGES="$work/native24"
export A7R5_ASPECT_STOCK_USR="$stock/archive/0700_part_image/dev/nflasha15"
export A7R5_ASPECT_STOCK_AVCAM_PARTITION="$stock/archive/0700_part_image/dev/nflasha3"
export R5_SOUND_WORKSPACE="$work/native24/work"
# 显式区分组件验证与历史 DAT 验证环境。
unset A7R5_FINAL_READBACK A7R5_FINAL_BUNDLE A7R5_OPTIONAL_AP_READBACK
"$py" -B -m pytest -p no:cacheprovider \
  a7r5-firmware-features/native24-combined/tests/test_tabs.py \
  a7r5-firmware-features/tests/test_operation_fixes.py -q --junitxml="$out/menu-integration.xml"
"$py" -B -m pytest -p no:cacheprovider \
  a7r5-firmware-features/native24-combined/tests/test_recovery_retry.py \
  a7r5-firmware-features/native24-combined/tests/test_background_interaction.py \
  a7r5-firmware-features/native24-combined/tests/test_preview_idle.py \
  a7r5-firmware-features/native24-combined/tests/test_ui_sync.py \
  a7r5-firmware-features/native24-combined/tests/test_runtime.py \
  a7r5-firmware-features/native24-combined/tests/test_stability.py \
  a7r5-firmware-features/native24-combined/tests/test_relative_parameters.py \
  a7r5-firmware-features/native24-combined/tests/test_native_e4_parameters.py \
  -k 'not baseline_rejects and not current_components_preserve_local_patches' \
  -q --junitxml="$out/native.xml"
"$py" -B -m pytest -p no:cacheprovider a7r5-firmware-features/photo-aspect-ratios/src \
  -q --junitxml="$out/aspect.xml"
"$py" -B -m pytest -p no:cacheprovider \
  a7r5-firmware-features/photo-electronic-shutter-sound/tests/test_sound.py \
  a7r5-firmware-features/tests/test_compose_419.py \
  a7r5-firmware-features/tests/test_compose_look24.py \
  a7r5-firmware-features/tests/test_compose_phase4.py::test_selectable_capture_modules_use_only_expected_archive_members \
  -q --junitxml="$out/sound-plans.xml"
export A7R5_ASPECT_AP_INPUT="$stock/components/usr/lib/appFw.so"
export A7R5_ASPECT_CAPTURE="$work/aspect-standalone"
export A7R5_ASPECT_NATIVE24_IMAGES="$work/aspect-standalone/stock-images"
"$py" -B -m pytest -p no:cacheprovider \
  a7r5-firmware-features/photo-aspect-ratios/src/test_ap.py \
  a7r5-firmware-features/photo-aspect-ratios/src/test_ap_state.py \
  a7r5-firmware-features/photo-aspect-ratios/src/test_persistence_recovery.py \
  a7r5-firmware-features/photo-aspect-ratios/src/test_guide.py \
  a7r5-firmware-features/photo-aspect-ratios/src/test_resources.py \
  -q --junitxml="$out/standalone.xml"
printf '%s\n' "回执目录：$out"
