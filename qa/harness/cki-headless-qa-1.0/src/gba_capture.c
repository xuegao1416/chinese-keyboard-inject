/*
 * gba_capture.c — scripted, headless mGBA driver for GBA acceptance QA.
 *
 *   boots a ROM, replays a key/step script, dumps one 256x256 framebuffer per
 *   named step, and writes a plain-text behaviour log of memory probes.
 *
 * Why this exists: "visual pass" only means something if the frames come from
 * YOUR machine, from the EXACT candidate ROM, produced by an input sequence you
 * can read and re-run. Everything here is that.
 *
 * Build:  cc -O2 -o build/gba_capture src/gba_capture.c -lmgba
 * Run:    ./build/gba_capture <rom.gba> <script.txt> --out out/
 *
 * !! DO NOT ADD -DCOLOR_16_BIT !!  See PITFALLS.md #1.
 *    The distro libmgba is built with a 32-bit color_t. Defining the macro
 *    makes your color_t 16-bit, so the core writes a 256 KB framebuffer into
 *    what your binary thinks is 128 KB. Compiles clean, core-dumps on frame 1.
 *    The static assert below turns that silent crash into a build error.
 *
 * !! KEY TIMING IS NOT TUNABLE BY FEEL !!  See PITFALLS.md #2.
 *    `tap()` defaults to press-2-frames / release-120-frames. That is the
 *    timing the CKI 1.0 behaviour baseline was recorded with. "60 looks about
 *    the same" is false: it lands "mash A until screen X" loops in a different
 *    place and every memory read afterwards is garbage.
 */
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <stdint.h>
#include <stdarg.h>

#include <mgba/core/core.h>
#include <mgba/core/config.h>
#include <mgba/core/log.h>
#include <mgba/internal/gba/input.h>

/* --- keeping the terminal readable --------------------------------------- */
/* mGBA's default logger prints a line per DMA and per SWI: thousands of lines
 * per run, which buries the one log you actually want. The `logLevel` config
 * key does NOT gate this (tried; no effect), so install a logger that drops
 * everything on the floor instead. --verbose leaves the real one in place.
 *
 * Do not delete this thinking it is cosmetic: the run output has to be readable
 * for a human to notice "Invalid video register" when things go wrong. Use
 * --verbose for that. */
static void quiet_log(struct mLogger* l, int cat, enum mLogLevel lvl,
                      const char* fmt, va_list args) {
    (void) l; (void) cat; (void) lvl; (void) fmt; (void) args;
}
static struct mLogger QUIET_LOGGER = { .log = quiet_log, .filter = NULL };

/* --- the one compile-time guard that matters (PITFALLS.md #1) ------------- */
_Static_assert(sizeof(color_t) == 4,
    "color_t is 16-bit: the distro libmgba is 32-bit. Remove -DCOLOR_16_BIT.");

#define MAX_SYM   64
#define FB_W      256
#define FB_H      256
#define GBA_W     240
#define GBA_H     160
#define FRAME_PX  (FB_W * FB_H)

#define DEF_DOWN  2
#define DEF_UP    120

static color_t fb[FB_W * FB_H];
static struct mCore *C;
static FILE *LOG;
static const char *OUTDIR = ".";

struct Sym { char name[32]; uint32_t addr; };
static struct Sym syms[MAX_SYM];
static int nsym;

static const char *KEYNAME[10] = {
    "A", "B", "SELECT", "START", "RIGHT", "LEFT", "UP", "DOWN", "R", "L"
};
static const int KEYBIT[10] = {
    GBA_KEY_A, GBA_KEY_B, GBA_KEY_SELECT, GBA_KEY_START,
    GBA_KEY_RIGHT, GBA_KEY_LEFT, GBA_KEY_UP, GBA_KEY_DOWN,
    GBA_KEY_R, GBA_KEY_L
};

static uint32_t rd32(uint32_t a) { return C->busRead32(C, a); }
static uint8_t  rd8 (uint32_t a) { return (uint8_t)C->busRead8(C, a); }

static void frames(int n) { while (n-- > 0) C->runFrame(C); }

static int keybit(const char *n) {
    for (int i = 0; i < 10; i++)
        if (strcasecmp(n, KEYNAME[i]) == 0) return KEYBIT[i];
    return -1;
}

static void tap(int bit, int down, int up) {
    C->addKeys(C, 1u << bit);
    frames(down);
    C->clearKeys(C, 1u << bit);
    frames(up);
}

static struct Sym *sym_find(const char *name, size_t n) {
    for (int i = 0; i < nsym; i++)
        if (strlen(syms[i].name) == n && strncmp(syms[i].name, name, n) == 0)
            return &syms[i];
    return NULL;
}

/* address token: "0x1234" | "SYM" | "SYM+0x40"
 * A symbol is a *cell*: its value is read live as a 32-bit pointer. */
static int addr_of(const char *tok, uint32_t *out) {
    if (tok[0] == '0' && (tok[1] == 'x' || tok[1] == 'X')) {
        *out = (uint32_t)strtoul(tok, NULL, 16);
        return 0;
    }
    const char *plus = strchr(tok, '+');
    size_t n = plus ? (size_t)(plus - tok) : strlen(tok);
    struct Sym *s = sym_find(tok, n);
    if (!s) return -1;
    uint32_t v = rd32(s->addr);
    if (plus) v += (uint32_t)strtoul(plus + 1, NULL, 16);
    *out = v;
    return 0;
}

static void die(const char *msg, const char *arg, int line) {
    fprintf(stderr, "gba_capture: line %d: %s%s%s\n",
            line, msg, arg ? ": " : "", arg ? arg : "");
    exit(2);
}

static void out_path(char *dst, size_t n, const char *name, const char *ext) {
    snprintf(dst, n, "%s/%s.%s", OUTDIR, name, ext);
}

/* --- script ------------------------------------------------------------- */
/* Commands (one per line, '#' starts a comment, blank lines ignored):
 *
 *   frames N                     run N frames
 *   key NAME [DOWN] [UP]         press NAME for DOWN frames (default 2),
 *                                release for UP frames (default 120)
 *   hold NAME                    add NAME to the held set (no frame advance)
 *   release NAME                 remove NAME from the held set
 *   ptr SYM 0xADDR               define SYM = the 32-bit pointer stored at ADDR,
 *                                read LIVE (at each use, not at definition)
 *   untillive SYM LO HI MAX [K]  press K (default A) up to MAX times, checking
 *                                after each press whether ptr SYM is inside
 *                                [LO,HI); stop early if it is          (LO/HI hex)
 *   repeat N <command>           run <command> N times
 *   shot NAME                    write out/NAME.raw (256x256x4, native order)
 *   text "STRING"                print STRING to the log (\n and \t fine)
 *   peek ADDR LEN [be]           print LEN bytes at ADDR as hex, no newline;
 *                                "be" prints them in reverse (descending) order
 *   peek32 ADDR [be]             print a 32-bit word as 8 hex digits
 */
static void run_line(char *line, int lineno);

static void run_tokens(char *t[], int n, int lineno) {
    const char *cmd = t[0];

    if (!strcmp(cmd, "frames")) {
        if (n < 2) die("frames needs a count", NULL, lineno);
        frames(atoi(t[1]));
    } else if (!strcmp(cmd, "key")) {
        if (n < 2) die("key needs a button name", NULL, lineno);
        int bit = keybit(t[1]);
        if (bit < 0) die("unknown button", t[1], lineno);
        int down = n > 2 ? atoi(t[2]) : DEF_DOWN;
        int up   = n > 3 ? atoi(t[3]) : DEF_UP;
        tap(bit, down, up);
    } else if (!strcmp(cmd, "hold") || !strcmp(cmd, "release")) {
        if (n < 2) die("hold/release need a button name", NULL, lineno);
        int bit = keybit(t[1]);
        if (bit < 0) die("unknown button", t[1], lineno);
        if (cmd[0] == 'h') C->addKeys(C, 1u << bit);
        else               C->clearKeys(C, 1u << bit);
    } else if (!strcmp(cmd, "ptr")) {
        if (n < 3) die("ptr needs a name and an address", NULL, lineno);
        if (nsym >= MAX_SYM) die("too many symbols", NULL, lineno);
        if (t[2][0] != '0' || (t[2][1] != 'x' && t[2][1] != 'X'))
            die("ptr address must be a 0x literal", t[2], lineno);
        snprintf(syms[nsym].name, sizeof syms[nsym].name, "%s", t[1]);
        syms[nsym].addr = (uint32_t)strtoul(t[2], NULL, 16);
        nsym++;
    } else if (!strcmp(cmd, "untillive")) {
        if (n < 5) die("untillive SYM LO HI MAX [KEY]", NULL, lineno);
        struct Sym *s = sym_find(t[1], strlen(t[1]));
        if (!s) die("unknown symbol", t[1], lineno);
        uint32_t lo = (uint32_t)strtoul(t[2], NULL, 16);
        uint32_t hi = (uint32_t)strtoul(t[3], NULL, 16);
        int max = atoi(t[4]);
        int bit = n > 5 ? keybit(t[5]) : GBA_KEY_A;
        if (bit < 0) die("unknown button", t[5], lineno);
        for (int i = 0; i < max; i++) {
            tap(bit, DEF_DOWN, DEF_UP);
            uint32_t v = rd32(s->addr);
            if (v >= lo && v < hi) break;
        }
    } else if (!strcmp(cmd, "repeat")) {
        if (n < 3) die("repeat takes a count and a command", NULL, lineno);
        int k = atoi(t[1]);
        char buf[2048];
        size_t w = 0;
        buf[0] = '\0';
        for (int i = 2; i < n && w + strlen(t[i]) + 2 < sizeof buf; i++) {
            if (i > 2) buf[w++] = ' ';
            size_t l = strlen(t[i]);
            memcpy(buf + w, t[i], l);
            w += l;
            buf[w] = '\0';
        }
        /* run_line() tokenises in place, so each pass needs its own copy --
         * without this, the second iteration only ever sees the first token. */
        for (int i = 0; i < k; i++) {
            char one[2048];
            memcpy(one, buf, w + 1);
            run_line(one, lineno);
        }
    } else if (!strcmp(cmd, "shot")) {
        if (n < 2) die("shot needs a name", NULL, lineno);
        char p[1024];
        out_path(p, sizeof p, t[1], "raw");
        FILE *f = fopen(p, "wb");
        if (!f) die("cannot write", p, lineno);
        fwrite(fb, sizeof(color_t), FRAME_PX, f);
        fclose(f);
        fprintf(stderr, "  shot  %s\n", p);
    } else if (!strcmp(cmd, "text")) {
        if (n < 2) die("text needs a quoted string", NULL, lineno);
        for (const char *s = t[1]; *s; s++) {
            if (s[0] == '\\' && s[1] == 'n') { fputc('\n', LOG); s++; }
            else if (s[0] == '\\' && s[1] == 't') { fputc('\t', LOG); s++; }
            else fputc(*s, LOG);
        }
    } else if (!strcmp(cmd, "peek") || !strcmp(cmd, "peek32")) {
        int is32 = cmd[4] == '3';
        // peek32's length is implied by the command name, so it takes only an
        // address. Sharing one arity check with `peek` made every legal
        // `peek32 ADDR` die on the first line of the script.
        if (n < (is32 ? 2 : 3)) die("peek needs an address and a length", NULL, lineno);
        uint32_t a;
        if (addr_of(t[1], &a) != 0) die("bad address", t[1], lineno);
        int len = is32 ? 4 : atoi(t[2]);
        const char *flag = is32 ? (n > 2 ? t[2] : NULL) : (n > 3 ? t[3] : NULL);
        int be = flag && !strcmp(flag, "be");
        for (int i = 0; i < len; i++) {
            int k = be ? (len - 1 - i) : i;
            fprintf(LOG, "%02X", rd8(a + k));
        }
    } else {
        die("unknown command", cmd, lineno);
    }
}

static void run_line(char *line, int lineno) {
    char *t[16];
    int n = 0;
    char *p = line;
    while (*p && n < 16) {
        while (*p == ' ' || *p == '\t') p++;
        if (!*p) break;
        if (*p == '#') break;
        if (*p == '"') {            /* quoted arg: keep the quotes off */
            t[n++] = ++p;
            while (*p && *p != '"') p++;
            if (*p) *p++ = '\0';
        } else {
            t[n++] = p;
            while (*p && *p != ' ' && *p != '\t') p++;
            if (*p) *p++ = '\0';
        }
    }
    if (n) run_tokens(t, n, lineno);
}

static void usage(void) {
    fprintf(stderr,
        "usage: gba_capture <rom.gba> <script.txt> [--out DIR] [--save FILE] [--verbose]\n"
        "  --out DIR    where .raw frames and capture.log go (default .)\n"
        "  --save FILE  load a .sav read-only before reset (default: none)\n"
        "  --verbose    keep mGBA's own logging (a line per DMA; off by default)\n");
}

int main(int ac, char **av) {
    const char *rom = NULL, *script = NULL, *save = NULL;
    int verbose = 0;

    for (int i = 1; i < ac; i++) {
        if (!strcmp(av[i], "--out") && i + 1 < ac)       OUTDIR = av[++i];
        else if (!strcmp(av[i], "--save") && i + 1 < ac) save = av[++i];
        else if (!strcmp(av[i], "--verbose") || !strcmp(av[i], "-v")) verbose = 1;
        else if (!strcmp(av[i], "-h") || !strcmp(av[i], "--help")) { usage(); return 0; }
        else if (!rom)                                   rom = av[i];
        else if (!script)                                script = av[i];
        else { usage(); return 2; }
    }
    if (!rom || !script) { usage(); return 2; }

    if (!verbose) mLogSetDefaultLogger(&QUIET_LOGGER);

    C = mCoreFind(rom);
    if (!C) { fprintf(stderr, "gba_capture: no core handles %s\n", rom); return 2; }
    C->init(C);
    C->setVideoBuffer(C, fb, FB_W);

    if (!mCoreLoadFile(C, rom)) {
        fprintf(stderr, "gba_capture: cannot load %s\n", rom);
        return 2;
    }
    mCoreConfigInit(&C->config, "gba_capture");
    struct mCoreOptions o = {0};
    mCoreConfigLoadDefaults(&C->config, &o);
    mCoreLoadConfig(C);

    if (save && !mCoreLoadSaveFile(C, save, true))
        fprintf(stderr, "gba_capture: warning: could not load save %s\n", save);

    C->reset(C);

    FILE *s = fopen(script, "r");
    if (!s) { fprintf(stderr, "gba_capture: cannot open script %s\n", script); return 2; }

    char logpath[1024];
    out_path(logpath, sizeof logpath, "capture", "log");
    LOG = fopen(logpath, "w");
    if (!LOG) { fprintf(stderr, "gba_capture: cannot write %s\n", logpath); return 2; }

    char line[2048];
    int lineno = 0;
    while (fgets(line, sizeof line, s)) {
        lineno++;
        size_t l = strlen(line);
        while (l && (line[l - 1] == '\n' || line[l - 1] == '\r')) line[--l] = '\0';
        run_line(line, lineno);
    }
    fclose(s);
    fclose(LOG);

    C->deinit(C);
    fprintf(stderr, "gba_capture: done, log -> %s\n", logpath);
    return 0;
}
