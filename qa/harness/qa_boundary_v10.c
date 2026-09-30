/* qa/harness/qa_boundary_v10.c — mGBA headless driver for the CKI 1.0
 * behaviour gate (docs/QA_ACCEPTANCE_STANDARD.md gate 4 and gate 5).
 *
 * It boots the injected ROM, walks to the naming screen, enters Chinese mode,
 * then presses A / B and dumps, after every step, both the 10 bytes of the name
 * buffer and the lock state. It also writes one raw framebuffer per step; those
 * become the v10_*.png captures via the usual 240x160 BGR555 conversion.
 *
 * Produces: qa_boundary_v10_result.log + v10_*.raw
 * Build deps: libmgba, and libminizip (WSL: sudo apt install -y libminizip1).
 *
 * The three constants below are the only ROM-specific addresses in this file.
 * They are read off qa/report_v10_clang_route.json — and the 1.0 point is that
 * report_v10_gnu_route.json carries the *same* three values, so they are a
 * property of the host ROM, not of whichever compiler built the payload.
 *
 *   CK_NS_PTR      resolver.naming_screen_global        (EWRAM pointer)
 *   CK_NAME_BUF    the injected name buffer inside the NamingScreen struct
 *   CK_LOCK_STATE  the adapter's `0xF000 | page` lock word (big-endian u16)
 */
#define CK_NS_PTR     0x02036240u
#define CK_NAME_BUF   0x1800u
#define CK_LOCK_STATE 0x1e26u

#include <stdio.h>
#include <stdint.h>
#include <mgba/core/core.h>
#include <mgba/core/config.h>
#include <mgba/internal/gba/input.h>

static color_t fb[256 * 256];

static void F(struct mCore *c, int n) { while (n--) c->runFrame(c); }
static void T(struct mCore *c, int k) {
    c->addKeys(c, 1u << k); F(c, 2);
    c->clearKeys(c, 1u << k); F(c, 120);
}
static uint32_t R32(struct mCore *c, uint32_t a) { return c->busRead32(c, a); }
static uint8_t  R8 (struct mCore *c, uint32_t a) { return c->busRead8(c, a); }

static void D(const char *n) {
    FILE *f = fopen(n, "wb");
    fwrite(fb, sizeof(color_t), 65536, f);
    fclose(f);
}

/* One line per step: name buffer as 10 hex bytes, then the lock word. */
static void L(struct mCore *c, FILE *f, const char *t) {
    uint32_t n = R32(c, CK_NS_PTR);
    fprintf(f, "%s ", t);
    for (int i = 0; i < 10; i++) fprintf(f, "%02X", R8(c, n + CK_NAME_BUF + i));
    fprintf(f, " state=%02X%02X\n",
            R8(c, n + CK_LOCK_STATE + 1), R8(c, n + CK_LOCK_STATE));
}

int main(int ac, char **av) {
    struct mCore *c = mCoreFind(av[1]);
    c->init(c);
    c->setVideoBuffer(c, fb, 256);
    mCoreLoadFile(c, av[1]);
    mCoreConfigInit(&c->config, "qa");
    struct mCoreOptions o = {0};
    mCoreConfigLoadDefaults(&c->config, &o);
    mCoreLoadConfig(c);
    c->reset(c);

    /* Boot, then mash A until the naming screen's EWRAM pointer is live. */
    F(c, 600);
    for (int i = 0; i < 40; i++) {
        T(c, GBA_KEY_A);
        uint32_t n = R32(c, CK_NS_PTR);
        if (n >= 0x02000000 && n < 0x02040000) break;
    }
    F(c, 180);

    /* Walk the stock cursor onto the PAGE label and press A to enter CN mode. */
    for (int i = 0; i < 8; i++) T(c, GBA_KEY_RIGHT);
    T(c, GBA_KEY_A);

    FILE *f = fopen("qa_boundary_v10_result.log", "w");
    L(c, f, "locked_empty");  D("v10_locked_empty.raw");
    T(c, GBA_KEY_A); L(c, f, "one");          D("v10_1cn.raw");
    T(c, GBA_KEY_A); L(c, f, "two");          D("v10_2cn.raw");
    T(c, GBA_KEY_A); L(c, f, "three");        D("v10_3cn.raw");
    T(c, GBA_KEY_A); L(c, f, "fourth");       D("v10_4th.raw");
    T(c, GBA_KEY_B); L(c, f, "after_delete"); D("v10_delete.raw");
    T(c, GBA_KEY_A); L(c, f, "after_readd");  D("v10_readd.raw");
    fclose(f);

    c->deinit(c);
    return 0;
}
