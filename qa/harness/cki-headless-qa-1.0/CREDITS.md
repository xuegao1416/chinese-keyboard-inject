# Credits / 致谢与署名

This project is a ROM-injection tool. It does **not** redistribute any game ROM
image and does **not** redistribute any font glyph bitmaps. The `CKP4` payload
is an index table that maps on-screen slots to the host ROM's own character
codes; it relies on the Chinese font the host hack already carries. The
following are credited because this tool builds on their work.

## Base decompilation

- **pret** — `pret/pokeemerald`, the base decompilation that makes the whole
  approach possible. No license file is shipped upstream; credit is given by
  convention. https://github.com/pret/pokeemerald

## Expansion framework

- **Rom Hacking Hideout (RHH)** — `rh-hideout/pokeemerald-expansion`. Per the
  expansion README, derivative works must credit RHH. Suggested line:

  ```
  Based off RHH's pokeemerald-expansion https://github.com/rh-hideout/pokeemerald-expansion/
  ```

## Chinese recompiled Emerald fork (the host family this injector targets)

- **`rh-hideout-chinese/pokeemerald-expansion`** and **`sayseong/pokeemerald-expansion`**
  — the Chinese fork that supplies the font and display work this injector
  depends on.
- Font / text work credited to: **sayseong, 卧看微尘, 泡泡** (and the fork's own
  CREDITS list). Verify the exact current list against the upstream README before
  publishing; do not trim or guess names.
- Per the Chinese fork's stated terms, its translated **text** may be reused with
  attribution. This tool reuses neither the text nor the font — only the host's
  existing character-code layout.

## Original Chinese font & text source

- **2011 漫游 & TGB 联合汉化组** — original Chinese font and text source for the
  Emerald family. Listed here in acknowledgement; please consult their published
  credits for the full contributor roster.

## Test hosts (not redistributed)

- `LightPlatinum` and any other hack used only as a local test target are **not**
  included in this repository.

## Note on permissions

No one in this chain can grant or withhold legal "authorization" for a Pokémon
Emerald derivative — the underlying code belongs to Nintendo and is decompiled
without a license. The community operates on **correct attribution + not
redistributing copyrighted assets**. This project follows that convention.
