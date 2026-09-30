#!/usr/bin/env python3
"""raw2png.py -- turn a headless mGBA framebuffer dump (.raw) into a PNG.

No third-party packages; see tools/gbapng.py for the format notes and for how
to verify the pixel byte order rather than trusting it.

USAGE
    python3 tools/raw2png.py out/v10_1cn.raw
    python3 tools/raw2png.py --scale 2 --outdir out/png out/*.raw
    python3 tools/raw2png.py --probe 120,80 out/v10_1cn.raw
"""
import argparse
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import gbapng  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("inputs", nargs="+")
    ap.add_argument("-o", "--out", help="output PNG (single input only)")
    ap.add_argument("--outdir", help="output directory (default: next to input)")
    ap.add_argument("--scale", type=int, default=1,
                    help="integer nearest-neighbour upscale (default 1)")
    ap.add_argument("--full", action="store_true",
                    help="keep 256x256 instead of cropping to the 240x160 screen")
    ap.add_argument("--bits16", action="store_true",
                    help="last resort: raw was written with a 16-bit color_t")
    ap.add_argument("--probe", metavar="X,Y",
                    help="print the colour of one pixel and exit; writes no PNG")
    args = ap.parse_args()

    bits = 16 if args.bits16 else 32

    paths = []
    for p in args.inputs:
        hits = sorted(glob.glob(p))
        paths.extend(hits if hits else [p])

    if args.probe:
        px, py = (int(t) for t in args.probe.split(","))
        w, h, rgb = gbapng.read_raw(paths[0], bits)
        j = (py * w + px) * 3
        print("%s (%d,%d) -> R=%d G=%d B=%d  #%02X%02X%02X"
              % (os.path.basename(paths[0]), px, py,
                 rgb[j], rgb[j + 1], rgb[j + 2], rgb[j], rgb[j + 1], rgb[j + 2]))
        return

    if args.out and len(paths) != 1:
        sys.exit("raw2png: --out needs exactly one input")

    for p in paths:
        w, h, rgb = gbapng.read_raw(p, bits)
        w, h, px = gbapng.scale_nearest(rgb, w, h, max(1, args.scale), args.full)
        if args.out:
            out = args.out
        else:
            out = os.path.splitext(p)[0] + ".png"
            if args.outdir:
                out = os.path.join(args.outdir, os.path.basename(out))
        d = os.path.dirname(out)
        if d:
            os.makedirs(d, exist_ok=True)
        gbapng.write_png(out, w, h, px)
        print("%-40s -> %s  (%dx%d)" % (os.path.basename(p), out, w, h))


if __name__ == "__main__":
    main()
