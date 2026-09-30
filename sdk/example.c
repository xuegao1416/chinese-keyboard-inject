#include "cki_keyboard.h"
/* Host owns this state. Use your actual persistent name buffer when integrating. */
static unsigned char name[8] = {0xFF};
static CKIKeyboard keyboard;
typedef char capacity_includes_eos[(sizeof(name) >= 3) ? 1 : -1];
static void draw_cell(void *ctx, unsigned int x, unsigned int y, unsigned short code, int selected) {
    (void)ctx; (void)x; (void)y; (void)code; (void)selected;
    /* Render high byte, low byte, FF using the host's matching text renderer.
       Clear each cell first; code == 0 represents an empty cell. */
}
static void draw_name(void *ctx, const unsigned char *text) { (void)ctx; (void)text; }
int example_open(void) {
    CKIConfig config = {name, sizeof(name), 7, {0, 0}, draw_cell, draw_name, 0};
    int ok = cki_keyboard_init(&keyboard, &config);
    if (ok) cki_keyboard_render(&keyboard);
    return ok;
}
int example_key(unsigned int key) { return (int)cki_keyboard_input(&keyboard, (CKIInput)key); }
