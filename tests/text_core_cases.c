#include "cki_text.h"
#define CHECK(x) do { if (!(x)) return __LINE__; } while (0)
static int custom(unsigned char b, void *context) { return b == *(unsigned char *)context; }
int main(void) {
    CKITextScan s;
    unsigned char mixed[12] = {0xBB, 1, 1, 0xBC, 0xFF};
    unsigned char invalid[4] = {1, 0xFF, 0xAA, 0xAA};
    unsigned char full[3] = {1, 1, 0xFF};
    unsigned char excluded[4] = {6, 0x1B, 0xFF};
    unsigned char no_eos[2] = {0xBB, 0xBC};
    unsigned char pair_no_eos[2] = {1, 1};
    unsigned char tiny[2] = {0xFF, 0xAA};
    unsigned char lead = 0x80;
    CKITextPolicy p = {custom, &lead};
    unsigned char alt[5] = {0xFF};
    CHECK(cki_text_scan(mixed, sizeof(mixed), 0, &s));
    CHECK(s.bytes == 4 && s.tokens == 3 && s.last == 3);
    CHECK(cki_text_delete(mixed, sizeof(mixed), 0));
    CHECK(mixed[3] == 0xFF);
    CHECK(cki_text_delete(mixed, sizeof(mixed), 0));
    CHECK(mixed[1] == 0xFF && mixed[0] == 0xBB);
    CHECK(cki_text_delete(mixed, sizeof(mixed), 0));
    CHECK(!cki_text_delete(mixed, sizeof(mixed), 0));
    s.bytes = 99; s.tokens = 98; s.last = 97;
    CHECK(!cki_text_scan(invalid, sizeof(invalid), 0, &s));
    CHECK(s.bytes == 99 && s.tokens == 98 && s.last == 97);
    CHECK(!cki_text_delete(invalid, sizeof(invalid), 0));
    CHECK(!cki_text_append(invalid, sizeof(invalid), 4, 0xBB, 0));
    CHECK(invalid[0] == 1 && invalid[1] == 0xFF && invalid[2] == 0xAA);
    CHECK(!cki_text_scan(no_eos, sizeof(no_eos), 0, &s));
    CHECK(!cki_text_scan(pair_no_eos, sizeof(pair_no_eos), 0, &s));
    CHECK(!cki_text_append(tiny, sizeof(tiny), 4, 0x0101, 0));
    CHECK(tiny[0] == 0xFF && tiny[1] == 0xAA);
    CHECK(cki_text_append(tiny, sizeof(tiny), 4, 0xBB, 0));
    CHECK(tiny[0] == 0xBB && tiny[1] == 0xFF);
    CHECK(!cki_text_append(full, sizeof(full), 4, 0xBB, 0));
    CHECK(full[0] == 1 && full[1] == 1 && full[2] == 0xFF);
    CHECK(cki_text_scan(excluded, sizeof(excluded), 0, &s) && s.tokens == 2);
    CHECK(cki_text_append(mixed, sizeof(mixed), 1, 0x0101, 0));
    CHECK(!cki_text_append(mixed, sizeof(mixed), 1, 0xBB, 0));
    CHECK(!cki_text_append(alt, sizeof(alt), 4, 0xFF, &p));
    CHECK(!cki_text_append(alt, sizeof(alt), 4, 0x80, &p));
    CHECK(!cki_text_append(alt, sizeof(alt), 4, 0x01BB, &p));
    CHECK(!cki_text_append(alt, sizeof(alt), 4, 0x80FF, &p));
    CHECK(cki_text_append(alt, sizeof(alt), 4, 0x8080, &p));
    CHECK(cki_text_scan(alt, sizeof(alt), &p, &s) && s.tokens == 1 && s.bytes == 2);
    CHECK(cki_text_delete(alt, sizeof(alt), &p) && alt[0] == 0xFF);
    CHECK(!cki_text_scan(0, 2, 0, &s));
    CHECK(!cki_text_scan(alt, 0, 0, &s));
    CHECK(!cki_text_scan(alt, sizeof(alt), 0, 0));
    return 0;
}
