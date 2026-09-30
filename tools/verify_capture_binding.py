#!/usr/bin/env python3
"""verify_capture_binding.py -- does every capture still run against today's bytes?

  python tools/verify_capture_binding.py [--prefix boundary]

Each capture directory carries artifact.txt written by the runner:

  rom=<path the emulator actually booted>
  sha256=<sha256 of that file at capture time>
  script=<the key script that was replayed>
  report=<the injection report the NS literal came from>
  harness=<sha256 of build/gba_capture that produced the frames>   (optional, see below)

This re-hashes the named ROM and compares. A mismatch means the screenshot was
taken against bytes that no longer exist, so it cannot certify the current build
no matter how good it looks -- which is exactly how 14 hosts were found to have
been silently accepted on stale frames.

The ROM is not the only input to a frame.  Re-binding one route-gap host on
2026-09-27 produced 13 of 27 frames that differed from the archived capture by a
flat ~1.48x brightness -- which reads exactly like the patch having started to
interfere with the host.  It had not: re-running the *unpatched* ROM on today's
harness reproduced today's frames, and re-running it on the archived harness
reproduced the archived ones.  That control is now in the tree as a same-build
pair (test_roms/qa_20260926/pokedelphia_v0.1/boundary_final_patched/ and
.../boundary_final_clean/, both carrying the same `harness=` value): 27 PNGs
byte-identical, both capture.log files line-identical.  The rig's own source had
been edited between the two rounds (see
qa/harness/cki-headless-qa-1.0/REPO_DELTA.md), and a frame is a function of
emulator + ROM, not of ROM alone.  So `harness=` is compared against the binary
that exists now, and a mismatch is reported.  Captures recorded before the field
existed are counted, not failed -- there are hundreds of them, and the point of
the field is that a new round cannot be silent about which rig ran it.

--prefix selects which run directories to audit (default: every *_patched /
*_clean pair that carries artifact.txt).
"""
import glob
import hashlib
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
QA = os.path.join(ROOT, 'test_roms', 'qa_20260926')
HARNESS_BIN = os.path.join(ROOT, 'qa', 'harness', 'cki-headless-qa-1.0',
                           'build', 'gba_capture')


def sha256(path):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


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


def main(argv):
    prefix = None
    if '--prefix' in argv:
        prefix = argv[argv.index('--prefix') + 1]
    harness_now = sha256(HARNESS_BIN) if os.path.isfile(HARNESS_BIN) else None
    hosts = sorted(os.path.basename(h) for h in glob.glob(os.path.join(QA, '*'))
                   if os.path.isdir(h))
    bad, checked, undated = [], 0, 0
    for host in hosts:
        hdir = os.path.join(QA, host)
        runs = sorted(d for d in glob.glob(os.path.join(hdir, '*'))
                      if os.path.isdir(d) and (prefix is None
                                               or d.split(os.sep)[-1].startswith(prefix)))
        for d in runs:
            a = read_art(d)
            if not a:
                continue
            checked += 1
            name = os.path.basename(d)
            problems = []
            rom = a.get('rom', '').replace('/mnt/d/', 'D:/').replace('/', os.sep)
            if not os.path.isfile(rom):
                problems.append('ROM it booted is gone: %s' % rom)
            elif sha256(rom) != a.get('sha256'):
                problems.append('bytes changed since capture')
            for key in ('script', 'report'):
                if a.get(key) and not os.path.isfile(
                        a[key].replace('/mnt/d/', 'D:/').replace('/', os.sep)):
                    problems.append('%s file missing' % key)
            if not os.path.isfile(os.path.join(d, 'capture.log')):
                problems.append('no capture.log')
            if a.get('harness'):
                if harness_now and a['harness'] != harness_now:
                    problems.append('harness differs since capture')
            elif harness_now:
                undated += 1
            if problems:
                bad.append((host, name, '; '.join(problems)))
    for host, name, why in bad:
        print('UNBOUND %-38s %-22s %s' % (host, name, why))
    if not checked:
        print('NO CAPTURES: no artifact.txt under %s' % QA)
        print('The capture tree is the local corpus workbench and is not published with '
              'the repository (see the repository-layout section of README.md). An empty '
              'audit is not a pass - exiting non-zero instead of reporting green.')
        return 2
    print('%d run dir(s) checked, %d unbound' % (checked, len(bad)))
    if harness_now is None:
        print('harness: build/gba_capture not built here, so no frame is checked against a rig')
    else:
        print('harness: %d capture(s) recorded it, %d predate the field'
              % (checked - undated, undated))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
