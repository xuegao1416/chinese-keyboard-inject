#!/usr/bin/env python3
"""Recover PlaySE and the window/text engine APIs from a naked ROM.

1.0 originally identified these five functions with a *call-order motif* over the
naming screen's print cluster ("the first external callee is FillWindowPixelBuffer;
PutWindowTilemap and CopyWindowToVram show up as a repeated Fill->X->Y triple").
That motif was only ever demonstrated on modern-GCC output. On the agbcc build of
`pokeemerald-rogue` it resolves four of the five to *wrong* addresses that are
still distinct, in range and Thumb-tagged - nothing downstream notices without a
linker map (`docs/MATRIX.md` Sec.3). The root cause is that the motif depends on
which function the caller happens to pick as the print cluster and on the exact
instruction ordering the compiler chose.

This module keeps that motif as a **fallback** and adds a shape-based primary
path that does not depend on either:

1. `_window_trio` finds `FillWindowPixelBuffer`, `PutWindowTilemap` and
   `CopyWindowToVram` as a single structural object. They live in one object file
   (`gflib/window.o`) and are always called as a group: one of them (Fill) is
   *immediately followed* by each of the other two in many call sites, and the
   other two are adjacent to each other. Across two independently built ROMs this
   identifies exactly one triple.
2. Within that triple, the two non-Fill members are separated by **argument
   shape**: `CopyWindowToVram(windowId, mode)` always has its second argument set
   to a small constant at the call site, `PutWindowTilemap(windowId)` takes one
   argument and does not. Measured: 100% vs 28-36% of call sites.
3. `AddTextPrinterParameterized3` is a 7-argument printer, so every call site
   pushes exactly three outgoing stack words. Among the functions with that shape
   the one that is also called from inside the naming-screen code island is the
   answer.

Every step refuses loudly when its evidence is ambiguous; the caller then falls
back to the motif, and `inject_v10.precheck` still enforces `window_api_same_block`
on whatever comes out.
"""
import re
from collections import Counter

from trampoline import decode_thumb_bl

BASE = 0x08000000

# Naming-screen-local sites that the rest of the resolver locates reliably on
# every build tried; used to bound the code island AddText must be called from.
LOCAL_SITES = ("character", "page", "backspace", "ok", "handle", "delete",
               "getchar", "flash", "lr_frame")
ISLAND_PAD = 0x1000          # margin around the local sites, either side
NS_CLUSTER = 0x4000          # how far a site may sit from `ok` and still be NamingScreen
TRIO_SPAN = 0x1000           # window.o's three functions sit far closer than this
TRIO_EDGE = 15               # min adjacent-call count for a "these two always co-occur" edge
NS_WINDOW_ISLAND = 0x3000    # code-island half-width used to test "external" (legacy)
ADDTEXT_MIN_SITES = 100      # min ROM-wide BL sites for a gflib text printer (see _find_addtext)
LAST_INFO = {}               # diagnostic: which path was used (never serialized)

# BL shape: `11110...` then `11111...`. Matching the raw bytes first and only then
# decoding keeps the sweep cheap: a plain decode over every 2-byte offset of a
# 32 MiB image is ~16M calls.
_BL_BYTES = re.compile(rb"(?=[\x00-\xff][\xf0-\xf7][\x00-\xff][\xf8-\xff])")


def _sweep_bls(rom):
    """Every Thumb BL in the image as (file_offset, target_without_thumb_bit)."""
    out = []
    for m in _BL_BYTES.finditer(rom):
        q = m.start()
        if q & 1:
            continue
        v = decode_thumb_bl(rom, q)
        if v is not None:
            out.append((q, v & ~1))
    return out


def _adjacent_pairs(bls, gap=8):
    pair = {}
    for i in range(len(bls) - 1):
        (q0, t0), (q1, t1) = bls[i], bls[i + 1]
        if q1 - q0 <= gap:
            pair[(t0, t1)] = pair.get((t0, t1), 0) + 1
    return pair


def _window_trios(bls):
    """Candidate triples of *distinct* callees that always co-occur.

    One member (the hub) is called immediately before each of the other two at
    least TRIO_EDGE times, and those other two are adjacent to each other at least
    TRIO_EDGE times. Self-pairs (a function called twice in a row) contribute no
    triple because the three members are always distinct addresses.
    """
    pair = _adjacent_pairs(bls)
    nodes = sorted({a for (a, b), c in pair.items() if c >= TRIO_EDGE and a != b}
                   | {b for (a, b), c in pair.items() if c >= TRIO_EDGE and a != b})
    trios = set()
    n = len(nodes)
    for i in range(n):
        A = nodes[i]
        for j in range(i + 1, n):
            B = nodes[j]
            for k in range(j + 1, n):
                C = nodes[k]
                if C - A > TRIO_SPAN:
                    continue
                for hub, p, q in ((A, B, C), (B, A, C), (C, A, B)):
                    if (pair.get((hub, p), 0) >= TRIO_EDGE
                            and pair.get((hub, q), 0) >= TRIO_EDGE
                            and (pair.get((p, q), 0) + pair.get((q, p), 0)) >= TRIO_EDGE):
                        trios.add((A, B, C))
                        break
    return trios, pair


def _arg_shape(rom, q, back=0x0C):
    """(mode_arg, fill_arg) for a call site: is r1 a mode constant / a PIXEL_FILL?"""
    mode = fill = False
    for k in range(2, back + 1, 2):
        h = int.from_bytes(rom[q - k:q - k + 2], "little")
        if h & 0xFF00 == 0x2100:
            imm = h & 0xFF
            if imm in (1, 2, 3):
                mode = True
            if (imm >> 4) == (imm & 0xF):        # PIXEL_FILL(n) == n | n<<4
                fill = True
    return mode, fill


def _classify_trio(rom, bls, members):
    """Name the three window APIs by argument shape.

    `FillWindowPixelBuffer(windowId, fillValue)` is always called with a fill
    value, which in this codebase is `PIXEL_FILL(n)` = `n | n<<4` - the high and
    low nibbles of the byte are equal. `CopyWindowToVram(windowId, mode)` always
    sets its mode argument to 1/2/3. `PutWindowTilemap(windowId)` takes one
    argument and does neither. Measured on both hosts: fill rate 0.94/0.95 for
    Fill, 0.17/0.15 for Put; mode rate 1.00 for Copy, 0.02-0.09 for the others.
    """
    sites = {t: [] for t in members}
    for q, t in bls:
        if t in sites:
            sites[t].append(q)
    if any(not sites[t] for t in members):
        return None
    mode_rate, fill_rate = {}, {}
    for t in members:
        n = len(sites[t])
        ms = [q for q in sites[t]]
        mode_rate[t] = sum(1 for q in ms if _arg_shape(rom, q)[0]) / n
        fill_rate[t] = sum(1 for q in ms if _arg_shape(rom, q)[1]) / n
    fill = [t for t in members if fill_rate[t] > 0.5]
    copy = [t for t in members if mode_rate[t] > 0.5]
    if len(fill) != 1 or len(copy) != 1 or fill[0] == copy[0]:
        return None
    put = [t for t in members if t not in (fill[0], copy[0])]
    if len(put) != 1:
        return None
    return fill[0], put[0], copy[0]


BURST_SPAN = 0x10          # Fill/Put/Copy sit within this of each other in one burst
BURST_MIN = 3              # a triple must repeat this often to be believed at all
BURST_MIN_SITES = 100      # traffic floor for a function to enter an argument pool


def _arg_pools(rom, bls):
    """Callees sorted by the *arguments* their callers pass: (fill, put, copy) pools.

    Same two tests `_classify_trio` applies inside a candidate triple, applied to the
    whole image instead: more than half the sites load r1 with a PIXEL_FILL-shaped byte
    (n|n<<4), or with a CopyWindowToVram mode (1/2/3). Whatever is neither and still
    carries traffic is a Put candidate.
    """
    sites, mode, fill = Counter(), Counter(), Counter()
    for q, t in bls:
        sites[t] += 1
        m, f = _arg_shape(rom, q)
        mode[t] += m
        fill[t] += f
    big = {t for t, n in sites.items() if n >= BURST_MIN_SITES}
    fills = {t for t in big if fill[t] > sites[t] / 2}
    copies = {t for t in big if mode[t] > sites[t] / 2}
    puts = big - fills - copies
    return fills, puts, copies


def _burst_trios(rom, bls, span=BURST_SPAN):
    """Ordered Fill -> Put -> Copy bursts, counted per triple.

    `_window_trios` asks three functions to be mutually adjacent, which needs them to
    occur in more than one order across the image. A host whose drawing code always
    uses one order has the API and can never satisfy that: the burst contributes the
    edges Fill->Put and Put->Copy, never Fill->Copy or Copy->Fill, so the triangle
    closes on nothing. This test reads the order instead of ignoring it.
    """
    fills, puts, copies = _arg_pools(rom, bls)
    offs = [q for q, _ in bls]
    target = dict(bls)
    hits = Counter()
    for i, q in enumerate(offs):
        if target[q] not in fills:
            continue
        for j in range(i + 1, len(offs)):
            q2 = offs[j]
            if q2 - q > span:
                break
            t2 = target[q2]
            if t2 not in puts:
                continue
            for k in range(j + 1, len(offs)):
                q3 = offs[k]
                if q3 - q > span:
                    break
                t3 = target[q3]
                if t3 in copies and t3 not in (target[q], t2):
                    hits[(target[q], t2, t3)] += 1
    return hits


def _text_printer_shape(rom, q, back=0x1A):
    """True for a call site that looks like a 7-argument printer.

    `AddTextPrinterParameterized3(windowId, fontId, x, y, *color, speed, *str)`
    takes seven arguments, so the four beyond r0-r3 sit in registers and three
    outgoing stack words are stored at [sp,#0], [sp,#4] and [sp,#8]; a fifth
    stack word at [sp,#0x10] means the callee takes eight or more arguments and
    is not it. The coordinate and speed arguments are immediate moves.
    """
    offs, r2imm, nlit = set(), 0, 0
    for k in range(2, back + 1, 2):
        h = int.from_bytes(rom[q - k:q - k + 2], "little")
        if h & 0xF800 == 0x9000:                 # str rX,[sp,#imm]
            offs.add((h & 0xFF) * 4)
        elif h & 0xFF00 == 0x2200:               # movs r2,#imm8
            r2imm += 1
        if 0x4800 <= h < 0x5000:                 # ldr rN,[pc,#lit]
            nlit += 1
    return ({0, 4, 8} <= offs and 0x10 not in offs and r2imm >= 1 and nlit >= 1)


def ns_island(r, cluster=NS_CLUSTER):
    """The naming screen's own code island as (lo, hi).

    min..max over LOCAL_SITES is only sound while every one of those sites belongs to
    the same subsystem, and they do not always: astral_emerald's `handle` sits 0xC9000
    past its own handlers, which inflates a 14 KB island to 826 KB and lets every text
    printer in the game fall inside it - five candidates tied there. `ok` is a
    naming-screen handler by definition, so the island is the cluster around *it*;
    anything further than NS_CLUSTER away is some other subsystem's function that
    resolve_modern happened to also name. Measured on all 19 archived hosts that bind
    AddText today: this rule returns the same single function on every one of them.
    """
    ok = r["ok"]
    vals = [r[k] for k in LOCAL_SITES
            if isinstance(r.get(k), int) and abs(r[k] - ok) <= cluster]
    return min(vals) - ISLAND_PAD, max(vals) + ISLAND_PAD


def _find_addtext(rom, r, bls, exclude, counts):
    """The 7-arg printer called from the naming-screen code island.

    Shape alone leaves a rival on several hosts: a naming-screen helper that also
    takes seven arguments. `AddTextPrinterParameterized3` is a gflib text routine
    the whole game prints through, so it is called from hundreds of sites, while
    the rival is local to one screen. Measured across the nine hosts that resolve
    here: printer 182-211 call sites, best rival 29.
    """
    lo, hi = ns_island(r)
    cand = Counter()
    for q, t in bls:
        if lo <= q < hi and t not in exclude and _text_printer_shape(rom, q):
            cand[t] += 1
    keep = [t for t in cand if counts[t] >= ADDTEXT_MIN_SITES]
    if len(keep) != 1:
        LAST_INFO["addtext_candidates"] = {hex(t): (n, counts[t]) for t, n in cand.items()}
        LAST_INFO["addtext_island"] = [hex(lo), hex(hi)]
        return None
    return keep[0]


PLAYSE_MIN_SITES = 400      # ROM-wide BL call sites a shared sound entry point has
PLAYSE_MIN_CONST = 0.85     # of those sites, how many load r0 with a literal SE id
SE_SELECT_ID = 5            # `PlaySE(SE_SELECT)` - the cursor/key-press sound
SE_SELECT_MIN_HITS = 100    # how many call sites must pass that one id


def sound_api(rom, bls=None):
    """The ROM's shared sound entry point, found by the *values* its callers pass.

    `PlaySE(u16 songNum)` is called from everywhere and almost always with a literal
    sound id, and one id dominates the whole ROM because every cursor move plays it:
    `SE_SELECT == 5`. So scan every BL target, take the `movs r0,#imm8` that sits
    immediately before each site (immediately, because within-16-bytes can be shadowed
    by a later writer to r0), and ask for 5 to be the most frequent such literal.

    Measured over all 26 archived samples on 2026-09-26: exactly one function per ROM
    satisfies this on 25 of them, at 863-1213 call sites with 440-737 `#5` hits, and on
    the 19 that already had a PlaySE bound by other reasoning it is the *same* function
    every time. The near-miss this rejects is `SetGpuReg`, which shares the traffic and
    the literal-argument shape but whose literals are REG_ register offsets - its
    dominant immediate is 0x50/0x52, never 5.

    Returns `(target_without_thumb_bit, sites, select_hits)` or None. astral_emerald is
    the None case: its author replaced the shared sound entry point with private helpers.
    """
    if bls is None:
        bls = _sweep_bls(rom)
    sites = Counter()
    ids = {}
    for q, t in bls:
        sites[t] += 1
        if q >= 2:
            hw = int.from_bytes(rom[q - 2:q], "little")
            if hw & 0xFF00 == 0x2000:          # movs r0,#imm8; no rotate field exists
                ids.setdefault(t, []).append(hw & 0xFF)
    best = None
    for t, vals in ids.items():
        if sites[t] < PLAYSE_MIN_SITES:
            continue
        c = Counter(vals)
        mode, count = c.most_common(1)[0]
        if mode == SE_SELECT_ID and count >= SE_SELECT_MIN_HITS:
            if best is None or count > best[2]:
                best = (t, sites[t], count)
    return best


def _playse(rom, r, bls=None, counts=None):
    """The shared sound entry point, or 0 when the host does not have one.

    This used to be a statement about *location* - "the OK handler's callee outside the
    naming-screen island" - which is why astral_emerald could not be answered: its OK
    handler's only callee is the host's own text printer, so proximity either ships a
    printer as the sound API or refuses. The argument-space fingerprint above answers
    the same question from what the callee *does*, is unique on 25/26 samples, and
    agrees with every binding the location rule made correctly.

    0 is a real answer, not a failure: the adapter compiles its click sounds away and
    the patch stays correct but silent. The unsafe direction is binding a guessed
    function, and this route cannot do that - it binds a fingerprinted target or none.
    """
    if bls is None:
        bls = _sweep_bls(rom)
    hit = sound_api(rom, bls)
    if hit is None:
        band = playse_band(rom, bls)
        LAST_INFO["playse"] = None
        LAST_INFO["playse_band"] = [(hex(t), n, round(f, 2)) for t, n, f in band[:4]]
        return 0
    target, sites, hits = hit
    LAST_INFO["playse"] = {"target": hex(BASE + target), "sites": sites, "se_select_sites": hits}
    # The island rule is kept as a cross-check only: when it names a different
    # function we go with the fingerprint and record the disagreement, because the
    # disagreement itself is the signal that the island assumption has drifted.
    lo = max(0, min(r["character"], r["getchar"], r["handle"]) - NS_WINDOW_ISLAND)
    hi = min(len(rom), max(r["character"], r["getchar"], r["handle"]) + 0x5000)
    prox = {t for q, t in calls(rom, r["ok"], r["ok"] + 0x40)
            if not (lo <= t - BASE < hi)}
    if prox and target not in prox:
        LAST_INFO["playse_island_disagrees"] = [hex(BASE + t) for t in sorted(prox)]
    return target | 1


def playse_band(rom, bls=None):
    """Functions whose traffic and argument *shape* look like a shared engine API.

    Superseded as an identifier by `sound_api` above, which adds the argument *values*
    and therefore separates `PlaySE` from `SetGpuReg` - the two are indistinguishable on
    traffic and shape alone (both are called 400+ times with `movs r0,#imm` nearby).
    Kept because when `sound_api` finds nothing this is the diagnostic that says why:
    a band holding only REG-offset-shaped members means the host has no sound entry
    point, while a band with an unbound member means the resolver is at fault.
    """
    if bls is None:
        bls = _sweep_bls(rom)
    sites = {}
    for q, t in bls:
        sites.setdefault(t, []).append(q)
    rows = []
    for t, ss in sites.items():
        if len(ss) < PLAYSE_MIN_SITES:
            continue
        hits = 0
        for q in ss:
            for d in range(2, 18, 2):
                if q - d < 0:
                    break
                if int.from_bytes(rom[q - d:q - d + 2], "little") & 0xFF00 == 0x2000:
                    hits += 1
                    break
        frac = hits / len(ss)
        if frac >= PLAYSE_MIN_CONST:
            rows.append((t, len(ss), frac))
    rows.sort(key=lambda x: -x[1])
    return rows


def window_block_rival(rom, bls, fill, put, copy, pad=0x2000):
    """Fill-shaped callees inside the block Put and Copy share, excluding `fill`.

    inject_v10's `window_api_same_block` check is a proxy: window.o's three members are
    one object file, so they sit together, and a trio that does not is probably a
    mis-binding. astral_emerald breaks the proxy without breaking the identity - its
    Fill is 0x9454 past Put/Copy - so when the span fails the check has to ask the
    question the proxy was standing in for: is there a *nearer* candidate for Fill that
    the resolver ignored? An empty answer is the proof that proximity could not have
    done better, which is what makes the unique-ordered-burst answer the only evidence
    left standing. Measured on stock 1.9.4 the block holds two fill-shaped functions,
    so on a stock layout this returns non-empty for any trio that is not the real one.
    """
    fills, _puts, _copies = _arg_pools(rom, bls)
    lo, hi = min(put, copy) - pad, max(put, copy) + pad
    return sorted(t for t in fills if lo <= t < hi and t != fill)


def resolve_engine_apis_shape(rom, r):
    """Shape-based path. Returns the five APIs or None when evidence is ambiguous."""
    bls = _sweep_bls(rom)
    trios, _pair = _window_trios(bls)
    # Recorded on every path, not only the empty one: a refusal message that quotes
    # this number has to be able to tell "no triples exist" from "never got that far".
    LAST_INFO["trio_count"] = len(trios)
    if trios:
        # More than one triple can satisfy the co-call topology once a newer expansion
        # spreads window.o's members far enough apart that the span filter stops
        # collapsing them. Only the real Fill/Put/Copy set has the argument shapes that
        # tell the three apart, so classify every candidate and keep those that resolve:
        # on all seven hosts sampled exactly one survives, and on the two validated
        # hosts it is the same trio the single-candidate path used.
        named = {}
        for t in trios:
            cls = _classify_trio(rom, bls, t)
            if cls is not None:
                named[cls] = t
        if len(named) != 1:
            LAST_INFO["trio_classifiable"] = len(named)
            return None
        fill, put, copy = next(iter(named))
    else:
        # No triangle does not mean no window API. It can also mean every drawing
        # burst in the host uses one order, which is what astral_emerald turned out to
        # be: 13 fill-shaped and 4 mode-shaped functions at stock's rates, and eight
        # ordered Fill;Put;Copy bursts - a unique triple under the ordered test, on a
        # ROM where the triangle test finds zero. Uniqueness is the whole safety of
        # this route, so two survivors is a refusal, not a tie-break.
        burst = Counter({t: n for t, n in _burst_trios(rom, bls).items()
                         if n >= BURST_MIN})
        LAST_INFO["burst_trio_count"] = len(burst)
        if len(burst) != 1:
            LAST_INFO["burst_trios"] = [(tuple(hex(x) for x in k), v)
                                        for k, v in burst.most_common(4)]
            return None
        fill, put, copy = next(iter(burst))
        LAST_INFO["window_method"] = "burst"
    counts = Counter(t for _, t in bls)
    addtext = _find_addtext(rom, r, bls, exclude={fill, put, copy}, counts=counts)
    if addtext is None:
        LAST_INFO["addtext_ambiguous"] = True
        return None
    return {"PlaySE": _playse(rom, r, bls=bls, counts=counts), "FillWindowPixelBuffer": fill | 1,
            "PutWindowTilemap": put | 1, "CopyWindowToVram": copy | 1,
            "AddTextPrinterParameterized3": addtext | 1}


# --------------------------------------------------------------------------
# Legacy motif path - kept verbatim as the fallback for hosts the shape path
# cannot decide. This is the code the upstream snapshot shipped and is the path
# that reproduces the validated-host report byte for byte.
# --------------------------------------------------------------------------

def calls(rom, start, end):
    out = []
    for q in range(start, min(end, len(rom) - 4), 2):
        v = decode_thumb_bl(rom, q)
        if v is not None:
            out.append((q, v & ~1))
    return out


def resolve_engine_apis_motif(rom, r, draw):
    # NamingScreen is a tight local code island around its handlers/helpers.
    lo = max(0, min(r['character'], r['getchar'], r['handle']) - 0x3000)
    hi = min(len(rom), max(r['character'], r['getchar'], r['handle']) + 0x5000)

    def external(t):
        o = t - BASE
        return not (lo <= o < hi)

    # PlaySE comes from the argument-space fingerprint, not from this island: the
    # island test spans min..max of the naming-screen sites, and astral_emerald's
    # `handle` sits 0xC8000 past its own handlers, so its window is 851 KB wide and
    # nothing in it is "external" - the location rule cannot even state the question.
    playse = _playse(rom, r)
    # DrawTextEntry begins with FillWindowPixelBuffer; later in the same local print cluster
    # CopyWindowToVram and PutWindowTilemap occur as an adjacent pair.
    dcalls = calls(rom, draw, draw + 0x240)
    ext = [(q, t) for q, t in dcalls if external(t)]
    if not ext:
        raise RuntimeError('no external calls in DrawTextEntry cluster')
    fill = ext[0][1]
    # Put is recognized by two repeated Fill -> TextPrinter -> Put motifs in the print cluster.
    # Find repeated middle/last targets after occurrences of the Fill target.
    triples = []
    for i, (q, t) in enumerate(ext):
        if t != fill:
            continue
        window = ext[i + 1:i + 4]
        if len(window) >= 2:
            triples.append(window)
    # frequency of targets occurring shortly after Fill
    after = {}
    for w in triples:
        for q, t in w:
            after[t] = after.get(t, 0) + 1
    repeated = [t for t, n in after.items() if n >= 2 and t != fill]
    # In this ABI AddTextPrinter3 and PutWindowTilemap repeat; Put is the later member in Fill-X-Put motifs.
    addtext = put = None
    for i in range(len(ext) - 2):
        q0, t0 = ext[i]
        q1, t1 = ext[i + 1]
        q2, t2 = ext[i + 2]
        if t0 == fill and t1 in repeated and t2 in repeated and t1 != t2:
            addtext = t1
            put = t2
            break
    if addtext is None:
        raise RuntimeError(f'text/window motif unresolved: {[(hex(q), hex(t)) for q, t in ext]}')
    # Copy is the external callee immediately before Put in the first DrawTextEntry path.
    copy = None
    for i, (q, t) in enumerate(ext):
        if t == put and i > 0:
            cand = ext[i - 1][1]
            if cand not in (fill, addtext):
                copy = cand
                break
    if copy is None:
        # Later print path has Put followed immediately by Copy.
        for i, (q, t) in enumerate(ext[:-1]):
            if t == put and ext[i + 1][1] not in (fill, addtext, put):
                copy = ext[i + 1][1]
                break
    if copy is None:
        raise RuntimeError('CopyWindowToVram unresolved')
    return {'PlaySE': playse, 'FillWindowPixelBuffer': fill | 1, 'PutWindowTilemap': put | 1,
            'CopyWindowToVram': copy | 1, 'AddTextPrinterParameterized3': addtext | 1}


def resolve_engine_apis(rom, r, draw=None):
    """Shape-based resolution with the legacy motif as a fallback."""
    LAST_INFO.clear()
    try:
        got = resolve_engine_apis_shape(rom, r)
    except BaseException as e:                        # noqa: BLE001 - fall back
        LAST_INFO["shape_error"] = f"{type(e).__name__}: {e}"
        got = None
    if got is not None:
        LAST_INFO["method"] = "shape"
        return got
    LAST_INFO["method"] = "motif"
    if draw is None:
        raise RuntimeError("legacy motif fallback requires the DrawTextEntry offset")
    return resolve_engine_apis_motif(rom, r, draw)
