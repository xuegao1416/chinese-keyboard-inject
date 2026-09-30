#!/usr/bin/env python3
"""Test the 1.0 gates against deliberately broken resolver output.

The structural pre-check is the reason a wrong resolution fails loudly instead
of producing a corrupt ROM. A gate that is never seen to fire is not evidence, so
this drives it with a set of realistic wrong-but-plausible resolutions and
asserts that each one is caught.

Mutations applied (each is a mistake a resolver could actually make):

  * the handler table is redirected at a different handler
  * a resolved handler is not a Thumb function entry
  * the frame callsite is no longer a BL to HandleKeyboardEvent
  * the delete site is not a function entry
  * an engine API aliases another engine API
  * the three window APIs are far apart (the real agbcc failure, docs/MATRIX.md)
  * the free run is not uniform / not aligned
  * the payload does not fit the free run

Usage:
  python tools/selftest_gates.py ROM.gba [--map MAP]
"""
import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "injector"))

from engine_api_resolver import resolve_engine_apis  # noqa: E402
from gmain_resolver import resolve_gmain             # noqa: E402
from inject_v10 import (BASE, NEED, REFERENCE_PAYLOAD,
                        derive_draw_text_entry, find_free, precheck)  # noqa: E402
from map_oracle import oracle_checks, parse_map      # noqa: E402
from resolve_modern import resolve_modern               # noqa: E402


def free_space_guard_selftest():
    """Prove the 0xFF free-space guard actually fires.

    Synthesise the exact shape the guard exists for: an erased-looking 0xFF run
    that a literal pool still loads a pointer into (i.e. live data), sitting next
    to a genuinely clean all-zero run that is *larger*, so size alone would pick
    the wrong one. Without the guard the 0xFF run wins; with it, the clean run.
    """
    import struct
    size = 0x100000
    rom = bytearray(b"\x11" * size)
    rom[0x40000:0x48000] = b"\xFF" * 0x8000          # erased-looking, but "live"
    rom[0x60000:0x69000] = b"\x00" * 0x9000          # clean, and bigger
    q = 0x20000                                      # `ldr r0,[pc,#0]`
    rom[q], rom[q + 1] = 0x00, 0x48
    lit = (q + 4) & ~3
    rom[lit:lit + 4] = struct.pack("<I", BASE + 0x40000)
    loose = find_free(bytes(rom), NEED, 0, strict=False)
    tight = find_free(bytes(rom), NEED, 0, strict=True)
    ok = (loose["start"] == 0x40000 and loose["literal_pool_refs"]
          and tight["start"] == 0x60000 and not tight["literal_pool_refs"])
    print(f"  {'CAUGHT' if ok else 'MISSED'}  free-space guard: guard off -> "
          f"{loose['start']:#x} (refs {len(loose['literal_pool_refs'])}), "
          f"guard on -> {tight['start']:#x}")
    return ok


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("rom")
    ap.add_argument("--map", dest="mapfile")
    ap.add_argument("--object", default="src/naming_screen.o")
    a = ap.parse_args()

    rom = Path(a.rom).read_bytes()
    guard_ok = free_space_guard_selftest()
    r = resolve_modern(rom)
    gm = resolve_gmain(rom)
    draw = derive_draw_text_entry(rom, r)
    ext = resolve_engine_apis(rom, r, (draw & ~1) - BASE)
    free = find_free(rom, NEED, r["handler_table"])

    checks, problems = precheck(rom, r, ext, gm, draw, free, REFERENCE_PAYLOAD)
    print(f"clean input: {sum(c['ok'] for c in checks)}/{len(checks)} checks, "
          f"{len(problems)} problem(s)")
    if problems:
        print("  the baseline must be clean before mutations mean anything")
        for p in problems:
            print("   -", p)
        raise SystemExit(1)

    cases = [
        ("handler table redirected at another handler", "r", "page", r["page"] + 0x40),
        ("resolved handler is not a function entry", "r", "page", r["page"] + 1),
        ("frame site no longer a BL to HandleKeyboardEvent", "r", "lr_frame", r["lr_frame"] + 2),
        ("delete site is not a function entry", "r", "delete", r["delete"] + 2),
        ("engine API aliases another engine API", "ext", "PlaySE", ext["FillWindowPixelBuffer"]),
        ("window APIs are far apart (the agbcc failure)", "ext", "FillWindowPixelBuffer",
         ext["PutWindowTilemap"] + 0x10000),
        ("free run is not uniform / not aligned", "free", "start", free["start"] + 1),
        ("payload does not fit the free run", "free", "start", len(rom) - 10),
    ]

    missed = 0
    for label, where, key, val in cases:
        rr, ee, ff = dict(r), dict(ext), dict(free)
        {"r": rr, "ext": ee, "free": ff}[where][key] = val
        try:
            _c, probs = precheck(rom, rr, ee, gm, draw, ff, REFERENCE_PAYLOAD)
        except BaseException as e:  # a raise is a catch too, just noisier
            probs = [f"raised {type(e).__name__}: {e}"]
        print(f"  {'CAUGHT' if probs else 'MISSED'}  {label}")
        for p in probs[:2]:
            print("            -", p)
        missed += 0 if probs else 1

    if a.mapfile:
        symbols, sections = parse_map(a.mapfile)
        rows, probs = oracle_checks(symbols, sections, r, gm, ext, a.object, a.mapfile)
        print(f"oracle vs map: {len(rows) - len(probs)}/{len(rows)} agree")
        if probs:
            print("  note: this ROM is not oracle-confirmed; inject_v10.py will refuse "
                  "to patch it without --allow-unvalidated")
            for p in probs[:4]:
                print("            -", p)

    print(f"\n{len(cases) - missed}/{len(cases)} mutations caught")
    if missed or not guard_ok:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
