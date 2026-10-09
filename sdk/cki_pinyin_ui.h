/* SPDX-License-Identifier: MIT */
#ifndef CKI_PINYIN_UI_H
#define CKI_PINYIN_UI_H
#include "cki_pinyin.h"
/* Reuse CKI's 8-column, 4-row window. The host owns its tiles/palette/cursor.
 * Spell and candidates occupy this SAME window at different times. */
typedef enum {
  CKI_PINYIN_UI_UP,
  CKI_PINYIN_UI_DOWN,
  CKI_PINYIN_UI_LEFT,
  CKI_PINYIN_UI_RIGHT,
  CKI_PINYIN_UI_A,
  CKI_PINYIN_UI_B,
  CKI_PINYIN_UI_L,
  CKI_PINYIN_UI_R,
  CKI_PINYIN_UI_SELECT,
  CKI_PINYIN_UI_START
} CKIPinyinUIKey;
typedef enum {
  CKI_PINYIN_UI_REJECTED,
  CKI_PINYIN_UI_CURSOR,
  CKI_PINYIN_UI_REDRAW,
  CKI_PINYIN_UI_LATIN,
  CKI_PINYIN_UI_DONE
} CKIPinyinUIResult;
typedef struct {
  /* Host encoded a..z (not ASCII assumptions). These arrays are copied at init.
   */
  unsigned short letters[26];
  void *context;
  void (*cell)(void *, unsigned int, unsigned int, unsigned short, int);
  void (*composition)(void *, const char *, unsigned int, unsigned int, int);
  void (*name)(void *, const unsigned char *);
} CKIPinyinUIDraw;
typedef struct {
  CKIPinyin *input;
  CKIPinyinUIDraw draw;
  unsigned int cursor;
  int candidates;
} CKIPinyinUI;
int cki_pinyin_ui_init(CKIPinyinUI *, CKIPinyin *, const CKIPinyinUIDraw *);
void cki_pinyin_ui_render(const CKIPinyinUI *);
CKIPinyinUIResult cki_pinyin_ui_key(CKIPinyinUI *, CKIPinyinUIKey);
#endif
