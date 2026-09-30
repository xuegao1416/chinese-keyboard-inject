# The Chinese label on the page-swap button

**Status: ON by default.** The stock page-swap button says `lower` / `upper` /
`others` (what the *next* Latin page is), which is stale once Chinese mode is on.

While Chinese mode is on the button is re-lettered to **切换** and the stale word
strip is hidden; leaving Chinese mode puts both back, byte for byte. The payload
carries **no glyph data**: the two glyphs are copied out of the keyboard window's
own tile data, which the game itself has just decompressed there - the same rule
`chars[]` follows.

Pass `--no-cn-label` to opt out. A host whose keyboard windows do not match the
shape `label_resolver.py` looks for simply keeps the plain keyboard: that prints
a warning and carries on, it does not refuse the ROM.

## What it does

The stock naming screen's right-hand column has a page-swap button whose word
strip reads `lower` / `upper` / `others` (what the *next* Latin page is). While
Chinese mode is on, the button is re-lettered to **切换** and the stale word strip
is hidden; leaving Chinese mode puts both back, byte for byte. The payload
carries **no glyph data**: the two glyphs are copied out of the keyboard
window's own tile data, which the game itself has just decompressed there - the
same rule `chars[]` follows.

## The size problem, and the space available

The first working version blitted each glyph as a full 16x16 cell. On screen the
two characters burst out of the capsule. Measuring the real thing:

- the button is a 32x16 OAM sprite whose centre sits at (204,83), so its canvas
  starts at screen (188,75);
- the capsule drawn by `page_swap_button.png` is **28x9** at canvas (2,4), and
  nothing outside it is visible (the frame sprite does not extend past it);
- the stock word it replaces, `lower`, is only **6 px tall** inside that opening;
- the host's Chinese face puts **12x12** ink into the cell.

So the glyph *has* to be scaled down. Cropping the ink box to 9 rows (the first
attempt) cut the bottom horizontal strokes clean off; `ck_draw_glyph` now
box-samples the whole ink box into the opening's height, keeping the glyph's full
width (two glyphs + 2 px gap = 26 of the 28 px). Ink tone 1 wins over tone 2
inside each sample so thin strokes survive the squeeze.

`CK_LABEL_FONT` asks for `FONT_SMALL` first, but on the test host both Chinese
faces hand the printer the same 12x12 ink (`chinese_small.png` is not actually
smaller there), so the scaling does the real work. The define stays so a host
whose small face *is* smaller gets it for free.

## The bugs that had to be found first

1. **VRAM does not accept 8-bit writes on the GBA.** The first implementation
   wrote tiles with `u8*` stores: hardware drops them, so the blit silently did
   nothing while the state machine reported success.
2. **4bpp packs four pixels per 16-bit word, and the write mask has to match.**
   The second version selected a whole *byte* (`0x00FF`/`0xFF00`) keyed on `x&1`
   and therefore clobbered the neighbouring pixel, and for `x` with `(x&3)>=2`
   it wrote the wrong byte outright. On screen this looked like the glyph
   dissolving into vertical stripes; there is nothing for the compiler to warn
   about. `ck_opx` now computes the word and the 4-bit shift explicitly.
3. **The scratch area matters.** The first version stashed the button's tiles
   into low BG tiles. Bad idea: BG0's whole tilemap is filled with tile 0, so
   writing there would have been visible. The stash lives in OBJ VRAM's tail
   (tile 1016), verified blank before use.
4. **The button must keep its own palette.** Giving it the frame sprite's
   palette slot (an early attempt at making the tones read consistently) turns
   the capsule yellow: the art paints its silhouette with index 13, which is the
   page-swap variant colour in the button's palette but a plain yellow in the
   frame's. Ink is index 1 = white in every page-swap palette, so there was
   nothing to fix.

An earlier self-inflicted symptom - the whole keyboard coming out washed out and
striped - was a consequence of (1): with the ink counter reading garbage, the
settle loop thrashed and the borrowed window was left mid-state.

## How it works now

Driven by a counter in the frame sprite's `data[4]`:

0. stash the button's eight tiles, hide the word strip, remember nothing else
1. render 切/换 into whichever keyboard window is currently **behind** the other
   one (never visible - the synthetic page must not be on screen), remember that
   window's tile base
2. wait until the printer's ink stops growing (it is a per-frame state machine)
3. verify both cells really hold glyphs (>= 20 ink px each, else abort and leave
   the stock UI alone); crop each glyph to its own ink box, scale it into the
   28x9 opening and draw it pixel by pixel - the capsule art underneath is left
   untouched, so the button is only ever re-lettered, never rebuilt; then hand
   both windows back to the current page

Anything unexpected aborts the label completely - never half-applied.

## Verified on the test host

| Check | Result |
| --- | --- |
| Which characters | `chars[4244]` = 切, `chars[1946]` = 换, found by sweeping all 224 pages x 32 cells in mGBA against reference bitmaps: **0/256 mismatch** for both |
| Where a window cell's tiles live | `charBlock*512 + baseBlock + 2*row*width + 1 + 2*col`; `injector/label_resolver.py` finds the two keyboard `WindowTemplate` records by a 16-byte signature occurring exactly once (`0x7174f4`) |
| Where the glyph tiles are | the text printer decompresses them into the window's tile data (ink = 1, second tone = 2, window fill = 13) - confirmed by dumping BG VRAM frame by frame (local scratch capture, not published) |
| On-screen result | right column shows 切换 in the orange capsule, no word strip, nothing else moved |
| Leaving Chinese mode | the strip and its word come back; the right column is pixel-identical to a no-label build |
| Page-swap key still works | lock `C000` -> `0000` -> `C000` on the PAGE cell |
| Behaviour gate | `qa/harness` log byte-for-byte identical to the archived one |
| Structure pre-check | 23/23 |
| Cursor | 38 / 54 / 70 / ... unchanged |

Residual whole-frame differences vs a no-label build are confined to the right
column plus the name-field caret / mon sprite, i.e. animating elements whose
phase shifts by the frame or two the label steps consume before input is handled
again. The keyboard, name text and every static element match exactly.

## Turning it off

```bash
python3 injector/inject_v10.py <rom> -o out.gba --toolchain gnu --workdir build --no-cn-label
```

Probes used: `qa_headless/{label_probe,label_dbg,glyph_probe,glyph_scan,asset_probe,asset_swap_probe,btn_probe,cells_probe}.c` — throwaway capture drivers, kept in the local scratch tree and not published (the rig they ran on is `qa/harness/`).
