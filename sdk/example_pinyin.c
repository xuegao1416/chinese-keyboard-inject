/* SPDX-License-Identifier: MIT
 * Synthetic host codes for a compileable example, not a font or universal
 * charset. */
#include "cki_pinyin_ui.h"
static const unsigned short codes[] = {0x0101, 0x0102};
static const CKIPinyinEntry entries[] = {{"ai", 0, 1}, {"zi", 1, 1}};
static const CKIPinyinDictionary dictionary = {entries, 2, codes, 2};
static CKIPinyin input;
static CKIPinyinUI ui;
/* Supply actual a..z display codes and callbacks from your own host. */
int example_pinyin_open(unsigned char *name, unsigned int capacity,
                        unsigned int max_tokens, const CKITextPolicy *encoding,
                        const CKIPinyinUIDraw *draw) {
  if (!cki_pinyin_init(&input, name, capacity, max_tokens, &dictionary,
                       encoding))
    return 0;
  return cki_pinyin_ui_init(&ui, &input, draw);
}
CKIPinyinUIResult example_pinyin_key(CKIPinyinUIKey key) {
  /* On CURSOR update only the host cursor from ui.cursor; never clear the grid.
     On LATIN return to host keyboard; call cki_pinyin_backspace there for
     deletion. On DONE persist the name using the host's verified save-field
     capacity. */
  return cki_pinyin_ui_key(&ui, key);
}
