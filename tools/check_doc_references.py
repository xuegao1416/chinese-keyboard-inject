#!/usr/bin/env python3
"""check_doc_references.py -- every path, line number and section cited in the docs must exist.

Why this exists: this repository's rule is that a written claim is a checked claim, and
the docs cite three kinds of thing that rot silently - file paths, `file.c:1234` line
numbers, and `§6` section numbers.  A line-number citation survived four rounds of
payload edits and then broke in one comment-only change (the SELECT / PAGE-tab fix sites
moved by one line when the gate comments above them grew), which is exactly the failure
this script catches.

What it checks
  * `path/to/file.ext` inside backticks: must land somewhere.  Every one that does is
    counted by where it lands - `published` (a reader on a clean clone can open it),
    `local` (it only exists under test_roms/, i.e. it is the name of where
    a result came from: allowed, and counted, because the ratio is the publication
    boundary), or `external` (listed in EXTERNAL below with the reason it is not here).
    Anything that lands nowhere fails.
  * `file.c:1234`: same, plus the line number must be within the file AND the token in
    ANCHORS must still be on that line.  Every payload line citation has to be listed in
    ANCHORS, so a new one fails until someone pins what it is supposed to point at.
    A line number in a source this repo does not ship cannot be checked by anyone, so
    EXTERNAL does not excuse it: the citation has to be de-pinned to symbol names
    instead.  (docs/CHANGELOG.md used to carry `src/naming_screen.c:1444` from an
    upstream 1.9.4 read; two of its four numbers had already drifted out of reach of
    any copy in the tree.)
  * A bare `:1234` is rejected outright: it names no file, so no anchor can pin it.
    Docs that mean a line have to write the whole path.
  * `§N` (a section citation): the file it points into is the nearest `.md` named earlier
    in the same sentence, or the citing doc if none is named - and the number must be a
    heading that file really has (`## 6. ...`, `### 4.2 ...`, or `## 十五、`, since the
    evidence tree numbers its sections in 汉字).  This one was added the day it found
    three: a `见 §6 末尾` pointing at a backlog entry that never existed, a `§5.3` into a
    section with no subsections, and a `门禁 #6` whose number belonged to the evidence
    tree's own ladder rather than the published doc it was cited from.  A § into a file
    nobody ships is not excused either (same doctrine as line numbers): write the heading
    name instead, or the whole path if the file is in the evidence tree.
  * The doc set itself is derived (every published `.md`), not remembered, so a new doc
    cannot slip in unscanned; NOT_SCANNED below is the only way out and each prefix has to
    pay for itself with a reason.  An exclusion that excludes nothing fails.

Usage:  python tools/check_doc_references.py [--self-test]
--self-test exercises the rules on synthetic citations plus one deliberately broken entry in
each table, so the checker itself is testable; exit 0 with everything green, 1 on any failure.
"""
import argparse
import os
import posixpath
import re
import sys

if hasattr(sys.stdout, "reconfigure"):      # docs cite Chinese file names
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Which published markdown we do NOT police, by path prefix, with the reason.  The list is
# deliberately tiny and every entry has to be paid for: everything else in the tree is
# scanned without anyone remembering to add it, so a new doc cannot slip through uncounted.
NOT_SCANNED = {
    "qa/harness/": "vendored headless-harness drop: upstream's files, so a citation fix inside them "
                   "is allowed but must be booked in REPO_DELTA.md and is caught by "
                   "tools/check_harness_delta.py (two of these eight were edited on 2026-09-27 to "
                   "pass this very audit).  Not hiding anything: with this table emptied all 19 "
                   "docs - including these 8 - still report 0 bad references (measured 2026-09-27)",
}

# Cited, deliberately not in the tree.  An empty `why` is not allowed: if a reference is
# here, somebody has to say what it points at.
EXTERNAL = {
    "src/naming_screen.c": "upstream pokeemerald source - quoted as the host's own definition",
    "README_v39.md": "readme shipped with the 1.0 delivery package, not a file of this repo",
    # MATRIX.md documents one matrix run.  The ROMs below were the user's own samples for
    # it; the binaries were never published here, the run's raw data is (qa/matrix_v10.json).
    "Emerald-Gauntlet_v1.0.gba": "matrix sample, binary not shipped; row lives in qa/matrix_v10.json",
    "LightPlatinum_v062.gba": "matrix sample, binary not shipped; row lives in qa/matrix_v10.json",
    "v048_known_good.gba": "matrix sample, binary not shipped; row lives in qa/matrix_v10.json",
    # Named in MATRIX.md only to say which sample it is NOT - the 1.2 original is a
    # pre-decomp binary patch and was never run through the injector.
    "白金光1.2修复版.gba": "cited as out-of-scope and never measured; no binary, no row",
    "origin_lp12_fixed.gba": "same sample under its ascii name: out-of-scope, never measured",
    # Sample ROMs this repo builds itself.  `*.gba` is gitignored repo-wide, so no built
    # input is ever in a public checkout - only the report rows that name it are.
    "pokeemerald-ch_modern_build.gba": "locally built sample ROM; the .map it was checked against is upstream's",
    "pokeemerald-rogue_release_build.gba": "locally built sample ROM; see docs/MATRIX.md for the project it came from",
    # Files a *run* produces.  Published code writes each of them; none of them is
    # published, because they describe one machine's one run.
    "capture.log": "the harness behaviour log for one capture (qa/harness/.../run_capture.sh)",
    "RESULTS.md": "per-round working log under test_roms/qa_20260926/",
    # Asset names inside the *host's* own graphics tree, cited the way docs/naming_screen.c
    # is cited: as the host's identifier.  docs/LABEL.md measures against them.
    "page_swap_button.png": "the host's own PAGE-button tile (graphics/naming_screen/ in the fork)",
    "chinese_small.png": "the host's own small-font sheet (graphics/fonts/ in the fork)",
}

# file.c:NNN citations and the token that line must still contain.  Names are checked
# rather than whole statements so a reformat does not fail the gate.
ANCHORS = {}  # Current docs cite symbols; old line anchors belonged to the 1.0 payload.

SPAN = re.compile(r"`([^`\n]+)`")
FILE_CITATION = re.compile(r"^[\w./-]+\.(py|c|h|md|json|txt|png|log|sh|tsv|gba|ld|yaml)$")
LINE_CITATION = re.compile(r"^([\w./-]+\.c):(\d+)$")
BARE_LINE = re.compile(r"^:\d+$")     # ":1130" names no file - nothing to check

# The third citation type that rots: `§6`.  A path tells you *which* file, a line number
# tells you *where*, and a section number is a claim that some file has a heading with
# that number - which is exactly what nothing was checking until this round found three
# broken ones by hand (a "见 §6 末尾" pointing at a backlog entry that never existed, and
# two "门禁 #6"/"§6" labels that crossed files and landed on the wrong item).
SEC_CITATION = re.compile(r"§\s*(\d+(?:\.\d+)*)")
HEAD = re.compile(r"^#{2,4}\s+(\d+(?:\.\d+)*|[一二三四五六七八九十]+)(?:[、.．\s]|$)")
CLAUSE_END = re.compile(r"[。！？；]|\n\n")
MD_PATH = re.compile(r"([\w./-]+\.md)")


def cn_num(s):
    """十五 -> 15.  Only needed for test_roms/README.md, whose ## headings count in 汉字."""
    digits = {c: i for i, c in enumerate("一二三四五六七八九", 1)}
    if "十" in s:
        tens, _, ones = s.partition("十")
        return (digits.get(tens, 1) or 1) * 10 + (digits.get(ones, 0))
    return digits.get(s, 0)


def section_numbers(rel):
    nums = set()
    try:
        body = open(os.path.join(ROOT, rel.replace("/", os.sep)), encoding="utf-8",
                    errors="replace").read()
    except OSError:
        return None                                   # not in this view - not our business
    for line in body.splitlines():
        m = HEAD.match(line)
        if not m:
            continue
        n = m.group(1)
        nums.add(n if n[0].isdigit() else str(cn_num(n)))
    return nums


def resolve_section(doc, text, start):
    """Which file a `§N` at `start` points into: the nearest `.md` named earlier in the
    same sentence, else the doc itself.  Naming the nearest one (not requiring adjacency)
    is what makes `docs/MATRIX.md` §4–§5 resolve for both numbers."""
    window = text[max(0, start - 200):start]
    cut = [m.end() for m in CLAUSE_END.finditer(window)]
    if cut:
        window = window[cut[-1]:]
    named = MD_PATH.findall(window)
    return posixpath.normpath(named[-1]) if named else doc


def check_sections(doc, text, report, kinds):
    """Every §N in a scanned doc must land on a heading that really carries that number."""
    for m in SEC_CITATION.finditer(text):
        num, target = m.group(1), resolve_section(doc, text, m.start())
        if target not in INDEX:                       # doc-relative, or basename-only
            here = posixpath.normpath(os.path.dirname(doc) + "/" + target)
            cands = BY_BASENAME.get(target.rsplit("/", 1)[-1], [])
            target = here if here in INDEX else (cands[0] if len(cands) == 1 else target)
        if target not in INDEX:
            if target.startswith(LOCAL_ONLY):         # evidence tree, not in this checkout
                kinds["sec-unshipped"] = kinds.get("sec-unshipped", 0) + 1
                continue
            report("%-34s §%s" % (doc, num), "cited from %s, which is not a file" % target)
            continue
        kinds["section"] = kinds.get("section", 0) + 1
        nums = section_numbers(target)
        if num not in nums:
            have = " ".join(sorted(nums, key=lambda x: [int(p) for p in x.split(".")]))
            report("%-34s §%s" % (doc, num),
                   "%s has no such heading (it has: %s)" % (target, have or "none - unnumbered"))



# What a public checkout does not contain - the two "never distributed" lines of .gitignore.
# Docs cite into them on purpose (docs/CHANGELOG.md's 版本库 section records the convention:
# those are the names of where a result came from, not links to open), so a citation that
# only lands down here is not an error.  It is counted separately and printed, because
# "how much of the trail a reader can actually open" is a number worth keeping honest.
# Not published, so not policed as documentation.  `dist/` is the player package that
# tools/build_windows_package.py generates: its .md files are byte-copies of ones this
# audit already scans, so leaving it in the doc set would inflate the count and let a
# stale package fail the audit for a reason that has nothing to do with the tree.
LOCAL_ONLY = ("test_roms/", "dist/")


def build_index():
    """Every file in the tree, repo-relative with forward slashes."""
    rels = []
    for base, dirs, files in os.walk(ROOT):
        dirs[:] = [d for d in dirs if d not in (".git", "node_modules", "__pycache__")]
        rels += [os.path.relpath(os.path.join(base, f), ROOT).replace(os.sep, "/")
                 for f in files]
    return sorted(rels)


INDEX = build_index()
BY_BASENAME = {}
for _r in INDEX:
    BY_BASENAME.setdefault(_r.rsplit("/", 1)[-1], []).append(_r)


def local_only(paths):
    return all(p.startswith(LOCAL_ONLY) for p in paths)


def published_md():
    """Every markdown a public checkout ships."""
    return [r for r in INDEX if r.endswith(".md") and not r.startswith(LOCAL_ONLY)]


def all_docs():
    """... minus the ones NOT_SCANNED pays to skip - derived, not remembered."""
    return sorted(d for d in published_md()
                  if not any(d.startswith(p) for p in NOT_SCANNED))


def classify(span, doc):
    """published / local / external / dead - how much of the trail a reader can open.
    Docs name files three ways: repo-relative (`tools/x.py`), relative to the doc's own
    directory (`report_v10_clang_route.json` inside qa/README.md) and host-relative into
    the evidence tree (`run6_patched/png/a.png`)."""
    span = posixpath.normpath(span)        # `./build.sh` and `a/../b.md` are the same file
    if span.startswith(LOCAL_ONLY):
        return "local"
    cand = []
    if span in INDEX:
        cand.append(span)
    here = posixpath.normpath(os.path.dirname(doc) + "/" + span).lstrip("./")
    if here in INDEX:
        cand.append(here)
    cand += BY_BASENAME.get(span, [])
    cand += [r for r in INDEX if r.endswith("/" + span)]
    if cand:
        return "local" if local_only(cand) else "published"
    if span in EXTERNAL:
        return "external"
    return "dead"


def check_text(doc, text, report, kinds=None):
    for span in set(m.group(1).strip() for m in SPAN.finditer(text)):
        lm = LINE_CITATION.match(span)
        if lm:
            rel, line = lm.group(1), int(lm.group(2))
            path = os.path.join(ROOT, rel.replace("/", os.sep))
            if not os.path.exists(path):
                # Deliberately not excused by EXTERNAL: a line number in a file nobody
                # has is a claim nobody can check.  Cite the symbol instead.
                if kinds is not None:
                    kinds["dead"] = kinds.get("dead", 0) + 1
                report("%-34s %s" % (doc, span), "no such file")
                continue
            if kinds is not None:
                k = "local" if rel.startswith(LOCAL_ONLY) else "published"
                kinds[k] = kinds.get(k, 0) + 1
            body = open(path, encoding="utf-8", errors="replace").read().splitlines()
            anchor = ANCHORS.get(span)
            if anchor is None:
                report("%-34s %s" % (doc, span),
                       "unpinned line citation - add it to ANCHORS with the token the line holds")
            elif line > len(body):
                report("%-34s %s" % (doc, span), "file has %d lines" % len(body))
            elif anchor not in body[line - 1]:
                report("%-34s %s" % (doc, span),
                       "line %d holds no %r (starts %r)"
                       % (line, anchor, body[line - 1][:48]))
            continue
        if BARE_LINE.match(span):
            report("%-34s %s" % (doc, span),
                   "a line number with no file - write the whole path so ANCHORS can pin it")
            continue
        if not FILE_CITATION.match(span):
            continue
        kind = classify(span, doc)
        if kinds is not None:
            kinds[kind] = kinds.get(kind, 0) + 1
        if kind == "dead":
            report("%-34s %s" % (doc, span), "nowhere in the tree, the doc's own directory "
                                            "or test_roms/, and not in EXTERNAL")
    check_sections(doc, text, report, kinds if kinds is not None else {})


# (span, must_be_caught).  A green run of this script is only worth anything if the
# script can still fail, so every rule above gets one case here - including the two
# citations that are supposed to pass, which is what catches an over-eager regex.
SELFTEST = [
    ("no_such_file_zzz.py", True),
    ("src/naming_screen.c:1444", True),           # line pin into a source we do not ship
    (":1130", True),                              # line pin with no file at all
    ("qa/font_gate_verdicts.json", False),
    ("./qa/font_gate_verdicts.json", False),      # same file, written with a leading ./
    ("test_roms/roms/some_retired_sample.gba", False),   # provenance name, by prefix
    ("白金光1.2修复版.gba", False),  # EXTERNAL with a stated reason
]

# Same idea for the § rule: (doc, text, must_be_caught).  The last one is the defect that
# started this - a bare §N inside a doc whose headings are not numbered at all.
SECTEST = [
    ("docs/USAGE.md", "见 `docs/HOOKS.md` §6 第 1 条", False),
    ("docs/USAGE.md", "见 `docs/HOOKS.md` §99", True),
    ("docs/USAGE.md", "见 `docs/MATRIX.md` §4–§5", False),   # one path, two numbers
    ("docs/USAGE.md", "见 §99", True),
    ("docs/CHANGELOG.md", "见 §999", True),
    ("docs/USAGE.md", "`test_roms/README.md` §15.5", False),  # local tree: checked or skipped
]


def selftest():
    fake = "payload/adapter_v10.c:1"
    ANCHORS[fake] = "not_a_real_token"            # exercise the anchor-mismatch branch
    try:
        for span, should_fail in SELFTEST + [(fake, True)]:
            hits = []
            check_text("docs/USAGE.md", "cite `%s` here" % span, lambda w, y: hits.append(w))
            if bool(hits) != should_fail:
                print("! %-40s %s" % (span, "not caught" if should_fail else "wrongly caught"))
                return 1
    finally:
        del ANCHORS[fake]

    for doc, text, should_fail in SECTEST:
        hits = []
        check_text(doc, text, lambda w, y: hits.append(w), {})
        if bool(hits) != should_fail:
            print("! %-40s %s" % (text, "not caught" if should_fail else "wrongly caught"))
            return 1

    docs = all_docs()
    texts = {d: open(os.path.join(ROOT, d), encoding="utf-8").read() for d in docs}
    def table_hits():
        hits = []
        check_tables(docs, texts, lambda w, y: hits.append(y))
        return hits
    tables = []
    EXTERNAL["_selftest_made_up.md"] = "used only by --self-test"
    try:
        tables.append(("stale EXTERNAL entry", any("nothing cites it" in h
                                                   for h in table_hits())))
    finally:
        del EXTERNAL["_selftest_made_up.md"]
    NOT_SCANNED["_selftest_no_such_dir/"] = "used only by --self-test"
    try:
        tables.append(("NOT_SCANNED excluding nothing",
                       any("excludes nothing" in h for h in table_hits())))
    finally:
        del NOT_SCANNED["_selftest_no_such_dir/"]
    empty_docs = []
    hits = []
    check_tables(empty_docs, texts, lambda w, y: hits.append(y))
    tables.append(("empty doc set", any("derived to empty" in h for h in hits)))
    tables.append(("the real tables need no excuses", not table_hits()))
    for label, ok in tables:
        if not ok:
            print("! %-40s self-test failed" % label)
            return 1
    print("OK: selftest, %d citation rule(s) + %d section rule(s) + %d table rule(s)"
          % (len(SELFTEST) + 1, len(SECTEST), len(tables)))
    return 0


def check_tables(docs, texts, report):
    """The tables' own hygiene: an excuse nobody uses is as bad as a claim nobody checked."""
    if not docs:
        # A gate that scans nothing must not green-pass - the classic false-green shape.
        report("%-34s (the doc set)" % "", "derived to empty - INDEX or NOT_SCANNED is wrong")
    for name, why in EXTERNAL.items():
        if not why.strip():
            report("%-34s %s" % ("(external table)", name), "listed without a reason")
        elif not any(name in t for t in texts.values()):
            report("%-34s %s" % ("(external table)", name),
                   "nothing cites it any more - drop the excuse")
    for p, why in NOT_SCANNED.items():
        if not why.strip():
            report("%-34s %s" % ("(not-scanned table)", p), "excluded without a reason")
        elif not sum(1 for d in published_md() if d.startswith(p)):
            report("%-34s %s" % ("(not-scanned table)", p), "excludes nothing - drop it")
    for span, token in ANCHORS.items():
        path, line = span.rsplit(":", 1)
        p = os.path.join(ROOT, path.replace("/", os.sep))
        body = open(p, encoding="utf-8", errors="replace").read().splitlines()
        if token not in body[int(line) - 1]:
            report("%-34s %s" % ("(anchor table)", span), "anchor no longer true")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--self-test", action="store_true",
                    help="check the checker against synthetic citations and exit")
    args = ap.parse_args()
    if args.self_test:
        return selftest()
    bad = []
    kinds = {}
    def report(where, why):
        bad.append((where, why))
    docs = all_docs()
    texts = {}
    for doc in docs:
        texts[doc] = open(os.path.join(ROOT, doc), encoding="utf-8").read()
        check_text(doc, texts[doc], report, kinds)
    check_tables(docs, texts, report)
    if bad:
        for where, why in bad:
            print("! %-50s %s" % (where, why))
    print("\n%s: %d doc(s) scanned, %d bad reference(s)" % ("FAIL" if bad else "OK",
                                                            len(docs), len(bad)))
    print("   citations by where they land: %s"
          % ", ".join("%s %d" % (k, kinds[k]) for k in sorted(kinds)))
    return 1 if bad else 0


sys.exit(main())
