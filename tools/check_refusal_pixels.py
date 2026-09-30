#!/usr/bin/env python3
"""check_refusal_pixels.py -- is a gate refusal visually silent?

  python tools/check_refusal_pixels.py [<host_dir> ...]
  CKI_BOUNDARY_RD=run6 python tools/check_refusal_pixels.py <host_dir> ...
  python tools/check_refusal_pixels.py --self-test   # the accounting, without any PNGs
  python tools/check_refusal_pixels.py --self-test   # the accounting, on synthetic frames

Reads <host_dir>/<CKI_BOUNDARY_RD>_patched/png and ..._clean/png (default
boundary_final) and applies one rule:

  Where the control holds one colour in every sampled frame, the patched run may
  only show a colour the control itself shows within +-CKI_NOVEL_RADIUS pixels of
  that spot in some sampled frame.  Anything else is NOVEL ink.

The radius is what separates this from a plain pixel diff, and it exists because
of a measured artefact, not taste.  The naming screen animates on its own: the
avatar and the arrow cursor bob, the PAGE tab pulses through a 10-step grey ramp
(measured 2026-09-27: the tab at (190,77) walks 57,82,107,...,255 two frames per
step on BOTH runs), and the first slot dash under "YOUR NAME?" creeps vertically
one pixel at a time over hundreds of frames.  The gate spends 12-40 frames
measuring before it decides, so the patched run is that many frames *ahead* of its
control on every one of those motions.  Measured the same day on the probe route:
14 of 18 refused hosts put the slot dash at y=63 where their control's 10 samples
only ever caught y=64 and y=65, which a radius-of-0 rule reads as ink the host
cannot draw.  It is not -- the same element in that control's own 27-frame boundary
run walks 65 -> 64 -> 65 -> 64 -> 62.  A slow animation sampled ten times does not
enumerate its own positions, so "is this pixel constant in the control" is the
wrong question and "could this host show this colour around here" is the right one.

That relaxation is calibrated against a real defect rather than chosen to make the
numbers green.  The archived pre-fix run (boundary_prefix, which carries
CK-DELETE-GHOST: a grey cell in a name slot the stock renderer leaves white) is
counted by the same code, totalled over the 18 refused hosts:

    radius   pre-fix (CK-DELETE-GHOST)   post-fix boundary_final   post-fix run6
       0                      615 px                         0 px         714 px
       1                      286 px                         0 px           0 px
       2                       84 px                         0 px           0 px
       3                        0 px                         0 px           0 px

The shipped default of 2 still fails every frame of the one defect this rule was
built to catch; radius 3 would have hidden it.  The cost is stated here rather
than buried in a constant: a patch that shifts existing ink by 2 px or less is
invisible to this rule. It is a phase/ink discriminator, not a pixel-exact diff --
for exactness there is tools/grid_frame_equivalence.py and the human visual gate.
The stricter alternative (re-run each control with the gate's frame count padded
in, which the payload could print) would remove the artefact instead of tolerating
it, and is not built.

Exit 0 = every refused host is visually silent.  Which hosts are refused is read from
`qa/validated_hosts.json`, not from the argument list: the tally used to be over
whatever the operator typed, so running this over the whole capture tree printed
"19/26 silent" and looked like a regression, when 7 of those 26 are the hosts the gate
*let through* (they are supposed to differ) and 1 is a host the injector never patched.
Entered hosts are still reported, just in their own line and never as a failure.

Read this together with tools/check_boundary_route.py, which proves the *behaviour*
half; a host can pass that and still fail here.
"""
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, 'qa', 'validated_hosts.json')
RD = os.environ.get('CKI_BOUNDARY_RD', 'boundary_final')
RADIUS = int(os.environ.get('CKI_NOVEL_RADIUS', '2'))


def classes():
    """{host stem: 'entered' | 'refused' | 'not-injected'} from the ledger."""
    try:
        with open(LEDGER, encoding='utf-8') as f:
            led = json.load(f)
    except (OSError, ValueError):
        return {}
    out = {h['rom'][:-4]: h.get('font_gate', 'refused') for h in led.get('hosts', [])}
    for h in led.get('excluded', []):
        out.setdefault(h['rom'][:-4], 'not-injected')
    for h in (led.get('out_of_scope', {}) or {}).get('hosts', []):
        out.setdefault(h['rom'][:-4], 'not-injected')
    return out


def pngs(d):
    return sorted(f for f in os.listdir(d) if f.endswith('.png'))


def constant_map(frames):
    """[y][x] = the colour every frame agrees on, or None where it varies."""
    w, h = frames[0].size
    px0 = frames[0].load()
    const = [[px0[x, y] for x in range(w)] for y in range(h)]
    for im in frames[1:]:
        px = im.load()
        for y in range(h):
            row = const[y]
            for x in range(w):
                if row[x] is not None and row[x] != px[x, y]:
                    row[x] = None
    return const


def audit(host_dir, rd=None, radius=None):
    """(novel, phase_px, diff_px, nframes), or None when the trees are not there."""
    rd = rd or RD
    return audit_dirs(os.path.join(host_dir, rd + '_patched'),
                      os.path.join(host_dir, rd + '_clean'), radius)


def audit_dirs(patched_dir, clean_dir, radius=None):
    """Same, for two capture dirs picked by hand (the ledger binds captures by sha,
    so it knows the directory names this tool would only guess from RD)."""
    from PIL import Image
    radius = RADIUS if radius is None else radius
    pp = os.path.join(patched_dir, 'png')
    pc = os.path.join(clean_dir, 'png')
    if not (os.path.isdir(pp) and os.path.isdir(pc)):
        return None
    names = pngs(pc)
    if not names:
        return None
    ctrl = [Image.open(os.path.join(pc, f)).convert('RGB') for f in names]
    cload = [im.load() for im in ctrl]
    const = constant_map(ctrl)
    w, h = ctrl[0].size
    novel, phase, moved = [], 0, 0
    for f in pngs(pp):
        if f not in names:
            continue
        pa = Image.open(os.path.join(pp, f)).convert('RGB').load()
        pb = cload[names.index(f)]
        for y in range(h):
            row = const[y]
            for x in range(w):
                if pa[x, y] == pb[x, y]:
                    continue
                moved += 1
                if row[x] is None:
                    continue                        # the control animates here
                c = pa[x, y]
                hit = False
                for im in (cload if radius else ()):
                    for yy in range(max(0, y - radius), min(h, y + radius + 1)):
                        for xx in range(max(0, x - radius), min(w, x + radius + 1)):
                            if im[xx, yy] == c:
                                hit = True
                                break
                        if hit:
                            break
                    if hit:
                        break
                if hit:
                    phase += 1
                else:
                    novel.append((f, x, y, c, row[x]))
    return novel, phase, moved, len(names)


def tally(dirs, cls, audits):
    """Print the per-host lines and return (rc, summary).

    Split out of main() so the accounting -- which hosts are in the denominator, and
    what an empty denominator means -- is testable without 26 x 27 PNGs.  The pixel
    rule itself is calibrated in the archived `CK-DELETE-GHOST` table above.
    """
    bad = skipped = refused = entered = notinj = uncls = inert = 0
    for d in dirs:
        host = os.path.basename(d)
        r = audits.get(host)
        kind = cls.get(host)
        if r is None:
            skipped += 1
            print('SKIP %-38s no %s png trees' % (host, RD))
            continue
        novel, phase, moved, n = r
        xs = [p[1] for p in novel]
        ys = [p[2] for p in novel]
        steps = sorted({p[0].split('_')[0] for p in novel})
        if kind == 'entered':
            entered += 1
            if not moved:
                inert += 1
                print('IDLE %-38s gate let this host into Chinese mode yet not one '
                      'pixel differs -- that is the shape of an inert patch' % host)
            else:
                print('OPEN %-38s %d px differ, %d novel (Chinese mode opened here; '
                      'not counted as a refusal)' % (host, moved, len(novel)))
            continue
        if kind == 'not-injected':
            notinj += 1
            print('NINJ %-38s the injector refused this host, so its frames prove '
                  'nothing about the font gate (%d px differ)' % (host, moved))
            continue
        if kind is None:
            uncls += 1
        refused += 1
        if novel:
            bad += 1
            print('FAIL %-38s %d novel px at (%d,%d)..(%d,%d) on %s '
                  '(e.g. %s vs %s); %d px self-animated, %d px phase'
                  % (host, len(novel), min(xs), min(ys), max(xs), max(ys),
                     ','.join(steps), novel[0][3], novel[0][4], moved - phase,
                     phase))
        else:
            print('PASS %-38s 0 novel px (%d px differ; %d where the control '
                  'animates, %d within %dpx of a colour it shows)'
                  % (host, moved, moved - phase, phase, RADIUS))
    print('\n%d/%d refused hosts are visually silent (%d skipped, %d not classified '
          'in the ledger)' % (refused - bad, refused, skipped, uncls))
    print('  reported but not in that denominator: %d entered (Chinese mode opened, '
          '%d of them show no pixel change at all), %d never injected'
          % (entered, inert, notinj))
    if not cls:
        print('  no ledger classes available (%s missing) -- the denominator above is '
              'whatever was typed on the command line, which is not a gate' % LEDGER)
        return 1, dict(refused=refused, bad=bad, entered=entered, notinj=notinj,
                       skipped=skipped, uncls=uncls, inert=inert)
    return (1 if bad or not refused else 0), dict(
        refused=refused, bad=bad, entered=entered, notinj=notinj, skipped=skipped,
        uncls=uncls, inert=inert)


NOVEL = [('03_locked_grid.png', 10, 10, (31, 31, 31), (0, 0, 0))]


def self_test():
    """Prove the denominator logic bites, without needing any frames.

    Each case is a whole-tree invocation reduced to the numbers that decide it.
    """
    cls = {'a_refused': 'refused', 'b_refused': 'refused', 'c_entered': 'entered',
           'd_never': 'not-injected'}
    clean = ( [], 5, 40, 27)
    dirty = (NOVEL, 5, 40, 27)
    cases = [
        ('refused host with novel ink fails',
         dict(cls), ['x/a_refused', 'x/b_refused'],
         {'a_refused': clean, 'b_refused': dirty}, 1),
        ('an entered host is never in the refusal denominator',
         dict(cls), ['x/c_entered'], {'c_entered': dirty}, 1),
        ('empty denominator is not a pass',
         dict(cls), ['x/c_entered', 'x/d_never'],
         {'c_entered': clean, 'd_never': clean}, 1),
        ('no ledger means no gate', {}, ['x/a_refused'], {'a_refused': clean}, 1),
        ('all refused hosts silent passes',
         dict(cls), ['x/a_refused', 'x/b_refused', 'x/c_entered'],
         {'a_refused': clean, 'b_refused': clean, 'c_entered': dirty}, 0),
    ]
    fails = 0
    import io
    from contextlib import redirect_stdout
    for name, c, dirs, audits, want in cases:
        buf = io.StringIO()
        with redirect_stdout(buf):
            rc, s = tally(dirs, c, audits)
        got = 'ok' if rc == want else 'rc=%d, wanted %d' % (rc, want)
        if rc != want:
            fails += 1
        print('%-46s %s' % (name, got))
    # the shape the old tally misread: the whole tree, classes known
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc, s = tally(['x/a_refused', 'x/b_refused', 'x/c_entered', 'x/d_never'],
                      cls, {'a_refused': clean, 'b_refused': clean,
                            'c_entered': dirty, 'd_never': dirty})
    shape = (s['refused'], s['entered'], s['notinj'], s['bad'])
    print('%-46s %s' % ('whole tree tallies 2 refused / 1 entered / 1 not injected',
                        'ok' if shape == (2, 1, 1, 0) and rc == 0 else shape))
    fails += shape != (2, 1, 1, 0) or rc != 0
    print('\n%s' % ('SELF-TEST OK' if not fails else 'SELF-TEST FAILED: %d case(s)' % fails))
    return 1 if fails else 0


def main(argv):
    if '--self-test' in argv:
        return self_test()
    dirs = [a.rstrip('/\\') for a in argv[1:] if not a.startswith('-')]
    if not dirs:
        print(__doc__)
        return 2
    audits = {os.path.basename(d.rstrip('/\\')): audit(d) for d in dirs}
    return tally(dirs, classes(), audits)[0]


if __name__ == '__main__':
    sys.exit(main(sys.argv))
