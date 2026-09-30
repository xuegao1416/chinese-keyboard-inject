# Deliberate deltas between this working tree and the shipped 1.0 package

`dist/CKI-headless-qa-1.0.zip` freezes what left the machine as the 1.0 QA rig, together
with its `SHA256SUMS.txt` (40 entries) and `MANIFEST.txt` (41 files, the manifest itself
excluded). This directory is the *live* source. The `.zip` is a local hand-off artifact and
is not published with the repository (archives are git-ignored), so a clone carries the
deltas below rather than the frozen bytes.

Measured on 2026-09-27, in this directory:

```
sha256sum -c SHA256SUMS.txt   ->  36 OK, 3 mismatches, 1 listed file absent
git ls-files .                ->  57 tracked files, 18 of them not in the manifest
```

| file | state | why |
| --- | --- | --- |
| `src/gba_capture.c` | changed | After the 1.0 package was frozen, `peek` and `peek32` shared one arity check, so every legal `peek32 ADDR` was rejected as too few arguments. The two commands now have separate arities. No script semantics, key timing, or capture behaviour changed. |
| `README.md` | changed | One line: a cited path is now marked as a name rather than a link, so the repository's own citation audit (`tools/check_doc_references.py`) can vouch for the rig's docs. Text only. |
| `scripts/README.md` | changed | +15 lines: a section describing the four CKI scripts below (two templates plus two substituted instances) and which sentinel each carries. Text only. |
| `reference/v10_locked_empty.raw` | absent | 2026-09-26 corpus cleanup deleted every `.raw` framebuffer dump that already had a converted `.png` (3900 files, 1.02 GB). `reference/v10_locked_empty.png` is still here and is byte-for-byte what the `.raw` produced. `MANIFEST.txt` is upstream's text and still counts that `.raw`; this file, not `MANIFEST.txt`, is where the delta is recorded. |
| `scripts/cki_probe_template.txt`, `scripts/cki_boundary_template.txt`, `scripts/cki_probe.txt`, `scripts/cki_boundary.txt` | added | The CKI key scripts: two sentinel-carrying templates plus the base-case host's substituted instances. They were written in the local scratch tree; publishing them is what makes the 10-step probe and the 27-step boundary route in `docs/` reproducible (`tools/qa_bench/qa_one.sh` feeds the templates). None of the four contains a ROM path. |
| `scripts/append_probe.txt`, `scripts/append_probe_ch.txt`, `scripts/ch_probe.txt`, `scripts/esmeralda_gate.txt`, `scripts/esmeralda_probe.txt`, `scripts/lock_probe.txt`, `scripts/lock_probe_ch.txt`, `scripts/lock_probe_rogue.txt`, `scripts/gate_rogue.txt`, `scripts/bailan_pinyin.txt` | added | Per-host diagnostics from the rounds that fixed the lock-word and visual-gate questions: reachability of the PAGE-role cell, one RIGHT step at a time, on `ch` / `esmeralda` / `rogue`; plus `bailan_pinyin.txt`, the reference host's own pinyin screen that `docs/` compares against. Each carries its host's NS literal and no ROM path. Nothing outside this directory references the eight lock/append/esmeralda/rogue ones; `bailan_pinyin.txt` is cited by `docs/`. |
| `sw8.txt` | added | A one-off 8xRIGHT navigation sweep left at the bundle root by an early probe, where it should have been under `scripts/`. Nothing in the repository references it. Kept, and named here, so the file list a clone gets stays honest; it is not part of any gate. |
| `MANIFEST.txt` | added (upstream's own) | Ships inside the 1.0 package; the package's hash list deliberately excludes it. |
| `REPO_DELTA.md`, `SHA256SUMS.txt` | ours | This file, and the frozen hash list it is describing. A manifest cannot hash itself. |

Nothing else was added, removed, or edited. A checkout of this repo builds the same rig with
`./build.sh`; the `.zip` remains the artifact to hand a third party.

`python tools/check_harness_delta.py` re-measures both numbers above and fails if the
mismatching or untracked-from-manifest sets stop matching this table - the reason this file
was rewritten is that it had drifted (it claimed 38 OK and three differences while two README
edits had already landed unrecorded), and a hand-maintained delta list drifts the moment
nobody re-runs the command it describes.
