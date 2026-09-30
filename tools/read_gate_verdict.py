#!/usr/bin/env python3
"""read_gate_verdict.py -- read the font gate's own numbers out of captured RAM.

  python tools/read_gate_verdict.py [--probe] [--json OUT] [--dump early|late] [host_dir ...]

Why this exists.  The gate decides "does this host actually draw Hanzi" by measuring
the hidden keyboard window (payload/adapter_v10.c, ck_page_stats/ck_gate_step) and
parking what it measured on the PAGE button sprite:

    0x2E  STEP   0 idle / 2..n still sampling / 0xFFFE UNFIT = measured and refused
    0x30  DIAG   mt  = smallest single-quadrant ink over the printed cells
    0x32  PREV   ink total of the previous frame (what stops growing = printing done)

mt is one of the four things the verdict ANDs together, so it is the number the
threshold question is actually about -- and the screenshot can never show it for a
refused host, because a refused host never paints that page.  The capture harness
cannot dereference, so instead of adding a verb the probe route dumps the whole
64-sprite array (64*0x44 bytes) plus ns[CK_FID], and this script walks the same chain
the payload does:

    fid = ns[0x1E24]        bid = gSprites[fid][0x3C]        words = gSprites[bid][0x2E..]

What --probe adds.  The measurement build is the shipped payload plus three writes
inserted immediately after the existing CK_GATE_DIAG write, into button-sprite slots
the shipped code never touches; the verdict logic is otherwise identical, and its
generator is not part of this repository (the slots below are fully specified, which
is what lets the build be recreated).  It records the *whole* verdict-frame tuple,
which is what the refuse-side margin needs and DIAG alone cannot give:

    0x36 = mt | wn<<8       wn = narrowest ink box over the printed cells  (>= CK_CN_MIN_W?)
    0x38 = zn | gap<<8      zn = cells with no ink, gap = printed cells with a bare midline
    0x3A = fid | bid<<8     self-check: the sprite the payload resolved to, from inside

Cross-checks this script performs rather than assumes:
  * the UNFIT sentinel must sit on exactly the resolved sprite and on no other sprite;
  * --probe's mt must equal the shipped build's DIAG for the same host (the probe build
    is only trustworthy if the two agree on the number both of them record);
  * the verdict found in RAM must agree with qa/validated_hosts.json's font_gate field,
    which came from the screenshots and not from this readout.

Two limits are part of the design, not failures of it:
  * On hosts that ENTER Chinese mode, 0x32 (PREV) is later owned by the 切换 label
    (adapter_v10.c re-uses data[2] there), so `sum` on an entered host is label state,
    not the gate's.  0x30 (DIAG) survives, which is why the accept-side mt is readable.
  * The chain needs ns[CK_FID] to be the byte the stock layout says it is.  On hosts
    whose naming-screen struct differs the payload itself resolves the same bogus id,
    so no verdict is locatable there -- reported as unresolved, never guessed around.

Result on this corpus (2026-09-27, kept in qa/font_gate_verdicts.json).  22 of 25 hosts
located, all agreeing with the ledger: 5 entered at wn 10 / mt 6 / zn 0 / gap 0, which is
+1 px over the cut, and 17 refused at wn 6 / mt 0 / zn 0 / gap 0, i.e. -3 px.  zn and gap
are 0 on both sides, so the midline criterion separated nothing here -- it is a guard
against a page that never printed.  The 3 unresolved hosts are the collapse described
above, and on those the payload's three words land in host-owned gSprites[0].data[]:
their outcomes are proven by other evidence, their attribution is not.
"""
import argparse
import json
import os
import re
import sys

SPRITE = 0x44
NSPRITES = 64
STEP_OFF, DIAG_OFF, PREV_OFF = 0x2E, 0x30, 0x32
UNFIT = 0xFFFE
CK_FID = 0x1E24           # ns byte: sprite id of the naming-screen frame sprite
CK_SPR_BTNID = 0x3C       # frame sprite data byte: sprite id of the PAGE button
PROBE_STATS = 0x36        # probe build: mt | wn<<8
PROBE_CELLS = 0x38        # probe build: zn | gap<<8
PROBE_IDS = 0x3A          # probe build: fid | bid<<8
CK_CN_MIN_W = 9           # payload/adapter_v10.c: the width cut being calibrated
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def read_dump(path):
    """Return (sprite bytes, fid, gSprites base) from one capture.log."""
    txt = open(path, "r", errors="replace").read()
    m = re.search(r"GSPR ([0-9A-Fa-f]*)", txt)
    if not m:
        raise ValueError("no GSPR dump in %s" % path)
    hexs = m.group(1)
    if len(hexs) != SPRITE * NSPRITES * 2:
        raise ValueError("dump is %d hex chars, expected %d" % (len(hexs), SPRITE * NSPRITES * 2))
    f = re.search(r"CKFID ([0-9A-Fa-f]{2})", txt)
    if not f:
        raise ValueError("no CKFID byte in %s" % path)
    g = re.search(r"GSBASE (0x[0-9A-Fa-f]+)", txt)
    return bytes.fromhex(hexs), int(f.group(1), 16), (g.group(1) if g else None)


def u16(buf, sprite, off):
    b = buf[sprite * SPRITE + off:]
    return b[0] | (b[1] << 8)


def verdict(path, probe=False):
    buf, fid, base = read_dump(path)
    if fid >= NSPRITES:
        return {"stem": _stem(path), "located": False, "reason": "fid %d out of range" % fid}
    bid = buf[fid * SPRITE + CK_SPR_BTNID]
    if bid >= NSPRITES:
        return {"stem": _stem(path), "located": False, "reason": "bid %d out of range" % bid}
    if bid == fid:
        # The stock screen creates the frame and button sprites separately, so a chain
        # that lands on one sprite for both is not the gate's state - it is whatever the
        # host keeps in that sprite's data[].  Report it as unattributable, not a verdict.
        return {"stem": _stem(path), "located": False,
                "reason": "chain collapses: fid == bid == %d" % fid}
    step, diag, prev = (u16(buf, bid, STEP_OFF), u16(buf, bid, DIAG_OFF), u16(buf, bid, PREV_OFF))
    stray = [i for i in range(NSPRITES) if i != bid and u16(buf, i, STEP_OFF) == UNFIT]
    out = {
        "stem": _stem(path), "located": True, "fid": fid, "bid": bid,
        "step": step, "diag_mt": diag, "prev_sum": (None if prev == 0xFFFF else prev),
        "verdict": {0: "entered", UNFIT: "refused"}.get(step, "sampling"),
        "stray_unfit": stray, "gsprites": base, "rom_sha": rom_sha(path),
    }
    if probe:
        ids = u16(buf, bid, PROBE_IDS)
        stats, cells = u16(buf, bid, PROBE_STATS), u16(buf, bid, PROBE_CELLS)
        out["probe"] = {
            "mt": stats & 0xFF, "wn": stats >> 8, "zn": cells & 0xFF, "gap": cells >> 8,
            "ids": ids, "ids_ok": ids == (fid | (bid << 8)),
            "wn_margin": (stats >> 8) - CK_CN_MIN_W,
        }
        # zn/gap are counts over 32 cells; anything above 32 is not a gate measurement
        # but the host's (or the label's, when frame==button) own data in that slot.
        out["probe"]["plausible"] = out["probe"]["ids_ok"] and cells & 0xFF <= 32 and cells >> 8 <= 32
    return out


def _stem(path):
    # <root>/test_roms/qa_20260926/<stem>/<dumpdir>/capture.log
    return os.path.basename(os.path.dirname(os.path.dirname(path)))


def rom_sha(path):
    """The sha256 gate_diag.sh recorded for the ROM this dump came from."""
    p = os.path.join(os.path.dirname(path), "artifact.txt")
    if not os.path.isfile(p):
        return None
    m = re.search(r"^sha256=([0-9a-f]{64})", open(p, encoding="utf-8", errors="replace").read(), re.M)
    return m.group(1) if m else None


def ledger_gate():
    p = os.path.join(REPO, "qa", "validated_hosts.json")
    d = json.load(open(p, encoding="utf-8"))
    return {os.path.splitext(h["rom"])[0]: h for h in d["hosts"]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("hosts", nargs="*", help="host dirs containing gate_diag_* (default: all 25)")
    ap.add_argument("--probe", action="store_true", help="decode the measurement build's extra slots")
    ap.add_argument("--dump", default="late", choices=("early", "late"),
                    help="which dump dir to read (early = taken while ns[CK_FID] is still live)")
    ap.add_argument("--json", help="also write the table as JSON")
    a = ap.parse_args()

    tag = "gate_diag_patched" + ("_probe" if a.probe else "") + ("_early" if a.dump == "early" else "")
    root = os.path.join(REPO, "test_roms", "qa_20260926")
    gates = ledger_gate()
    stems = a.hosts or sorted(gates)
    rows, problems = [], []
    for s in stems:
        p = os.path.join(root, s, tag, "capture.log")
        if not os.path.isfile(p):
            rows.append({"stem": s, "located": False, "reason": "no capture"})
            continue
        try:
            r = verdict(p, a.probe)
        except ValueError as e:
            rows.append({"stem": s, "located": False, "reason": str(e)})
            continue
        rows.append(r)
        want = gates.get(s) or {}
        if r["located"] and want.get("font_gate") and r["verdict"] != want["font_gate"]:
            problems.append("%s: RAM says %s, ledger says %s"
                            % (s, r["verdict"], want["font_gate"]))
        if r["located"] and r.get("stray_unfit"):
            problems.append("%s: UNFIT also on sprite(s) %s" % (s, r["stray_unfit"]))
        if not a.probe:
            if r["located"] and r["rom_sha"] and r["rom_sha"] not in (
                    want.get("output_sha256"), want.get("output_sha256_gnu")):
                problems.append("%s: dump ROM %s is not the ledger's output"
                                % (s, r["rom_sha"][:12]))
            continue
        pb = r["probe"] if r["located"] else None
        if pb and not pb["plausible"]:
            problems.append("%s: probe slots do not look like a gate write (ids=%s)"
                            % (s, pb["ids"]))
        # Same host, shipped ROM: the probe build is only evidence about the tool the
        # user runs if the number both builds record is the same number.
        ship_p = os.path.join(root, s, "gate_diag_patched", "capture.log")
        if not os.path.isfile(ship_p):
            continue
        ship = verdict(ship_p)
        r["shipped"] = {k: ship.get(k) for k in
                        ("located", "reason", "verdict", "fid", "bid", "diag_mt",
                         "prev_sum", "rom_sha")}
        if not ship["located"]:
            continue
        if ship["rom_sha"] and ship["rom_sha"] not in (
                want.get("output_sha256"), want.get("output_sha256_gnu")):
            problems.append("%s: shipped dump ROM %s is not the ledger's output"
                            % (s, ship["rom_sha"][:12]))
        if pb and ship["diag_mt"] != pb["mt"]:
            problems.append("%s: probe mt %d != shipped DIAG %d" % (s, pb["mt"], ship["diag_mt"]))
        if r["located"] and ship["verdict"] != r["verdict"]:
            problems.append("%s: shipped build %s but probe build %s"
                            % (s, ship["verdict"], r["verdict"]))

    for r in rows:
        if not r["located"]:
            print("%-34s --   %s" % (r["stem"], r.get("reason", "")))
            continue
        line = "%-34s %-8s fid=%-2d bid=%-2d mt=%-3d sum=%-5s" % (
            r["stem"], r["verdict"], r["fid"], r["bid"], r["diag_mt"],
            "-" if r["prev_sum"] is None else r["prev_sum"])
        if a.probe:
            pb = r["probe"]
            line += "  wn=%-3d zn=%-3d gap=%-3d margin=%+d" % (
                pb["wn"], pb["zn"], pb["gap"], pb["wn_margin"])
        print(line)

    found = [r for r in rows if r["located"]]
    print("\nlocated %d/%d; ledger agreement %s"
          % (len(found), len(rows), "OK" if not problems else "MISMATCH"))
    for q in problems:
        print("  ! " + q)
    if a.probe:
        good = [r for r in found if r["probe"]["plausible"]]
        for cls in ("refused", "entered"):
            g = [r for r in good if r["verdict"] == cls]
            if g:
                print("%-8s n=%-2d wn %s  mt %s  gap %s  zn %s" % (
                    cls, len(g),
                    range_str(sorted({r["probe"]["wn"] for r in g})),
                    range_str(sorted({r["probe"]["mt"] for r in g})),
                    range_str(sorted({r["probe"]["gap"] for r in g})),
                    range_str(sorted({r["probe"]["zn"] for r in g}))))
    if a.json:
        alt = tag if tag.endswith("_early") else tag + "_early"
        agree, differ = 0, []
        for r in rows:
            if not r["located"]:
                continue
            p2 = os.path.join(root, r["stem"], alt, "capture.log")
            if not os.path.isfile(p2):
                continue
            try:
                r2 = verdict(p2, a.probe)
            except ValueError:
                continue
            keys = ("located", "verdict", "fid", "bid", "diag_mt", "prev_sum")
            if all(r2.get(k) == r.get(k) for k in keys) and (
                    not a.probe or r2["probe"] == r["probe"]):
                agree += 1
            else:
                differ.append(r["stem"])
        print("end-of-route vs post-press dump: %d identical%s"
              % (agree, (", differ " + ", ".join(differ)) if differ else ""))
        json.dump({"threshold_wn": CK_CN_MIN_W, "dump": tag,
                   "dump_variants_agree": agree, "dump_variants_differ": differ,
                   "rows": rows},
                  open(a.json, "w", encoding="utf-8"), indent=1, ensure_ascii=False)
        print("wrote %s" % a.json)
    return 1 if problems else 0


def range_str(vals):
    return ("%d" % vals[0]) if len(vals) == 1 else "%d..%d" % (vals[0], vals[-1])


sys.exit(main())
