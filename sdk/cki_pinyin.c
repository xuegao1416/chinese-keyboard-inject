/* SPDX-License-Identifier: MIT */
/* Freestanding, host-configured pinyin state machine. */
#include "cki_pinyin.h"
static int compare(const char *a, const char *b) {
  while (*a && *a == *b) {
    a++;
    b++;
  }
  return (unsigned char)*a - (unsigned char)*b;
}
static void lookup(CKIPinyin *s) {
  unsigned int lo = 0, hi = s->dictionary->entry_count;
  s->match = 0;
  s->page = s->cursor = 0;
  if (!s->length)
    return;
  while (lo < hi) {
    unsigned int m = lo + (hi - lo) / 2;
    int c = compare(s->spelling, s->dictionary->entries[m].key);
    if (!c) {
      s->match = &s->dictionary->entries[m];
      return;
    }
    if (c < 0)
      hi = m;
    else
      lo = m + 1;
  }
}
static void clear(CKIPinyin *s) {
  s->length = 0;
  s->spelling[0] = 0;
  s->match = 0;
  s->page = s->cursor = 0;
}
static int valid_dictionary(const CKIPinyinDictionary *d,
                            const CKITextPolicy *policy) {
  unsigned int i, j;
  if (!d || !d->entries || !d->entry_count || !d->codes || !d->code_count)
    return 0;
  for (i = 0; i < d->entry_count; i++) {
    const CKIPinyinEntry *e = &d->entries[i];
    if (!e->key || !e->key[0])
      return 0;
    for (j = 0; e->key[j]; j++)
      if (j >= CKI_PINYIN_MAX || e->key[j] < 'a' || e->key[j] > 'z')
        return 0;
    if (i && compare(d->entries[i - 1].key, e->key) >= 0)
      return 0;
    if (!e->count || e->offset > d->code_count ||
        e->count > d->code_count - e->offset)
      return 0;
  }
  for (i = 0; i < d->code_count; i++) {
    unsigned char probe[3] = {0xff, 0xff, 0xff};
    if (!d->codes[i] || !cki_text_append(probe, 3, 1, d->codes[i], policy))
      return 0;
  }
  return 1;
}
int cki_pinyin_init(CKIPinyin *s, unsigned char *t, unsigned int cap,
                    unsigned int max, const CKIPinyinDictionary *dictionary,
                    const CKITextPolicy *policy) {
  CKITextScan v;
  if (!s)
    return 0;
  s->active = 0;
  if (!t || !max || !valid_dictionary(dictionary, policy) ||
      !cki_text_scan(t, cap, policy, &v) || v.tokens > max)
    return 0;
  s->dictionary = dictionary;
  s->encoding.is_lead = policy ? policy->is_lead : 0;
  s->encoding.context = policy ? policy->context : 0;
  s->text = t;
  s->capacity = cap;
  s->max_tokens = max;
  s->chinese = 1;
  clear(s);
  s->active = 1;
  return 1;
}
int cki_pinyin_letter(CKIPinyin *s, char c) {
  if (!s || !s->active || !s->chinese || s->length >= CKI_PINYIN_MAX)
    return 0;
  if (c >= 'A' && c <= 'Z')
    c += 'a' - 'A';
  if (c < 'a' || c > 'z')
    return 0;
  s->spelling[s->length++] = c;
  s->spelling[s->length] = 0;
  lookup(s);
  return 1;
}
int cki_pinyin_backspace(CKIPinyin *s) {
  if (!s || !s->active)
    return 0;
  if (s->chinese && s->length) {
    s->spelling[--s->length] = 0;
    lookup(s);
    return 1;
  }
  return cki_text_delete(s->text, s->capacity, &s->encoding);
}
int cki_pinyin_latin(CKIPinyin *s, unsigned short c) {
  if (!s || !s->active || s->chinese || c > 255)
    return 0;
  return cki_text_append(s->text, s->capacity, s->max_tokens, c, &s->encoding);
}
unsigned short cki_pinyin_candidate(const CKIPinyin *s, unsigned int i) {
  unsigned int n;
  if (!s || !s->active || !s->match || i >= CKI_PINYIN_PAGE)
    return 0;
  n = s->page * CKI_PINYIN_PAGE + i;
  return n < s->match->count ? s->dictionary->codes[s->match->offset + n] : 0;
}
int cki_pinyin_select(CKIPinyin *s) {
  unsigned short code;
  if (!s || !s->active || !s->chinese)
    return 0;
  code = cki_pinyin_candidate(s, s->cursor);
  if (!code ||
      !cki_text_append(s->text, s->capacity, s->max_tokens, code, &s->encoding))
    return 0;
  clear(s);
  return 1;
}
int cki_pinyin_page(CKIPinyin *s, int delta) {
  unsigned int n;
  if (!s || !s->active || !s->chinese || !s->match || !delta)
    return 0;
  n = 1 + (s->match->count - 1) / CKI_PINYIN_PAGE;
  s->page = delta > 0 ? (s->page + 1 == n ? 0 : s->page + 1)
                      : (s->page ? s->page - 1 : n - 1);
  s->cursor = 0;
  return 1;
}
int cki_pinyin_cursor(CKIPinyin *s, int delta) {
  unsigned int n;
  if (!s || !s->active || !s->chinese || !s->match || !delta)
    return 0;
  n = s->match->count - s->page * CKI_PINYIN_PAGE;
  if (n > CKI_PINYIN_PAGE)
    n = CKI_PINYIN_PAGE;
  s->cursor = delta > 0 ? (s->cursor + 1 == n ? 0 : s->cursor + 1)
                        : (s->cursor ? s->cursor - 1 : n - 1);
  return 1;
}
void cki_pinyin_mode(CKIPinyin *s, int chinese) {
  if (s && s->active) {
    s->chinese = !!chinese;
    clear(s);
  }
}
int cki_pinyin_finish(CKIPinyin *s) {
  CKITextScan v;
  if (!s || !s->active || s->length ||
      !cki_text_scan(s->text, s->capacity, &s->encoding, &v) || !v.tokens ||
      v.tokens > s->max_tokens)
    return 0;
  s->active = 0;
  return 1;
}
