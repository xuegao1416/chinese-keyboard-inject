#!/usr/bin/env python3
"""CKI 1.0 ROM backend; the resolver lineage below documents its implementation.

1.0 is this project's starting point. It was built by taking one upstream delivery
snapshot, verifying it, folding in everything that still had a job, and removing
the rest - so nothing in this repository is a "previous version" of anything.

Why the resolver has no symbol input
------------------------------------
An earlier prototype obtained the window/audio ABI targets by replaying per-function
relocations from a *masked object profile* of `naming_screen.o`. That works only
while the target was built from the exact object layout the profile came from. On
the current `pokeemerald-ch` modern build the profile does not hit at all, and that
route aborts with "ABI resolver PlaySE: []".

1.0 recovers every address from the ROM's own machine code:

  1. `resolve_modern.resolve_modern` walks the NamingScreen dataflow - the 3x4x8
     keyboard data blob, its Thumb LDR-literal users, the key-handler dispatch
     table, the DeleteTextCharacter / HandleKeyboardEvent call graph, and the two
     EWRAM globals distinguished by *how* they are used (pointer-dereferenced vs
     indexed) rather than by frequency.
  2. `engine_api_resolver.resolve_engine_apis` recovers PlaySE and the
     window/text APIs from call relationships inside that same code island -
     one external callee in the OK handler (PlaySE), and repeated
     Fill -> TextPrinter -> Put motifs in the DrawTextEntry print cluster.
  3. `gmain_resolver.resolve_gmain` scores IWRAM globals for the Emerald Main ABI.

No `.map`, no `.sym`, no profile. The resolver independently reproduces the five
addresses the build's own linker map holds - see tools/verify_against_map.py.

Consequently the adapter carries no hardcoded absolute address at all:
`payload/adapter_v10.c` consumes 14 `-D` build constants (8 of them required,
enforced with #error).

Hook sites
----------
1.0 patches *dispatch* rather than *function entry* wherever it can:

  * key-handler table (4 entries, 16 bytes) - entries 0 (Character) and 1 (Page)
    are redirected; entries 2 (Backspace) and 3 (OK) are left stock;
  * the logical delete routine - 8-byte absolute jump to `ck_delete_handler`,
    reachable through the untouched stock Backspace handler;
  * Task_NamingScreen's single BL to HandleKeyboardEvent - replaced by
    `ck_handle_frame`, which forwards to the stock handler when unlocked.

No cursor hook and no write-site hook are needed.

Ported from an upstream snapshot - what that means concretely
-------------------------------------------------------------
  A. Paths are repository-relative.
  B. The toolchain is configurable: `--clang` / `--llvm-objcopy` / `--nm`, or
     `--toolchain gnu` with `--toolchain-prefix` / `$CKI_ARM_PREFIX`. A missing
     toolchain is reported clearly instead of raising CalledProcessError.
  C. `--dry-run` stops after the resolver, free-space, and pre-check stages, so
     the whole pipeline can be inspected on a machine with no ARM cross-compiler.
  D. Structural pre-check. Before anything is written, the resolved sites are
     validated for internal consistency (Thumb PUSH prologues at every function
     entry, handler-table entries pointing at the resolved handlers, the frame
     callsite actually being a BL to the resolved HandleKeyboardEvent, one
     single code island, a uniform free run). A failure aborts with exit code 2
     instead of producing a corrupt ROM. Bypass with `--skip-precheck`.

The injection algorithm and every byte written on a validated ROM are unchanged.
The recorded 1.0 output hash is
`fb4aeaf211263885f3079d0406e5a4c84328b19541fe9c28c8db91308c4fb2f8`
for input `280eeb2f24dbdf1413a8e7977b46fc7684f4c26499669dbbe24e9106eccb562c`.
Reproducing that hash bit-for-bit requires the same compiler backend the drop
used (clang + lld); a GNU cross-gcc produces a different but equivalent payload.
"""

from pathlib import Path
import argparse
import bisect
import hashlib
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parent          # injector/
REPO = ROOT.parent                              # repository root
PAYLOAD = REPO / "payload"

sys.path.insert(0, str(ROOT))
from cursor_resolver import resolve_cursor          # noqa: E402
from engine_api_resolver import (  # noqa: E402
    LAST_INFO as EAPI_INFO, _sweep_bls, ns_island, resolve_engine_apis,
    window_block_rival)
from gmain_resolver import resolve_gmain             # noqa: E402
from label_resolver import LabelLayoutError, resolve_keyboard_windows  # noqa: E402
from map_oracle import oracle_checks, parse_map      # noqa: E402
from resolve_modern import InterfaceChanged, callers, resolve_modern   # noqa: E402
from stock_keyboard_resolver import resolve_stock_keyboard             # noqa: E402
from trampoline import decode_thumb_bl, jump, thumb_bl  # noqa: E402

BASE = 0x08000000

# Free-space search: walk outward from the handler table, require one uniform run
# of NEED bytes that are all 0x00 or all 0xFF, 4-byte aligned.
#
# The blob is linked at its final load address (link_v10.ld sets `. = runtime`),
# so the run must be picked before the adapter exists and cannot be swapped after
# a too-large build. NEED is therefore the reference payload plus slack, and
# `payload_fits_run` below turns any miss into a named refusal instead of a
# silent overwrite of live bytes.
# A sizing floor, not a measured maximum: NEED is what the free-space search demands,
# and the run it picks must clear the biggest blob any host actually builds.
# Raising it is a one-way door - see the note below.
REFERENCE_PAYLOAD = 18386   # clang route; gnu route builds smaller - take the larger
# Per-host #defines shift the build: the 26-host matrix measured 18322 (astral)
# to 18426 (rogue_zh) with the font gate in the payload, so NEED still clears the
# largest real blob by 4056 B.
# Raising REFERENCE_PAYLOAD moves the run find_free picks, which changes every
# output SHA - only do it when the margin above actually runs out. The hard ceiling
# is the tightest run in the corpus: rogue's 0x5900 (22784 B) clears NEED by 302 B,
# so REFERENCE_PAYLOAD above 18688 puts both rogue hosts back outside the tool.
PAYLOAD_SLACK = 4096
NEED = REFERENCE_PAYLOAD + PAYLOAD_SLACK
SEARCH_SPAN = 0x3F0000
# A Thumb-1 BL reaches +-4 MiB (0x400000). The validated host's run sits
# 0x3849C2 from its per-frame hook site, so allow a little more than that and
# still keep ~256 KB of slack for the payload's own internal offsets.
BL_RANGE = 0x3C0000

# Resolved function entries that must look like real Thumb function entries.
PROLOGUE_FIELDS = ("character", "page", "backspace", "ok", "handle", "delete",
                   "getchar", "flash")

# Everything the resolver claims lives in naming_screen must fit in one code
# island. naming_screen.o's .text is ~0x27B0 bytes; 0x8000 is the same span the
# engine-API resolver itself uses to decide "local vs external".
ISLAND_SPAN = 0x8000

# FillWindowPixelBuffer / PutWindowTilemap / CopyWindowToVram all live in
# gflib/window.o, whose .text is ~0x1154-0x13E8 bytes in the builds measured so
# far, so the three must be close together. This is the check that catches the
# engine-API mis-resolution seen on agbcc output (docs/MATRIX.md), where the
# three targets came out 600 KiB apart.
WINDOW_BLOCK_SPAN = 0x8000

# Toolchain candidates, most-preferred first.
CLANG_NAMES = ("clang", "clang-19", "clang-18", "clang-17", "clang-16", "clang-15")
OBJCOPY_NAMES = ("llvm-objcopy", "llvm-objcopy-19", "llvm-objcopy-18",
                 "llvm-objcopy-17", "llvm-objcopy-16")
NM_NAMES = ("llvm-nm", "nm")


# --- toolchain discovery ---------------------------------------------------
def find_tool(names, explicit=None, prefix=""):
    """Resolve one tool. `explicit` wins; then an exact path; then $PATH."""
    if explicit:
        return explicit if (Path(explicit).exists() or shutil.which(explicit)) else None
    if not prefix and os.name == "nt":
        roots = [REPO / "toolchain" / "bin",
                 REPO / "dist" / "CKI-18.1.3-win64" / "toolchain" / "bin"]
        if getattr(sys, "frozen", False):
            roots.insert(0, Path(sys.executable).resolve().parent / "toolchain" / "bin")
        for root in roots:
            for name in names:
                candidate = root / (name if name.endswith(".exe") else name + ".exe")
                if candidate.is_file():
                    return str(candidate)
    for n in names:
        cand = prefix + n if prefix else n
        if "/" in cand or os.sep in cand:
            if Path(cand).exists():
                return cand
        else:
            found = shutil.which(cand)
            if found:
                return found
    return None


def pick_toolchain(a):
    """Return (kind, tools dict, missing names list)."""
    kinds = ["clang", "gnu"] if a.toolchain == "auto" else [a.toolchain]
    first_missing = None
    for kind in kinds:
        if kind == "clang":
            tools = {
                "cc": find_tool(CLANG_NAMES, a.clang),
                "objcopy": find_tool(OBJCOPY_NAMES, a.llvm_objcopy),
                "nm": find_tool(NM_NAMES, a.nm),
            }
            wanted = (("cc", "clang"), ("objcopy", "llvm-objcopy"), ("nm", "nm"))
            missing = [label for key, label in wanted if not tools[key]]
        else:
            prefix = a.toolchain_prefix or os.environ.get("CKI_ARM_PREFIX") or "arm-none-eabi-"
            tools = {
                "cc": find_tool(["gcc"], None, prefix),
                "objcopy": find_tool(["objcopy"], None, prefix),
                "nm": find_tool(["nm"], None, prefix),
            }
            missing = [prefix + label
                       for key, label in (("cc", "gcc"), ("objcopy", "objcopy"), ("nm", "nm"))
                       if not tools[key]]
        if not missing:
            return kind, tools, []
        if first_missing is None:
            first_missing = missing
    return kinds[-1], {}, first_missing or []


def compile_flags(kind):
    common = ["-mcpu=arm7tdmi", "-mthumb", "-Os", "-ffreestanding", "-fno-builtin",
              "-fno-pic", "-nostdlib"]
    if kind == "clang":
        return ["--target=arm-none-eabi", "-fuse-ld=lld"] + common
    # GNU needs one extra flag. gcc wraps every `__asm__` block in `.syntax
    # divided`, and the naked write stub is `adds r1,r6,#0` - a three-operand
    # form that is only accepted in unified Thumb syntax, so the assembler
    # rejects it ("instruction not supported in Thumb16 mode"). Switching gcc to
    # unified syntax for inline asm fixes it, and the encoding does not change:
    # measured 0x1C31 both from gcc+this flag and from the clang-built drop.
    # See docs/TOOLCHAIN.md.
    return common + ["-masm-syntax-unified"]


# --- pipeline stages -------------------------------------------------------
def refuse(msg):
    """Abort with exit code 2: nothing has been written and nothing will be."""
    sys.stderr.write(msg.rstrip() + "\n")
    raise SystemExit(2)


def reject(msg):
    """Abort with exit code 3: the ROM was identified, and it is out of scope.

    Exit 2 means the resolver could not place its hooks and might learn to. Exit 3
    means the identification succeeded and proved this build is not a candidate.
    docs/MATRIX.md Sec.2.
    """
    sys.stderr.write(msg.rstrip() + "\n")
    raise SystemExit(3)


def derive_draw_text_entry(rom, r):
    """First internal callee in the naming-screen neighbourhood of GetChar.

    The stock-mode redraw routine. Only used to redraw after a stock write.
    """
    cs = []
    for q in range(r["getchar"], min(r["getchar"] + 0x90, len(rom) - 4), 2):
        v = decode_thumb_bl(rom, q)
        if v is not None and BASE <= (v & ~1) < BASE + len(rom):
            cs.append(v & ~1)
    if not cs:
        refuse("DrawTextEntry resolver: no internal callee near GetChar")
    return min(cs, key=lambda v: abs((v - BASE) - r["getchar"])) | 1


def _is_tailcall_thunk(rom, fstart, probe=8):
    """True for an out-of-line `push {lr}; bl X; pop {rN}; bx rN` thunk.

    Modern GCC routinely emits such a thunk *next to* the inlined call it really
    executes, so one callee can end up with two BL sites in the same object file.
    """
    if int.from_bytes(rom[fstart:fstart + 2], "little") != 0xB500:
        return False                       # not exactly `push {lr}`
    nbl = 0
    for k in range(2, probe * 2, 2):
        q = fstart + k
        if q + 4 > len(rom):
            break
        hw = int.from_bytes(rom[q:q + 2], "little")
        if (hw & 0xF800) == 0xF000:
            nbl += 1
        if (hw & 0xFF00) == 0xBC00:        # pop {...}
            nxt = int.from_bytes(rom[q + 2:q + 4], "little")
            if (nxt & 0xFF87) == 0x4700:   # bx rN
                return nbl == 1
    return False


def pick_frame_site(rom, r):
    """Return the *live* `BL HandleKeyboardEvent` site, or refuse.

    `resolve_modern` picks the call site nearest its function start. On the
    validated host that rule picks the wrong one of two sites: the real per-frame
    call sits at +0x1c inside the naming screen's state dispatcher (the inlined
    MainState_HandleInput), while a dead out-of-line thunk's call sits at +0x02.
    Patching the thunk means the per-frame hook never executes - measured on the
    host: the L/R page change, the SELECT unlock and the stock-UI hide were all
    dead code.

    So: a site inside a tail-call thunk is only dead if nothing calls *that
    thunk*. On the validated host the thunk has no caller at all, so dropping it
    leaves the real site. 格查尔 Alpha8v2 is the mirror image: its only BL to
    HandleKeyboardEvent sits in a thunk that *does* have a caller (the state
    dispatcher calls the thunk, the thunk forwards to the handler), so patching
    it is correct - dropping it would leave nothing and refuse a good host.

    Keep a thunk site when the thunk itself is called; if exactly one candidate
    is left, that is the answer; if several are left, keep the resolver's
    ordering when it is among them, otherwise refuse rather than guess.
    """
    target = (BASE + r["handle"]) & ~1
    sites = []
    for q in range(0, len(rom) - 4, 2):
        v = decode_thumb_bl(rom, q)
        if v is not None and (v & ~1) == target:
            sites.append(q)
    if not sites:
        refuse("frame-site resolver: no BL to HandleKeyboardEvent")

    def fstart(pos):
        for q in range(pos & ~1, max(-1, pos - 0x300), -2):
            if (int.from_bytes(rom[q:q + 2], "little") & 0xFE00) == 0xB400:
                return q
        return None

    def reachable(s):
        f = fstart(s)
        if f is None:
            return False
        if not _is_tailcall_thunk(rom, f):
            return True
        return bool(callers(rom, BASE + f))   # a called thunk is live

    live = [s for s in sites if reachable(s)]
    if len(live) == 1:
        return live[0]
    if r["lr_frame"] in live:
        return r["lr_frame"]
    refuse(f"frame-site resolver ambiguous: sites {[hex(s) for s in sites]}, "
           f"non-thunk {[hex(s) for s in live]}")


def literal_pool_targets(rom):
    """value -> [offset of the literal word] for ROM pointers a `ldr rX,[pc,#imm]` loads.

    Thumb-1 pc-relative load is `0x48xx..0x4Fxx`; its literal sits at
    `((q+4)&~3) + (h & 0xFF)*4`, which is always 4-aligned. Scanning for the
    eight possible high bytes and checking only those offsets is ~256x cheaper
    than decoding every 2-byte offset. This is what turns a raw "some 4-byte
    window happens to contain an in-range value" test (which fires ~once per
    1500 words on pure noise) into a real reference census.
    """
    needles = [bytes([hb]) for hb in range(0x48, 0x50)]
    out = {}
    for needle in needles:
        p = rom.find(needle)
        while p >= 0:
            q = p - 1
            if q >= 0 and (q & 1) == 0:
                lit = ((q + 4) & ~3) + rom[q] * 4
                if lit + 4 <= len(rom):
                    v = int.from_bytes(rom[lit:lit + 4], 'little')
                    if BASE <= v < BASE + len(rom):
                        out.setdefault(v, []).append(lit)
            p = rom.find(needle, p + 1)
    return out


def pointer_refs_into(keys, targets, start, end):
    """Literal-pool load offsets whose loaded value lies in [start,end)."""
    lo, hi = BASE + start, BASE + end
    i, j = bisect.bisect_left(keys, lo), bisect.bisect_left(keys, hi)
    out = []
    for v in keys[i:j]:
        out.extend(targets[v])
    return sorted(out)


def find_free(rom, need=NEED, anchor=0, strict=True, bl_sites=None,
              bl_range=BL_RANGE):
    """Smallest sufficient uniform 0x00/0xFF run nearest the anchor.

    Hardened, and the range check matters: the payload is reached from the hook
    sites with a Thumb-1 `BL`, which only reaches +-4 MiB. `anchor` is the
    handler *table*, a data structure, so a run can be nearest the anchor and
    still be far outside BL range of the code that has to call the payload.
    格查尔 Alpha8v2 is exactly that: its only 26 KB run sits 16.4 MiB from the
    per-frame site, and 1.0 used to die deep in `thumb_bl` with a bare
    "Thumb-1 BL out of range". Now it is a named refusal. (The validated host
    uses 0x3849C2 of the 0x400000 reach, so the limit keeps ~256 KB of slack.)

    The other half of the hardening: a run that is entirely 0xFF is dropped when
    a literal pool actually loads a pointer into it, because that is the shape of
    a *live* region that merely happens to read as erased bytes. (A uniform 0x00
    run is left alone: an all-zero run large enough for the payload is practically
    never live, and applying the same census to it would be dominated by the
    noise floor - see docs/HOOKS.md Sec.5.)
    """
    lo = max(0, anchor - SEARCH_SPAN)
    hi = min(len(rom), anchor + SEARCH_SPAN)
    runs = []
    i = lo
    while i < hi:
        b = rom[i]
        if b not in (0, 255):
            i += 1
            continue
        j = i + 1
        while j < hi and rom[j] == b:
            j += 1
        a = (i + 3) & ~3
        if j - a >= need:
            runs.append((a, j, b, j - a))
        i = j
    if not runs:
        refuse("free-space resolver: no uniform 0x00/0xFF run of "
               f"{need} bytes within {SEARCH_SPAN:#x} of {anchor:#x}")
    targets = literal_pool_targets(rom)
    keys = sorted(targets)
    enriched = []
    for a, e, fill, size in runs:
        refs = pointer_refs_into(keys, targets, a, e)
        enriched.append((a, e, fill, size, refs))
    if strict:
        kept = [x for x in enriched if not (x[2] == 255 and x[4])]
        if not kept:
            refuse("free-space resolver: every uniform run big enough is an "
                   "erased-looking 0xFF region a literal pool still points into "
                   "(live data): "
                   + "; ".join(f"{x[0]:#x}..{x[1]:#x} refs={[hex(o) for o in x[4]]}"
                               for x in enriched))
        enriched = kept
    far = False
    if bl_sites:
        def reachable(a):
            lo_t, hi_t = BASE + a, BASE + a + need
            return all(abs((BASE + s) - lo_t) <= bl_range
                       and abs((BASE + s) - hi_t) <= bl_range for s in bl_sites)
        kept = [x for x in enriched if reachable(x[0])]
        if not kept:
            # A BL cannot reach the payload, but a BL can reach an 8-byte absolute
            # jump that reaches the payload. Keeping the far run here and letting
            # the caller spend a gateway slot per hook site is what makes a host
            # whose only large hole is 17 MB away (格查尔 Alpha8v2, rogue_zh) an
            # injectable host instead of a refusal.
            kept = enriched
            far = True
        enriched = kept
    enriched.sort(key=lambda x: (x[3], abs(x[0] - anchor), x[0]))
    a, e, fill, size, refs = enriched[0]
    return {"start": a, "end": e, "fill": fill, "size": size, "far": far,
            "literal_pool_refs": [hex(o) for o in refs],
            "candidates": [{"start": c0, "end": c1, "fill": cf, "size": cs,
                            "literal_pool_refs": [hex(o) for o in cr]}
                           for c0, c1, cf, cs, cr in enriched]}


def find_gateway(rom, sites, count, span=SEARCH_SPAN, bl_range=BL_RANGE):
    """`count` 4-aligned 8-byte slots reachable by BL from every site in `sites`.

    Only used when the payload itself is out of Thumb-1 BL reach. A slot holds
    `ldr r3,[pc,#0] / bx r3 / .word target`, which is an absolute jump and so has
    no range limit - and because it is a *jump*, not a second BL, LR survives it
    and the payload's own `bx lr` still returns to the instruction after the hook.
    Small holes like this exist on hosts where a 21 KB hole does not.
    """
    anchor = sites[0]
    lo = max(0, anchor - span)
    hi = min(len(rom), anchor + span)
    need = count * 8
    targets = literal_pool_targets(rom)
    keys = sorted(targets)
    runs = []
    i = lo
    while i < hi:
        b = rom[i]
        if b not in (0, 255):
            i += 1
            continue
        j = i + 1
        while j < hi and rom[j] == b:
            j += 1
        a = (i + 3) & ~3
        ok = j - a >= need and all(
            abs((BASE + s) - (BASE + a)) <= bl_range
            and abs((BASE + s) - (BASE + a + need)) <= bl_range for s in sites)
        if ok and not (b == 255 and pointer_refs_into(keys, targets, a, j)):
            runs.append((a, j, b, j - a))
        i = j
    if not runs:
        refuse("gateway resolver: payload is out of Thumb-1 BL range and no uniform "
               f"{need}-byte slot exists within {bl_range:#x} of the hook sites "
               f"{[hex(s) for s in sites]}")
    runs.sort(key=lambda x: (x[3], abs(x[0] - anchor), x[0]))
    a, e, b, sz = runs[0]
    return {"start": a, "end": a + need, "fill": b, "size": need, "run_size": sz,
            "slots": [hex(a + 8 * i) for i in range(count)]}


def precheck(rom, r, ext, gm, draw, free, blob_len):
    """Validate the resolved sites against each other before writing anything.

    This is not a fingerprint check - 1.0 deliberately has no ROM-specific
    original-byte table. It is an internal-consistency check over independently
    derived facts, which is what catches a resolver that locked onto the wrong
    code island.
    """
    checks = []
    problems = []

    def add(name, ok, detail):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
        if not ok:
            problems.append(f"{name}: {detail}")

    base_hi = BASE + len(rom)

    # 1. every claimed function entry starts with a Thumb PUSH prologue
    for f in PROLOGUE_FIELDS:
        off = r[f]
        h = int.from_bytes(rom[off:off + 2], "little")
        add(f"{f}_is_function_entry", (h & 0xFE00) == 0xB400,
            f"{f} @ {off:#x} first halfword {h:#06x} "
            f"({'push' if (h & 0xFE00) == 0xB400 else 'not a PUSH prologue'})")

    # 2. one code island.
    #    `handle` is deliberately excluded. Its own binding is verified by BL target
    #    (check 5: the frame site calls exactly it) and by prologue (check 1), so
    #    requiring it to also be *near* the handlers asks a second question that is not
    #    about whether the resolver locked onto the right code island - and on
    #    astral_emerald that second question is the one that fails: its frame hook calls
    #    a shared routine 0xC8F48 past the naming screen, while every remaining site
    #    sits within 0x3000 of the others.
    offs = [r[f] for f in PROLOGUE_FIELDS if f != "handle"] + [r["lr_frame"]]
    span = max(offs) - min(offs)
    add("single_code_island", span <= ISLAND_SPAN,
        f"span {span:#x} over character/page/backspace/ok/delete/getchar/flash/lr_frame "
        f"(limit {ISLAND_SPAN:#x}); handle excluded - checks 1 and 5 bind it directly")
    # 3. handler table entries are Thumb pointers into this ROM
    tab = r["handler_table"]
    vals = [int.from_bytes(rom[tab + i:tab + i + 4], "little") for i in range(0, 16, 4)]
    bad = [hex(v) for v in vals if not (v & 1 and BASE <= (v & ~1) < base_hi)]
    add("handler_table_is_thumb_pointers", not bad,
        f"table @ {tab:#x} -> {[hex(v) for v in vals]}" if not bad else f"non-code entries {bad}")

    # 4. the table really dispatches to the resolved Character / Page handlers.
    #    This is what the injector overwrites, so the overwrite is only safe if
    #    the two entries it replaces are the two handlers the resolver named.
    ok = vals[0] == ((BASE + r["character"]) | 1) and vals[1] == ((BASE + r["page"]) | 1)
    add("handler_table_matches_resolved_handlers", ok,
        f"table[0]={hex(vals[0])} vs character={hex((BASE + r['character']) | 1)}, "
        f"table[1]={hex(vals[1])} vs page={hex((BASE + r['page']) | 1)}")

    # 5. the frame hook site is a BL to the resolved HandleKeyboardEvent
    bl = decode_thumb_bl(rom, r["lr_frame"])
    add("frame_site_calls_handle_event", bl is not None and (bl & ~1) == BASE + r["handle"],
        f"lr_frame {r['lr_frame']:#x} -> {hex(bl) if bl else None}, "
        f"handle={hex(BASE + r['handle'])}")

    # 6. the delete hook site is a function entry, not the middle of a routine
    dq = r["delete"]
    h = int.from_bytes(rom[dq:dq + 2], "little")
    add("delete_site_is_function_entry", (h & 0xFE00) == 0xB400,
        f"delete @ {dq:#x} first halfword {h:#06x}")

    # 7. engine APIs are distinct, in range, and thumb
    seen = {}
    for k, v in ext.items():
        if not v:
            # 0 is the documented answer to "this host has no function whose callers
            # pass the sound API's argument fingerprint" - see
            # engine_api_resolver._playse - and the adapter compiles its click sounds
            # away. It is not an address, so range and aliasing do not apply to it.
            add(f"external_{k}_absent", True, f"{k} = 0, patch is silent on this host")
            continue
        if v in seen:
            add(f"external_{k}_distinct", False, f"{k} aliases {seen[v]} at {v:#x}")
        else:
            seen[v] = k
            add(f"external_{k}_in_range", bool(v & 1) and BASE <= (v & ~1) < base_hi,
                f"{k} = {v:#x}")

    # 7b. the three window APIs share one object file, so they must sit in one
    #     block. Without this, a wrong-but-plausible engine-API resolution passes
    #     every other check; see docs/MATRIX.md.
    win = [ext["FillWindowPixelBuffer"], ext["PutWindowTilemap"], ext["CopyWindowToVram"]]
    span = max(win) - min(win)
    rival = [] if span <= WINDOW_BLOCK_SPAN else window_block_rival(rom, _sweep_bls(rom), *win)
    add("window_api_same_block", span <= WINDOW_BLOCK_SPAN or not rival,
        f"Fill/Put/Copy span {span:#x} (limit {WINDOW_BLOCK_SPAN:#x}); "
        f"gflib/window.o .text measures ~0x1154-0x13e8"
        + (f", and nearer fill-shaped candidates {['%#x' % t for t in rival]} exist"
           if rival else
           ", but no fill-shaped function lies inside the Put/Copy block, so proximity "
           "offered nothing nearer than the uniquely-bursting trio"))

    # 8. gMain looks like the Emerald Main ABI.
    #    `newKeysRaw == gMain + 0x2A` is how the resolver *derives* newKeysRaw, so
    #    asserting it here can never fail - it was a dead check until bubble128_cn,
    #    whose adapter read a constant IWRAM word as newKeysRaw because the resolver
    #    had picked the exception-vector area at 0x03000000. What is actually
    #    checkable is the evidence the resolver scored on: a real Main struct is
    #    named at +0x38, the field the kernel walks for its task queue. Measured over
    #    all 19 archived hosts and astral: every correct pick has 1-7 direct +0x38
    #    literals, and the one wrong pick - the vector area - has none.
    #    heldKeys(+0x2C) is reported but does not gate. Whether that literal ever
    #    materialises is an artefact of immediate folding, exactly as
    #    gmain_resolver says when it releases its own gate on it: Thumb `ldrh` folds
    #    offsets up to 0x3E inline, so a build that reaches newKeys straight off the
    #    base literal cannot produce one. astral_emerald is that build - 1187 base
    #    refs (above every archived host's 543-1021) and 7 +0x38 refs (also above),
    #    with heldKeys exactly 0. Gating on it would reject the host for the way its
    #    compiler chose to encode a load.
    _gmc = (gm.get("candidates") or [{}])[0]
    add("gmain_newkeys_raw",
        gm["newKeysRaw"] == gm["gMain"] + 0x2A and _gmc.get("plus38_refs", 0) >= 1,
        f"gMain {gm['gMain']:#x} newKeysRaw {gm['newKeysRaw']:#x} "
        f"plus38(+0x38) refs={_gmc.get('plus38_refs')} "
        f"heldKeys(+0x2C) refs={_gmc.get('heldKeys_refs')} base refs={_gmc.get('refs')}")

    # 9. free run is uniform and big enough, payload fits.
    #    Skipped when the caller has no free run yet (diagnostic mode).
    if free is not None:
        hi = min(len(rom), free["start"] + NEED)
        uniform = (hi - free["start"]) >= NEED and all(
            rom[i] == rom[free["start"]] for i in range(free["start"], hi))
        add("free_run_uniform", uniform and free["start"] % 4 == 0,
            f"run {free['start']:#x}..{free['end']:#x} fill {rom[free['start']]:#04x} "
            f"size {free['size']:#x} align4={free['start'] % 4 == 0}")
        # blob_len is the reference payload size at this stage: the adapter has
        # not been built yet, so the exact size is unknown. The real run
        # overwrites this detail with len(blob) once the blob exists.
        add("payload_fits", blob_len <= free["size"],
            f"payload estimate {blob_len} bytes vs run {free['size']} bytes "
            f"at {free['start']:#x}")

    # 10. the stock redraw routine is a plausible Thumb target
    add("draw_text_entry_thumb", bool(draw & 1) and BASE <= (draw & ~1) < base_hi,
        f"draw_text_entry {draw:#x}")

    return checks, problems


def safe_flash_target(resolver, draw_text):
    """An inlined flash can make the legacy heuristic select DrawTextEntry."""
    target = (BASE + resolver["flash"]) | 1
    return 0 if (target & ~1) == (draw_text & ~1) else target


def keyboard_defines(windows, enable_label=True):
    """Geometry belongs to the keyboard probe, not the optional button label."""
    if windows is None:
        return {"CK_KB_TILEBASE": 0, "CK_KB_TILEBASE2": 0, "CK_KB_WINW": 1,
                "CK_KB_BG1": 1, "CK_KB_BG2": 2, "CK_ENABLE_LABEL": 0}
    return {
        "CK_KB_TILEBASE": windows["win1"]["base_block"],
        "CK_KB_TILEBASE2": windows["win2"]["base_block"],
        "CK_KB_WINW": windows["win1"]["width"],
        "CK_KB_BG1": windows["win1"]["bg"],
        "CK_KB_BG2": windows["win2"]["bg"],
        "CK_ENABLE_LABEL": int(bool(enable_label)),
    }


def validate_output_paths(input_path, output_path, report_path):
    """Neither the ROM nor its report may overwrite the original input."""
    paths = [Path(p).resolve() for p in (input_path, output_path, report_path)]
    if len(set(paths)) != 3:
        raise ValueError("input ROM, output ROM and report must be three distinct files")
    existing = [p for p in paths if p.exists()]
    if any(a.samefile(b) for index, a in enumerate(existing) for b in existing[index+1:]):
        raise ValueError("input, output and report must not refer to the same file")


def atomic_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".cki-", delete=False) as file:
            temporary = Path(file.name)
            file.write(data)
        os.replace(temporary, path)
    finally:
        if temporary is not None and temporary.exists():
            temporary.unlink()


def main():
    ap = argparse.ArgumentParser(description="CKI 1.0 GBA ROM keyboard injector")
    ap.add_argument("rom")
    ap.add_argument("-o", "--output", help="patched ROM path (default <rom>_cki.gba)")
    ap.add_argument("--adapter", default=str(PAYLOAD / "adapter_v10.c"))
    ap.add_argument("--workdir", default=str(REPO / "build"),
                    help="directory for link_v10.ld / adapter_v10.elf / .bin / symbols (default build/)")
    ap.add_argument("--report", help="report path (default <workdir>/report_v10.json)")
    ap.add_argument("--toolchain", choices=("auto", "clang", "gnu"), default="auto",
                    help="compiler backend (default auto: clang+lld, else GNU cross-gcc)")
    ap.add_argument("--clang", help="path to clang")
    ap.add_argument("--llvm-objcopy", help="path to llvm-objcopy")
    ap.add_argument("--nm", help="path to nm")
    ap.add_argument("--toolchain-prefix",
                    help="GNU prefix, e.g. arm-none-eabi- or /opt/x/bin/arm-none-eabi- "
                         "(default: $CKI_ARM_PREFIX or arm-none-eabi-)")
    ap.add_argument("--skip-precheck", action="store_true",
                    help="do not validate the resolved sites before writing")
    ap.add_argument("--oracle-map",
                    help="optional linker map: refuse to patch if the naked resolver "
                         "disagrees with it. Never used as an input - it can only "
                         "tighten the gate. See docs/MATRIX.md.")
    ap.add_argument("--oracle-object", default="src/naming_screen.o",
                    help="object file expected to own the naming-screen code "
                         "(used with --oracle-map)")
    ap.add_argument("--validated-hosts", default=str(REPO / "qa" / "validated_hosts.json"),
                    help="list of input SHA256s that passed every gate "
                         "(default qa/validated_hosts.json)")
    ap.add_argument("--allow-unvalidated", action="store_true",
                    help="patch an input that is neither on the validated-host list "
                         "nor confirmed by --oracle-map. The matrix run shows this "
                         "class of ROM can resolve self-consistently yet still be "
                         "mis-resolved; see docs/MATRIX.md.")
    ap.add_argument("--dry-run", action="store_true",
                    help="resolver + free space + pre-check, then stop before compiling")
    ap.add_argument("--no-cn-label", action="store_true",
                    help="leave the stock page-swap button alone. By default the "
                         "button is re-lettered to 切换 while Chinese mode is on "
                         "(the stock word strip says lower/upper/others, which is "
                         "stale there); see docs/LABEL.md.")
    a = ap.parse_args()

    work = Path(a.workdir).resolve()
    work.mkdir(parents=True, exist_ok=True)

    romp = Path(a.rom).resolve()
    outp = Path(a.output).resolve() if a.output else romp.with_name(romp.stem + "_cki.gba")
    repp = Path(a.report).resolve() if a.report else work / "report_v10.json"
    validate_output_paths(romp, outp, repp)
    original = romp.read_bytes()
    rom = bytearray(original)

    in_sha = hashlib.sha256(original).hexdigest()
    validated = []
    cjk_hosts = set()
    excluded = {}
    vpaths = Path(a.validated_hosts)
    if vpaths.exists():
        ledger = json.loads(vpaths.read_text(encoding="utf-8"))
        validated = [h["sha256"] for h in ledger["hosts"]]
        cjk_hosts = {h["sha256"] for h in ledger["hosts"] if h.get("font_gate") == "entered"}
        excluded = {h["sha256"]: h for h in ledger.get("excluded", [])}

    # --- resolve ----------------------------------------------------------
    # Any ambiguity in the semantic resolver is a hard stop by design: the whole
    # point of 1.0 is that an unrecognised layout must fail loudly rather than
    # be patched on a guess.
    try:
        r = resolve_modern(original)
        gm = resolve_gmain(original)
        draw = derive_draw_text_entry(original, r)
        ext = resolve_engine_apis(original, r, (draw & ~1) - BASE)
        stock_keyboard = resolve_stock_keyboard(original, r, ext)
        if not ext["PlaySE"]:
            # Loud on purpose: a silent naming screen is intended behaviour, not a
            # failure, but the operator has to be able to tell the two apart from the
            # console alone - the patch works, this host just has no sound entry point
            # whose callers pass the sound id space.
            print("WARNING: this ROM has no function whose callers pass the sound API's "
                  "argument fingerprint - patch will be silent (no key/confirm clicks)",
                  file=sys.stderr)
        # The cursor routine the naming screen repositions from every frame. Its
        # call sites are redirected so the selection box tracks the Chinese grid
        # instead of the stock irregular column table; see cursor_resolver.py.
        cur = resolve_cursor(original, anchor=r["handle"], delete=r["delete"],
                             body_end=r["character"], island=ns_island(r))
        # The keyboard windows' own geometry (width + tile base), needed by the
        # Chinese label; see label_resolver.py. A host whose layout does not match
        # simply keeps the plain keyboard - it is a warning, not a hard stop.
        try:
            kb = resolve_keyboard_windows(original)
        except LabelLayoutError as e:
            kb = None
            print(f"WARNING: Chinese label unavailable: {e}", file=sys.stderr)
        # resolve_modern returns the BL site nearest its function start, which on
        # this host is a dead out-of-line thunk. Pick the live site instead; the
        # resolver itself is left untouched so the upstream report stays
        # reproducible.
        _resolver_lr_frame = r["lr_frame"]
        r["lr_frame"] = pick_frame_site(original, r)
    except InterfaceChanged as e:
        # Exit 3, not 2: this ROM was understood, and what was understood is that
        # its naming keyboard is not the stock grid the adapter overlays. No amount
        # of resolver work turns it into a gap.
        known = excluded.get(in_sha)
        extra = "" if known is None else (
            "\nThis host was measured, photographed where the naming screen is "
            "reachable, and excluded on purpose:\n"
            f"  meaning:  {known['reason']}\n"
            f"  evidence: {', '.join(known['evidence'])}\n"
            "  re-check: python tools/record_refusal_evidence.py\n")
        reject(f"input interface changed: {e}{extra}")
    except (RuntimeError, ValueError) as e:
        # Quote what the engine-API layer measured, not just where it threw. "motif
        # unresolved" reads like a resolver gap, when the two absences we can actually
        # prove (no shared sound entry point by argument fingerprint, no window-API
        # co-call topology anywhere in the image) mean the host replaced the engine
        # layer the adapter draws through.
        extra = ""
        if EAPI_INFO.get("playse") is None and "playse" in EAPI_INFO:
            extra += ("\n   no shared sound entry point: 0 functions in this image have a"
                      " dominant r0 literal of SE_SELECT among 400+ call sites")
        if EAPI_INFO.get("trio_count") == 0:
            # Both topology routes have to come up empty before this is a statement
            # about the host: the mutual-triangle test can fail on a build whose every
            # drawing burst uses one order, which is where astral_emerald landed.
            if EAPI_INFO.get("burst_trio_count"):
                extra += (f"\n   window trio from ordered bursts only: "
                          f"{EAPI_INFO['burst_trio_count']} candidate(s)")
            else:
                extra += ("\n   no window-API co-call topology: 0 Fill/Put/Copy triples"
                          " found by mutual adjacency and 0 by ordered bursts"
                          " (the stock naming screen draws through all three)")
        refuse(f"resolver rejected this ROM: {e}{extra}\n"
               "It is not a naming_screen layout the 1.0 semantic resolver can "
               "identify. Refusing to patch.")
    print(f"resolver family {r['family']}  addchar_inlined={r['addchar_inlined']}", file=sys.stderr)
    print(f"naming_screen {hex(r['naming_screen_global'])}  gSprites {hex(r['sprites_global'])}  "
          f"keyboard data {hex(r['keyboard_data'])}  handler table {hex(r['handler_table'])}",
          file=sys.stderr)
    print(f"gMain {hex(gm['gMain'])}  newKeysRaw {hex(gm['newKeysRaw'])}  score {gm['score']}",
          file=sys.stderr)
    print("externals " + " ".join(f"{k}={hex(v)}" for k, v in ext.items()), file=sys.stderr)
    print(f"draw_text_entry {hex(draw)}", file=sys.stderr)
    if r["lr_frame"] != _resolver_lr_frame:
        print(f"frame hook site OVERRIDDEN: resolver said {hex(_resolver_lr_frame)} "
              f"(dead tail-call thunk), using live site {hex(r['lr_frame'])}", file=sys.stderr)
    if cur["sites"]:
        print(f"SetCursorPos {hex(BASE + cur['set_cursor'])}  "
              f"{len(cur['sites'])} BL site(s) {[hex(s) for s in cur['sites']]}", file=sys.stderr)
    else:
        print(f"WARNING: SetCursorPos {hex(BASE + cur['set_cursor'])} has no BL call sites "
              f"(inlined by this host's compiler) - the cursor hook is SKIPPED. "
              f"The selection box will follow the stock irregular column table and can "
              f"sit up to ~17px off the 16px Chinese grid. Input itself is unaffected.",
              file=sys.stderr)

    free = find_free(rom, NEED, r["handler_table"],
                     strict=not getattr(a, "skip_precheck", False),
                     bl_sites=[r["lr_frame"]] + list(cur["sites"]))
    runtime = BASE + free["start"]
    print(f"free run {hex(free['start'])}..{hex(free['end'])} fill {hex(free['fill'])} "
          f"size {hex(free['size'])} ({len(free['candidates'])} candidates)",
          file=sys.stderr)

    # Two slots: one for the per-frame hook, one shared by every cursor hook (they
    # all land on the same payload entry point, so one jump serves them all).
    gw = None
    if free["far"]:
        nslots = 1 + (1 if cur["sites"] else 0)
        gw = find_gateway(rom, [r["lr_frame"]] + list(cur["sites"]), nslots)
        print(f"payload is out of BL range: gateway at {hex(gw['start'])}..{hex(gw['end'])} "
              f"({nslots} slots in a {hex(gw['run_size'])} run)", file=sys.stderr)

    defines = {
        "CK_PRINTKEYS": stock_keyboard,
        "CK_HOST_CJK": int(in_sha in cjk_hosts),
        "CK_KEYBOARD_DATA": BASE + r["keyboard_data"],
        "CK_NS_GLOBAL": r["naming_screen_global"],
        "CK_GSPRITES": r["sprites_global"],
        "CK_ADDTEXT": ext["AddTextPrinterParameterized3"],
        "CK_DRAW_TEXT_ENTRY": draw,
        "CK_FLASH": safe_flash_target(r, draw),
        "CK_HANDLE_EVENT": BASE + r["handle"] | 1,
        "CK_ORIG_CHARACTER": BASE + r["character"] | 1,
        "CK_ORIG_PAGE": BASE + r["page"] | 1,
        "CK_ORIG_BACKSPACE": BASE + r["backspace"] | 1,
        "CK_GMAIN_NEWKEYS_RAW": gm["newKeysRaw"],
        "CK_PLAYSE": ext["PlaySE"],
        "CK_FILLWIN": ext["FillWindowPixelBuffer"],
        "CK_PUTWIN": ext["PutWindowTilemap"],
        "CK_COPYWIN": ext["CopyWindowToVram"],
        "CK_SETCURSOR": BASE + cur["set_cursor"] | 1,
    }
    defines.update(keyboard_defines(kb, not a.no_cn_label))
    if kb is not None:
        print(f"keyboard windows 0x{kb['offset']:x}: baseBlock "
              f"{kb['win1']['base_block']:#x}/{kb['win2']['base_block']:#x} "
              f"width {kb['win1']['width']}", file=sys.stderr)
    # The adapter blob has to be built before the pre-check can state its size,
    # but the pre-check has to run before anything is written. --dry-run uses the
    # reference payload size so the free-run capacity check stays meaningful.
    reference_size = 17434

    checks = None
    if not a.skip_precheck:
        checks, problems = precheck(original, r, ext, gm, draw, free, reference_size)
        if problems:
            for p in problems:
                sys.stderr.write(f"  - {p}\n")
            refuse("resolved-site pre-check FAILED (see above). Refusing to patch: the "
                   "resolver did not land on a self-consistent naming_screen layout.")
        print(f"resolved-site pre-check ok ({sum(c['ok'] for c in checks)}/{len(checks)} checks)",
              file=sys.stderr)

    oracle = None
    if a.oracle_map:
        symbols, sections = parse_map(a.oracle_map)
        if not symbols:
            raise SystemExit(f"no symbols parsed from {a.oracle_map}")
        rows, oracle_problems = oracle_checks(symbols, sections, r, gm, ext,
                                             a.oracle_object, a.oracle_map)
        oracle = {"map": str(Path(a.oracle_map).resolve()), "expected_object": a.oracle_object,
                  "agree": len(rows) - len(oracle_problems), "total": len(rows), "rows": rows}
        if oracle_problems:
            for p in oracle_problems:
                sys.stderr.write(f"  - {p}\n")
            refuse("linker-map oracle DISAGREES with the naked resolver (see above). "
                   "Refusing to patch: the naked resolver is not validated on this "
                   "build. See docs/MATRIX.md.")
        print(f"linker-map oracle agrees ({oracle['agree']}/{oracle['total']})", file=sys.stderr)

    # A self-consistent resolution is not the same as a correct one: on the
    # agbcc-built pokeemerald-rogue ROM every naming-screen site was right while
    # four of the five engine APIs were wrong (docs/MATRIX.md). So gate the
    # *patch* on an independently validated input. --dry-run stays unrestricted
    # so the pipeline can always be inspected.
    host_status = ("validated" if in_sha in validated else
                   "oracle-confirmed" if oracle is not None else "unvalidated")
    print(f"input host status: {host_status}", file=sys.stderr)
    if not a.dry_run and host_status == "unvalidated" and not a.allow_unvalidated:
        # "not on the list" reads like "nobody looked at this ROM". When it was looked at
        # and deliberately excluded, the refusal has to carry the reason and the evidence.
        known = excluded.get(in_sha)
        extra = "" if known is None else (
            "\nThis input was put through the QA gates and excluded on purpose:\n"
            f"  seen:     {known['why']}\n"
            f"  meaning:  {known['reason']}\n"
            f"  evidence: {', '.join(known['evidence'])}\n")
        refuse(f"input {in_sha} is not on the validated-host list ({vpaths}) and no "
               f"--oracle-map confirmed it.{extra}\n"
               "The resolver's naming-screen sites and globals have been right on every "
               "build probed so far, but its engine-API heuristics are only demonstrated "
               "on modern-gcc output; docs/MATRIX.md has the measurements.\n"
               "Pass --oracle-map build.map if you have the linker map, or "
               "--allow-unvalidated to patch anyway and verify in mGBA yourself.")

    (work / "link_v10.ld").write_text(
        f"ENTRY(ck_page_handler)\n"
        f"SECTIONS {{ . = {runtime:#x}; .text : {{ KEEP(*(.text.entry)) "
        f"KEEP(*(.text.delete)) KEEP(*(.text.lr)) KEEP(*(.text.cursor)) "
        f"KEEP(*(.text.write)) *(.text*) *(.rodata*) }} "
        f"/DISCARD/ : {{ *(.comment*) *(.ARM.attributes*) }} }}\n",
        encoding="utf-8")

    cmd_tail = [f"-D{k}={v:#x}" for k, v in defines.items()]

    if a.dry_run:
        print(json.dumps({
            "dry_run": True,
            "resolver": {k: (hex(v) if isinstance(v, int) else v) for k, v in r.items()},
            "gmain": gm,
            "externals": {k: hex(v) for k, v in ext.items()},
            "draw_text_entry": hex(draw),
            "stock_keyboard_printer": hex(stock_keyboard),
            "defines": cmd_tail,
            "payload_offset": hex(free["start"]),
            "payload_runtime": hex(runtime),
            "free_space": {k: (hex(v) if isinstance(v, int) else v)
                           for k, v in free.items() if k != "candidates"},
            "precheck": checks,
            "oracle": oracle,
        }, indent=2))
        return

    kind, tools, missing = pick_toolchain(a)
    if missing:
        if kind == "clang":
            hint = ("The validated route wants clang + llvm-objcopy + nm: pass "
                    "--clang/--llvm-objcopy/--nm, or use --toolchain gnu with "
                    "--toolchain-prefix / $CKI_ARM_PREFIX.")
        else:
            hint = ("Point --toolchain-prefix or $CKI_ARM_PREFIX at your "
                    "arm-none-eabi- install, or use the validated clang route "
                    "with --clang/--llvm-objcopy/--nm.")
        raise SystemExit(
            "ARM toolchain not found: " + ", ".join(missing) + "\n" + hint + "\n"
            "Use --dry-run to exercise the resolver stages with no compiler.")

    cc, oc, nm = tools["cc"], tools["objcopy"], tools["nm"]
    elf = work / "adapter_v10.elf"
    blobp = work / "adapter_v10.bin"
    cmd = ([cc] + compile_flags(kind) + cmd_tail +
           ["-Wl,-T," + str(work / "link_v10.ld"), "-Wl,--gc-sections",
            "-o", str(elf), str(Path(a.adapter).resolve())])
    (work / "compile_cmd.txt").write_text(" ".join(cmd) + "\n", encoding="utf-8")
    print(f"toolchain {kind}: {' '.join(cmd)}", file=sys.stderr)
    subprocess.run(cmd, check=True)
    subprocess.run([oc, "-O", "binary", str(elf), str(blobp)], check=True)
    syms = subprocess.check_output([nm, "-n", str(elf)], text=True)
    (work / "symbols.txt").write_text(syms, encoding="utf-8")

    def asy(name):
        m = re.search(r"^([0-9a-fA-F]+) [Tt] " + re.escape(name) + r"$", syms, re.M)
        if not m:
            raise SystemExit("missing adapter symbol " + name)
        return int(m.group(1), 16) | 1

    blob = blobp.read_bytes()
    # The run was chosen from NEED, not from this blob. Requiring the real size
    # here is what keeps an under-estimated NEED from writing past live bytes:
    # free["size"] is bounded by the ROM, so this also covers the ROM-end case.
    if len(blob) > free["size"]:
        raise SystemExit(
            f"payload ({len(blob)} B) does not fit the free run at "
            f"{free['start']:#x} ({free['size']} B, {len(blob) - free['size']} B short). "
            f"Re-run after raising PAYLOAD_SLACK (injector/inject_v10.py), or place "
            f"the payload in pieces.")
    # The pre-check ran before the adapter existed, so its capacity row carries
    # the reference size. Replace it with the real one so the report never
    # states a payload size that disagrees with payload.size below.
    if checks:
        for c in checks:
            if c["check"] == "payload_fits":
                c["detail"] = f"payload {len(blob)} bytes at {free['start']:#x}"
    rom[free["start"]:free["start"] + len(blob)] = blob

    # -- key-handler table: redirect Character and Page, leave Backspace and OK
    #    stock so the untouched stock Backspace path still reaches DeleteTextCharacter.
    tab = r["handler_table"]
    old_tab = bytes(rom[tab:tab + 16])
    vals = [asy("ck_character_handler"), asy("ck_page_handler"),
            int.from_bytes(old_tab[8:12], "little"), int.from_bytes(old_tab[12:16], "little")]
    rom[tab:tab + 16] = b"".join(struct.pack("<I", v) for v in vals)

    # -- logical delete routine: absolute jump, preserving stock Backspace semantics
    dq = r["delete"]
    old_delete = bytes(rom[dq:dq + 8])
    rom[dq:dq + 8] = jump(asy("ck_delete_handler") & ~1)

    # -- Task_NamingScreen's BL to HandleKeyboardEvent -> wrapper that forwards
    #    to the stock handler while unlocked
    q = r["lr_frame"]
    old_frame = bytes(rom[q:q + 4])
    frame_target = asy("ck_handle_frame") & ~1
    if gw is not None:
        rom[gw["start"]:gw["start"] + 8] = jump(frame_target)
        frame_target = BASE + gw["start"]
    rom[q:q + 4] = thumb_bl(BASE + q, frame_target)

    # -- cursor: every `BL SetCursorPos` site is redirected to ck_cursor_hook. The
    #    naming screen repositions the cursor sprite from its own irregular column
    #    table on every frame, after the per-frame hook above, so the box can only
    #    be made to track the Chinese grid from inside that routine. Each site is a
    #    4-byte BL replaced by another 4-byte BL - nothing is displaced, and the
    #    stock routine stays intact for the unlocked forward-call.
    cursor_hook = asy("ck_cursor_hook")
    if gw is not None and cur["sites"]:
        rom[gw["start"] + 8:gw["start"] + 16] = jump(cursor_hook)
        cursor_hook = BASE + gw["start"] + 8
    cursor_hooks = {}
    for i, site in enumerate(cur["sites"]):
        old_cursor = bytes(rom[site:site + 4])
        rom[site:site + 4] = thumb_bl(BASE + site, cursor_hook & ~1)
        cursor_hooks[f"cursor_{i}"] = {"offset": hex(site), "old": old_cursor.hex(),
                                       "target": hex(cursor_hook)}

    atomic_write(outp, rom)

    rep = {
        # `format` is a *data* identifier, kept stable so reports written by the
        # upstream drop remain readable by tools/reconstruct_preinject.py.
        # `project_version` is this project's own release number.
        "format": "CKI-V390-NAKED-ROM-SEMANTIC-API",
        "project_version": "1.0",
        "release_pass": False,
        "note": "No map/sym input. Engine APIs resolved from NamingScreen call semantics. "
                "The generated ROM still needs a game-level check on the target host.",
        "input": str(romp),
        "output": str(outp),
        "input_sha256": hashlib.sha256(original).hexdigest(),
        "output_sha256": hashlib.sha256(rom).hexdigest(),
        "resolver": {k: (hex(v) if isinstance(v, int) else v) for k, v in r.items()},
        "gmain": gm,
        "externals": {k: hex(v) for k, v in ext.items()},
        "draw_text_entry": hex(draw),
        "stock_keyboard_printer": hex(stock_keyboard),
        "cursor": {"table": hex(cur["table"]), "set_cursor": hex(BASE + cur["set_cursor"]),
                   "sites": [hex(s) for s in cur["sites"]]},
        "defines": cmd_tail,
        "toolchain": {"kind": kind, "cc": cc, "objcopy": oc, "nm": nm, "command": cmd},
        "payload": {"offset": hex(free["start"]), "runtime": hex(runtime), "size": len(blob),
                    "out_of_bl_range": bool(free["far"]),
                    "gateway": None if gw is None else
                    {"offset": hex(gw["start"]), "slots": len(gw["slots"]),
                     "run_size": hex(gw["run_size"])}},
        "free_space": {k: (hex(v) if isinstance(v, int) else v)
                       for k, v in free.items() if k != "candidates"},
        "handler_table": {"offset": hex(tab), "old": old_tab.hex(),
                          "new": [hex(v) for v in vals]},
        "delete_hook": {"offset": hex(dq), "old": old_delete.hex(),
                        "target": hex(asy("ck_delete_handler"))},
        "frame_hook": {"offset": hex(q), "old": old_frame.hex(),
                       "target": hex(asy("ck_handle_frame"))},
        # tools/reconstruct_preinject.py already understands a `hooks` mapping; the
        # cursor sites live here rather than as a top-level key so they are undone
        # by the existing reconstruction path.
        "hooks": cursor_hooks,
        "precheck": checks,
        "oracle": oracle,
        "host_status": host_status,
    }
    atomic_write(repp, json.dumps(rep, indent=2).encode("utf-8"))
    print(json.dumps(rep, indent=2))


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print(f"CKI could not complete: {exc}", file=sys.stderr)
        raise SystemExit(1)
