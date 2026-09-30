#include "cki_keyboard.h"
static const unsigned short characters[@COUNT@] = {
@CHARACTERS@
};
unsigned int cki_keyboard_page_count(void) { return (@COUNT@u + 31u) / 32u; }
static unsigned short cell(const CKIKeyboard *k, unsigned int i) {
    unsigned int n = k->page * 32u + i;
    return n < @COUNT@u ? characters[n] : 0;
}
int cki_keyboard_init(CKIKeyboard *k, const CKIConfig *c) {
    CKITextScan scan;
    if (k) k->active = 0;
    if (!k || !c || !c->text || !c->capacity || !c->max_tokens ||
        !cki_text_scan(c->text, c->capacity, &c->encoding, &scan) || scan.tokens > c->max_tokens) return 0;
    k->host = *c; k->page = 0; k->cursor = 0; k->active = 1;
    return 1;
}
void cki_keyboard_render(const CKIKeyboard *k) {
    unsigned int i;
    if (!k || !k->active) return;
    if (k->host.draw_cell) for (i = 0; i < 32; ++i)
        k->host.draw_cell(k->host.context, i % 8u, i / 8u, cell(k, i), i == k->cursor);
    if (k->host.draw_name) k->host.draw_name(k->host.context, k->host.text);
}
CKIEvent cki_keyboard_input(CKIKeyboard *k, CKIInput key) {
    unsigned int pages;
    if (!k || !k->active) return CKI_REJECTED;
    pages = cki_keyboard_page_count();
    switch (key) {
    case CKI_UP: k->cursor = (k->cursor + 24u) % 32u; break;
    case CKI_DOWN: k->cursor = (k->cursor + 8u) % 32u; break;
    case CKI_LEFT: k->cursor = (k->cursor / 8u) * 8u + (k->cursor + 7u) % 8u; break;
    case CKI_RIGHT: k->cursor = (k->cursor / 8u) * 8u + (k->cursor + 1u) % 8u; break;
    case CKI_L: k->page = k->page ? k->page - 1u : pages - 1u; break;
    case CKI_R: k->page = k->page + 1u == pages ? 0u : k->page + 1u; break;
    case CKI_A:
        if (!cell(k, k->cursor) || !cki_text_append(k->host.text, k->host.capacity, k->host.max_tokens, cell(k, k->cursor), &k->host.encoding)) return CKI_REJECTED;
        break;
    case CKI_B:
        if (!cki_text_delete(k->host.text, k->host.capacity, &k->host.encoding)) return CKI_REJECTED;
        break;
    case CKI_LATIN: k->active = 0; return CKI_EXIT_LATIN;
    case CKI_DONE: k->active = 0; return CKI_FINISHED;
    default: return CKI_REJECTED;
    }
    cki_keyboard_render(k);
    return CKI_CHANGED;
}
