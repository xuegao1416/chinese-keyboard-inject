"""Locate the naming screen's keyboard window templates in a naked ROM.

Why this exists
---------------
The Chinese label puts the two glyphs 切换 into the stock page-swap button's
sprite tiles. The glyph tiles are *not* carried in the payload - they are copied
out of the keyboard window's own tile data after the game itself has drawn them.
To address a cell inside that window we need two pieces of pure layout data:

    tile index of cell (col,row) = charBlock*512 + baseBlock + 2*row*width + 1 + 2*col

`width` and `baseBlock` live in the ROM as 8-byte `struct WindowTemplate`
records.  The two keyboard-page windows are byte-identical except for `bg`
(1 and 2) and `baseBlock` (0x30 and 0xC8), which makes a 16-byte signature that
occurs exactly once in the whole ROM (verified against the test matrix).

No .map / .sym is used or needed: the record is found by its content and then
validated, following the same "recognise, then refuse if it does not add up"
rule as the rest of the injector.
"""

from __future__ import annotations

# struct WindowTemplate { u8 bg; u8 tilemapLeft; u8 tilemapTop; u8 width;
#                        u8 height; u8 paletteNum; u16 baseBlock; }  = 8 bytes
# The two keyboard page windows, exactly as this family lays them out:
#   WIN_KB_PAGE_1: bg=1 left=3 top=10 width=19 height=8 pal=10 baseBlock=0x030
#   WIN_KB_PAGE_2: bg=2 left=3 top=10 width=19 height=8 pal=10 baseBlock=0x0C8
KB_SIGNATURE = bytes([
    0x01, 0x03, 0x0A, 0x13, 0x08, 0x0A, 0x30, 0x00,
    0x02, 0x03, 0x0A, 0x13, 0x08, 0x0A, 0xC8, 0x00,
])


class LabelLayoutError(RuntimeError):
    """Raised when the ROM's keyboard-window layout is not the one we know."""


def _record(rom: bytes, off: int) -> dict:
    bg, left, top, width, height, pal = rom[off:off + 6]
    base = int.from_bytes(rom[off + 6:off + 8], "little")
    return {"offset": off, "bg": bg, "tilemap_left": left, "tilemap_top": top,
            "width": width, "height": height, "palette": pal, "base_block": base}


def resolve_keyboard_windows(rom: bytes) -> dict:
    """Return the two keyboard-page WindowTemplates, or raise.

    Raises LabelLayoutError when the ROM does not look like this family - the
    caller then leaves the Chinese label switched off rather than guessing.
    """
    hits = []
    i = rom.find(KB_SIGNATURE)
    while i >= 0:
        hits.append(i)
        i = rom.find(KB_SIGNATURE, i + 1)

    if len(hits) != 1:
        raise LabelLayoutError(
            f"expected exactly one keyboard-window template pair, found {len(hits)}")

    base_off = hits[0]
    win1 = _record(rom, base_off)
    win2 = _record(rom, base_off + 8)

    for w in (win1, win2):
        if w["bg"] > 3:
            raise LabelLayoutError(f"window bg out of range: {w}")
        if not (1 <= w["width"] <= 32) or not (1 <= w["height"] <= 32):
            raise LabelLayoutError(f"window size out of range: {w}")
        if not (0 < w["base_block"] < 0x400):
            raise LabelLayoutError(f"window baseBlock out of range: {w}")

    if (win1["width"], win1["height"], win1["tilemap_left"], win1["tilemap_top"]) != \
       (win2["width"], win2["height"], win2["tilemap_left"], win2["tilemap_top"]):
        raise LabelLayoutError("the two keyboard windows do not share one geometry")
    if win1["bg"] == win2["bg"]:
        raise LabelLayoutError("the two keyboard windows are not on two different BGs")

    return {"offset": base_off, "win1": win1, "win2": win2}
