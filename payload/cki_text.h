#ifndef CKI_TEXT_H
#define CKI_TEXT_H

/* Freestanding host-encoded text. Capacity includes the 0xFF terminator.
 * Callbacks must be deterministic; a lead always consumes exactly one trail.
 * 0xFF is reserved and cannot occur inside a character. */
typedef struct {
    int (*is_lead)(unsigned char byte, void *context);
    void *context;
} CKITextPolicy;

typedef struct {
    unsigned int bytes;
    unsigned int tokens;
    unsigned int last;
} CKITextScan;

static inline int cki_text_is_lead(unsigned char byte, const CKITextPolicy *policy)
{
    if (policy && policy->is_lead)
        return policy->is_lead(byte, policy->context);
    return byte >= 1 && byte <= 0x1E && byte != 6 && byte != 0x1B;
}

/* Forward tokenization is essential: a pair's trail may itself be a lead.
 * Output is untouched when malformed text or missing EOS is encountered. */
static inline int cki_text_scan(const unsigned char *text, unsigned int capacity,
                                const CKITextPolicy *policy, CKITextScan *out)
{
    CKITextScan result = {0, 0, 0};
    if (!text || !capacity || !out)
        return 0;
    while (result.bytes < capacity) {
        unsigned int width;
        if (text[result.bytes] == 0xFF) {
            *out = result;
            return 1;
        }
        width = cki_text_is_lead(text[result.bytes], policy) ? 2u : 1u;
        if (width == 2u && (capacity - result.bytes < 2u ||
                           text[result.bytes + 1u] == 0xFF))
            return 0;
        result.last = result.bytes;
        result.bytes += width;
        ++result.tokens;
    }
    return 0;
}

/* Validate the whole old buffer and proposed character before any write. */
static inline int cki_text_append(unsigned char *text, unsigned int capacity,
                                  unsigned int max_tokens, unsigned short code,
                                  const CKITextPolicy *policy)
{
    CKITextScan scan;
    unsigned char high = (unsigned char)(code >> 8);
    unsigned char low = (unsigned char)code;
    unsigned int width = high ? 2u : 1u;
    if (low == 0xFF || high == 0xFF ||
        (high && !cki_text_is_lead(high, policy)) ||
        (!high && cki_text_is_lead(low, policy)))
        return 0;
    if (!cki_text_scan(text, capacity, policy, &scan) ||
        scan.tokens >= max_tokens || capacity - scan.bytes <= width)
        return 0;
    if (high)
        text[scan.bytes] = high;
    text[scan.bytes + width - 1u] = low;
    text[scan.bytes + width] = 0xFF;
    return 1;
}

/* Mode-independent deletion; malformed buffers remain completely untouched. */
static inline int cki_text_delete(unsigned char *text, unsigned int capacity,
                                  const CKITextPolicy *policy)
{
    CKITextScan scan;
    if (!cki_text_scan(text, capacity, policy, &scan) || !scan.tokens)
        return 0;
    text[scan.last] = 0xFF;
    return 1;
}

#endif
