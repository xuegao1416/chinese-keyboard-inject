/* SPDX-License-Identifier: MIT */
#include "cki_pinyin_ui.h"
/* 26 alphabet cells, then six empty cells. START opens candidates.
 * Host supplies the encoded a..z glyphs; no ASCII/font assumption. */
int cki_pinyin_ui_init(CKIPinyinUI *u, CKIPinyin *s, const CKIPinyinUIDraw *d) {
  if (!u)
    return 0;
  u->input = 0;
  if (!s || !s->active || !s->chinese || !d || !d->cell)
    return 0;
  u->input = s;
  u->draw = *d;
  u->cursor = 0;
  u->candidates = 0;
  cki_pinyin_ui_render(u);
  return 1;
}
void cki_pinyin_ui_render(const CKIPinyinUI *u) {
  unsigned int i, pages;
  const CKIPinyin *s;
  if (!u || !u->input || !u->input->active)
    return;
  s = u->input;
  pages =
      s->match ? 1 + (s->match->count - 1) / CKI_PINYIN_PAGE : 0;
  for (i = 0; i < 32; i++)
    u->draw.cell(u->draw.context, i % 8, i / 8,
                 u->candidates ? cki_pinyin_candidate(s, i)
                               : (i < 26 ? u->draw.letters[i] : 0),
                 i == u->cursor);
  if (u->draw.composition)
    u->draw.composition(u->draw.context, s->spelling, s->page, pages,
                        u->candidates);
  if (u->draw.name)
    u->draw.name(u->draw.context, s->text);
}
CKIPinyinUIResult cki_pinyin_ui_key(CKIPinyinUI *u, CKIPinyinUIKey key) {
  CKIPinyin *s;
  unsigned int col, row;
  if (!u || !u->input || !u->input->active || !u->input->chinese)
    return CKI_PINYIN_UI_REJECTED;
  s = u->input;
  col = u->cursor % 8;
  row = u->cursor / 8;
  switch (key) {
  case CKI_PINYIN_UI_UP:
    u->cursor = ((row + 3) % 4) * 8 + col;
    break;
  case CKI_PINYIN_UI_DOWN:
    u->cursor = ((row + 1) % 4) * 8 + col;
    break;
  case CKI_PINYIN_UI_LEFT:
    u->cursor = row * 8 + (col + 7) % 8;
    break;
  case CKI_PINYIN_UI_RIGHT:
    u->cursor = row * 8 + (col + 1) % 8;
    break;
  case CKI_PINYIN_UI_A:
    if (u->candidates) {
      s->cursor = u->cursor;
      if (!cki_pinyin_select(s))
        return CKI_PINYIN_UI_REJECTED;
      u->candidates = 0;
      u->cursor = 0;
    } else if (u->cursor >= 26 ||
               !cki_pinyin_letter(s, (char)('a' + u->cursor)))
      return CKI_PINYIN_UI_REJECTED;
    break;
  case CKI_PINYIN_UI_B:
    if (u->candidates) {
      u->candidates = 0;
      u->cursor = 0;
    } else if (!cki_pinyin_backspace(s))
      return CKI_PINYIN_UI_REJECTED;
    break;
  case CKI_PINYIN_UI_L:
  case CKI_PINYIN_UI_R:
    if (!u->candidates || !cki_pinyin_page(s, key == CKI_PINYIN_UI_R ? 1 : -1))
      return CKI_PINYIN_UI_REJECTED;
    u->cursor = 0;
    break;
  case CKI_PINYIN_UI_SELECT:
    cki_pinyin_mode(s, 0);
    return CKI_PINYIN_UI_LATIN;
  case CKI_PINYIN_UI_START:
    if (s->length) {
      if (!s->match)
        return CKI_PINYIN_UI_REJECTED;
      u->candidates = 1;
      u->cursor = 0;
      s->cursor = 0;
    } else {
      if (!cki_pinyin_finish(s))
        return CKI_PINYIN_UI_REJECTED;
      return CKI_PINYIN_UI_DONE;
    }
    break;
  default:
    return CKI_PINYIN_UI_REJECTED;
  }
  if (key == CKI_PINYIN_UI_UP || key == CKI_PINYIN_UI_DOWN ||
      key == CKI_PINYIN_UI_LEFT || key == CKI_PINYIN_UI_RIGHT)
    return CKI_PINYIN_UI_CURSOR;
  cki_pinyin_ui_render(u);
  return CKI_PINYIN_UI_REDRAW;
}
