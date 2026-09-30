#!/usr/bin/env python3
"""montage.py -- tile several captures into one contact sheet, for eyeballing.

Accepts .raw framebuffer dumps and .png files, in any mix. Stdlib only.

Reading order is fixed and deterministic: row-major, left to right, top to
bottom, in the order given on the command line. The sheet carries no text
labels -- drawing glyphs would mean bundling a font into a dependency-free
tool -- so the console prints the legend for you.

USAGE
    python3 tools/montage.py -o out/sheet.png --cols 4 --scale 2 out/*.raw
    python3 tools/montage.py -o out/sheet.png reference/v10_*.png
"""
import argparse
import glob
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gbapng  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("-o", "--out", required=True)
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--scale", type=int, default=1)
    ap.add_argument("--gap", type=int, default=4)
    ap.add_argument("--bg", default="202020", help="gap colour, RRGGBB")
    ap.add_argument("--full", action="store_true",
                    help="keep .raw tiles at the full 256x256 instead of "
                         "cropping them to the 240x160 screen")
    args = ap.parse_args()

    paths = []
    for p in args.inputs:
        hits = sorted(glob.glob(p))
        paths.extend(hits if hits else [p])
    if not paths:
        sys.exit("montage: no inputs matched")

    tiles = [gbapng.load(p, crop_raw_to_screen=not args.full) for p in paths]
    k = max(1, args.scale)
    cw = max(t[0] for t in tiles) * k
    ch = max(t[1] for t in tiles) * k
    cols = max(1, args.cols)
    rows = int(math.ceil(len(tiles) / float(cols)))
    g = args.gap
    W = cols * cw + (cols + 1) * g
    H = rows * ch + (rows + 1) * g
    canvas = bytearray(bytes.fromhex(args.bg) * (W * H))

    for i, (tw, th, rgb) in enumerate(tiles):
        r, c = divmod(i, cols)
        ox = g + c * (cw + g) + (cw - tw * k) // 2
        oy = g + r * (ch + g) + (ch - th * k) // 2
        for y in range(th * k):
            srow = (y // k) * tw * 3
            drow = (oy + y) * W * 3
            for x in range(tw * k):
                s = srow + (x // k) * 3
                d = drow + (ox + x) * 3
                canvas[d:d + 3] = rgb[s:s + 3]
        print("  [%d] row %d col %d  %s" % (i, r, c, os.path.basename(paths[i])))

    gbapng.write_png(args.out, W, H, canvas)
    print("montage -> %s  (%dx%d, %d tiles, %d cols)"
          % (args.out, W, H, len(tiles), cols))


if __name__ == "__main__":
    main()
