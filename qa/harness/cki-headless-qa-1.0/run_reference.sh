#!/usr/bin/env bash
# run_reference.sh -- boot an injected ROM through the CKI 1.0 behaviour probe,
# dump one frame per step, convert them to PNG, and check the behaviour log
# against the recorded baseline.
#
# Usage:  bash run_reference.sh <injected-rom.gba> [outdir]
#
# The ROM you pass must be the injected output of the CKI 1.0 injector, not the
# stock input. If you are unsure, check its sha256 against the report's
# output_sha256 first -- a probe run on the wrong ROM produces a confidently
# wrong log.
set -euo pipefail
cd "$(dirname "$0")"

ROM=${1:-}
OUT=${2:-out/reference}
if [ -z "$ROM" ]; then
    echo "usage: bash run_reference.sh <injected-rom.gba> [outdir]" >&2
    exit 2
fi
if [ ! -f "$ROM" ]; then
    echo "run_reference.sh: no such ROM: $ROM" >&2
    exit 2
fi
command -v python3 >/dev/null 2>&1 || { echo "python3 is needed for the png tools" >&2; exit 2; }

if [ ! -x build/qa_boundary_v10 ]; then
    echo "build/qa_boundary_v10 missing -- building first"
    bash build.sh
fi

mkdir -p "$OUT"
rm -f "$OUT"/v10_*.raw "$OUT"/qa_boundary_v10_result.log "$OUT"/log.diff

echo "== 1/4  boot, walk to the naming screen, enter CN mode, press A/B =="
./build/qa_boundary_v10 "$ROM" "$OUT/"

echo
echo "== 2/4  behaviour log =="
cat "$OUT/qa_boundary_v10_result.log"

echo
echo "== 3/4  baseline comparison =="
if [ -f reference/qa_boundary_v10_result.log ]; then
    if diff -u reference/qa_boundary_v10_result.log "$OUT/qa_boundary_v10_result.log" > "$OUT/log.diff"; then
        rm -f "$OUT/log.diff"
        echo "MATCH: behaviour log is byte-identical to the packaged baseline."
    else
        echo "MISMATCH -- differences against the baseline:"
        cat "$OUT/log.diff"
        echo
        echo "  A mismatch is a finding, not a tooling error, UNLESS the ROM is not"
        echo "  the one the baseline came from (wrong sha256, or a different host)."
        echo "  Check report.input/output_sha256 before concluding anything."
        exit 1
    fi
else
    echo "no packaged baseline log; skipping"
fi

echo
echo "== 4/4  frames -> PNG, contact sheet, and frame-by-frame comparison =="
mkdir -p "$OUT/png"
python3 tools/raw2png.py --outdir "$OUT/png" "$OUT"/*.raw
python3 tools/montage.py -o "$OUT/behaviour_montage.png" --cols 4 \
    "$OUT/v10_locked_empty.raw" "$OUT/v10_1cn.raw" "$OUT/v10_2cn.raw" \
    "$OUT/v10_3cn.raw" "$OUT/v10_4th.raw" "$OUT/v10_delete.raw" "$OUT/v10_readd.raw"

if [ -f reference/v10_locked_empty.png ]; then
    echo
    echo "--- each frame vs the packaged reference frame ---"
    bad=0
    for n in locked_empty 1cn 2cn 3cn 4th delete readd; do
        if ! python3 tools/png_cmp.py "reference/v10_$n.png" "$OUT/png/v10_$n.png"; then
            bad=$((bad + 1))
        fi
    done
    if [ "$bad" -eq 0 ]; then
        echo "ALL 7 FRAMES IDENTICAL to the packaged reference."
    else
        echo "$bad of 7 frames differ -- open them side by side before deciding anything."
    fi
fi

echo
echo "Now do the part no tool can do for you: look at"
echo "  $OUT/behaviour_montage.png"
echo "against docs/QA_ACCEPTANCE_STANDARD.md gate 5."
