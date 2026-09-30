#!/usr/bin/env python3
"""check_harness_delta.py -- the vendored rig's delta list must match the rig on disk.

qa/harness/cki-headless-qa-1.0/ ships a frozen 1.0 package's SHA256SUMS.txt, and REPO_DELTA.md
is the hand-written account of every way our copy differs from it.  Both rot the same way:
edit the rig, or add a script, and nothing complains.  That already happened once - the delta
file claimed "38 OK and exactly three differences" while two README edits had landed
unrecorded - which is why this check exists.

It re-measures the two facts the document asserts and compares them against the document:

  * `sha256sum -c SHA256SUMS.txt`  -> which files mismatch, which listed file is absent
  * `git ls-files`                 -> which tracked files the manifest never listed

and fails unless the union of those sets is exactly the set of paths named in REPO_DELTA.md's
table, with the same state (changed / absent / added / ours), and unless the counts quoted in
its code block are the counts measured now.

Usage:  python tools/check_harness_delta.py [--self-test]
"""
import os
import re
import subprocess
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RIG = os.path.join(ROOT, "qa", "harness", "cki-headless-qa-1.0")
import hashlib

OK_STATES = ("changed", "absent", "added", "ours")
BACKTICK = re.compile(r"`([^`]+)`")


def measure(rig=RIG):
    """Return (ok_count, mismatch, missing, unlisted, tracked_total) for the rig on disk."""
    sums = os.path.join(rig, "SHA256SUMS.txt")
    listed = {}
    for line in open(sums, encoding="utf-8"):
        if "  " in line:
            digest, name = line.rstrip("\n").split("  ", 1)
            listed[name] = digest
    mismatch, missing, ok = [], [], 0
    for name, digest in sorted(listed.items()):
        path = os.path.join(rig, *name.split("/"))
        if not os.path.isfile(path):
            missing.append(name)
            continue
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        if h.hexdigest() == digest:
            ok += 1
        else:
            mismatch.append(name)
    tracked = subprocess.run(["git", "ls-files", "."], cwd=rig, capture_output=True,
                             text=True).stdout.split()
    unlisted = sorted(p.replace("\\", "/") for p in tracked if p not in listed)
    return ok, sorted(mismatch), sorted(missing), unlisted, len(tracked)


def documented(path):
    """Parse REPO_DELTA.md's table into {relpath: state} plus the counts it quotes."""
    rows, quoted = {}, {}
    for line in open(path, encoding="utf-8"):
        line = line.rstrip("\n")
        if line.startswith("|") and line.count("|") >= 3:
            cells = [c.strip() for c in line.strip("|").split("|")]
            if len(cells) < 2 or cells[0] in ("file", "---"):
                continue
            state = next((s for s in OK_STATES if cells[1].startswith(s)), None)
            if state is None:
                continue
            for name in BACKTICK.findall(cells[0]):
                rows[name] = state
        m = re.search(r"(\d+) OK, (\d+) mismatches, (\d+) listed file", line)
        if m:
            quoted["ok"], quoted["mismatch"], quoted["missing"] = map(int, m.groups())
        m = re.search(r"(\d+) tracked files, (\d+) of them not in the manifest", line)
        if m:
            quoted["tracked"], quoted["unlisted"] = map(int, m.groups())
    return rows, quoted


def audit(rows, quoted, ok, mismatch, missing, unlisted, tracked):
    """Every way the document and the disk can disagree, as strings; empty means they agree."""
    fails = []
    measured = {n: "changed" for n in mismatch}
    measured.update({n: "absent" for n in missing})
    measured.update({n: rows.get(n, "added/ours") for n in unlisted})
    for name, state in sorted(measured.items()):
        if name not in rows:
            fails.append("%s: differs on disk (%s) but REPO_DELTA.md never names it" % (name, state))
    for name, state in sorted(rows.items()):
        if state == "changed" and name not in mismatch:
            fails.append("%s: table says changed, the manifest still matches it" % name)
        if state == "absent" and name not in missing:
            fails.append("%s: table says absent, the file is on disk" % name)
        if state in ("added", "ours") and name not in unlisted:
            fails.append("%s: table says %s, but the manifest lists it" % (name, state))
    for key, want in (("ok", ok), ("mismatch", len(mismatch)), ("missing", len(missing)),
                      ("tracked", tracked), ("unlisted", len(unlisted))):
        if quoted.get(key) != want:
            fails.append("quoted count %s = %s, measured %d" % (key, quoted.get(key), want))
    return fails


def selftest():
    """The audit must be able to go red for each drift it claims to catch."""
    #        table                        quoted counts                       mismatch  missing unlisted tracked want_red
    cases = [
        ("file edited but not in the table",
         {"scripts/known.txt": "added"}, {}, ["x/y.c"], [], ["x/y.c"], 1, True),
        ("table claims a change that never happened",
         {"x/y.c": "changed"}, {"ok": 1}, [], [], [], 1, True),
        ("table claims absent but the file is there",
         {"reference/g.raw": "absent"}, {"ok": 1}, [], [], [], 1, True),
        ("quoted counts drifted",
         {"x/y.c": "changed"}, {"ok": 40, "mismatch": 9, "missing": 1, "tracked": 5, "unlisted": 2},
         ["x/y.c"], [], [], 4, True),
        ("a table that matches reality",
         {"x/y.c": "changed", "s/new.txt": "added"},
         {"ok": 1, "mismatch": 1, "missing": 0, "tracked": 2, "unlisted": 1},
         ["x/y.c"], [], ["s/new.txt"], 2, False),
    ]
    bad = 0
    for label, rows, quoted, mismatch, missing, unlisted, tracked, want_red in cases:
        fails = audit(rows, quoted, 1, mismatch, missing, unlisted, tracked)
        if bool(fails) != want_red:
            bad += 1
            print("FAIL selftest %-42s expected %s, got %s%s"
                  % (label, "red" if want_red else "green",
                     "red" if fails else "green",
                     "" if not fails else " -> " + fails[0]))
    print("%s: selftest, %d drift case(s) + 1 agreement case" % ("OK" if not bad else "FAIL",
                                                                 len(cases) - 1))
    return 1 if bad else 0


def main(argv):
    if "--self-test" in argv:
        return selftest()
    ok, mismatch, missing, unlisted, tracked = measure()
    rows, quoted = documented(os.path.join(RIG, "REPO_DELTA.md"))
    fails = audit(rows, quoted, ok, mismatch, missing, unlisted, tracked)
    print("%d OK, %d mismatched, %d absent, %d unlisted of %d tracked"
          % (ok, len(mismatch), len(missing), len(unlisted), tracked))
    for f in fails:
        print("DRIFT  %s" % f)
    if fails:
        print("REPO_DELTA.md and the rig on disk disagree; fix the table (qa/harness/"
              "cki-headless-qa-1.0/REPO_DELTA.md), not this check.")
        return 1
    print("OK: REPO_DELTA.md names exactly the %d file(s) that differ from the frozen "
          "1.0 package." % (len(mismatch) + len(missing) + len(unlisted)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
