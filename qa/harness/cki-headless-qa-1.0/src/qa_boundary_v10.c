/* qa_boundary_v10.c — mGBA headless driver for the CKI 1.0 behaviour gate
 * (docs/QA_ACCEPTANCE_STANDARD.md gate 4 and gate 5).
 *
 * It boots the injected ROM, walks to the naming screen, enters Chinese mode,
 * then presses A / B and dumps, after every step, both the 10 bytes of the name
 * buffer and the lock state. It also writes one raw framebuffer per step; those
 * become the v10_*.png captures via tools/raw2png.py.
 *
 * Produces: <out>/qa_boundary_v10_result.log + <out>/v10_*.raw
 * Build deps: libmgba (the harness itself needs no libminizip; mGBA's core
 *             dlopen's nothing here — libminizip is only needed by the mGBA
 *             *port* front-ends, listed in SETUP for completeness).
 *
 * !! DO NOT ADD -DCOLOR_16_BIT !!  See PITFALLS.md #1. The static assert below
 *    turns the otherwise-silent 128 KB/256 KB framebuffer mismatch into a
 *    compile error.
 *
 * !! THE THREE CONSTANTS BELOW ARE ROM-SPECIFIC AND THE TIMINGS ARE NOT !!
 *    The constants are read off qa/report_v10_clang_route.json — and the 1.0
 *    point is that report_v10_gnu_route.json carries the *same* three values,
 *    so they are a property of the host ROM, not of whichever compiler built
 *    the payload.
 *
 *      CK_NS_PTR      resolver.naming_screen_global        (EWRAM pointer)
 *      CK_NAME_BUF    the injected name buffer inside the NamingScreen struct
 *      CK_LOCK_STATE  the adapter's `0xF000 | page` lock word (big-endian u16)
 *
 *    They can be overridden at build time without touching this file:
 *      cc -O2 -DCK_NS_PTR=0x02036240u -DCK_NAME_BUF=0x1800u ... 
 *    Overriding them and then claiming the baseline log still applies is
 *    invalid: re-record the baseline with run_reference.sh.
 */
#include <stdio.h>
#include <stdlib.h>
#include <stdint.h>
#include <stdarg.h>
#include <mgba/core/core.h>
#include <mgba/core/config.h>
#include <mgba/core/log.h>
#include <mgba/internal/gba/input.h>

#ifndef CK_NS_PTR
#define CK_NS_PTR     0x02036240u
#endif
#ifndef CK_NAME_BUF
#define CK_NAME_BUF   0x1800u
#endif
#ifndef CK_LOCK_STATE
#define CK_LOCK_STATE 0x1e26u
#endif

_Static_assert(sizeof(color_t) == 4,
    "color_t is 16-bit: the distro libmgba is 32-bit. Remove -DCOLOR_16_BIT.");

/* mGBA's own logger prints a line per DMA -- thousands per run, which buries
 * the behaviour log you actually want. The `logLevel` config key does not gate
 * it, so a no-op logger is installed instead; set GBA_CAPTURE_VERBOSE=1 to keep
 * the real one (useful when a run misbehaves: "Invalid video register" and
 * "Bad BIOS Load8" are real signals).
 *
 * This -- plus the 4-byte color_t assert and the optional out-dir argument --
 * are the only differences from qa/harness/qa_boundary_v10.c as it sits in the
 * CKI repo. None of them touch input timing or memory reads, and
 * reference/qa_boundary_v10_result.log was re-recorded with this build and
 * checked byte-identical against the original baseline, and across two runs. */
static void quiet_log(struct mLogger* l, int cat, enum mLogLevel lvl,
                      const char* fmt, va_list args) {
    (void) l; (void) cat; (void) lvl; (void) fmt; (void) args;
}
static struct mLogger QUIET_LOGGER = { .log = quiet_log, .filter = NULL };

static color_t fb[256 * 256];
static const char *OUT = "";     /* optional prefix for the produced files */

static void F(struct mCore *c, int n) { while (n--) c->runFrame(c); }
static void T(struct mCore *c, int k) {
    c->addKeys(c, 1u << k); F(c, 2);
    c->clearKeys(c, 1u << k); F(c, 120);
}
static uint32_t R32(struct mCore *c, uint32_t a) { return c->busRead32(c, a); }
static uint8_t  R8 (struct mCore *c, uint32_t a) { return c->busRead8(c, a); }

static void D(const char *n) {
    char p[1024];
    snprintf(p, sizeof p, "%s%s", OUT, n);
    FILE *f = fopen(p, "wb");
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
    if (ac < 2) { fprintf(stderr, "usage: %s <rom.gba> [out-dir/]\n", av[0]); return 2; }
    if (ac > 2) OUT = av[2];

    if (!getenv("GBA_CAPTURE_VERBOSE")) mLogSetDefaultLogger(&QUIET_LOGGER);

    struct mCore *c = mCoreFind(av[1]);
    if (!c) { fprintf(stderr, "no core handles %s\n", av[1]); return 2; }
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

    char lp[1024];
    snprintf(lp, sizeof lp, "%sqa_boundary_v10_result.log", OUT);
    FILE *f = fopen(lp, "w");
    if (!f) { fprintf(stderr, "cannot write %s\n", lp); return 2; }
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
