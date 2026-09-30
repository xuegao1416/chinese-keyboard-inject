#!/usr/bin/env python3
"""Make the README's before/after figure from captured emulator frames.

Maintainer tool: it reads the QA capture tree, which is not published with the
source. Run it from a corpus checkout after a capture round.

Each panel is a real 240x160 frame grabbed by the headless rig
(qa/harness/.../run_capture.sh) from the ROM named in the panel label: the left
one is the *unpatched* input, the others are the patched output of the same
route, so the comparison is same-host, same-script, same-step.

  python tools/make_readme_figure.py [--host pokeemerald-ch_modern_build]
"""
import argparse
import os
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QA = os.path.join(ROOT, 'test_roms', 'qa_20260926')
OUT = os.path.join(ROOT, 'docs', 'assets')

SCALE = 3          # 240x160 -> 720x480 per panel; nearest, never resampled smooth
LABEL_H = 78
GAP = 18

# (frame path relative to the host dir, zh label, en label)
# Frame 06_cn3 is the last grid press that the host accepted: its own name
# length limit rejects a 4th double-byte char, so the label says three.
PANELS = [
    ('{clean}/png/03_locked_grid.png',   '未注射：原版键盘',       'before: stock symbol page'),
    ('{patched}/png/03_locked_grid.png', '注射后：4x8 中文网格',   'after: injected 4x8 Chinese grid'),
    ('{patched}/png/06_cn3.png',         '3 个汉字已上屏（每字 2 字节）', 'after: three 2-byte Hanzi in the name field'),
]
ZOOM_PANELS = [
    ('{clean}/png/06_cn3.png',   '未注射：同样的按键，姓名栏仍为空', 'before: same key presses, nothing entered'),
    ('{patched}/png/06_cn3.png', '注射后：3 个双字节汉字',           'after: 3 Hanzi, 2 bytes each'),
]
NAME_BAR = (0, 26, 240, 70)     # the trainer-name field, below the "你的名字?" prompt


def font(size, bold=False):
    for cand in (r'C:\Windows\Fonts\msyhbd.ttc' if bold else r'C:\Windows\Fonts\msyh.ttc',
                 r'C:\Windows\Fonts\NotoSansSC-VF.ttf',
                 r'C:\Windows\Fonts\arialbd.ttf' if bold else r'C:\Windows\Fonts\arial.ttf'):
        try:
            return ImageFont.truetype(cand, size)
        except OSError:
            continue
    return ImageFont.load_default()


def panel(path, zh, en, scale=SCALE):
    im = Image.open(path).convert('RGB')
    if im.size != (240, 160):
        raise SystemExit('%s: expected a 240x160 GBA frame, got %s' % (path, im.size))
    im = im.resize((240 * scale, 160 * scale), Image.NEAREST)
    canvas = Image.new('RGB', (im.width, im.height + LABEL_H), (24, 24, 28))
    canvas.paste(im, (0, 0))
    d = ImageDraw.Draw(canvas)
    d.text((10, im.height + 8), zh, font=font(26, True), fill=(250, 250, 250))
    d.text((10, im.height + 44), en, font=font(20), fill=(170, 175, 185))
    d.rectangle([0, 0, canvas.width - 1, im.height - 1], outline=(70, 70, 78))
    return canvas


def strip(panels):
    w = sum(p.width for p in panels) + GAP * (len(panels) - 1)
    h = max(p.height for p in panels)
    out = Image.new('RGB', (w, h), (12, 12, 16))
    x = 0
    for p in panels:
        out.paste(p, (x, 0))
        x += p.width + GAP
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', default='pokeemerald-ch_modern_build')
    ap.add_argument('--clean', default='run2_clean')
    ap.add_argument('--patched', default='run2_patched')
    a = ap.parse_args()

    hd = os.path.join(QA, a.host)
    os.makedirs(OUT, exist_ok=True)

    def resolve(tpl):
        p = os.path.join(hd, tpl.format(clean=a.clean, patched=a.patched))
        if not os.path.isfile(p):
            raise SystemExit('missing capture frame: %s\n'
                             'this figure is generated from the QA corpus, which is not '
                             'published with the source.' % p)
        return p

    def caption(img, note):
        c = Image.new('RGB', (img.width, img.height + 34), (12, 12, 16))
        c.paste(img, (0, 0))
        ImageDraw.Draw(c).text((10, img.height + 9), note, font=font(18), fill=(150, 156, 168))
        return c

    big = strip([panel(resolve(t), zh, en) for t, zh, en in PANELS])
    big = caption(big, 'host: %s   |   same script, same key timing, only the patch differs' % a.host)
    big.save(os.path.join(OUT, 'injection_before_after.png'))
    print('%s  %dx%d' % (os.path.relpath(os.path.join(OUT, 'injection_before_after.png'), ROOT),
                         big.width, big.height))

    zoom = []
    for t, zh, en in ZOOM_PANELS:
        im = Image.open(resolve(t)).convert('RGB').crop(NAME_BAR)
        w, h = im.size
        im = im.resize((w * 4, h * 4), Image.NEAREST)
        c = Image.new('RGB', (im.width, im.height + 58), (24, 24, 28))
        c.paste(im, (0, 0))
        d = ImageDraw.Draw(c)
        d.text((10, im.height + 4), zh, font=font(24, True), fill=(250, 250, 250))
        d.text((10, im.height + 30), en, font=font(17), fill=(170, 175, 185))
        zoom.append(c)
    z = strip(zoom)
    z = caption(z, 'crop of the same frames above   |   host: %s' % a.host)
    z.save(os.path.join(OUT, 'name_field_before_after.png'))
    print('%s  %dx%d' % (os.path.relpath(os.path.join(OUT, 'name_field_before_after.png'), ROOT),
                         z.width, z.height))


if __name__ == '__main__':
    sys.exit(main())
