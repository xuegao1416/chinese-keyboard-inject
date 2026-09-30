#!/usr/bin/env python3
"""Calibrate the runtime CJK-font gate from the captures we already have.

payload/adapter_v10.c decides "does this host actually draw Chinese glyphs" by
measuring the ink of one probe cell inside the keyboard window. That decision
needs a threshold, and a threshold invented in a text editor is a guess. This
script measures the same quantity the payload measures - per-cell ink and ink
bounding-box width - from the *screenshots* of every host that reached the
locked-grid step, so the cut is placed where the corpus actually separates.

The keyboard window is located per host from the patched-vs-clean frame diff
(the grid is the thing that changed), then tiled into 16x16 cells.

  python tools/calibrate_font_gate.py [--report]

What this table can and cannot show since the gate went in.  The entered rows are the
screenshot-side cross-check: on all 7 the median 16x16 cell measures 11 px wide against
CK_CN_MIN_W = 9.  That is a different ruler from the gate's own - the gate measures its
hidden page and reads 10 px there, so the accept-side margin on record is +1 px, not the
+2 px this box suggests.  The per-cell minimum column is NOT comparable to the threshold -
this tool tiles the patched-vs-control diff box, while the payload measures the window's
own 8x4 cell grid, so the border cells here are cut through.  The refused rows are not a
measurement of the same quantity at all, and reading them as one would be a mistake: a
refused host never draws the page on screen (the gate measures it in the hidden window and
puts the tiles back), so the screenshot can only show phase.
Measured 2026-09-27 on boundary_final, every refused host's grid frame does differ
from its own control - by 53 to 245 px - and check_refusal_pixels.py reports 0 of
those as ink the host cannot draw.  The diff box either still tiles 3 bogus cells of
the stock page (8 hosts, inkMed 220 = a whole 16x16 cell, i.e. the stock grid itself
caught 2 px later) or contains no tileable region at all (10 hosts, cells=0).
Both margins are now measured on the gate's own side: tools/read_gate_verdict.py walks
ns[0x1E24] -> gSprites[fid][0x3C] -> gSprites[bid] over a dump of the whole sprite array
- it peeks 4352 bytes and dereferences in Python, so no indirect peek had to be added to
the harness - and qa/font_gate_verdicts.json records 5 entered hosts at wn 10 / mt 6 and
17 refused at wn 6 / mt 0.  Where this table and that file disagree, that file is the one
measuring what the payload decides on.

Reads the local capture tree under test_roms/; not published with the repo.
"""
import argparse
import json
import os
import sys
from collections import OrderedDict

from PIL import Image
import numpy as np

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QA = os.path.join(ROOT, 'test_roms', 'qa_20260926')
LEDGER = os.path.join(ROOT, 'qa', 'validated_hosts.json')

# (patched frame, clean frame) candidates, tried in order.  boundary_final_* / run6_*
# are the current build; the older trees stay listed so a host that has not been
# re-recorded still measures.
PATCHED = ['boundary_final_patched/png/b03_locked.png',
           'run6_patched/png/03_locked_grid.png',
           'boundary_patched/png/b03_locked.png', 'run2_patched/png/03_locked_grid.png',
           'run1_patched/png/03_locked_grid.png', 'run_patched/png/03_locked_grid.png']
CLEAN = ['boundary_final_clean/png/b03_locked.png',
         'run6_clean/png/03_locked_grid.png',
         'boundary_clean/png/b03_locked.png', 'run2_clean/png/03_locked_grid.png',
         'run1_clean/png/03_locked_grid.png', 'run_clean/png/03_locked_grid.png']


def gray(p):
    return np.asarray(Image.open(p).convert('L'), dtype=int)


def grid_box(patched, clean):
    """Bounding box of the region the patch changed: that is the keyboard grid."""
    if clean is not None and patched.shape == clean.shape:
        d = np.abs(patched - clean) > 30
        d[:48] = False          # the name box / prompt also changes; keyboard is below
        rows = np.where(d.any(1))[0]
        cols = np.where(d.any(0))[0]
        if len(rows) and len(cols):
            return int(cols.min()), int(rows.min()), int(cols.max()) + 1, int(rows.max()) + 1
    return 16, 72, 240, 160     # fallback: lower-left area of a GBA frame


def cell_stats(img, box):
    x0, y0, x1, y1 = box
    inks, ws, hs = [], [], []
    for cy in range(y0, min(y1, img.shape[0]) - 15, 16):
        for cx in range(x0, min(x1, img.shape[1]) - 15, 16):
            blk = img[cy:cy + 16, cx:cx + 16]
            m = blk > 200                       # ink is palette index 1 = white
            n = int(m.sum())
            if n == 0:
                continue
            ys, xs = np.where(m)
            inks.append(n)
            ws.append(int(xs.max() - xs.min() + 1))
            hs.append(int(ys.max() - ys.min() + 1))
    if not inks:
        return None
    q = lambda v: (min(v), sorted(v)[len(v) // 2], max(v))
    return len(inks), q(inks), q(ws), q(hs)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--report', action='store_true', help='also write qa/font_gate_calibration.json')
    a = ap.parse_args()

    ledger = json.loads(open(LEDGER, encoding='utf-8').read())
    validated = {h['rom'] for h in ledger['hosts']}
    # What the payload decided at runtime on these same bytes, so the table can be
    # read as "did the screenshot agree with the gate".
    gates = {h['rom']: h.get('font_gate', '-') for h in ledger['hosts']}

    rows = []
    for stem in sorted(os.listdir(QA)):
        hd = os.path.join(QA, stem)
        if not os.path.isdir(hd):
            continue
        p = next((os.path.join(hd, c) for c in PATCHED if os.path.isfile(os.path.join(hd, c))), None)
        if not p:
            continue
        cp = next((os.path.join(hd, c) for c in CLEAN if os.path.isfile(os.path.join(hd, c))), None)
        pi = gray(p)
        ci = gray(cp) if cp and os.path.isfile(cp) else None
        st = cell_stats(pi, grid_box(pi, ci))
        if not st:
            # The diff box holds nothing tileable.  That is a row, not a dropped host:
            # dropping these 10 made the table read as "10 hosts missing" on exactly the
            # hosts where the screenshot has the least to say.  It is NOT the same as
            # "identical to control" -- check the frame counts in the module docstring.
            same = bool(ci is not None and (pi == ci).all())
            rows.append(dict(stem=stem, cells=0, ink_med=0, ink_min=0, ink_max=0,
                             boxw_med=0, boxw_min=0, boxw_max=0, boxh_med=0,
                             gate=gates.get(stem + '.gba', '-'), identical=same,
                             no_region=not same,
                             validated=stem + '.gba' in validated or stem in validated))
            continue
        n, (il, im, iH), (wl, wm, wH), (hl, hm, hH) = st
        rows.append(dict(stem=stem, cells=n, ink_med=im, ink_min=il, ink_max=iH,
                         boxw_med=wm, boxw_min=wl, boxw_max=wH, boxh_med=hm,
                         gate=gates.get(stem + '.gba', '-'), identical=False,
                         no_region=False,
                         validated=stem + '.gba' in validated or stem in validated))

    rows.sort(key=lambda r: (r['ink_med'], r['boxw_med']))
    print('%-38s %5s %7s %7s %7s  %-8s %s'
          % ('host', 'cells', 'inkMed', 'boxW', 'boxH', 'gate', 'ledger'))
    for r in rows:
        print('%-38s %5d %7d %7d %7d  %-8s %s'
              % (r['stem'][:38], r['cells'], r['ink_med'], r['boxw_med'], r['boxh_med'],
                 r['gate'], ('its own control, pixel for pixel'
                             if r['identical'] else
                             'diff has no keyboard region' if r['no_region'] else
                             'validated' if r['validated'] else '-')))
    print('\n%d host(s) measured' % len(rows))
    if a.report:
        out = os.path.join(ROOT, 'qa', 'font_gate_calibration.json')
        with open(out, 'w', encoding='utf-8') as f:
            json.dump(rows, f, indent=1, ensure_ascii=False)
        print('wrote %s' % os.path.relpath(out, ROOT))
    return 0


if __name__ == '__main__':
    sys.exit(main())
