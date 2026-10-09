#include "cki_pinyin_ui.h"
#include <assert.h>
#include <stdio.h>
static unsigned short codes[35];
static const CKIPinyinEntry entries[] = {{"ai", 0, 33}, {"zi", 33, 2}};
static const CKIPinyinDictionary dictionary = {entries, 2, codes, 35};
static int lead(unsigned char b, void *ctx) {
  return b == *(unsigned char *)ctx;
}
static unsigned int draws;
static void cell(void *ctx, unsigned int x, unsigned int y, unsigned short code,
                 int selected) {
  (void)ctx;
  (void)code;
  (void)selected;
  assert(x < 8 && y < 4);
  ++draws;
}
static void spell(CKIPinyin *s, const char *p) {
  while (*p)
    assert(cki_pinyin_letter(s, *p++));
}
int main(void) {
  unsigned char lead_byte = 0x80, buf[8] = {0xff},
                guard[6] = {0xcc, 0xff, 0xcc, 0xcc, 0xcc, 0xcc};
  CKITextPolicy policy = {lead, &lead_byte};
  CKIPinyin s;
  CKIPinyinUI ui;
  CKIPinyinUIDraw draw = {0};
  unsigned int i, n;
  for (i = 0; i < 35; i++)
    codes[i] = (unsigned short)(0x8000 + i + 1);
  codes[34] =
      0x8080; /* A trail that is also a lead must still delete atomically. */
  assert(cki_pinyin_init(&s, buf, sizeof(buf), 3, &dictionary, &policy));
  spell(&s, "AI");
  assert(cki_pinyin_candidate(&s, 0) == 0x8001);
  assert(cki_pinyin_page(&s, -1) && s.page == 1);
  assert(cki_pinyin_candidate(&s, 1) == 0);
  assert(cki_pinyin_select(&s) && buf[0] == 0x80 && buf[1] == 33 &&
         buf[2] == 255);
  cki_pinyin_mode(&s, 0);
  assert(cki_pinyin_backspace(&s) && buf[0] == 255);
  assert(cki_pinyin_latin(&s, 0xbb));
  cki_pinyin_mode(&s, 1);
  spell(&s, "zi");
  s.cursor = 1;
  assert(cki_pinyin_select(&s));
  assert(buf[1] == 0x80 && buf[2] == 0x80);
  assert(cki_pinyin_backspace(&s) && buf[1] == 255 && buf[0] == 0xbb);
  spell(&s, "zzzzzz");
  assert(!cki_pinyin_letter(&s, 'a'));
  assert(!cki_pinyin_select(&s));
  assert(!cki_pinyin_finish(&s));
  cki_pinyin_mode(&s, 1);
  for (i = 0; i < 26; i++)
    draw.letters[i] = (unsigned short)(0xd5 + i);
  draw.cell = cell;
  assert(cki_pinyin_ui_init(&ui, &s, &draw));
  assert(draws == 32);
  n = draws;
  assert(cki_pinyin_ui_key(&ui, CKI_PINYIN_UI_RIGHT) == CKI_PINYIN_UI_CURSOR);
  assert(draws == n);
  spell(&s, "ai");
  assert(cki_pinyin_ui_key(&ui, CKI_PINYIN_UI_START) == CKI_PINYIN_UI_REDRAW);
  assert(cki_pinyin_ui_key(&ui, CKI_PINYIN_UI_R) == CKI_PINYIN_UI_REDRAW &&
         s.page == 1);
  ui.cursor = 1;
  assert(cki_pinyin_ui_key(&ui, CKI_PINYIN_UI_A) == CKI_PINYIN_UI_REJECTED);
  assert(cki_pinyin_ui_key(&ui, CKI_PINYIN_UI_B) == CKI_PINYIN_UI_REDRAW &&
         !ui.candidates);
  assert(cki_pinyin_ui_key(&ui, CKI_PINYIN_UI_SELECT) == CKI_PINYIN_UI_LATIN);
  assert(cki_pinyin_backspace(&s) && buf[0] == 255);
  assert(!cki_pinyin_finish(&s));
  assert(cki_pinyin_latin(&s, 0xbb));
  assert(cki_pinyin_finish(&s));
  assert(!cki_pinyin_backspace(&s));
  /* Byte capacity and token count independently reject overflow, leaving guards
   * intact. */
  assert(cki_pinyin_init(&s, guard + 1, 3, 2, &dictionary, &policy));
  spell(&s, "zi");
  assert(cki_pinyin_select(&s));
  spell(&s, "zi");
  assert(!cki_pinyin_select(&s));
  assert(guard[0] == 0xcc && guard[4] == 0xcc);
  buf[0] = 255;
  assert(cki_pinyin_init(&s, buf, 8, 1, &dictionary, &policy));
  spell(&s, "ai");
  assert(cki_pinyin_select(&s));
  spell(&s, "ai");
  assert(!cki_pinyin_select(&s));
  /* Bad reinitialization deactivates prior sessions; no stale mutable text
   * access. */
  buf[0] = 0x80;
  buf[1] = 255;
  assert(!cki_pinyin_init(&s, buf, 8, 3, &dictionary, &policy));
  assert(!s.active);
  assert(!cki_pinyin_backspace(&s));
  assert(!cki_pinyin_ui_init(&ui, &s, &draw));
  assert(!ui.input);
  {
    CKIPinyinEntry bad[] = {{"zi", 0, 1}, {"ai", 1, 1}};
    CKIPinyinDictionary d = {bad, 2, codes, 35};
    buf[0] = 255;
    assert(!cki_pinyin_init(&s, buf, 8, 3, &d, &policy));
    bad[0].key = "ai";
    bad[1].key = "zi";
    bad[1].offset = 35;
    assert(!cki_pinyin_init(&s, buf, 8, 3, &d, &policy));
    bad[1].offset = 1;
    bad[0].count = 0;
    assert(!cki_pinyin_init(&s, buf, 8, 3, &d, &policy));
  }
  codes[0] = 0x80ff;
  buf[0] = 255;
  assert(!cki_pinyin_init(&s, buf, 8, 3, &dictionary, &policy));
  puts("PASS pinyin custom encoding, candidates, pages, modes, redraw, "
       "capacities and malformed inputs");
  return 0;
}
