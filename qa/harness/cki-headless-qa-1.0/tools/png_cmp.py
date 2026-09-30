#!/usr/bin/env python3
"""png_cmp.py -- pixel-compare two captures (.raw and/or .png), and say where.

This is the tool that turns "looks about right" into a number. Typical use:
you re-run the reference probe and want to know whether the frames you just
produced are the reference frames, not merely similar ones.

If the two images have different dimensions, the overlapping top-left region is
compared and the script says so. That is the normal case when one side is a
256x256 .raw and the other is a 240x160 cropped PNG.

USAGE
    python3 tools/png_cmp.py a.png b.png
    python3 tools/png_cmp.py --tol 2 a.png b.png      # allow +/-2 per channel

EXIT
    0 identical (within tolerance)   1 different   2 usage/format error
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gbapng  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("a")
    ap.add_argument("b")
    ap.add_argument("--tol", type=int, default=0,
                    help="per-channel tolerance, default 0 (exact)")
    ap.add_argument("--report", metavar="PNG",
                    help="write a PNG marked with the differing pixels")
    args = ap.parse_args()

    wa, ha, ra = gbapng.load(args.a)
    wb, hb, rb = gbapng.load(args.b)
    w, h = min(wa, wb), min(ha, hb)
    if w <= 0 or h <= 0:
        sys.exit("png_cmp: no overlapping region between %s and %s" % (args.a, args.b))

    diff = 0
    worst = 0
    minx, miny, maxx, maxy = w, h, -1, -1
    mark = bytearray(ra[:w * h * 3]) if args.report else None

    for y in range(h):
        rowa = y * wa * 3
        rowb = y * wb * 3
        for x in range(w):
            i = rowa + x * 3
            j = rowb + x * 3
            d = 0
            for c in range(3):
                k = abs(ra[i + c] - rb[j + c])
                if k > d:
                    d = k
            if d > args.tol:
                diff += 1
                if d > worst:
                    worst = d
                if x < minx:
                    minx = x
                if y < miny:
                    miny = y
                if x > maxx:
                    maxx = x
                if y > maxy:
                    maxy = y
                if mark is not None:
                    m = (y * w + x) * 3
                    mark[m] = 0xFF
                    mark[m + 1] = 0
                    mark[m + 2] = 0xFF

    a, b = os.path.basename(args.a), os.path.basename(args.b)
    if wa != wb or ha != hb:
        print("note: %s is %dx%d, %s is %dx%d -- compared the %dx%d overlap"
              % (a, wa, ha, b, wb, hb, w, h))

    if diff == 0:
        print("SAME   %s == %s   (%dx%d compared, %d pixels, tol=%d)"
              % (a, b, w, h, w * h, args.tol))
        return 0

    print("DIFFER %s vs %s   %d/%d pixels (%.3f%%), worst channel delta %d"
          % (a, b, diff, w * h, 100.0 * diff / (w * h), worst))
    print("       first/last differing box: x %d..%d  y %d..%d"
          % (minx, maxx, miny, maxy))
    if args.report:
        gbapng.write_png(args.report, w, h, mark)
        print("       marked pixels written to %s" % args.report)
    return 1


if __name__ == "__main__":
    sys.exit(main())
