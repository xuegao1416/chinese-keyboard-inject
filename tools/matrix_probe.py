#!/usr/bin/env python3
"""Run the 1.0 naked resolver across a set of ROMs and report where it lands.

This is the "heterogeneous matrix" harness the 1.0 checkpoint calls out as
remaining work. For each ROM it reports, with no side effects:

  * whether `resolve_modern` identifies the NamingScreen dataflow, or rejects it
    (and with which message);
  * the resolved naming-screen sites and globals;
  * whether `resolve_engine_apis` produced external addresses;
  * whether an injector-sized uniform free run exists near the handler table;
  * if a linker map is supplied for that ROM, a full oracle cross-check.

Nothing is written to any ROM. Exit code is 0 when every ROM either passed or
was rejected with a documented reason; 1 if any ROM resolved without a map to
confirm it (i.e. is neither validated nor refused).

Usage:
  python tools/matrix_probe.py --rom a.gba --map a.map --rom b.gba -o matrix.json
"""
import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "injector"))

from engine_api_resolver import resolve_engine_apis  # noqa: E402
from gmain_resolver import resolve_gmain             # noqa: E402
from inject_v10 import NEED, derive_draw_text_entry, find_free, precheck  # noqa: E402
from map_oracle import oracle_checks, parse_map      # noqa: E402
from resolve_modern import resolve_modern               # noqa: E402
from trampoline import decode_thumb_bl             # noqa: E402

BASE = 0x08000000


def probe(rom_path, map_path=None, expected_object="src/naming_screen.o"):
    rom = Path(rom_path).read_bytes()
    out = {"rom": Path(rom_path).name, "size": len(rom),
           "sha256": hashlib.sha256(rom).hexdigest()}

    try:
        r = resolve_modern(rom)
    except BaseException as e:
        out["status"] = "REJECTED_BY_RESOLVER"
        out["reason"] = f"{type(e).__name__}: {e}"
        return out

    out["status"] = "RESOLVED"
    out["family"] = r["family"]
    out["sites"] = {k: hex(r[k]) for k in
                    ("character", "page", "backspace", "ok", "handle", "delete",
                     "getchar", "flash", "lr_frame", "handler_table",
                     "naming_screen_global", "sprites_global", "keyboard_data")}
    gm = resolve_gmain(rom)
    out["gmain"] = hex(gm["gMain"])
    draw = derive_draw_text_entry(rom, r)
    out["draw_text_entry"] = hex(draw)

    try:
        ext = resolve_engine_apis(rom, r, (draw & ~1) - BASE)
        out["externals"] = {k: hex(v) for k, v in ext.items()}
    except BaseException as e:
        out["externals"] = f"REJECTED_BY_RESOLVER ({type(e).__name__}: {e})"
        ext = None

    try:
        free = find_free(rom, NEED, r["handler_table"])
        out["free_space"] = {"start": hex(free["start"]), "size": hex(free["size"]),
                             "candidates": len(free["candidates"])}
        out["free_space_ok"] = True
    except SystemExit:
        out["free_space"] = "no injector-sized uniform run"
        out["free_space_ok"] = False
        free = None

    if ext is not None:
        # free may be None when the ROM has no injector-sized uniform run; the
        # resolver-level checks still run so the report says *why* it failed.
        _checks, problems = precheck(rom, r, ext, gm, draw, free, 17434)
        out["structural_precheck_ok"] = not problems
        if problems:
            out["structural_precheck_problems"] = problems

    if map_path and Path(map_path).exists():
        symbols, sections = parse_map(map_path)
        rows, problems = oracle_checks(symbols, sections, r, gm, ext or {},
                                       expected_object, map_path)
        out["oracle"] = {"agree": len(rows) - len(problems), "total": len(rows),
                         "pass": not problems,
                         "mismatches": [x for x in rows if not x["ok"]]}
        if not problems:
            out["status"] = "RESOLVED_AND_ORACLE_CONFIRMED"
        else:
            out["status"] = "RESOLVED_BUT_ORACLE_MISMATCH"
    else:
        out["oracle"] = None
    return out


def main():
    ap = argparse.ArgumentParser(description="1.0 naked resolver matrix probe")
    ap.add_argument("--rom", action="append", required=True, help="repeatable")
    ap.add_argument("--map", action="append", default=[],
                    help="repeatable; paired with --rom by file stem")
    ap.add_argument("--object", default="src/naming_screen.o")
    ap.add_argument("-o", "--out", help="write the JSON result here")
    a = ap.parse_args()

    maps = {}
    for m in a.map:
        p = Path(m)
        maps[p.stem] = p

    results = []
    for rompath in a.rom:
        p = Path(rompath)
        if not p.exists():
            results.append({"rom": p.name, "status": "MISSING"})
            continue
        m = maps.get(p.stem)
        res = probe(p, m, a.object)
        res["map"] = str(m) if m else None
        results.append(res)
        print(json.dumps(res, indent=2), flush=True)

    unresolved = [x for x in results
                  if x.get("status") in ("RESOLVED", "RESOLVED_BUT_ORACLE_MISMATCH")]
    print(f"\n{len(results)} ROM(s): "
          + ", ".join(f"{x['rom']}={x.get('status')}" for x in results))
    if a.out:
        Path(a.out).write_text(json.dumps(results, indent=2))
    if unresolved:
        print("note: not confirmed by a map oracle - treat as unvalidated")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
