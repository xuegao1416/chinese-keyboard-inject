#!/usr/bin/env python3
"""Recover `gMain` (and therefore `gMain.newKeysRaw`) from a ROM's own code.

Emerald-family Main ABI: heldKeysRaw +0x28, newKeysRaw +0x2A, heldKeys +0x2C.
In this family `gMain` is a very frequently referenced IWRAM global while the
direct `gMain+0x2C` literal is rare, so the resolver scores structure - a single
direct heldKeys literal and no neighbouring +4/+8 aliases - instead of trusting a
hardcoded address.

This is the only copy of the scoring rule in the repository. Two structural gates run
before scoring: a direct `gMain+0x2C` literal must exist, and so must a direct
`gMain+0x38` one - see resolve_gmain."""
from collections import Counter


def resolve_gmain(rom: bytes):
    c = Counter(int.from_bytes(rom[i:i + 4], "little") for i in range(0, len(rom) - 3, 4))

    def rank(require_held):
        rows = []
        for p, n in c.items():
            if 0x03000000 <= p < 0x03008000 and p % 4 == 0 and n >= 100:
                held = c[p + 0x2c]
                plus38 = c[p + 0x38]
                if require_held and not held:
                    continue
                # A real `gMain` is always addressed at +0x38 somewhere - Main's task
                # queue is walked through that field by the kernel, so no candidate the
                # code never names at +0x38 is it. This is the predicate that separates
                # the struct from the neighbouring IWRAM block that shares its shape:
                # bubble128_cn's true gMain (map says 0x03003714) has +0x38 refs but a
                # low direct-heldKeys count, and the 0x03000000 vector area that beat it
                # on raw reference count has none at all. Measured over the 13 hosts that
                # resolve: every correct pick has 1-5 +0x38 refs, the one wrong pick has 0.
                if not plus38:
                    continue
                # Prefer a single direct heldKeys literal and no neighboring +4/+8 aliases.
                score = n - 150 * abs(held - 1) - 3 * c[p + 4] - 3 * c[p + 8]
                rows.append((score, p, n, held, plus38))
        rows.sort(reverse=True)
        return rows

    rows = rank(True)
    # `held` is a preference, not a proof. Whether `gMain+0x2C` ever appears as its
    # own literal is an artefact of immediate folding - Thumb `ldrh` encodes offsets
    # up to 0x3E inline, so a build that reaches newKeys straight off the base
    # literal cannot produce one. astral_emerald's real gMain (0x03002408, 1187 refs,
    # 0 aliases) is named at +0x2C exactly zero times, and the gate alone left the
    # 119-ref 0x03003990 standing - at score -1993.
    #
    # A negative score means the candidate lost more to the shape penalties than it
    # gained from references, i.e. it is contradicting the rule that selected it. Only
    # then is the gate released, and only for a strictly better answer. quetzal's
    # correct 0x03002370 scores +1018 so it never takes the branch; bubble128's
    # correct 0x03003714 scores -42 and takes it, and both ranks agree on it there.
    if not rows or rows[0][0] < 0:
        alt = rank(False)
        if alt and (not rows or alt[0][0] > rows[0][0]):
            rows = alt
    if not rows:
        raise SystemExit("gMain resolver: no candidate")
    best = rows[0]
    if len(rows) > 1 and best[0] <= rows[1][0]:
        raise SystemExit("gMain resolver ambiguous")

    return {
        "gMain": best[1],
        "newKeysRaw": best[1] + 0x2a,
        "score": best[0],
        "candidates": [
            {"gMain": hex(p), "refs": n, "heldKeys_refs": h, "plus38_refs": r, "score": s}
            for s, p, n, h, r in rows[:8]
        ],
    }
