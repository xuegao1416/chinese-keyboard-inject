#!/usr/bin/env python3
"""record_refusal_evidence.py -- make "rejected by design" mean something checkable.

The matrix reports 26 injectable / 6 rejected-by-design / 0 failures. Until now the
6 were carried by one sentence each in test_roms/reports_full/work/<stem>.log, a
sentence only `inject_v10` had ever read. That is the weakest kind of claim this
project has been burned by: a tool prints a reason, the reason is copied into a
table, and nobody re-measures it.

So this re-derives each refusal from the ROM bytes on disk today and checks three
things that must agree:

  1. resolve_modern() still raises InterfaceChanged with exactly the logged text
     (the log is a transcript of a measurement, not an assertion);
  2. a headless capture of that same host exists, and its artifact.txt binds it to
     the sha256 we just hashed -- so the frames were taken against these bytes;
  3. for the two hosts whose keyboard was photographed, the frames are there.

Condition 3 is deliberately weaker than the injectable side. bailan_pinyin and
maplefall_ch reach their naming screen by mashing A, so their replaced keyboard is
on camera. The four PVPdalao builds auto-name the player and hand back control in a
bedroom walled off by moving boxes, so the naming screen is a route gap for them --
see qa/README.md "What the refusals are evidenced by". Their evidence is items 1 and
2 (the route capture proves the host boots and is playable under the rig), and this
tool prints that distinction instead of hiding it.

  python tools/record_refusal_evidence.py            # dry run
  python tools/record_refusal_evidence.py --write    # update qa/validated_hosts.json

A fourth thing is repaired rather than checked: `out_of_scope` in the same ledger
carries the same six refusals as a decision record, and its rows were hand-copied from
a column that cuts at 60 characters, so they published four different keyboard-table
addresses as one truncated prefix.  See `sync_out_of_scope()`.
"""
import argparse
import datetime
import glob
import hashlib
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, 'injector'))
from resolve_modern import InterfaceChanged, resolve_modern  # noqa: E402

LEDGER = os.path.join(ROOT, 'qa', 'validated_hosts.json')
WORK = os.path.join(ROOT, 'test_roms', 'reports_full', 'work')
ROMDIRS = [os.path.join(ROOT, 'test_roms', 'roms'),
           os.path.join(ROOT, 'test_roms', 'roms_noncjk')]
QA = os.path.join(ROOT, 'test_roms', 'qa_20260926')

# Which capture proves what, per host. A host is not "photographed" just because a
# directory with that name exists -- the script it ran decides that.
PHOTO_SCRIPT = 'mash_a.txt'          # reaches the naming screen on the pinyin builds
ROUTE_SCRIPT = 'pv_ng2.txt'          # reaches playable control, not the naming screen

REASONS = {
    'PVPdalao_Pre2': 'Open-source Chinese PvP hack (author credit shown in-game). Its '
        'naming keyboard layout table stores the four symbol rows 14 bytes apart, so the '
        '4x8 Chinese page the adapter writes would be read back with the wrong row stride. '
        'The visible grid was not photographed: this build auto-names the player in its '
        'custom arrival scene and the bedroom exit is blocked by moving boxes, so the '
        'naming screen is a route gap, not a behaviour failure.',
    'PVPdalao_Pre3': 'Same keyboard table as PVPdalao_Pre2 at a different offset; the four '
        'symbol rows sit on a 14-byte stride. Not photographed for the same route reason.',
    'PVPdalao_V1.0': 'Same 14-byte stride as the other PVPdalao builds. Not photographed for '
        'the same route reason.',
    'PVPdalao_V1.1': 'Same 14-byte stride; verified byte-for-byte here: rows at 0x6d2fcc are '
        'a1a2a3a4a5 / a6a7a8a9aa / abacb5b6baae / b0b1b2b3b4 each zero-padded to 14, with '
        'non-keyboard data from +56. Not photographed for the same route reason.',
    'bailan_pinyin': 'BaiLan pinyin-IME build: the naming screen shows a QWERTY pinyin '
        'keyboard with its own 拼音 / ABC / 删除文字 / 确认 keys, which is on camera here. '
        'The stock 4x8 grid this adapter overlays does not exist in that UI.',
    'maplefall_ch': 'Same replaced pinyin keyboard as bailan_pinyin, green theme, photographed '
        'here: 拼音 / abc / 1/? / 删除文字 / 完毕 over a QWERTY grid.',
}


def rel(p):
    return os.path.relpath(p, ROOT).replace(os.sep, '/')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def find_rom(stem):
    for d in ROMDIRS:
        p = os.path.join(d, stem + '.gba')
        if os.path.isfile(p):
            return p
    return None


def read_art(d):
    p = os.path.join(d, 'artifact.txt')
    if not os.path.isfile(p):
        return None
    kv = {}
    for line in open(p, encoding='utf-8', errors='replace'):
        if '=' in line:
            k, v = line.rstrip('\n').split('=', 1)
            kv[k] = v
    return kv


def collect():
    """(accepted, problems, notes) where accepted is a list of ledger-ready dicts."""
    ok, bad, notes = [], [], []
    matrix_rows = {}
    mp = os.path.join(ROOT, 'test_roms', 'reports_full', 'matrix.tsv')
    with open(mp, encoding='utf-8', errors='replace') as f:
        head = f.readline().rstrip('\n').split('\t')
        for line in f:
            c = line.rstrip('\n').split('\t')
            if len(c) >= len(head):
                matrix_rows[c[0]] = (c[head.index('exit')], c[head.index('verdict')])
    for lp in sorted(glob.glob(os.path.join(WORK, '*.log'))):
        stem = os.path.basename(lp)[:-4]
        # Only the verdict line is comparable.  --write appends this tool's own
        # explanation below it, so reading the whole file made every host look
        # "stale" the second time this ran -- a self-inflicted mismatch between
        # what the tool writes and what it then trusts.
        logged = next((l for l in open(lp, encoding='utf-8', errors='replace')
                       if l.startswith('input interface changed: ')), '').rstrip()
        if not logged:
            continue
        rom = find_rom(stem)
        if rom is None:
            bad.append((stem, 'no ROM on disk to re-measure'))
            continue
        digest = sha256(rom)
        try:
            resolve_modern(open(rom, 'rb').read())
            bad.append((stem, 'resolve_modern returned -- this host is no longer refused'))
            continue
        except InterfaceChanged as e:
            now = 'input interface changed: ' + str(e)
        except (RuntimeError, ValueError) as e:
            bad.append((stem, f'now raises {type(e).__name__}, not InterfaceChanged: {e}'))
            continue
        # The work/<stem>.log is a transcript of some earlier run against bytes we
        # cannot hash-check (matrix.tsv records no input sha), so it can only
        # corroborate the *class* of verdict. bailan_pinyin and maplefall_ch were
        # logged before the resolver learned to say "and neither stock letter page
        # is present at stride 8 either", and that older wording is still on disk.
        # The measured text is what goes into the ledger.
        if now != logged:
            notes.append((stem, 'logged wording is stale\n'
                                f'    logged:   {logged}\n    measured: {now}'))
        row = matrix_rows.get(stem)
        if row is None:
            bad.append((stem, 'no row in test_roms/reports_full/matrix.tsv'))
            continue
        exit_code, verdict = row
        if exit_code != '3' or not verdict.startswith('REJECTED-BY-DESIGN input interface changed'):
            bad.append((stem, 'matrix.tsv does not record an interface-changed refusal '
                        f'(exit={exit_code}, verdict={verdict[:60]!r})'))
            continue

        cdir = os.path.join(QA, stem, 'refusal')
        art = read_art(cdir) if os.path.isdir(cdir) else None
        if art is None:
            bad.append((stem, 'no bound capture: ' + rel(cdir)
                        + '/artifact.txt is missing'))
            continue
        if art.get('sha256') != digest:
            bad.append((stem, 'capture bound to different bytes: artifact says '
                        + art.get('sha256', '')[:12] + ', ROM is ' + digest[:12]))
            continue
        pngs = glob.glob(os.path.join(cdir, 'png', '*.png'))
        if not pngs:
            bad.append((stem, 'bound capture has no frames'))
            continue
        script = os.path.basename(art.get('script', ''))
        photographed = script == PHOTO_SCRIPT
        evidence = [rel(lp),
                    'test_roms/reports_full/matrix.tsv',
                    rel(rom),
                    rel(cdir) + '/']
        if photographed:
            evidence.append(rel(cdir) + '/png/')
        ok.append({
            'sha256': digest,
            'rom': os.path.basename(rom),
            'why': now,
            'reason': REASONS.get(stem, ''),
            'evidence': evidence,
            'photographed': photographed,
            'shots': len(pngs),
            'recorded': datetime.date.today().isoformat(),
        })
    return ok, bad, notes


def sync_out_of_scope(led):
    """Re-point the `out_of_scope` rows at the measured refusal wording.

    `out_of_scope` is a decision record, but each row also carries a `class`: the
    machine's reason this host has no stock grid to overlay.  Those six strings were
    hand-copied out of a matrix column that cuts at 60 characters, which published
    the same `... (layout at 0x6d2` for four PVPdalao builds whose keyboard tables are
    at 0x6d2c7c / 0x6d2c6c / 0x6d2c7c / 0x6d2fcc, and cut both pinyin builds off
    mid-sentence.  The untruncated text is re-measured from the ROM bytes on every run
    of this tool and lands in `excluded[].why`, so the rows are repaired from the
    ledger itself rather than re-typed.  A row whose sha has no `excluded` entry is
    returned as missing: that is a decision pointing at a refusal nobody measures,
    which is the thing that rotted here in the first place.
    """
    measured = {h['sha256']: h['why'] for h in led['excluded']
                if h['why'].startswith('input interface changed: ')}
    fixed, missing = [], []
    for row in led.get('out_of_scope', {}).get('hosts', []):
        why = measured.get(row['sha256'])
        if why is None:
            missing.append(row['rom'])
        elif row.get('class') != why:
            row['class'] = why
            fixed.append(row['rom'])
    return fixed, missing


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--write', action='store_true', help='commit the ledger change')
    a = ap.parse_args()
    ok, bad, notes = collect()
    print(f'{len(ok)} refusal(s) re-measured from bytes and bound to a capture, '
          f'{len(bad)} problem(s)')
    for e in sorted(ok, key=lambda x: x['rom']):
        kind = 'naming screen on camera' if e['photographed'] else 'route capture only'
        print(f"  {e['rom']:24s} {e['sha256'][:12]}  shots={e['shots']:3d}  {kind}")
    for stem, why in bad:
        print(f'  !! {stem}: {why}')
    for stem, why in notes:
        print(f'  NOTE {stem}: {why}')

    led = json.load(open(LEDGER, encoding='utf-8'))
    keep = [h for h in led['excluded']
            if not h['why'].startswith('input interface changed: ')]
    for e in ok:
        e.pop('photographed'), e.pop('shots')
    # Sorted as a whole, not keep-first: this tool and record_validated_hosts.py each
    # write half of the list, and appending only one half sorted made the same seven
    # entries shuffle between runs -- 60 "changed" leaves in a positional diff for a
    # rewrite that changed six strings.
    led['excluded'] = sorted(keep + ok, key=lambda x: x['rom'])
    fixed, missing = sync_out_of_scope(led)
    if fixed:
        print('  out_of_scope rows re-synced to the measured wording: '
              + ', '.join(sorted(fixed)))
    if missing:
        bad += [(r, 'listed in out_of_scope but no interface-changed row in '
                    'excluded[] carries its measured wording') for r in missing]
        print('  !! out_of_scope rows with nothing to re-measure against: '
              + ', '.join(sorted(missing)))
    if not a.write:
        if fixed or missing:
            print('\nout_of_scope would change: %d re-synced, %d unmeasurable'
                  % (len(fixed), len(missing)))
        print('dry run; pass --write to update ' + os.path.relpath(LEDGER, ROOT))
        return 0 if not bad else 1
    with open(LEDGER, 'w', encoding='utf-8') as f:
        json.dump(led, f, indent=1, ensure_ascii=False)
        f.write('\n')
    print(f'\nwrote {len(led["excluded"])} excluded entries '
          f'({len(ok)} interface-changed, {len(keep)} other)')
    return 0 if not bad else 1


if __name__ == '__main__':
    raise SystemExit(main())
