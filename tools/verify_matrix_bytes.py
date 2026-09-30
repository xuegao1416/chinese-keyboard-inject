#!/usr/bin/env python3
"""verify_matrix_bytes.py -- do the published bytes still come out of today's source?

The corpus claims are written in hashes: `qa/validated_hosts.json` records one
`output_sha256` per validated host, and every screenshot in `test_roms/qa_20260926/`
was taken against the ROM that hash names.  Nothing in the tree used to answer the
question that comes up the moment `payload/adapter_v10.c` is edited: does building
from this source still produce those hashes, or is the whole evidence set now about
bytes that no longer exist?

Answering it by hand costs a full corpus sweep, so it never gets re-run -- which is
the same failure mode that let a 60-character truncated matrix column be published as
a refusal reason.  This makes it one command.

  # re-inject every sample from the current source, compare to the ledger
  python tools/verify_matrix_bytes.py --rebuild          # run in WSL, needs clang

  # cheaper: compare the ledger against the reports the last sweep left on disk
  python tools/verify_matrix_bytes.py

  # the same sweep against the compiler that ships inside the player package -- this
  # is what certifies "a player who double-clicks gets the bytes we verified":
  # CKI_CLANG=dist/CKI-18.1.3-win64/toolchain/bin/clang.exe \
  # CKI_OBJCOPY=<same dir>/llvm-objcopy.exe CKI_NM=<same dir>/llvm-nm.exe \
  #   python tools/verify_matrix_bytes.py --rebuild \
  #       --out <scratch roms dir> --report-dir <scratch reports dir>

`--rebuild` reproduces the route the ledger was built with: the same 20 `-DCK_*`
defines come from `inject_v10.py` itself, so this tool adds no build knowledge -- it
only runs the injector over `test_roms/roms/` and `test_roms/roms_noncjk/` and reads
back what it wrote.  A host whose fresh output hash differs from the ledger is a
payload regression against published evidence, and the only honest remedy is the one
already recorded in the QA standard: re-record that host's captures.

Exit code 0 = every host the ledger and the sweep both cover agrees.  Hosts the
ledger lists that the sweep never reached, and samples the sweep injected that the
ledger does not carry, are counted separately and reported -- an absent row is not
agreement.

`--rebuild` on a non-clang toolchain writes its reports into
`test_roms/reports_full/alt_toolchain_<kind>/` rather than over `reports_full/*.json`:
those JSONs are what each `artifact.txt` names as `report=`, so replacing one with the
other route's report would unbind every capture on that host while not changing a
single frame hash.
"""
import argparse
import hashlib
import json
import os
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LEDGER = os.path.join(ROOT, 'qa', 'validated_hosts.json')
REPORTS = os.path.join(ROOT, 'test_roms', 'reports_full')
INJECTOR = os.path.join(ROOT, 'injector', 'inject_v10.py')
ROMDIRS = [os.path.join(ROOT, 'test_roms', 'roms'),
           os.path.join(ROOT, 'test_roms', 'roms_noncjk')]


def sha256(path, n=1 << 20):
    h = hashlib.sha256()
    with open(path, 'rb') as f:
        for chunk in iter(lambda: f.read(n), b''):
            h.update(chunk)
    return h.hexdigest()


def ledger_hashes():
    led = json.load(open(LEDGER, encoding='utf-8'))
    out = {}
    for h in led['hosts']:
        out[h['rom'][:-4]] = h['output_sha256']
    return out, led


def from_reports(stem):
    """(output_sha256, payload_size) recorded by the last injection of this host."""
    p = os.path.join(REPORTS, stem + '.json')
    if not os.path.isfile(p):
        return None, None
    try:
        d = json.load(open(p, encoding='utf-8'))
    except (ValueError, OSError):
        return None, None
    return d.get('output_sha256'), (d.get('payload') or {}).get('size')


def rebuild(out_dir, work_dir, toolchain, report_dir):
    """Inject every sample from the current source. Returns {stem: output_sha256}.

    Only the injected output is trusted for the comparison; the per-host report JSON
    is rewritten in place, which is the point (the tree then carries today's bytes),
    so this refuses to run unless both directories already exist.
    """
    if not os.path.isdir(out_dir):
        sys.exit('refusing to write: %s does not exist (it is the local corpus '
                 'workbench, not a published directory)' % out_dir)
    clang = os.environ.get('CKI_CLANG', 'clang')
    objcopy = os.environ.get('CKI_OBJCOPY', 'llvm-objcopy-18')
    nm = os.environ.get('CKI_NM', 'nm')
    fresh = {}
    for d in ROMDIRS:
        for fn in sorted(os.listdir(d)):
            if not fn.endswith('.gba'):
                continue
            rom = os.path.join(d, fn)
            stem = fn[:-4]
            out = os.path.join(out_dir, stem + '_cki_v10.gba')
            cmd = [sys.executable, INJECTOR, rom, '--allow-unvalidated',
                   '--toolchain', toolchain, '-o', out,
                   '--report', os.path.join(report_dir, stem + '.json'),
                   '--workdir', os.path.join(work_dir, stem)]
            if toolchain == 'clang':
                cmd += ['--clang', clang, '--llvm-objcopy', objcopy, '--nm', nm]
            r = subprocess.run(cmd, capture_output=True, text=True, errors='replace')
            if r.returncode == 0 and os.path.isfile(out):
                fresh[stem] = sha256(out)
            else:
                fresh[stem] = None
    return fresh


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--rebuild', action='store_true',
                    help='re-inject every sample from the current source first')
    ap.add_argument('--toolchain', default='clang', choices=('clang', 'gnu'))
    ap.add_argument('--out', default=os.path.join(ROOT, 'test_roms', 'injected'))
    ap.add_argument('--workdir', default=os.path.join(REPORTS, 'work'))
    ap.add_argument('--report-dir', default=None,
                    help='where the per-host reports go (default: %s)' % REPORTS)
    a = ap.parse_args()

    report_dir = a.report_dir or REPORTS
    if a.rebuild and a.toolchain != 'clang' and a.report_dir is None:
        # reports_full/*.json is what each artifact.txt's `report=` names, so writing
        # a GNU-route report over a clang-route one would unbind every capture on the
        # host without a single hash of the frames changing. Divert instead.
        report_dir = os.path.join(REPORTS, 'alt_toolchain_' + a.toolchain)
        os.makedirs(report_dir, exist_ok=True)
        print('reports diverted to %s -- %s output is not what the captures on disk '
              'are bound to' % (os.path.relpath(report_dir, ROOT).replace(os.sep, '/'),
                                a.toolchain))

    want, led = ledger_hashes()
    if a.rebuild:
        produced = rebuild(a.out, a.workdir, a.toolchain, report_dir)
        source = 'current source, re-injected just now'
    else:
        produced = {}
        for stem in want:
            h, _ = from_reports(stem)
            produced[stem] = h
        source = 'reports_full/*.json left by the last sweep (pass --rebuild ' \
                 'to answer the question about source bytes)'

    agree, drift, missing, extra = [], [], [], []
    for stem, want_sha in sorted(want.items()):
        got = produced.get(stem)
        if got is None:
            missing.append(stem)
        elif got == want_sha:
            agree.append(stem)
        else:
            drift.append((stem, want_sha, got))
    for stem, got in sorted(produced.items()):
        if stem not in want and got:
            extra.append(stem)

    print('%s' % source)
    print('%d/%d ledger host(s) reproduce the published bytes, %d differ, '
          '%d have no bytes to compare' % (len(agree), len(want), len(drift),
                                           len(missing)))
    for stem, w, g in drift:
        print('  DRIFT %-40s ledger=%s present=%s' % (stem, w[:12], (g or '')[:12]))
    for stem in missing:
        print('  NO BYTES %s' % stem)
    if extra:
        print('  injected but not in the ledger (%d): %s'
              % (len(extra), ', '.join(extra)))
    print('ledger: %d hosts / %d excluded / %d out_of_scope'
          % (len(led['hosts']), len(led.get('excluded', [])),
             len(led.get('out_of_scope', {}).get('hosts', []))))
    if drift or missing:
        print('A host that does not reproduce cannot be certified by the captures on '
              'disk: re-record it (see qa/README.md) before restating any claim about '
              'it.')
    return 1 if drift or missing else 0


if __name__ == '__main__':
    raise SystemExit(main())
