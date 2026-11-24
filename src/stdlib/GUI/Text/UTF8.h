#ifndef BTRC_GUI_TEXT_UTF8_H
#define BTRC_GUI_TEXT_UTF8_H
#include <stddef.h>
#include <stdint.h>

/* Returns the width of one Unicode scalar or zero for invalid UTF-8. */
static inline int btrcTextDecodeUTF8(const unsigned char *p, size_t n, uint32_t *value) {
    if (!n) {
        return 0;
    }
    uint32_t a = p[0];
    if (a < 0x80) {
        *value = a;
        return 1;
    }
    unsigned count = a < 0xc2 ? 0 : a < 0xe0 ? 2 : a < 0xf0 ? 3 : a < 0xf5 ? 4 : 0;
    if (!count || count > n) {
        return 0;
    }
    uint32_t cp = a & (0x7fu >> count);
    for (unsigned i = 1; i < count; ++i) {
        if ((p[i] & 0xc0) != 0x80) {
            return 0;
        }
        cp = (cp << 6) | (p[i] & 63u);
    }
    if ((count == 3 && cp < 0x800) || (count == 4 && cp < 0x10000) || (cp >= 0xd800 && cp <= 0xdfff) ||
        cp > 0x10ffff) {
        return 0;
    }
    *value = cp;
    return (int)count;
}

#endif
