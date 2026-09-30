#!/usr/bin/env python3
"""Cross-check the naked-ROM resolver against a linker map.

`inject_v10.py` deliberately resolves every address without a `.map` or `.sym`.
That is only trustworthy if it can be *shown* to agree with the symbol oracle it
replaced. This tool runs the same three resolver stages the injector runs and
compares the result against the addresses in a linker map produced by the build
that made the ROM:

  1. the five external engine APIs;
  2. the globals (`gMain`, `gSprites`, `sNamingScreen`);
  3. object-file containment - every naming-screen-local site the resolver
     reports must land inside the `.text` range of the object the map says owns
     the naming screen.

Exit code is 0 only when every comparison passes. This is the check that caught
the engine-API mis-resolution on the agbcc-built `pokeemerald-rogue` ROM; see
docs/MATRIX.md.

Usage:
  python tools/verify_against_map.py ROM.gba --map build.map
  python tools/verify_against_map.py ROM.gba --map build.map --object src/naming_screen.o
"""
import argparse
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "injector"))

from engine_api_resolver import resolve_engine_apis  # noqa: E402
from gmain_resolver import resolve_gmain             # noqa: E402
from map_oracle import oracle_checks, parse_map      # noqa: E402
from resolve_modern import resolve_modern               # noqa: E402
from trampoline import decode_thumb_bl             # noqa: E402

BASE = 0x08000000


def resolve(rom):
    """The exact resolver half of inject_v10.py, without the CLI."""
    r = resolve_modern(rom)
    gm = resolve_gmain(rom)
    cs = [v & ~1 for v in
          (decode_thumb_bl(rom, q)
           for q in range(r["getchar"], min(r["getchar"] + 0x90, len(rom) - 4), 2))
          if v is not None and BASE <= (v & ~1) < BASE + len(rom)]
    draw = min(cs, key=lambda v: abs((v - BASE) - r["getchar"])) | 1
    ext = resolve_engine_apis(rom, r, (draw & ~1) - BASE)
    return r, gm, ext


def main():
    ap = argparse.ArgumentParser(description="compare the naked-ROM resolver against a linker map")
    ap.add_argument("rom")
    ap.add_argument("--map", required=True, dest="mapfile")
    ap.add_argument("--object", default="src/naming_screen.o",
                    help="object file expected to own the naming-screen code")
    ap.add_argument("-o", "--out", help="write the JSON result here")
    a = ap.parse_args()

    rom = Path(a.rom).read_bytes()
    symbols, sections = parse_map(a.mapfile)
    if not symbols:
        raise SystemExit(f"no symbols parsed from {a.mapfile}")
    r, gm, ext = resolve(rom)
    rows, problems = oracle_checks(symbols, sections, r, gm, ext, a.object, a.mapfile)

    print(f"resolver vs {Path(a.mapfile).name} - "
          f"{len(rows) - len(problems)}/{len(rows)} agree\n")
    width = max(len(x["name"]) for x in rows)
    for x in rows:
        print(f"  {'ok ' if x['ok'] else 'BAD'}  {x['kind']:11s} {x['name']:<{width}}  "
              f"resolver {str(x['resolver']):>12}   map {str(x['map']):>28}")

    result = {
        "format": "CKI-MAP-CROSSCHECK1",
        "rom": str(a.rom),
        "map": str(a.mapfile),
        "expected_object": a.object,
        "agree": len(rows) - len(problems),
        "total": len(rows),
        "pass": not problems,
        "rows": rows,
        "resolver": {k: (hex(v) if isinstance(v, int) else v) for k, v in r.items()},
    }
    if a.out:
        Path(a.out).write_text(json.dumps(result, indent=2))
    if problems:
        print("\nmismatches:")
        for p in problems:
            print("  - " + p)
        raise SystemExit(1)


if __name__ == "__main__":
    main()
