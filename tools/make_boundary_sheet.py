#!/usr/bin/env python3
"""make_boundary_sheet.py -- one inspectable contact sheet per gate-4 boundary run.

  python make_boundary_sheet.py <host_dir> [host_dir ...]

Gate 5 is a *human* gate: 27 steps of memory numbers prove the state machine, but
"no tilemap corruption / cursor-to-glyph alignment / Chinese-vs-stock transition"
is only answered by looking. Laying the frames out in one image with the step label
under each is what makes that reviewable in a single screenful instead of 27 files.

Writes <host_dir>/<RD>_<kind>_sheet.png for both kinds when both exist, RD being
CKI_BOUNDARY_RD (boundary_final for the 27-step route, run6 for the probe route).
"""
import os
import sys

from PIL import Image, ImageDraw

STEP_W, STEP_H = 240, 160
SCALE = 2
LABEL_H = 16
COLS = 5


def frames(kind_dir):
    d = os.path.join(kind_dir, 'png')
    if not os.path.isdir(d):
        return []
    return sorted(f for f in os.listdir(d) if f.endswith('.png'))


def sheet(host, kind, rd='boundary'):
    kdir = os.path.join(host, rd + '_' + kind)
    names = frames(kdir)
    if not names:
        return None
    cell_w, cell_h = STEP_W * SCALE, STEP_H * SCALE + LABEL_H
    rows = (len(names) + COLS - 1) // COLS
    img = Image.new('RGB', (COLS * cell_w, rows * cell_h), (24, 24, 28))
    dr = ImageDraw.Draw(img)
    for i, n in enumerate(names):
        f = os.path.join(kdir, 'png', n)
        im = Image.open(f).convert('RGB').crop((0, 0, STEP_W, STEP_H))
        x, y = (i % COLS) * cell_w, (i // COLS) * cell_h
        img.paste(im.resize((cell_w, STEP_H * SCALE), Image.NEAREST), (x, y))
        dr.text((x + 3, y + STEP_H * SCALE + 3), n[:-4], fill=(220, 220, 220))
    out = os.path.join(host, '%s_%s_sheet.png' % (rd, kind))
    img.save(out)
    return out


def main(argv):
    hosts = [a.rstrip('/\\') for a in argv[1:]]
    if not hosts:
        print(__doc__)
        return 2
    rd = os.environ.get('CKI_BOUNDARY_RD', 'boundary_final')
    n = 0
    for h in hosts:
        for kind in ('patched', 'clean'):
            p = sheet(h, kind, rd)
            if p:
                n += 1
                print('%-40s %s' % (os.path.basename(h), os.path.basename(p)))
    print('%d sheet(s)' % n)
    return 0 if n else 1


if __name__ == '__main__':
    sys.exit(main(sys.argv))
