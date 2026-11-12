#!/bin/sh
# 复验本次正式全功能包；只操作本地解包和新建的测试目录。
set -eu
PROJECT_ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/../../.." && pwd -P)
cd "$PROJECT_ROOT"
BUNDLE=$(CDPATH= cd -- "$1" && pwd -P)
READBACK=$(CDPATH= cd -- "$2" && pwd -P)
STOCK=$(CDPATH= cd -- "$3" && pwd -P)
export PYTHONPATH="$PROJECT_ROOT/a7r5-dat-tool/.venv/lib/python3.14/site-packages"
EVIDENCE=$("$PROJECT_ROOT/.venv/bin/python" -B - "$4" "$BUNDLE" "$STOCK" <<'PY'
import hashlib,json,sys
from pathlib import Path
sys.path.insert(0,'a7r5-dat-tool')
from a7r5dat.ext2read import Ext2
out,bundle,stock=map(Path,sys.argv[1:]);out=out.absolute()
if not out.resolve().is_relative_to(Path.cwd()/'.local') or out.exists():
    raise ValueError('测试输出必须是 .local 下的新目录')
out.mkdir(parents=True)
f=Ext2(stock/'archive/0700_part_image/dev/nflasha15')
try:raw=f.read_inode(f.walk('/lib/libstdc++.so.6.0.22'))
finally:f.mm.close();f.f.close()
if hashlib.sha256(raw).hexdigest()!='28f2d082aea5206c42ba15664f39e2eaf7febed8f6264305e7e16aa44c878389':
    raise ValueError('原厂 C++ 库身份不符')
(out/'libstdc++.so.6.0.22').write_bytes(raw)
native=bundle/'build-evidence/native24';r=json.loads((native/'build.json').read_text())
raw=bytearray((native/'cpapp-b.bin').read_bytes())
for row in reversed(r['raw_alternatives']['patches']):
    at=row['offset'];old,new=bytes.fromhex(row['before']),bytes.fromhex(row['after'])
    if raw[at:at+len(new)]!=new:raise ValueError('RAW 逆还原目标不符')
    raw[at:at+len(old)]=old
if hashlib.sha256(raw).hexdigest()!=r['raw_alternatives']['source_sha256']:
    raise ValueError('RAW 前像身份不符')
(out/'cp-before-raw.bin').write_bytes(raw)
print(out)
PY
)
export A7R5_FINAL_BUNDLE="$BUNDLE" A7R5_FINAL_READBACK="$READBACK"
export A7R5_NATIVE24_BUILD="$BUNDLE/build-evidence/native24"
export A7R5_NATIVE24_EVIDENCE="$EVIDENCE/native24"
export A7R5_NATIVE12_STD="$EVIDENCE/libstdc++.so.6.0.22"
export A7R5_ASPECT_AP_INPUT="$A7R5_NATIVE24_BUILD/appFw.so"
export A7R5_ASPECT_CP_INPUT="$A7R5_NATIVE24_BUILD/cpapp-b.bin"
export A7R5_ASPECT_CAPTURE="$BUNDLE/build-evidence/capture"
export A7R5_ASPECT_NATIVE24_IMAGES="$A7R5_NATIVE24_BUILD"
export A7R5_OPTIONAL_AP_READBACK="$READBACK"
export A7R5_ASPECT_STOCK_USR="$STOCK/archive/0700_part_image/dev/nflasha15"
export A7R5_ASPECT_STOCK_AVCAM_PARTITION="$STOCK/archive/0700_part_image/dev/nflasha3"
export R5_SOUND_WORKSPACE="$A7R5_NATIVE24_BUILD/work"
export A7R5_LONGRUN_BUILD="$A7R5_NATIVE24_BUILD"
export A7R5_LONGRUN_CP="$READBACK/components/cpapp-b.bin"
export A7R5_RAW_CP="$A7R5_LONGRUN_CP" A7R5_RAW_SOURCE_CP="$EVIDENCE/cp-before-raw.bin"
unset A7R5_COMPONENT_CAPTURE
exec "$PROJECT_ROOT/.venv/bin/python" -B -m pytest -p no:cacheprovider -q \
  a7r5-firmware-features/photo-aspect-ratios/src \
  a7r5-firmware-features/tests/test_full419_integration.py \
  a7r5-firmware-features/native24-combined/tests/test_tabs.py \
  a7r5-firmware-features/native24-combined/tests/test_recovery_retry.py \
  a7r5-firmware-features/tests/test_longrun_resources.py \
  a7r5-firmware-features/tests/test_raw_alternatives.py \
  a7r5-firmware-features/photo-electronic-shutter-sound/tests/test_sound.py \
  a7r5-firmware-features/tests/test_final_resources.py \
  a7r5-firmware-features/tests/test_resource_package_gate.py \
  a7r5-firmware-features/tests/test_snapshot_repair.py \
  a7r5-firmware-features/tests/test_cpu_evidence_scope.py \
  --junitxml="$EVIDENCE/results.xml"
