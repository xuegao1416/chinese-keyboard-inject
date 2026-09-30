#!/usr/bin/env python3
"""Optional linker-map oracle for the naked-ROM resolver.

1.0 resolves everything without a `.map`. That is the point - but it also means
the injector has no independent witness for its own output. The matrix run showed
why that matters: on the agbcc-built `pokeemerald-rogue` ROM the semantic
resolver finds every naming-screen site correctly, yet returns *wrong* addresses
for four of the five engine APIs. Nothing in the pipeline notices, because the
wrong addresses are still distinct, in range, and Thumb-tagged.

So the map is kept as an **optional** oracle, never as an input. Given a map,
`inject_v10.py --oracle-map` refuses to patch when the resolver disagrees with
it. Without a map, nothing changes. The oracle can only tighten the gate.

`parse_map` also returns `.text` section ownership, which is what lets a caller
assert that every resolved naming-screen site really landed inside the expected
object file.
"""
from pathlib import Path

BASE = 0x08000000
EWRAM_LO, EWRAM_HI = 0x02000000, 0x02040000
# Section names a linker script may route a file-static EWRAM object through.
# `ld -M` prints them without the leading dot for `ewram_data` but with it for
# `.sbss`, so compare on the dotted name stripped.
EWRAM_DATA_SECTIONS = ("ewram_data", "sbss", "bss", "data")

# name in the resolver result -> name in the linker map
EXTERNAL_SYMBOLS = ("PlaySE", "FillWindowPixelBuffer", "PutWindowTilemap",
                    "CopyWindowToVram", "AddTextPrinterParameterized3")
GLOBALS = {"gMain": "gMain", "gSprites": "sprites_global"}
LOCAL_FIELDS = ("character", "page", "backspace", "ok", "handle", "delete",
                "getchar", "flash", "lr_frame")


def parse_map(path):
    """Return (symbols, text_sections) from a GNU ld map.

    Handles both the plain `ADDR NAME` form and the `ADDR NAME = .` form that
    ld emits when a symbol is assigned a location inside a section.
    """
    symbols = {}
    sections = []
    for line in Path(path).read_text(errors="replace").splitlines():
        parts = line.split()
        if len(parts) == 4 and parts[2] == "=" and parts[0].startswith("0x"):
            try:
                symbols.setdefault(parts[1], int(parts[0], 16))
            except ValueError:
                pass
        elif len(parts) == 2 and parts[0].startswith("0x"):
            try:
                symbols.setdefault(parts[1], int(parts[0], 16))
            except ValueError:
                pass
        elif len(parts) == 4 and parts[0] == ".text" and parts[1].startswith("0x"):
            try:
                sections.append((parts[3], int(parts[1], 16), int(parts[2], 16)))
            except ValueError:
                pass
    return symbols, sections


def owner_of(sections, addr):
    """Which object file's .text contains this runtime address?"""
    for obj, start, size in sections:
        if start <= addr < start + size:
            return obj
    return None


def static_naming_screen_global(symbols, sections, map_path, expected_object):
    """Address of the naming-screen object's 4-byte EWRAM global.

    `sNamingScreen` is file-static, so ld does not always emit its name. The data
    section that names the object file does identify it: the naming screen keeps
    exactly one 4-byte EWRAM global, the pointer the adapter reads.

    Which section that lands in is the linker script's choice, not the source's:
    expansion builds put it in `ewram_data`, but a stock 1.9.4 build puts it in
    `.sbss` (`.sbss 0x02035358 0x4 src/naming_screen.o`). Matching only the first
    name made the oracle blind on upstream builds, and a silent oracle reads as a
    contradiction downstream. Ambiguity is still refused: more than one match is
    no evidence, so return None rather than guess.
    """
    hits = []
    for line in Path(map_path).read_text(errors="replace").splitlines():
        p = line.split()
        if len(p) != 4 or p[3] != expected_object or p[2] != "0x4":
            continue
        if p[0].lstrip(".") not in EWRAM_DATA_SECTIONS:
            continue
        addr = int(p[1], 16)
        if EWRAM_LO <= addr < EWRAM_HI:
            hits.append((p[0].lstrip("."), addr))
    return hits[0][1] if len(hits) == 1 else None


def oracle_checks(symbols, sections, r, gm, ext, expected_object="src/naming_screen.o",
                  map_path=None):
    """Compare resolver output against the map. Returns (rows, problems)."""
    rows = []

    def add(kind, name, got, want, ok, note=""):
        rows.append({"kind": kind, "name": name, "resolver": got, "map": want,
                     "ok": bool(ok), "note": note})

    for k in EXTERNAL_SYMBOLS:
        want, got = symbols.get(k), ext.get(k)
        add("external", k, None if got is None else hex(got),
            None if want is None else hex(want),
            want is not None and got is not None and (got & ~1) == want)

    for name, field in GLOBALS.items():
        want = symbols.get(name)
        got = gm["gMain"] if field == "gMain" else r.get(field)
        add("global", name, None if got is None else hex(got),
            None if want is None else hex(want),
            want is not None and got is not None and got == want)

    want = symbols.get("sNamingScreen")
    note = ""
    if want is None and map_path:
        want = static_naming_screen_global(symbols, sections, map_path, expected_object)
        note = ("recovered from the unique 4-byte EWRAM data section of "
                + expected_object)
    got = r.get("naming_screen_global")
    add("global", "sNamingScreen", None if got is None else hex(got),
        None if want is None else hex(want),
        want is not None and got is not None and got == want, note)

    for f in LOCAL_FIELDS:
        off = r[f]
        owner = owner_of(sections, BASE + off)
        add("containment", f, hex(off), owner or "(outside any .text section)",
            owner == expected_object, "" if owner == expected_object else
            f"expected {expected_object}")

    problems = [f"{x['kind']} {x['name']}: resolver {x['resolver']} vs map {x['map']} {x['note']}".strip()
                for x in rows if not x["ok"]]
    return rows, problems
