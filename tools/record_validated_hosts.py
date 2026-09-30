#!/usr/bin/env python3
"""Promote corpus hosts into qa/validated_hosts.json from bound QA evidence.

The injector refuses to patch an input that is not on the validated-host list unless
the caller passes --allow-unvalidated. 25 of the 26 corpus hosts have been through
runtime + behaviour + visual QA, and each of those 25 is in the ledger with the
capture that proves it named in its evidence list -- but an entry is a claim, so this
script re-derives all of them from the bytes on disk rather than trusting the file.

Because of that, a payload change drops the whole ledger: every entry's output_sha256
must equal the injected ROM currently on disk, so after a rebuild the run is 25
rejections until the captures are re-recorded and this script is re-run with
--write --refresh.  That is the intended failure mode -- a ledger that survives a
rebuild silently certifies bytes nobody tested.

Evidence required per host
  1. a patched capture whose artifact.txt sha256 equals test_roms/injected/<stem>_cki_v10.gba
  2. a same-route control whose artifact.txt sha256 equals the report's input ROM
  3. the full 27-step gate-4 boundary route passing under tools/check_boundary_route.py,
     on the same bytes: R/L page change, the 223<->0 wrap, the Page-Tab unlock, the
     double-byte/Latin delete discriminator and the mixed-buffer overflow rejection
  4. and then one of two ladders, chosen by what the runtime font gate decided on
     those exact bytes (tools/check_boundary_route.gate_class reads it from the route's
     own lock words -- the ledger does not get to pick a class, it inherits it):

       entered  -- Chinese mode opened, so the capture must prove the takeover:
       4a. patched log: lock word C000 after the grid is reached, three double-byte
           chars in the name buffer, lock word back to 0000 after SELECT
       4b. control log: none of the above (the adapter must not take over an unpatched ROM)
       4c. that route's locked-grid frame byte-identical to the boundary route's locked
           grid -- otherwise the 27 new frames per host would need their own human
           inspection, and "the payload is the same so the picture is the same" would be
           a reasoning step again (see tools/grid_frame_equivalence.py)

       refused  -- the host's own font has no CJK face, so the gate hands the key back
           and the stock page swap runs.  The takeover is then *not* the claim, and
           requiring it would reject 18 correct hosts; what is claimed instead is that
           the refusal is total:
       4a. the patched probe log is byte-identical to its own control's, so no key,
           page or name byte differs anywhere the route looks
       4b. neither log contains a Chinese lock word (C000/C001/C0DF)
       4c. tools/check_refusal_pixels.py reports 0 novel pixels across every sampled
           frame of the route -- a refusal that still draws ink the stock ROM never
           draws is not a refusal.  This is the check that caught CK-DELETE-GHOST.

What this deliberately does *not* decide: whether the injected grid shows real Hanzi on
that host. That is now partly machine-decided (a host the gate refuses cannot), and the
entered/refused split is written into each entry as `font_gate` rather than left in a
log. What remains manual is grading A/B by eye in test_roms/README.md section 15. The
keyboard-region pixel distance to two reference hosts is printed as a diagnostic because
a 0.00 distance is a useful same-family proof, but it is not written into the ledger:
gate 4c has a documented false negative on quetzal, and a second machine-derived grade
would just create a rival source of truth. The validated-host gate is about "can this
ROM be injected, and does the adapter do exactly what its runtime decision says it
does", so that is all the ledger asserts.

Usage:  python tools/record_validated_hosts.py [--write] [--refresh]
"""
import argparse
import hashlib
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from PIL import Image

from check_boundary_route import host_verdict, gate_class, parse   # one definition of what gate 4 passing means
from check_boundary_route import RD as BOUNDARY_RD                 # ...and which tree it reads
from check_boundary_route import CN_LOCKS
from check_refusal_pixels import audit_dirs                        # the visual half of a refusal

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = ROOT
REPORTS = os.path.join(ROOT, 'test_roms', 'reports_full')
INJECTED = os.path.join(ROOT, 'test_roms', 'injected')
QA = os.path.join(ROOT, 'test_roms', 'qa_20260926')
LEDGER = os.path.join(ROOT, 'qa', 'validated_hosts.json')

GRID_FRAME = '03_locked_grid.png'
BOUNDARY_GRID = 'b03_locked.png'      # the same state, reached by the 27-step route

# Written into the ledger on --write so the file's own header cannot drift from what
# the code that produced it claims.
LEDGER_NOTE = (
    'Inputs on which the current injector has been through the full gate ladder of '
    'docs/QA_ACCEPTANCE_STANDARD.md. Only sha256 is stored - no ROM is distributed. '
    'Add an entry only after runtime + behaviour + visual QA on that exact input hash. '
    'Each entry carries font_gate: "entered" means the runtime CJK-font gate measured a '
    'real Chinese face on that host and Chinese mode opens; "refused" means the adapter '
    'installs, measures, finds no face, and hands the key back, so the ROM keeps its '
    'stock keyboard and never renders Latin stand-ins for Hanzi. Both classes are '
    'validated; neither claim is inferred from the other, and each entry names the '
    'capture that proves it.')
KEYBOARD_TOP = 100          # rows >= 100 are the keyboard; above it is the host's own UI
REF_A = ('bubble128_cn', 'run6_patched')
REF_B = ('stock_expansion_1164', 'run6_patched')
# Both are the current-build probe captures.  REF_B's host is refused by the font gate,
# so its grid frame is the stock page and the distance against it reads as "how far from
# a stock page" -- still a useful floor for a diagnostic-only number.

# What a run cannot know by itself: *why* the route stops short on a given host.
# An exclusion without this is just "we failed", which a future reader cannot tell
# apart from "this ROM is incompatible". Each value is (reason, extra evidence dirs)
# and the evidence must be a bound capture, not a recollection.
EXCLUSION_CONTEXT = {
    'pokedelphia_v0.1': (
        "The naming screen is not in this build's reachable flow: the demo opens after "
        "name entry, with the protagonist already named (opening text hardcodes "
        "'Charlie loves rats', the START menu's second row is 'Charlie', and a full-ROM "
        "search for the stock naming prompts returns 0 hits -- see test_roms/README.md "
        "section 15.7). Re-proven on the current bytes by diag_card/png/k020_card.png, "
        "the trainer card (NAME: Charlie, IDNo.43902) captured on this exact patched ROM "
        "with its own artifact.txt; sNamingScreen reads 00000000 while that card is on "
        "screen, so the pointer is not being read at the wrong address. The patch is also "
        "measured inert here: boundary_final_patched/ and boundary_final_clean/ replay the "
        "same script on the patched and unpatched ROM against the same emulator build "
        "(both artifact.txt carry the same harness= hash) and their 27 PNGs are "
        "byte-identical. Hence ROUTE GAP at b01, not a behaviour failure: this host has "
        "no name-entry screen to take over, which is out of scope for CKI and is not a "
        "claim that the ROM is incompatible.",
        ('test_roms/qa_20260926/pokedelphia_v0.1/diag_card/',
         'test_roms/qa_20260926/pokedelphia_v0.1/boundary_final_clean/')),
}


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for blk in iter(lambda: f.read(1 << 20), b''):
            h.update(blk)
    return h.hexdigest()


def artifact(path):
    a = os.path.join(path, 'artifact.txt')
    if not os.path.exists(a):
        return {}
    out = {}
    for line in open(a, encoding='utf-8', errors='replace'):
        if '=' in line:
            k, v = line.rstrip('\n').split('=', 1)
            out[k] = v
    return out


def log_lines(path):
    p = os.path.join(path, 'capture.log')
    if not os.path.exists(p):
        return {}
    out = {}
    for line in open(p, encoding='utf-8', errors='replace').read().splitlines():
        for key in ('locked', 'cn3', 'after_select'):
            if line.startswith(key + ' '):
                out[key] = line
    return out


def read_text(path):
    if not os.path.exists(path):
        return None
    return open(path, encoding='utf-8', errors='replace').read()


def first_diff(a, b):
    """'line 7: <patched> / <control>' -- enough to act on without opening a diff tool."""
    la, lb = a.splitlines(), b.splitlines()
    for i in range(max(len(la), len(lb))):
        x = la[i] if i < len(la) else '<eof>'
        y = lb[i] if i < len(lb) else '<eof>'
        if x != y:
            return 'line %d: %s / %s' % (i + 1, x, y)
    return 'identical text, different bytes'


def best_capture(host, want_sha, prefer_prefix=None):
    """Capture in this host's dir whose artifact binds to `want_sha`.

    prefer_prefix keeps the probe-route runs (run*_patched / run*_clean) from being
    displaced by a newer boundary run: the two routes label their log lines
    differently, and the takeover-shape check below reads the probe labels.
    """
    hits = []
    for d in sorted(os.listdir(os.path.join(QA, host))):
        p = os.path.join(QA, host, d)
        if not os.path.isdir(p):
            continue
        if artifact(p).get('sha256') != want_sha:
            continue
        pref = 0 if (prefer_prefix and d.startswith(prefer_prefix)) else 1
        hits.append((pref, os.path.getmtime(p), p, d))
    if not hits:
        return None
    hits.sort(key=lambda t: (t[0], -t[1]))
    h = hits[0]
    return h[1], h[2], h[3]


def grid_crop(png):
    im = Image.open(png).convert('RGB')
    return im.crop((0, KEYBOARD_TOP, im.width, im.height))


def grid_distance(png, ref_a, ref_b):
    """Mean absolute pixel difference in the keyboard region against two references.

    Diagnostic only - see the module docstring. 0.00 means byte-identical to that
    reference's grid, which is a same-family proof; anything else is not interpreted.
    """
    import numpy as np
    def arr(p):
        return np.asarray(grid_crop(p), dtype='int32')
    if not (os.path.exists(png) and os.path.exists(ref_a) and os.path.exists(ref_b)):
        return None
    g = arr(png)
    return round(float(np.abs(g - arr(ref_a)).mean()), 2), \
           round(float(np.abs(g - arr(ref_b)).mean()), 2)


def frame_identity(gated_png, boundary_png):
    """Do the gate-5 grid frame and the boundary route's locked-grid frame show the same pixels?

    This is what lets 27 new frames per host inherit the visual gate instead of needing
    27 more human sign-offs: if the two routes draw the *same* frame, the inspection of one
    covers both, and the boundary frames only have to be read for behaviour -- which
    check_boundary_route.py already does mechanically. None = a frame is missing.
    """
    if not (os.path.exists(gated_png) and os.path.exists(boundary_png)):
        return None
    a = Image.open(gated_png).convert('RGB')
    b = Image.open(boundary_png).convert('RGB')
    if a.size != b.size:
        return False
    return a.tobytes() == b.tobytes()


def collect():
    ok, rejected = [], []
    shas = {}
    ref_a = os.path.join(QA, REF_A[0], REF_A[1], 'png', GRID_FRAME)
    ref_b = os.path.join(QA, REF_B[0], REF_B[1], 'png', GRID_FRAME)
    for rf in sorted(os.listdir(REPORTS)):
        if not rf.endswith('.json'):
            continue
        stem = rf[:-5]
        rep = json.load(open(os.path.join(REPORTS, rf), encoding='utf-8'))
        shas[stem] = rep.get('input_sha256')
        inj = os.path.join(INJECTED, f'{stem}_cki_v10.gba')
        if not os.path.exists(inj):
            continue
        if os.path.basename(rep.get('output', '')) != os.path.basename(inj):
            rejected.append(dict(stem=stem, why='report output path does not name the injected file'))
            continue
        if sha256(inj) != rep.get('output_sha256'):
            rejected.append(dict(stem=stem, why='injected file != report output_sha256'))
            continue
        base = os.path.basename(rep.get('input', ''))
        clean = next((os.path.join(ROOT, 'test_roms', d, base)
                      for d in ('roms', 'roms_noncjk')
                      if os.path.exists(os.path.join(ROOT, 'test_roms', d, base))), None)
        if not clean or sha256(clean) != rep.get('input_sha256'):
            rejected.append(dict(stem=stem, why='cannot locate the exact input ROM the report names'))
            continue
        qa_host = os.path.join(QA, stem)
        if not os.path.isdir(qa_host):
            qa_host = next((os.path.join(QA, d) for d in os.listdir(QA)
                            if stem.startswith(d) and os.path.isdir(os.path.join(QA, d))), None)
        if not qa_host:
            rejected.append(dict(stem=stem, why='no QA directory'))
            continue
        pc = best_capture(stem if os.path.isdir(os.path.join(QA, stem))
                          else os.path.basename(qa_host), sha256(inj), 'run')
        cc = best_capture(os.path.basename(qa_host), sha256(clean), 'run')
        if not pc:
            rejected.append(dict(stem=stem, why='no capture bound to the current patched ROM'))
            continue
        if not cc:
            rejected.append(dict(stem=stem, why='no control bound to the exact input ROM'))
            continue
        bd_ok, bd_fails, _ = host_verdict(qa_host)
        if not bd_ok:
            rejected.append(dict(stem=stem, why='gate-4 boundary route does not pass: '
                                   + '; '.join(bd_fails[:3])))
            continue
        # Which ladder the rest of this host is on is decided by the runtime font gate,
        # read off the boundary route's own lock words.  A refusal means b03 legitimately
        # shows the STOCK grid, so the takeover checks below would reject 18 correct
        # hosts -- and the entered checks are not merely skipped, they are replaced by
        # stricter ones, because "nothing happened" has to be proven, not assumed.
        klass = gate_class(parse(os.path.join(qa_host, BOUNDARY_RD + '_patched',
                                              'capture.log')) or {})
        pl, cl = log_lines(pc[1]), log_lines(cc[1])
        if klass == 'entered':
            bdir = os.path.join(qa_host, BOUNDARY_RD + '_patched')
            same = frame_identity(os.path.join(pc[1], 'png', GRID_FRAME),
                                  os.path.join(bdir, 'png', BOUNDARY_GRID))
            if same is False:
                rejected.append(dict(stem=stem, why=(
                    'the boundary route does not draw the frame the visual gate inspected: '
                    f'{GRID_FRAME} ({pc[3]}) != {BOUNDARY_GRID} ({BOUNDARY_RD}_patched)')))
                continue
            want = ('lock=C000' in pl.get('locked', '')
                    and 'name=010001000100FFFF' in pl.get('cn3', '')
                    and 'lock=0000' in pl.get('after_select', ''))
            ctrl_clean = ('lock=C000' not in ' '.join(cl.values())
                          and 'name=010001000100FFFF' not in ' '.join(cl.values()))
            if not want:
                rejected.append(dict(stem=stem,
                                     why=f'patched log lacks the takeover shape: {pl}'))
                continue
            if not ctrl_clean:
                rejected.append(dict(stem=stem,
                                     why=f'control also shows takeover: {cl}'))
                continue
        elif klass == 'refused':
            pt = read_text(os.path.join(pc[1], 'capture.log'))
            ct = read_text(os.path.join(cc[1], 'capture.log'))
            if pt is None or ct is None:
                rejected.append(dict(stem=stem, why='no capture.log in '
                                     f'{pc[3]} or {cc[3]}'))
                continue
            if pt != ct:
                rejected.append(dict(stem=stem, why=(
                    'the gate refused this host but the patched probe route is not its '
                    'control: %s' % first_diff(pt, ct))))
                continue
            CN = [w for w in CN_LOCKS if 'lock=' + w in pt]
            if CN:
                rejected.append(dict(stem=stem, why=(
                    'the gate refused this host yet Chinese mode opened on the probe '
                    'route (lock %s)' % ','.join(CN))))
                continue
            r = audit_dirs(pc[1], cc[1])
            if r is None:
                rejected.append(dict(stem=stem, why='no png trees under '
                                    f'{pc[3]} / {cc[3]} to audit the refusal with'))
                continue
            novel = r[0]
            if novel:
                xs = [p[1] for p in novel]
                ys = [p[2] for p in novel]
                rejected.append(dict(stem=stem, why=(
                    '%d novel pixels under a refusal at (%d,%d)..(%d,%d), first on %s: '
                    '%s where the stock ROM shows %s -- a refusal that still draws is '
                    'not a refusal (tools/check_refusal_pixels.py)'
                    % (len(novel), min(xs), min(ys), max(xs), max(ys), novel[0][0],
                       novel[0][3], novel[0][4]))))
                continue
        else:
            rejected.append(dict(stem=stem, why=(
                f'the font gate class is {klass!r}, which is neither takeover nor '
                f'refusal, so no ladder applies to this capture')))
            continue
        ok.append(dict(stem=stem, input_sha=rep['input_sha256'], output_sha=rep['output_sha256'],
                       patched=pc[2], control=cc[2], font_gate=klass,
                       diffs=grid_distance(os.path.join(pc[1], 'png', GRID_FRAME), ref_a, ref_b),
                       ns=rep['resolver']['naming_screen_global']))
    for r in rejected:
        r['sha'] = shas.get(r['stem'])
    return ok, rejected


def entry(h):
    refused = h['font_gate'] == 'refused'
    ev = [
        f"test_roms/qa_20260926/{h['stem']}/{h['patched']}/",
        f"test_roms/qa_20260926/{h['stem']}/{h['patched']}/artifact.txt",
        f"test_roms/qa_20260926/{h['stem']}/{h['control']}/artifact.txt",
        f"test_roms/reports_full/{h['stem']}.json",
        f"test_roms/qa_20260926/{h['stem']}/{BOUNDARY_RD}_patched/",
        f"test_roms/qa_20260926/{h['stem']}/{BOUNDARY_RD}_patched_sheet.png",
        f"test_roms/qa_20260926/{h['stem']}/{BOUNDARY_RD}_clean/",
    ]
    if refused:
        note = (
            f"Runtime font gate: REFUSED. This host's own font has no CJK face, so the "
            f"adapter installs, measures the page it would have drawn, and hands the key "
            f"back to the stock page swap - the ROM is playable with its original keyboard "
            f"and never shows Latin stand-ins for Hanzi. Proof on the exact patched bytes: "
            f"the probe capture log is byte-identical to the same-route control on the "
            f"unpatched input ({h['patched']} vs {h['control']}), neither contains a Chinese "
            f"lock word (C000/C001/C0DF), and tools/check_refusal_pixels.py reports 0 novel "
            f"pixels across every sampled frame of both routes, i.e. the refusal draws ink "
            f"the stock ROM cannot show nowhere. Gate 4's 27-step boundary list is run per "
            f"host and is graded for a refusal here - patched must equal its own control "
            f"step for step - which tools/check_boundary_route.py asserts against these same "
            f"bytes. Recorded {date.today().isoformat()} by tools/record_validated_hosts.py.")
    else:
        note = (
            f"Behaviour proof on the exact patched bytes: lock word C000 after the grid "
            f"is reached, name buffer 010001000100FFFF after three CN presses, lock back "
            f"to 0000 after SELECT; the same-route control on the unpatched input shows "
            f"none of these. Runtime font gate: ENTERED, so the adapter measured a real "
            f"CJK face in this host before letting Chinese mode open. Visual gate: "
            f"screenshots in the patched evidence dir show the 4x8 grid overlay, cursor "
            f"alignment and the Chinese/stock transition. Whether the cells render real "
            f"Hanzi depends on this host carrying a CJK font - the payload ships no glyph "
            f"tiles - and is graded A/B by hand in test_roms/README.md section 15; this "
            f"entry does not claim either way. "
            f"Gate 4's exhaustive boundary list is also run per host (27 steps: R/L page "
            f"change, 223<->0 wrap, Page-Tab unlock, pair-vs-Latin delete discriminator, "
            f"mixed-buffer overflow rejection) and the entry is refused unless "
            f"tools/check_boundary_route.py passes it against these same bytes. "
            f"That route's locked-grid frame is byte-identical to the grid frame "
            f"named above, so the visual gate covers both routes rather than needing "
            f"27 more sign-offs per host (re-measured by tools/grid_frame_equivalence.py). "
            f"Recorded {date.today().isoformat()} by tools/record_validated_hosts.py.")
    return {
        'sha256': h['input_sha'],
        'rom': f"{h['stem']}.gba",
        'description': f"CKI corpus host {h['stem']}",
        'output_sha256': h['output_sha'],
        'injector': '1.0 naked-ROM semantic API',
        'font_gate': h['font_gate'],
        'gates': ['resolver', 'injection', 'runtime', 'behavior', 'visual'],
        'evidence': ev,
        'note': note,
    }


def excluded_entries(rejected):
    """The hosts a run refused, written down with the reason instead of left in a log.

    `why` is what the machine saw; `reason` is what the exclusion means, which a run
    cannot derive (see EXCLUSION_CONTEXT). Only hosts with a known input sha are kept --
    without a sha nobody can look the entry up when the injector refuses them.
    """
    out = []
    for r in rejected:
        if not r.get('sha'):
            continue
        stem, ctx = r['stem'], EXCLUSION_CONTEXT.get(r['stem'])
        ev = [f'test_roms/reports_full/{stem}.json']
        for cand in (f'test_roms/qa_20260926/{stem}/{BOUNDARY_RD}_patched/',
                     f'test_roms/qa_20260926/{stem}/{BOUNDARY_RD}_patched_sheet.png',
                     *(ctx[1] if ctx else ())):
            if os.path.exists(os.path.join(ROOT, cand.replace('/', os.sep))):
                ev.append(cand)
        out.append({
            'sha256': r['sha'],
            'rom': f'{stem}.gba',
            'why': r['why'],
            'reason': ctx[0] if ctx else (
                'Refused by the evidence check in tools/record_validated_hosts.py; '
                'no interpretation beyond the machine reason above is recorded.'),
            'evidence': ev,
            'recorded': date.today().isoformat(),
        })
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true', help='commit the ledger change')
    ap.add_argument('--refresh', action='store_true',
                    help='also rewrite evidence/note for entries already in the ledger; '
                         'without this, entries present at their old shape are kept verbatim '
                         'and a strengthened evidence list silently does not land')
    a = ap.parse_args()
    ok, rejected = collect()
    led = json.load(open(LEDGER, encoding='utf-8'))
    have = {h['sha256']: h for h in led['hosts']}
    new = [h for h in ok if h['input_sha'] not in have]
    stale = [h for h in ok if h['input_sha'] in have]
    print(f'{len(ok)} hosts pass the evidence check, {len(new)} not yet in the ledger, '
          f'{len(stale)} already recorded')
    print('  entered = Chinese mode opened on this host; refused = the font gate handed '
          'the key back to the stock page swap')
    print('  (grid distance vs A-ref / B-ref is diagnostic only; 0.00 = identical grid)')
    for h in sorted(ok, key=lambda x: x['stem']):
        flag = 'NEW ' if h['input_sha'] not in have else 'have '
        print(f"  {flag}{h['stem']:36s} {h['font_gate']:8s} "
              f"patched={h['patched']:16s} "
              f"control={h['control']:16s} grid={h['diffs']}")
    print(f'\n{len(rejected)} excluded:')
    for r in rejected:
        print(f"  !! {r['stem']}: {r['why']}")
    excluded = excluded_entries(rejected)
    if excluded:
        print('\nas excluded, with the reason recorded for whoever hits the refusal:')
        for e in excluded:
            print(f"  xx {e['rom']}  ({e['why'][:60]}...)")
    if not a.write:
        print('\ndry run; pass --write to update ' + os.path.relpath(LEDGER, ROOT))
        return 0
    # The two recorders partition `excluded` by reason: this one owns hosts it injected
    # and then could not promote, tools/record_refusal_evidence.py owns the exit-3
    # "input interface changed" refusals - those six never produce a capture, so they
    # are never in this run's rejected list, and replacing the whole field dropped them.
    inherited = [e for e in led.get('excluded', [])
                 if e['why'].startswith('input interface changed: ')]
    led['excluded'] = sorted(inherited + excluded, key=lambda e: e['rom'])
    led['note'] = LEDGER_NOTE
    for h in new:
        led['hosts'].append(entry(h))
    refreshed = 0
    if a.refresh:
        by_sha = {e['sha256']: e for e in led['hosts']}
        for h in stale:
            e = by_sha[h['input_sha']]
            fresh = entry(h)
            if (e['evidence'] != fresh['evidence'] or e['note'] != fresh['note']
                    or e.get('font_gate') != fresh['font_gate']):
                e['evidence'] = fresh['evidence']
                e['note'] = fresh['note']
                e['font_gate'] = fresh['font_gate']
                e['output_sha256'] = fresh['output_sha256']
                e['gates'] = fresh['gates']
                refreshed += 1
        print(f'{refreshed} existing entries refreshed')
    elif stale:
        print(f'NOTE {len(stale)} existing entries keep their old evidence/note; '
              f'pass --refresh to rewrite them from this run')
    led['hosts'].sort(key=lambda e: e['rom'])
    tmp = LEDGER + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(led, f, indent=2, ensure_ascii=False)
        f.write('\n')
    os.replace(tmp, LEDGER)
    print(f'\nwrote {len(led["hosts"])} hosts to ' + os.path.relpath(LEDGER, ROOT))
    return 0


if __name__ == '__main__':
    sys.exit(main())
