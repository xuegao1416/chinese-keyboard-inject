#!/usr/bin/env python3
"""Is the boundary route's grid the same picture the visual gate already inspected?

Round 14 added 704 screenshots (26 hosts x 27 steps, patched). Nobody sat down and read
all of them, and "the payload is identical apart from resolved addresses" is a reasoning
step, not a measurement -- the same kind of step that failed the audit in Round 13.

So measure the one thing that makes the new frames inherit the old inspection: for every
host, compare the boundary route's locked-grid frame against the frame named in that
host's `qa/validated_hosts.json` evidence entry (the one gate 5 was signed off on). If
the pixels are the same, the visual gate covers both routes and the 27 new frames per
host only need to be read for *behaviour*, which check_boundary_route.py already does.

Prints the keyboard region (rows >= 100, the same crop record_validated_hosts.py uses),
and the whole frame, as mean absolute difference / differing pixel count. No threshold is
applied and nothing is rounded into passing: a host that differs says how much.

Usage:  python tools/grid_frame_equivalence.py [--host STEM]
"""
import argparse
import json
import os
import sys

from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from record_validated_hosts import KEYBOARD_TOP, LEDGER, QA, ROOT   # one source of the crop


def load(path):
    return Image.open(path).convert('RGB')


def diff(a, b, top=0):
    """(mean abs diff, differing pixels, max abs diff) over rows >= top."""
    if a.size != b.size:
        return None
    pa, pb = a.load(), b.load()
    total = differ = worst = 0
    n = 0
    for y in range(top, a.height):
        for x in range(a.width):
            r1, g1, b1 = pa[x, y]
            r2, g2, b2 = pb[x, y]
            d = abs(r1 - r2) + abs(g1 - g2) + abs(b1 - b2)
            total += d
            worst = max(worst, d)
            differ += d > 0
            n += 3
    return round(total / n, 4), differ, worst


def ledger_frames():
    """{stem: (gated frame path, evidence dir)} from the entries the ledger actually names."""
    led = json.load(open(LEDGER, encoding='utf-8'))
    out = {}
    for h in led['hosts']:
        stem = h['rom'][:-4]
        ev = [e for e in h['evidence'] if e.endswith('/') and 'boundary' not in e]
        if not ev:
            continue
        p = os.path.join(ROOT, ev[0].replace('/', os.sep), 'png', '03_locked_grid.png')
        if os.path.exists(p):
            out[stem] = p
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', help='only this stem')
    a = ap.parse_args()

    gated = ledger_frames()
    if not os.path.isdir(QA):
        print('NO CAPTURES: %s is the local corpus workbench and is not published with '
              'the repository. An empty comparison is not a pass, so this exits non-zero '
              'instead of reporting green.' % QA)
        return 2
    rows, missing = [], []
    for stem in sorted(os.listdir(QA)):
        if a.host and stem != a.host:
            continue
        bframe = os.path.join(QA, stem, 'boundary_patched', 'png', 'b03_locked.png')
        if not os.path.isdir(os.path.join(QA, stem, 'boundary_patched')):
            continue
        if not (os.path.exists(bframe) and stem in gated):
            missing.append(stem)
            continue
        x, y = load(gated[stem]), load(bframe)
        kb = diff(x, y, KEYBOARD_TOP)
        full = diff(x, y)
        rows.append((stem, kb, full))

    print(f"{'host':38s} {'keyboard mean/max':>22s} {'diff px':>9s}   {'whole-frame mean':>16s}")
    for stem, kb, full in rows:
        kbs = 'size mismatch' if kb is None else f"{kb[0]:>10} / {kb[2]:<8d}"
        print(f'{stem:38s} {kbs:>22s} {(kb[1] if kb else -1):>9d}   '
              f'{("n/a" if full is None else full[0]):>16}')

    if not rows:
        print('NO HOSTS compared: the capture tree under test_roms/ is the local corpus '
              'workbench and is not published with the repository. An empty comparison is '
              'not a pass, so this exits non-zero instead of reporting green.')
        return 2
    kb_ok = [r for r in rows if r[1] and r[1][0] == 0.0]
    print(f'\n{len(rows)} host(s) compared, {len(kb_ok)} with a byte-identical keyboard region')
    if missing:
        print(f'{len(missing)} skipped (no gated frame in the ledger, or no b03): {missing}')
    worst = [r for r in rows if r[1] and r[1][0] != 0.0]
    if worst:
        print('not identical:')
        for stem, kb, full in worst:
            print(f'  {stem:38s} keyboard mean={kb[0]} differing_px={kb[1]} max={kb[2]}')
    return 0


if __name__ == '__main__':
    sys.exit(main())
