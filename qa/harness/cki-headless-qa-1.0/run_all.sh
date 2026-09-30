#!/usr/bin/env bash
# run_all.sh -- the whole chain in one command, for when you just want to know
# whether this box reproduces the baseline.
#
#   1. check_env.sh   can this machine do it at all
#   2. build.sh       compile
#   3. verify.sh      run twice, prove it is reproducible and matches the baseline
#
# Usage:  bash run_all.sh <injected-rom.gba>
set -euo pipefail
cd "$(dirname "$0")"

if [ -z "${1:-}" ]; then
    echo "usage: bash run_all.sh <injected-rom.gba>" >&2
    exit 2
fi

bash check_env.sh
echo
bash build.sh
echo
bash verify.sh "$1"
