#!/usr/bin/env bash
# verify.sh -- prove this harness is reproducible on this box BEFORE you trust
# any frame it produces.
#
# A visual gate that cannot be re-run is not evidence. So: run the reference
# probe twice on the same ROM and check all four of
#   1. the two behaviour logs are byte-identical to each other,
#   2. the behaviour log matches the packaged baseline,
#   3. the two sets of raw frames are byte-identical,
#   4. the frames match the packaged reference frames, pixel for pixel.
#
# Usage:  bash verify.sh <injected-rom.gba>
set -euo pipefail
cd "$(dirname "$0")"

ROM=${1:-}
if [ -z "$ROM" ]; then
    echo "usage: bash verify.sh <injected-rom.gba>" >&2
    exit 2
fi
[ -f "$ROM" ] || { echo "verify.sh: no such ROM: $ROM" >&2; exit 2; }

if [ ! -x build/qa_boundary_v10 ]; then bash build.sh; fi

FRAMES="v10_locked_empty v10_1cn v10_2cn v10_3cn v10_4th v10_delete v10_readd"
rc=0

run_into() {
    local dir=$1
    mkdir -p "$dir/png"
    rm -f "$dir"/v10_*.raw "$dir"/qa_boundary_v10_result.log
    ./build/qa_boundary_v10 "$ROM" "$dir/" > "$dir/run.stdout" 2> "$dir/run.stderr"
    python3 tools/raw2png.py --outdir "$dir/png" "$dir"/*.raw > /dev/null
}

echo "== run A =="
run_into out/verify_a
echo "== run B =="
run_into out/verify_b

echo
echo "== 1. run A log vs run B log =="
if diff -q out/verify_a/qa_boundary_v10_result.log out/verify_b/qa_boundary_v10_result.log > /dev/null; then
    echo "   identical"
else
    echo "   FAIL: the same ROM produced two different logs. The harness is not"
    echo "   deterministic -- fix that before trusting anything else."
    rc=1
fi

echo
echo "== 2. log vs packaged baseline =="
if diff -u reference/qa_boundary_v10_result.log out/verify_a/qa_boundary_v10_result.log; then
    echo "   identical to reference/qa_boundary_v10_result.log"
else
    echo "   FAIL: differs from the baseline (see +/- above)."
    echo "   Real finding if this is the baseline ROM; wrong ROM otherwise."
    rc=1
fi

echo
echo "== 3. run A frames vs run B frames (raw bytes) =="
for n in $FRAMES; do
    if cmp -s "out/verify_a/$n.raw" "out/verify_b/$n.raw"; then
        echo "   same   $n.raw"
    else
        echo "   FAIL   $n.raw differs between two runs"
        rc=1
    fi
done

echo
echo "== 4. frames vs packaged reference frames (pixels) =="
if [ ! -f reference/v10_locked_empty.png ]; then
    echo "   no packaged reference frames; skipping"
else
    for n in $FRAMES; do
        if python3 tools/png_cmp.py "reference/$n.png" "out/verify_a/png/$n.png" > /dev/null; then
            echo "   same   $n"
        else
            echo "   FAIL   $n differs -- run tools/png_cmp.py by hand to see where"
            rc=1
        fi
    done
fi

echo
if [ "$rc" -eq 0 ]; then
    echo "VERIFIED: reproducible, and matching the packaged baseline."
else
    echo "NOT VERIFIED: see the FAIL lines above."
fi
exit "$rc"
