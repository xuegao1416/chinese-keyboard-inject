#!/usr/bin/env python3
"""check_boundary_route.py -- mechanical verdict for the gate-4 boundary route.

  python tools/check_boundary_route.py <host_dir> [<host_dir> ...]

Reads <host_dir>/<RD>_patched/capture.log and <RD>_clean/capture.log (RD defaults to
"boundary_final", the tree the current build is recorded into; the older pre-gate
"boundary_*" trees stay archived beside it - set CKI_BOUNDARY_RD to read one of those)
and asserts the numbers that payload/adapter_v10.c actually implies (see the header of
qa/harness/cki-headless-qa-1.0/scripts/cki_boundary_template.txt for where each one comes from).

Hosts split two ways now that the runtime font gate decides per host whether Chinese
mode opens: the ones that pass get the 27 rules below; the ones the gate refuses get a
different rule - patched must equal its own control step for step, because a refusal
that still changed what the keyboard *does* is not a refusal.  What it does NOT prove
is that the refusal changed nothing you can *see*: that is a separate audit, see
tools/check_refusal_pixels.py, which is the check that caught CK-DELETE-GHOST (a grey
cell left in a name slot after B-delete, on all 18 refused hosts) and which now reports
0 novel pixels for all 18 on both capture routes.

Why a checker and not eyes: the route is 27 steps x 26 hosts x 2 ROMs. A human can
read one log; nobody reads 1400 lines without sliding into "looks fine". Every rule
here is derived from the adapter source, so a rule that fails is either a host that
genuinely behaves differently or a bug -- both of which are the answer we want.
"""
import io
import os
import re
import sys

# step -> expected (lock, cell, name length in bytes); None = don't care
PATCH = {
    'b01': (None, None, None),
    'b02': (None, '08000000', None),   # walked onto the PAGE cell
    'b03': ('C000', '00000000', None),  # A there locks, cursor resets to (0,0)
    'b04': ('C001', None, None),        # R: page 0 -> 1
    'b05': ('C000', None, None),        # L: page 1 -> 0
    'b06': ('C0DF', None, None),        # L at 0 WRAPS to 223 (0xDF)
    'b07': ('C000', None, None),        # R at 223 WRAPS to 0
    'b08': (None, None, 2),             # CN char 1 (double byte)
    'b09': (None, None, 4),             # CN char 2 taken from page 1's grid
    'b10': (None, None, 6),             # CN char 3 fills the field
    'b11': ('C000', None, 6),           # CN char 4 REJECTED, buffer unchanged
    'b12': (None, None, 4),             # B erases a whole pair
    'b13': (None, None, 2),
    'b14': (None, None, 0),
    'b15': ('0000', '08000000', None),  # Page-Tab A unlocks
    'b16': ('C000', '00000000', None),  # and locks again -> repeatable toggle
    'b17': ('0000', None, None),        # SELECT is the other escape
    'b18': (None, None, 1),             # unlocked: stock write is ONE byte
    'b19': (None, None, 2),
    'b20': ('C000', '00000000', 2),     # re-locked with 2 Latin bytes in place
    'b21': (None, None, 4),             # mixed pair lands at 2..3
    'b22': (None, None, 6),             # mixed pair lands at 4..5 -> full
    'b23': ('C000', None, 6),           # third mixed CN char REJECTED at i=6
    'b24': (None, None, 4),             # B peels the two pairs...
    'b25': (None, None, 2),
    'b26': (None, None, 1),             # ...then single Latin bytes, one at a time
    'b27': ('C000', None, 0),
}

KV = re.compile(r'\b(ptr|cid|cell|lock|name)=([0-9A-Fa-f]*)')

# Which capture tree to read.  Re-recording under a fresh prefix keeps the
# published evidence intact until the new run is checked.
RD = os.environ.get('CKI_BOUNDARY_RD', 'boundary_final')

# Lock words only Chinese mode writes.  A refused host must never show one.
CN_LOCKS = ('C000', 'C001', 'C0DF')


def parse(path):
    steps = {}
    if not os.path.isfile(path):
        return None
    for line in io.open(path, encoding='utf-8', errors='replace'):
        line = line.strip()
        if not line:
            continue
        head = line.split(' ', 1)[0]
        if not re.match(r'^b\d\d$', head):
            continue
        steps[head] = dict(KV.findall(line))
    return steps or None


def gate_class(steps):
    """'entered' | 'refused' | 'route-gap' | 'no-capture' for one patched log.

    The runtime font gate decides per host whether Chinese mode opens at all, so
    the 27-step table below only describes half the corpus.  b03 is the frame
    after the first capsule press, which is where the two classes separate.
    """
    if not steps:
        return 'no-capture'
    if steps.get('b03', {}).get('lock', '').upper() == 'C000':
        return 'entered'
    ptr = steps.get('b01', {}).get('ptr') or ''
    try:
        if not 0x02000000 <= int(ptr, 16) < 0x02040000:
            return 'route-gap'
    except ValueError:
        return 'route-gap'
    return 'refused'


def nlen(name):
    """Buffer length in bytes up to the 0xFF terminator (EOS on these hosts)."""
    if not name:
        return -1
    b = bytes.fromhex(name)
    for i, v in enumerate(b):
        if v == 0xFF:
            return i
    return len(b)


def check_patched(steps, fails, notes, clean=None):
    if steps is None:
        fails.append('no patched capture.log')
        return
    if 'b01' not in steps:
        fails.append('route never reached the naming screen (no b01)')
        return
    # A naming screen that was never entered reads all-zero, and every number in
    # PATCH below is then meaningless. Call that out as a routing gap instead of
    # 27 behaviour failures -- same distinction the 10-frame sweep had to learn.
    # Liveness has to come from the struct pointer, not from the lock word: an
    # untouched naming screen reads 1111 on a pokeemerald host and 0000 on others,
    # and a *dead* pointer also reads 0000. Only ptr= separates the two.
    ptr = steps['b01'].get('ptr')
    if ptr is None:
        fails.append('b01 has no ptr= field: this capture predates the liveness probe, '
                     're-run it')
        return
    try:
        live = 0x02000000 <= int(ptr, 16) < 0x02040000
    except ValueError:
        live = False
    if not live:
        fails.append('ROUTE GAP: sNamingScreen is %s at b01, outside EWRAM - this host '
                     'needs its own nav route' % ptr)
        return
    if gate_class(steps) == 'refused':
        check_refused(steps, clean, fails, notes)
        return
    if steps['b01'].get('cid') != '00':
        notes.append('cursor sprite id is %s, so `cell=` below is the wrong sprite; '
                     'cell rules skipped' % steps['b01'].get('cid'))
        want = {k: (v[0], None, v[2]) for k, v in PATCH.items()}
    else:
        want = dict(PATCH)
    for step, (lk, cell, ln) in sorted(want.items()):
        got = steps.get(step)
        if got is None:
            fails.append('%s missing from the log' % step)
            continue
        if lk is not None and got.get('lock', '').upper() != lk:
            fails.append('%s lock=%s want %s' % (step, got.get('lock'), lk))
        if cell is not None and got.get('cell', '').upper() != cell:
            fails.append('%s cell=%s want %s' % (step, got.get('cell'), cell))
        if ln is not None:
            g = nlen(got.get('name', ''))
            if g != ln:
                fails.append('%s name has %d bytes, want %d (%s)'
                             % (step, g, ln, got.get('name')))
    # the page must drive the glyphs, not just the lock word
    n08, n09 = steps.get('b08', {}), steps.get('b09', {})
    if n08.get('name') and n09.get('name'):
        a, b = n08['name'][0:4], n09['name'][2:6]
        if a == b:
            notes.append('page 1 cell (0,0) gave the same glyph as page 0 (%s) - '
                         'R/L reachability proven, glyph-table switch not distinct' % a)


def check_refused(steps, clean, fails, notes):
    """The font gate decided this host has no CJK face, so the capsule press was
    handed to the stock page swap and Chinese mode never opened.  The 27 rules
    above are then the wrong table - they describe a mode this host is not in.
    What has to hold instead is that the refusal is *silent*: the patched run is
    indistinguishable from its own control step for step, and no step anywhere in
    the route carries a lock word the control does not."""
    base = (clean or {}).get('b01', {}).get('lock')
    if base is None:
        fails.append('gate refused but there is no control capture to compare with - '
                     'the silence is unproven')
        return
    taken = sorted(s for s, d in steps.items()
                   if d.get('lock') and (d['lock'].upper() in CN_LOCKS
                                         or d['lock'] != base))
    if taken:
        fails.append('gate refused at b03 yet %s carry lock %s (control base %s)'
                     % (','.join(taken),
                        [steps[s]['lock'] for s in taken], base))
    shared = sorted(set(steps) & set(clean))
    diff = [s for s in shared
            if {k: v for k, v in steps[s].items() if k != 'ptr'}
            != {k: v for k, v in clean[s].items() if k != 'ptr'}]
    if diff:
        fails.append('gate refused but patched differs from control on %d step(s): %s'
                     % (len(diff),
                        '; '.join('%s %s/%s vs %s/%s'
                                  % (s, steps[s].get('lock'), steps[s].get('name'),
                                     clean[s].get('lock'), clean[s].get('name'))
                                  for s in diff[:4])))
    notes.append('font gate refused this host: Chinese mode stays off, proved by '
                 'patched == control on all %d sampled steps (fields only - run '
                 'tools/check_refusal_pixels.py for the frames)' % len(shared))


def check_clean(steps, pf, want, fails, notes):
    if steps is None:
        fails.append('no clean control capture.log')
        return
    base = steps.get('b01', {}).get('lock')
    if base is None:
        fails.append('control has no b01')
        return
    moved = {s: d.get('lock') for s, d in steps.items()
             if d.get('lock') is not None and d['lock'] != base}
    if moved:
        fails.append('CONTROL ALSO SHOWS TAKEOVER: lock changed on %s (%s)'
                     % (','.join(sorted(moved)), sorted(set(moved.values()))))
    # a control that produced the patched buffer shape would be the real bug
    same = [s for s in want
            if s in steps and s in pf
            and nlen(steps[s].get('name', '')) == nlen(pf[s].get('name', ''))
            and nlen(steps[s].get('name', '')) >= 0
            and PATCH[s][2] is not None]
    if len(same) > 6:
        if not any(d.get('lock') not in (None, base) for d in pf.values()):
            # Nothing ever locked on either side, so both runs have the same shape by
            # construction: that is a host which never reaches name entry, not a control
            # that is secretly the patched ROM.  Which bytes each run booted is what
            # artifact.txt says (rom= / sha256= / harness=).
            notes.append('control name lengths match the patched run on %d steps and '
                         'neither run ever locked - expected when the host never reaches '
                         'the naming screen; the two artifact.txt files say which bytes '
                         'each run booted' % len(same))
        else:
            notes.append('control name lengths match the patched run on %d steps - '
                         'check the control really is unpatched' % len(same))


def host_verdict(host_dir):
    """(ok, fails, notes) for one host directory. Imported by record_validated_hosts.py
    so the ledger and this report cannot disagree about what passing means."""
    fails, notes = [], []
    pf = parse(os.path.join(host_dir, RD + '_patched', 'capture.log'))
    cl = parse(os.path.join(host_dir, RD + '_clean', 'capture.log'))
    check_patched(pf, fails, notes, cl)
    # A refused host has no Chinese mode to take over, so check_clean's
    # "did the control also change" rule would be comparing the wrong thing;
    # check_refused already demanded patched == control.
    if gate_class(pf) != 'refused':
        check_clean(cl, pf or {}, PATCH, fails, notes)
    return (not fails), fails, notes


def main(argv):
    dirs = [a for a in argv[1:] if not a.startswith('-')]
    if not dirs:
        print(__doc__)
        return 2
    bad = 0
    cls = {}
    for d in dirs:
        d = d.rstrip('/\\')
        ok, fails, notes = host_verdict(d)
        host = os.path.basename(d)
        cls[host] = gate_class(parse(os.path.join(
            d, RD + '_patched', 'capture.log')))
        if not ok:
            bad += 1
            print('FAIL %-38s %d rule(s)' % (host, len(fails)))
            for f in fails:
                print('      -', f)
        else:
            print('PASS %-38s %s' % (
                host, 'gate refused: patched == control, 27 steps'
                if cls[host] == 'refused' else '27/27 boundary steps'))
        for n in notes:
            print('  note', n)
    print('\n%d/%d hosts pass the full gate-4 boundary route' % (len(dirs) - bad, len(dirs)))
    for k in ('entered', 'refused', 'route-gap', 'no-capture'):
        n = sum(1 for v in cls.values() if v == k)
        if n:
            print('  %-11s %d' % (k + ':', n))
    return 1 if bad else 0


if __name__ == '__main__':
    sys.exit(main(sys.argv))
