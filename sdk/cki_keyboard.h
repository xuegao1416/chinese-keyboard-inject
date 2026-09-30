#ifndef CKI_KEYBOARD_H
#define CKI_KEYBOARD_H
#include "cki_text.h"
#define CKI_CELLS 32u
/* Full byte capacity includes the mandatory 0xFF terminator. */
typedef struct {
    unsigned char *text;
    unsigned int capacity, max_tokens;
    CKITextPolicy encoding;
    void (*draw_cell)(void *, unsigned int, unsigned int, unsigned short, int);
    void (*draw_name)(void *, const unsigned char *);
    void *context;
} CKIConfig;
typedef struct { CKIConfig host; unsigned int page, cursor; int active; } CKIKeyboard;
typedef enum { CKI_UP, CKI_DOWN, CKI_LEFT, CKI_RIGHT, CKI_L, CKI_R, CKI_A, CKI_B, CKI_LATIN, CKI_DONE } CKIInput;
typedef enum { CKI_REJECTED, CKI_CHANGED, CKI_EXIT_LATIN, CKI_FINISHED } CKIEvent;
int cki_keyboard_init(CKIKeyboard *, const CKIConfig *);
void cki_keyboard_render(const CKIKeyboard *);
CKIEvent cki_keyboard_input(CKIKeyboard *, CKIInput);
unsigned int cki_keyboard_page_count(void);
#endif
