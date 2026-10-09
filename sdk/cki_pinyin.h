/* SPDX-License-Identifier: MIT */
#ifndef CKI_PINYIN_H
#define CKI_PINYIN_H
#include "cki_text.h"
#define CKI_PINYIN_MAX 6
#define CKI_PINYIN_PAGE 32
/* Encodings are big-endian host character codes, never Unicode. */
typedef struct {
  const char *key;
  unsigned int offset, count;
} CKIPinyinEntry;
typedef struct {
  const CKIPinyinEntry *entries;
  unsigned int entry_count;
  const unsigned short *codes;
  unsigned int code_count;
} CKIPinyinDictionary;
/* Dictionary and policy context must outlive the session and remain immutable.
 */
typedef struct {
  const CKIPinyinDictionary *dictionary;
  CKITextPolicy encoding;
  unsigned char *text;
  unsigned int capacity, max_tokens;
  char spelling[CKI_PINYIN_MAX + 1];
  unsigned int length, page, cursor;
  int chinese, active;
  const CKIPinyinEntry *match;
} CKIPinyin;
/* cap includes EOS; max_tokens is independently enforced by the host. */
int cki_pinyin_init(CKIPinyin *, unsigned char *, unsigned int, unsigned int,
                    const CKIPinyinDictionary *, const CKITextPolicy *);
int cki_pinyin_letter(CKIPinyin *, char);
int cki_pinyin_backspace(CKIPinyin *);
int cki_pinyin_latin(CKIPinyin *, unsigned short);
int cki_pinyin_select(CKIPinyin *);
int cki_pinyin_page(CKIPinyin *, int);
int cki_pinyin_cursor(CKIPinyin *, int);
void cki_pinyin_mode(CKIPinyin *, int);
int cki_pinyin_finish(CKIPinyin *);
unsigned short cki_pinyin_candidate(const CKIPinyin *, unsigned int);
#endif
