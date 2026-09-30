# License note

This repository is released under the **MIT License** — see `LICENSE`.

## What is and is not shipped

- Only this project's own source: the injector (`injector/`), the payload
  (`payload/`), the tools (`tools/`) and the QA evidence (`qa/`).
- **No game ROM image.** ROMs are git-ignored (`*.gba`); supply your own.
- **No font glyph bitmap.** The keyboard's `chars[7168]` table is an *index*
  into the host ROM's own character codes. It carries no glyph data and relies
  on the Chinese font the host hack already ships.

## Third-party attribution

This tool builds on other people's work. The credits, the upstream licences and
the attribution lines those licences require (notably RHH's
pokeemerald-expansion) are listed in `CREDITS.md`. Review that file before
publishing anything derived from this repository.
