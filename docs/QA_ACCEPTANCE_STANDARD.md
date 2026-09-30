# CKI Release / Calibration Acceptance Standard

A ROM is **not** marked PASS from resolver success alone.

## Gates
1. **Resolver gate** — all required hooks/globals/ABI/free-space resolve uniquely; no ROM-specific absolute-address exception.
2. **Injection gate** — fresh unmodified input ROM is injected successfully; report records input/output SHA256 and selected sites.
3. **Runtime gate** — injected ROM boots in mGBA headless and reaches NamingScreen without crash/corruption.
4. **Behavior gate** — automated input covers Chinese page entry, A double-byte input, B pair delete, R/L page change, 223↔0 wrap, SELECT unlock, Page-Tab unlock, 3-CN boundary/4th rejection, mixed 7-byte input/overflow rejection.
5. **Visual gate (mandatory)** — fresh framebuffer screenshots from the exact candidate ROM are converted and manually inspected. Check: 8×4 grid, frozen 16px-stride geometry, cursor-to-glyph alignment, name-field rendering, no green/tilemap corruption, Chinese/stock transition. Screenshots must ship with the release/checkpoint.

## How gate 4 is executed

Gate 4 is a *list*, so it is only satisfied by a run that reaches every item. Each host
replays the 27-step route (`test_roms/qa_20260926/<stem>/boundary_final_patched/` — that
capture tree is the local evidence store, not part of the published repository; see
`docs/CHANGELOG.md` "版本库", plus the same
route on the unpatched input as control) and must pass `tools/check_boundary_route.py` —
27 assertions whose expected values are derived from `payload/adapter_v10.c`, not from the
screenshots. `qa/validated_hosts.json` imports that same verdict as a promotion condition, so
a host cannot be on the validated list while failing any item here. A route that never reaches
the naming screen is reported as `ROUTE GAP` (the NS pointer at step b01 is outside EWRAM),
which is a gap in the test rig's navigation, not evidence about the adapter — it excludes the
host from the ledger instead of being counted as a behaviour failure.

## Two host classes since the runtime font gate

The gate (`docs/HOOKS.md` §6) decides per host, at the moment the user presses A on the
PAGE cell, whether Chinese mode may open. Acceptance therefore has two shapes, and they
are checked by different rules:

- **entered** — the 27 behavioural assertions above apply unchanged.
- **refused** — Chinese mode must stay off, so the correct behaviour is *indistinguishable
  from the control*: `check_boundary_route.py` asserts patched == control field for field
  on all 27 steps, and skips the entered-host rules. Counting both classes together is how
  a refusal that silently did nothing gets mistaken for a pass, and also how a refusal that
  changed something gets mistaken for a pass, which is why the next line exists.

Frame evidence is a separate audit, run on both capture routes: `tools/check_refusal_pixels.py`
allows a pixel to differ between a refused host and its own control only where the control
itself shows that colour at or within 2 px of that spot in some sampled frame. The radius is
calibrated against a real defect, not chosen to make the numbers green: the archived pre-fix
run (`CK-DELETE-GHOST`, a grey cell where the stock renderer leaves white) still reports
84 novel px at radius 2 and only vanishes at 3, while the fixed build measures 0 on all 18
refused hosts on both routes. Everything the rule tolerates is phase — the gate spends 12–40
frames measuring, so a refused host is sampled that many frames ahead of its control on the
avatar, the ▶ cursor, the PAGE tab's 10-step grey pulse and the slot dash's one-pixel creep
(avatar, cursor, PAGE tab and slot dash all confirmed to follow the identical sequence by a
local probe run). The cost is stated in that
tool's docstring: ink that merely shifts by ≤2 px is invisible to this rule, so it is a
phase/ink discriminator and never a substitute for the human visual gate.

Measured 2026-09-27 on the rebuilt corpus: behaviour gate 25/25 (7 entered, 18 refused);
visual refusal gate 18/18 on `boundary_final` and 18/18 on `run6`; re-injecting all 25
inputs through the shipped `injector/inject_v10.py` with no override reproduces every
published ROM byte for byte. Do not report those as one number.

## Status vocabulary
- RESOLVER PASS: gate 1 only. Never implies runtime/visual success.
- RUNTIME PASS: gates 1–4.
- VISUAL PASS: gates 1–5; exact inspected screenshots are named in the report.
- RELEASE PASS: VISUAL PASS on every required regression ROM.

Resolver-only checkpoints therefore intentionally have no visual PASS badge.
