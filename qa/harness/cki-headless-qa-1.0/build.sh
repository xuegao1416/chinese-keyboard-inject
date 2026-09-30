#!/usr/bin/env bash
# build.sh -- compile the two harness binaries into build/.
#
# Usage:  bash build.sh
#         CC=clang bash build.sh          (any C11 compiler works)
#
# There is exactly one thing that must never happen here, and it is checked
# below rather than trusted to a comment: COLOR_16_BIT must not be defined.
set -euo pipefail
cd "$(dirname "$0")"

CC=${CC:-cc}
CFLAGS=${CFLAGS:--O2 -std=gnu11 -Wall -Wextra}

case " $CFLAGS " in
    *COLOR_16_BIT*)
        echo "build.sh: refusing to build -- COLOR_16_BIT is in CFLAGS." >&2
        echo "  The distribution libmgba is built with a 32-bit color_t." >&2
        echo "  See PITFALLS.md #1: this compiles clean and crashes on frame 1." >&2
        exit 2
        ;;
esac

mkdir -p build

echo "cc       = $CC"
echo "cflags   = $CFLAGS"
echo

$CC $CFLAGS -o build/gba_capture     src/gba_capture.c     -lmgba
echo "  built  build/gba_capture"

$CC $CFLAGS -o build/qa_boundary_v10 src/qa_boundary_v10.c -lmgba
echo "  built  build/qa_boundary_v10"

echo
echo "Both binaries carry a compile-time assert that sizeof(color_t) == 4,"
echo "so a wrong-linkage build fails here instead of crashing mid-run."
echo "Next:  bash run_reference.sh <injected-rom.gba>"
