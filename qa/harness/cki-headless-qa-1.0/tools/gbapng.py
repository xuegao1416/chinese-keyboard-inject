#!/usr/bin/env python3
"""gbapng.py -- shared reader/writer for the headless capture formats.

Stdlib only, on purpose: these tools have to run on a bare Ubuntu box with no
pip, and every extra moving part is one more place for the pixel byte order to
be silently wrong.

THE .raw FORMAT
    Written by src/gba_capture.c and src/qa_boundary_v10.c as
        fwrite(fb, sizeof(color_t), 65536, f)
    => exactly 65536 pixels of 32-bit native mGBA colour, little-endian uint32,
    laid out 0x00BBGGRR -- RED IS THE LOW BYTE:

        R = v & 0xFF      G = (v >> 8) & 0xFF      B = (v >> 16) & 0xFF

    The GBA screen is the top-left 240x160 of that 256x256 buffer.
    Verify it, do not assume it: `raw2png.py --probe X,Y file.raw` prints the
    decoded colour of one pixel, and you can compare that against a screen you
    know.
"""
import struct
import sys
import zlib

W = H = 256
VIS_W, VIS_H = 240, 160
RAW32 = W * H * 4          # 262144
RAW16 = W * H * 2          # 131072 -- the -DCOLOR_16_BIT accident


def to_rgb(data, bits=32):
    """Raw pixel bytes -> tightly packed RGB bytes (256x256)."""
    n = W * H
    out = bytearray(n * 3)
    if bits == 32:
        for i, c in enumerate(struct.unpack("<%dI" % n, data)):
            j = i * 3
            out[j] = c & 0xFF
            out[j + 1] = (c >> 8) & 0xFF
            out[j + 2] = (c >> 16) & 0xFF
    else:
        for i, c in enumerate(struct.unpack("<%dH" % n, data)):
            j = i * 3
            out[j] = (c & 0x1F) << 3
            out[j + 1] = ((c >> 5) & 0x1F) << 3
            out[j + 2] = ((c >> 10) & 0x1F) << 3
    return out


def read_raw(path, bits=32):
    data = open(path, "rb").read()
    want = RAW32 if bits == 32 else RAW16
    if len(data) != want:
        sys.exit(
            "gbapng: %s is %d bytes, expected %d for a %d-bit color_t.\n"
            "  A 131072-byte file means the harness was built with"
            " -DCOLOR_16_BIT.\n"
            "  See PITFALLS.md #1 -- rebuild without that macro; do not"
            " convert this file." % (path, len(data), want, bits))
    return W, H, to_rgb(data, bits)


def read_png(path):
    """8-bit RGB/RGBA, non-interlaced -> (w, h, rgb bytes)."""
    data = open(path, "rb").read()
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        sys.exit("gbapng: %s is not a PNG" % path)
    pos, idat = 8, b""
    w = h = bd = ct = inter = None
    while pos + 12 <= len(data):
        ln = struct.unpack(">I", data[pos:pos + 4])[0]
        tag = data[pos + 4:pos + 8]
        body = data[pos + 8:pos + 8 + ln]
        pos += 12 + ln
        if tag == b"IHDR":
            w, h, bd, ct, _comp, _filt, inter = struct.unpack(">IIBBBBB", body)
        elif tag == b"IDAT":
            idat += body
        elif tag == b"IEND":
            break
    if bd != 8 or ct not in (2, 6) or inter != 0:
        sys.exit("gbapng: %s: only 8-bit RGB/RGBA, non-interlaced" % path)

    bpp = 3 if ct == 2 else 4
    stride = w * bpp
    raw = zlib.decompress(idat)
    out = bytearray()
    prev = bytearray(stride)
    p = 0
    for _y in range(h):
        f = raw[p]
        p += 1
        line = bytearray(raw[p:p + stride])
        p += stride
        if f == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 0xFF
        elif f == 2:
            for i in range(stride):
                line[i] = (line[i] + prev[i]) & 0xFF
        elif f == 3:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                line[i] = (line[i] + ((a + prev[i]) >> 1)) & 0xFF
        elif f == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b = prev[i]
                c = prev[i - bpp] if i >= bpp else 0
                pp = a + b - c
                pa, pb, pc = abs(pp - a), abs(pp - b), abs(pp - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[i] = (line[i] + pr) & 0xFF
        elif f != 0:
            sys.exit("gbapng: %s: bad PNG filter %d" % (path, f))
        out += line
        prev = line

    if bpp == 3:
        return w, h, bytes(out)
    rgb = bytearray(w * h * 3)
    for i in range(w * h):
        rgb[i * 3:i * 3 + 3] = out[i * 4:i * 4 + 3]
    return w, h, bytes(rgb)


def write_png(path, w, h, rgb):
    raw = bytearray()
    stride = w * 3
    for y in range(h):
        raw.append(0)                       # filter type 0 (None)
        raw += rgb[y * stride:(y + 1) * stride]

    def chunk(tag, data):
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    open(path, "wb").write(png)


def load(path, crop_raw_to_screen=False):
    """Either format, dispatched on extension.

    `crop_raw_to_screen` trims a .raw to the 240x160 visible screen: the rest
    of the 256x256 buffer is the emulator's scratch area and shows up as black
    padding in a montage. Off by default so nothing is silently discarded.
    """
    low = path.lower()
    if low.endswith(".raw"):
        w, h, rgb = read_raw(path)
        if crop_raw_to_screen:
            return crop(rgb, w, h, VIS_W, VIS_H)
        return w, h, rgb
    if low.endswith(".png"):
        return read_png(path)
    sys.exit("gbapng: don't know how to read %s" % path)


def crop(rgb, w, h, cw, ch):
    """Top-left cw x ch region."""
    cw = min(cw, w)
    ch = min(ch, h)
    out = bytearray(cw * ch * 3)
    for y in range(ch):
        out[y * cw * 3:(y + 1) * cw * 3] = rgb[y * w * 3:y * w * 3 + cw * 3]
    return cw, ch, out


def scale_nearest(rgb, w, h, k, full=False):
    """Integer nearest-neighbour upscale; `full` keeps 256x256 instead of the
    240x160 visible area."""
    cw, ch = (W, H) if full else (VIS_W, VIS_H)
    ow, oh = cw * k, ch * k
    out = bytearray(ow * oh * 3)
    for y in range(oh):
        srow = (y // k) * w * 3
        drow = y * ow * 3
        for x in range(ow):
            s = srow + (x // k) * 3
            d = drow + x * 3
            out[d:d + 3] = rgb[s:s + 3]
    return ow, oh, out
