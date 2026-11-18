#!/bin/sh
# Read-only Fastboot evidence capture. Never sends flash, erase, download, or reboot.
set -eu

ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
FASTBOOT="$ROOT/a7r5-fastboot/host/read_fastboot_usb"
RUN=${1:-"$ROOT/a7r5-fastboot/runs/readonly-$(date +%Y%m%d-%H%M%S)"}

case "$RUN" in
  /*) ;;
  *) RUN="$ROOT/$RUN" ;;
esac
if [ -e "$RUN" ]; then
  echo "Output directory already exists: $RUN" >&2
  exit 2
fi
mkdir -m 700 -p "$RUN"
RUN_ABS=$(CDPATH= cd -- "$RUN" && pwd)

run_read() {
  label=$1
  shift
  for arg in "$@"; do
    case "$arg" in
      flash:*|erase:*|download:*|reboot)
        echo "Refusing non-read command: $arg" >&2
        exit 3
        ;;
    esac
  done
  "$FASTBOOT" "$@" >"$RUN_ABS/$label.log" 2>&1
}

run_read partition-table getvar:version "oem partition"
run_read sdm2 "oem partition dump nflasha 0 0x80" "upload:$RUN_ABS/sdm2.raw.bin"
run_read ap-bootrom "oem dumpbrom" "upload:$RUN_ABS/ap-bootrom.bin"
run_read nflasha2 "oem partition dump nflasha2" "upload:$RUN_ABS/nflasha2.logical.img"
run_read nflasha5 "oem partition dump nflasha5" "upload:$RUN_ABS/nflasha5.logical.img"
run_read nflasha2-raw "oem partition dump nflasha 0xc000 0xa000" "upload:$RUN_ABS/nflasha2.raw.img"

/usr/bin/shasum -a 256 "$RUN_ABS"/* > "$RUN_ABS/SHA256SUMS"
/usr/bin/stat -f '%N %z bytes' "$RUN_ABS"/* > "$RUN_ABS/SIZES"
printf 'Read-only capture complete: %s\n' "$RUN_ABS"
