#!/usr/bin/env bash
# run_capture.sh -- drive any GBA ROM through any key/step script.
#
# Usage:  bash run_capture.sh <rom.gba> [script.txt] [outdir]
#
# Defaults to scripts/chinese_gate.txt, which is the CKI 1.0 behaviour gate and
# reproduces reference/qa_boundary_v10_result.log exactly when run on the ROM
# that baseline was recorded from.
#
# Script language is documented at the top of src/gba_capture.c and in
# scripts/README.md. The short version:
#   frames N | key NAME [down] [up] | hold/release NAME | repeat N <cmd>
#   ptr SYM 0xADDR | untillive SYM LO HI MAX [KEY] | shot NAME
#   text "STRING" | peek ADDR LEN [be] | peek32 ADDR [be]
set -euo pipefail
cd "$(dirname "$0")"

ROM=${1:-}
SCRIPT=${2:-scripts/chinese_gate.txt}
OUT=${3:-out/capture}
SAVE=${SAVE:-}

if [ -z "$ROM" ]; then
    echo "usage: bash run_capture.sh <rom.gba> [script.txt] [outdir]" >&2
    exit 2
fi
[ -f "$ROM" ] || { echo "run_capture.sh: no such ROM: $ROM" >&2; exit 2; }
[ -f "$SCRIPT" ] || { echo "run_capture.sh: no such script: $SCRIPT" >&2; exit 2; }
command -v python3 >/dev/null 2>&1 || { echo "python3 is needed for the png tools" >&2; exit 2; }

if [ ! -x build/gba_capture ]; then
    echo "build/gba_capture missing -- building first"
    bash build.sh
fi

mkdir -p "$OUT"
rm -f "$OUT"/*.raw "$OUT"/capture.log

EXTRA=()
[ -n "$SAVE" ] && EXTRA=(--save "$SAVE")

echo "== 1/3  running $SCRIPT =="
./build/gba_capture "$ROM" "$SCRIPT" --out "$OUT" "${EXTRA[@]+"${EXTRA[@]}"}"

echo
echo "== 2/3  behaviour log ($OUT/capture.log) =="
cat "$OUT/capture.log"

echo
if [ "$SCRIPT" = "scripts/chinese_gate.txt" ] && [ -f reference/qa_boundary_v10_result.log ]; then
    echo "== 3/3  baseline comparison =="
    if diff -u reference/qa_boundary_v10_result.log "$OUT/capture.log"; then
        echo "MATCH: identical to the packaged CKI 1.0 baseline."
    else
        echo "MISMATCH vs the packaged baseline (see the +/- lines above)."
        echo "  Expected if you pointed this at a different ROM or changed the script."
        exit 1
    fi
else
    echo "== 3/3  no baseline applies to this script/ROM; skipping comparison =="
fi

echo
echo "frames -> PNG:"
python3 tools/raw2png.py --outdir "$OUT/png" "$OUT"/*.raw
