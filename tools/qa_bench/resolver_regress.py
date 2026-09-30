#!/usr/bin/env python3
"""Re-run the resolver over every archived report and diff field by field.

The corpus reports under test_roms/reports_full/*.json freeze what the resolver
produced for each host at the time that host was accepted (and, for 13 of them,
what a real emulator screenshot then confirmed). Any edit to resolve_modern.py
or gmain_resolver.py must reproduce those values exactly, host by host, or the
change is a regression and not a fix - regardless of what it does for the new
host it was written for.

Usage:  python3 tools/qa_bench/resolver_regress.py [--verbose]
Exit 0 = every archived field still reproduces. Exit 1 = at least one drift.
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "injector"))
from resolve_modern import resolve_modern          # noqa: E402
from gmain_resolver import resolve_gmain           # noqa: E402
try:
    from inject_v10 import pick_frame_site         # noqa: E402
except Exception:                                   # noqa: BLE001
    pick_frame_site = None

# Fields whose archived value is a promise. `flash`/`cursor` are reported but not
# used by 1.0, and `handle_via`/`getchar_repaired` are route labels that legitimately
# change when a route is added, so they are printed but not failed on.
HARD = ("keyboard_data", "getchar", "character", "page", "backspace", "ok",
        "handler_table", "handle", "delete", "lr_frame",
        "naming_screen_global", "sprites_global", "bufferchar")

SOFT = ("addchar", "cursor", "flash", "handle_via", "getchar_repaired",
        "addchar_inlined", "family")


def norm(v):
    if isinstance(v, str):
        try:
            return int(v, 16)
        except ValueError:
            return v
    return v


def main():
    verbose = "--verbose" in sys.argv
    drift = []
    rows = []
    for rp in sorted((ROOT / "test_roms/reports_full").glob("*.json")):
        try:
            rep = json.loads(rp.read_text(encoding="utf-8"))
        except Exception as exc:
            rows.append((rp.stem, "UNREADABLE " + str(exc)[:40]))
            continue
        rel = rep.get("input") or ""
        rom = ROOT / rel if rel else None
        if rom is None or not rom.exists():
            rom = next(iter(sorted(ROOT.glob("test_roms/roms*/" + rp.stem + ".gba"))), None)
        if rom is None or not rom.exists():
            rows.append((rp.stem, "NO-ROM"))
            continue
        want = rep.get("resolver") or {}
        want_g = rep.get("gmain") or {}
        try:
            got = resolve_modern(rom.read_bytes())
        except Exception as exc:
            rows.append((rp.stem, "RESOLVER_NOW_FAILS: " + str(exc)[:70]))
            drift.append((rp.stem, "resolver raised"))
            continue
        try:
            got_g = resolve_gmain(rom.read_bytes())
        except SystemExit as exc:
            got_g = {"error": str(exc)}
        # inject_v10 overwrites r["lr_frame"] with pick_frame_site() before it
        # writes the report, so the archived field is the *patched* site, not the
        # resolver's raw answer. Comparing raw-vs-patched reported five bogus
        # "regressions" all shifted by the same 0x1CE. Replay the same step here so
        # the harness checks the address that actually goes into the ROM.
        if pick_frame_site is not None:
            try:
                got["lr_frame"] = pick_frame_site(rom.read_bytes(), got)
            except BaseException as exc:                # noqa: BLE001 - refuse() exits
                got["lr_frame"] = "PICK_FAIL:" + str(exc)[:40]

        bad = []
        for k in HARD:
            if k not in want:
                continue
            if norm(want[k]) != norm(got.get(k)):
                bad.append("%s %s->%s" % (k, hex(norm(want[k])) if isinstance(norm(want[k]), int) else want[k],
                                          hex(norm(got.get(k))) if isinstance(norm(got.get(k)), int) else got.get(k)))
        for k in ("gMain", "newKeysRaw"):
            if norm(want_g.get(k)) != norm(got_g.get(k)):
                bad.append("gmain.%s %s->%s" % (k, want_g.get(k), got_g.get(k)))
        soft = []
        for k in SOFT:
            if k in want and norm(want[k]) != norm(got.get(k)):
                soft.append("%s %s->%s" % (k, want[k], got.get(k)))
        if bad:
            drift.append((rp.stem, "; ".join(bad)))
        rows.append((rp.stem, ("DRIFT " if bad else "ok ") +
                     ("| soft: " + "; ".join(soft) if soft else "") +
                     ("  " + hex(got["handler_table"]) if not bad else "")))
    for name, msg in rows:
        if verbose or msg.startswith(("DRIFT", "RESOLVER", "NO-ROM", "UNREADABLE")) or " soft:" in msg:
            print("%-36s %s" % (name[:36], msg))
    if not rows:
        print("NO REPORTS: test_roms/reports_full/*.json is the local corpus workbench "
              "and is not published with the repository. An empty regression run is not a "
              "pass, so this exits non-zero instead of reporting green.")
        return 2
    print("\n%d reports checked, %d with hard drift" % (len(rows), len(drift)))
    for name, msg in drift:
        print("  DRIFT %-32s %s" % (name[:32], msg))
    return 1 if drift else 0


if __name__ == "__main__":
    sys.exit(main())
