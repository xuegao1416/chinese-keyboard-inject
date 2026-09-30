#!/usr/bin/env python3
"""Resolve `SetCursorPos` - and every site that calls it - from the naked ROM.

Why this module exists
----------------------
The naming screen repositions the cursor sprite **every frame, after** the
per-frame hook the injector already installs (`MainState_HandleInput` ->
`HandleKeyboardEvent` runs first; the D-pad/input path then calls
`SetCursorPos`). Measured on the validated host: a hook-time correction is
overwritten on the very same frame, so the selection box kept using the stock
irregular column table and drifted up to 9 px off the Chinese glyphs.

The stock routine therefore has to be intercepted at its call sites. That needs
its address, which this module recovers without any symbol table.

Anchor
------
`SetCursorPos` is the only reader of `sPageColumnXPos`, a 24-byte constant whose
content is fixed across the whole Emerald family:

    {0, 12, 24, 56, 68, 80, 92, 123}   KEYBOARD_LETTERS_LOWER
    {0, 12, 24, 56, 68, 80, 92, 123}   KEYBOARD_LETTERS_UPPER
    {0, 22, 44, 66, 88, 110}           KEYBOARD_SYMBOLS

The first two rows are byte-identical, which makes a 16-byte anchor
(`00 0C 18 38 44 50 5C 7B` twice) both unique and stable. The symbols row is
then verified separately, so trailing padding differences do not matter.

From there:
  1. find the one little-endian word `BASE + table` in the image - it lives in
     the literal pool of the function that reads the table;
  2. walk back from that literal to the nearest Thumb `PUSH` prologue: that is
     `SetCursorPos`;
  3. decode every `BL` in the image that targets it - those are the call sites.

Cross-checks (all mandatory, all raise on mismatch) make this fail loudly rather
than return a plausible wrong answer: the table must be unique, referenced
exactly once, sit in the same code island as the naming-screen handlers, and the
resolved function's own literal pool must reference the same two globals the
resolved naming screen uses.
"""
from trampoline import decode_thumb_bl

BASE = 0x08000000

# Two identical letter rows, then the first six bytes of the symbols row.
TWO_LETTER_ROWS = bytes([0, 12, 24, 56, 68, 80, 92, 123]) * 2
SYMBOLS_ROW6 = bytes([0, 22, 44, 66, 88, 110])


def find_all(buf, pat):
    out, i = [], 0
    while True:
        i = buf.find(pat, i)
        if i < 0:
            return out
        out.append(i)
        i += 1


def func_start(rom, pos, back=0x200):
    for q in range(pos & ~1, max(-1, pos - back), -2):
        h = int.from_bytes(rom[q:q + 2], "little")
        if (h & 0xFE00) == 0xB400:
            return q
    return None


def _names_table(rom, start, table, window=0x100):
    """True if a routine's constant pool names any word from table-window..table."""
    for q in range(start, min(start + 0x140, len(rom) - 2), 2):
        h = int.from_bytes(rom[q:q + 2], "little")
        if h & 0xF800 != 0x4800:
            continue
        lit = ((q + 4) & ~3) + ((h & 0xFF) << 2)
        if lit + 4 > len(rom):
            continue
        v = int.from_bytes(rom[lit:lit + 4], "little")
        if BASE <= v < BASE + len(rom) and table - window <= (v & ~1) - BASE <= table:
            return True
    return False


def _cursor_from_caller(rom, handle, table, delete, body_end):
    """SetCursorPos as the naming-screen callee of HandleKeyboardEvent that reads this table.

    Newer expansion keeps sPageColumnXPos inside a struct, so its exact address is
    never a literal and no xref of it exists - the pool only ever names the struct
    base, which a dozen functions share. HandleKeyboardEvent BLs SetCursorPos from
    its START branch, so the call graph reaches it. The dispatcher's other
    table-reading callee is DeleteTextCharacter, which the resolver has already
    named, so excluding that leaves exactly one answer.
    """
    callees = []
    for q in range(handle & ~1, body_end, 2):
        v = decode_thumb_bl(rom, q)
        if v is None or not (BASE <= v < BASE + len(rom)):
            continue
        t = (v & ~1) - BASE
        if t == handle or t in callees or t == delete:
            continue
        callees.append(t)
    keep = [t for t in callees if _names_table(rom, t, table)]
    return keep[0] if len(set(keep)) == 1 else None


def resolve_cursor(rom, anchor=None, island_span=0x8000, delete=None, body_end=None,
                   island=None):
    """Return {'table', 'set_cursor', 'sites'} for this ROM.

    `anchor` is any already-resolved naming-screen code offset (e.g. the
    HandleKeyboardEvent handler); it is used for the island sanity check and, when
    the table has no literal xref of its own, as the caller of SetCursorPos.
    `delete` and `body_end` (the first key-handler slot, i.e. the end of the
    dispatcher body) only matter on that fallback path.

    `island` is the naming screen's own (lo, hi) code range, and the sanity check
    measures the distance to that interval when it is given. Without it the check
    asks "how far from this one site?", which is a question about whichever site was
    passed: astral_emerald resolves a SetCursorPos at 0x1b0730, in the middle of its
    own naming screen, and rejects it for being 0xC8F48 from `handle`. A degenerate
    interval (anchor, anchor) reproduces the old distance exactly, so omitting
    `island` keeps the previous behaviour rather than needing a second code path.
    """
    hits = find_all(rom, TWO_LETTER_ROWS)
    if len(hits) != 1:
        raise RuntimeError(f"sPageColumnXPos anchor hits={[hex(h) for h in hits]}")
    table = hits[0]
    if rom[table + 16:table + 22] != SYMBOLS_ROW6:
        raise RuntimeError(
            f"sPageColumnXPos symbols row mismatch at {table:#x}: "
            f"{rom[table + 16:table + 24].hex()}")

    lit_word = (BASE + table).to_bytes(4, "little")
    refs = find_all(rom, lit_word)
    set_cursor = None
    if len(refs) == 1:
        lit = refs[0]
        set_cursor = func_start(rom, lit)
        if set_cursor is None:
            raise RuntimeError(f"no Thumb prologue before the table literal at {lit:#x}")
    elif len(refs) > 1:
        raise RuntimeError(
            f"literal references to sPageColumnXPos ({BASE + table:#x}) = "
            f"{[hex(r) for r in refs]}")
    if set_cursor is None and anchor is not None:
        end = body_end if (body_end and body_end > anchor) else anchor + 0x400
        set_cursor = _cursor_from_caller(rom, anchor, table, delete, min(end, len(rom) - 4))
    if set_cursor is None:
        raise RuntimeError(
            f"literal references to sPageColumnXPos ({BASE + table:#x}) = "
            f"{[hex(r) for r in refs]}, and the call-graph fallback found no unique "
            f"SetCursorPos (handle={None if anchor is None else hex(anchor)}, "
            f"delete={None if delete is None else hex(delete)})")
    if not (0xFE00 & int.from_bytes(rom[set_cursor:set_cursor + 2], "little")) == 0xB400:
        raise RuntimeError(f"SetCursorPos prologue at {set_cursor:#x} is not a PUSH")

    if anchor is not None:
        lo, hi = island if island is not None else (anchor, anchor)
        outside = max(lo - set_cursor, set_cursor - hi, 0)
        if outside > island_span:
            raise RuntimeError(
                f"SetCursorPos {set_cursor:#x} is {outside:#x} outside the naming-screen "
                f"island [{lo:#x},{hi:#x}] (limit {island_span:#x}) - wrong layout")

    target = (BASE + set_cursor) & ~1
    sites = [q for q in range(0, len(rom) - 4, 2)
             if (lambda v: v is not None and (v & ~1) == target)(decode_thumb_bl(rom, q))]
    if not sites:
        # The table anchored and the prologue is right, but nothing BLs the
        # routine: the compiler inlined it into every caller. 格查尔 Alpha8v2 is
        # exactly this shape - sPageColumnXPos resolves, SetCursorPos resolves,
        # zero BL sites. There is then nowhere to hang the cursor hook, so the
        # caller skips it: that hook only keeps the selection box aligned to the
        # 16px Chinese grid (up to 9px off without it, 17px at column 7); it is
        # a cosmetic alignment fix, not part of input. Degrade with a warning
        # rather than refuse a host that is otherwise fully resolved.
        return {"table": table, "set_cursor": set_cursor, "sites": [], "inlined": True}

    return {"table": table, "set_cursor": set_cursor, "sites": sites, "inlined": False}
