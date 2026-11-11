#!/bin/bash
# 只读回放最终组件；缺陷探针通过表示复现成功，并非修复完成。
set -euo pipefail
root="$(cd "$(dirname "$0")/../../.." && pwd)"
audit="$root/a7r5-firmware-features/specs/4.19-operation-audit"
out="$(mktemp -d "${TMPDIR:-/tmp}/r5-419-operation-audit.XXXXXX")"
export R5_AUDIT_ROOT="$root"
export A7R5_NATIVE24_BUILD="$root/.local/full419-candidate-v2/build-evidence/native24"
export A7R5_FINAL_READBACK="$root/.local/full419-readback-v2"
export A7R5_FINAL_BUNDLE="$root/a7r5-firmware-features/releases/4.19-full"
export A7R5_ASPECT_AP_INPUT="$A7R5_NATIVE24_BUILD/appFw.so"
export A7R5_ASPECT_CAPTURE="$root/.local/full419-candidate-v2/build-evidence/capture"
export A7R5_OPTIONAL_AP_READBACK="$A7R5_FINAL_READBACK"
export R5_SOUND_WORKSPACE="$A7R5_NATIVE24_BUILD/work"
py="$root/.venv/bin/python"
test -x "$py"
test -f "$A7R5_FINAL_READBACK/components/usr/lib/appFw.so"
test -f "$A7R5_FINAL_READBACK/components/cpapp-b.bin"
"$py" -B - <<'PY'
import hashlib, json, os
from pathlib import Path
root = Path(os.environ['R5_AUDIT_ROOT'])
bundle = Path(os.environ['A7R5_FINAL_BUNDLE'])
lock = json.loads((bundle / 'lock.json').read_text())
if lock['version'] != '4.19' or lock['dat']['sha256'] != '48341bfbf31c4a97f1673f71d6a60e49bc4f6464b0c5b5a2355c5337b06c0f65':
    raise SystemExit('审计对象不是指定的 4.19 全功能包')
for name in ('usr/lib/appFw.so', 'cpapp-b.bin'):
    path = Path(os.environ['A7R5_FINAL_READBACK']) / 'components' / name
    with path.open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != lock['expected']['components'][name]['sha256']:
        raise SystemExit('最终组件摘要不符：' + name)
sources = json.loads((bundle / 'audit/source-lock.json').read_text())['firmware_sources']
for name, expected in sources.items():
    with (root / name).open('rb') as stream:
        actual = hashlib.file_digest(stream, 'sha256').hexdigest()
    if actual != expected:
        raise SystemExit('源码已变化，须重新评估审计对象：' + name)
PY
"$py" -B -m pytest -p no:cacheprovider \
  "$root/a7r5-firmware-features/native24-combined/tests/test_background_interaction.py" \
  "$root/a7r5-firmware-features/native24-combined/tests/test_preview_idle.py" \
  "$root/a7r5-firmware-features/native24-combined/tests/test_ui_sync.py" \
  -q --junitxml="$out/background.xml"
"$py" -B -m pytest -p no:cacheprovider \
  "$root/a7r5-firmware-features/photo-electronic-shutter-sound/tests/test_sound.py" \
  -q --junitxml="$out/sound.xml"
"$py" -B -m pytest -p no:cacheprovider "$audit/test_aspect_probes.py" \
  -q -s --junitxml="$out/aspect-probes.xml"
"$py" -B -m pytest -p no:cacheprovider "$audit/test_filter_probes.py" \
  -q -s --junitxml="$out/filter-probes.xml"
printf '%s\n' "审计回执：$out"
