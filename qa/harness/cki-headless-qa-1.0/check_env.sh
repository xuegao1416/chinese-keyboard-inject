#!/usr/bin/env bash
# check_env.sh -- tell me, before anything else, whether this box can run the
# headless capture harness. Run it first. It changes nothing.
#
# Usage:  bash check_env.sh
set -u

fail=0
row() { printf '  %-26s %s\n' "$1" "$2"; }
ok()  { row "$1" "ok   $2"; }
bad() { row "$1" "FAIL $2"; fail=1; }
note(){ row "$1" "     $2"; }

echo "== 1. OS / architecture =="
if [ -r /etc/os-release ]; then . /etc/os-release; ok "os" "${PRETTY_NAME:-unknown}"; else note os "not Linux?"; fi
arch=$(uname -m)
case "$arch" in
    x86_64) ok "arch" "$arch" ;;
    *)      bad "arch" "$arch -- libmgba packages here are x86_64; expect trouble" ;;
esac

echo
echo "== 2. C toolchain =="
if command -v cc >/dev/null 2>&1; then ok "cc" "$(cc --version | head -1)"
else bad cc "sudo apt install -y build-essential"; fi

echo
echo "== 3. libmgba: headers + shared library =="
if [ -f /usr/include/mgba/core/core.h ]; then ok "headers" "/usr/include/mgba/core/core.h"
else bad headers "sudo apt install -y libmgba-dev"; fi
if ldconfig -p 2>/dev/null | grep -q 'libmgba\.so'; then
    ok "libmgba" "$(ldconfig -p | grep -o 'libmgba\.so[.0-9]*' | head -1)"
else bad libmgba "sudo apt install -y libmgba-dev"; fi
if command -v pkg-config >/dev/null 2>&1 && pkg-config --exists mgba 2>/dev/null; then
    note "pkg-config" "mgba $(pkg-config --modversion mgba)"
else
    note "pkg-config" "no mgba.pc -- expected; build.sh links -lmgba directly"
fi

echo
echo "== 4. libminizip (runtime only; mGBA front-ends need it, this harness does not) =="
if ldconfig -p 2>/dev/null | grep -q 'libminizip\.so\.1'; then ok libminizip "present"
else note libminizip "absent -- only matters if you run an mGBA binary, not this harness"; fi

echo
echo "== 5. python3 (only used by tools/raw2png.py and tools/montage.py) =="
if command -v python3 >/dev/null 2>&1; then ok python3 "$(python3 -V 2>&1) (stdlib only, no pip needed)"
else bad python3 "sudo apt install -y python3"; fi

echo
echo "== 6. the check that actually matters: sizeof(color_t) =="
tmp=$(mktemp -d)
cat > "$tmp/chk.c" <<'EOF'
#include <stdio.h>
#include <mgba/core/interface.h>
int main(void) {
    printf("%zu", sizeof(color_t));
#ifdef COLOR_16_BIT
    printf(" COLOR_16_BIT");
#endif
    return 0;
}
EOF
if cc -O2 -o "$tmp/chk" "$tmp/chk.c" 2>"$tmp/err"; then
    res=$("$tmp/chk")
    case "$res" in
        4)  ok "sizeof(color_t)" "4 -- 32-bit native color, matches the .raw format" ;;
        *)  bad "sizeof(color_t)" "$res -- NOT 4. Do not trust any byte-order advice until this is 4." ;;
    esac
else
    bad "sizeof(color_t)" "could not compile a 4-line probe; see $tmp/err"
    sed -n '1,5p' "$tmp/err" | sed 's/^/      /'
fi
rm -rf "$tmp"

echo
if [ "$fail" -eq 0 ]; then
    echo "RESULT: this box can build and run the harness.  Next: bash build.sh"
    exit 0
fi
echo "RESULT: something above is missing. Install it, then run this again."
exit 2
