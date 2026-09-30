# CKI Release / Calibration Acceptance Standard

A ROM is **not** marked PASS from resolver success alone.

## Gates
1. **Resolver gate** — all required hooks/globals/ABI/free-space resolve uniquely; no ROM-specific absolute-address exception.
2. **Injection gate** — fresh unmodified input ROM is injected successfully; report records input/output SHA256 and selected sites.
3. **Runtime gate** — injected ROM boots in mGBA headless and reaches NamingScreen without crash/corruption.
4. **Behavior gate** — automated input covers Chinese page entry, A double-byte input, B pair delete, R/L page change, 223↔0 wrap, SELECT unlock, Page-Tab unlock, 3-CN boundary/4th rejection, mixed 7-byte input/overflow rejection.
5. **Visual gate (mandatory)** — fresh framebuffer screenshots from the exact candidate ROM are converted and manually inspected. Check: 8×4 grid, frozen 16px-stride geometry, cursor-to-glyph alignment, name-field rendering, no green/tilemap corruption, Chinese/stock transition. Screenshots must ship with the release/checkpoint.

## Status vocabulary
- RESOLVER PASS: gate 1 only. Never implies runtime/visual success.
- RUNTIME PASS: gates 1–4.
- VISUAL PASS: gates 1–5; exact inspected screenshots are named in the report.
- RELEASE PASS: VISUAL PASS on every required regression ROM.

Resolver-only checkpoints therefore intentionally have no visual PASS badge.
