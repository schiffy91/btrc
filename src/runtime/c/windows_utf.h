#ifndef BTRC_WINDOWS_UTF_H
#define BTRC_WINDOWS_UTF_H

#include <stddef.h>
#include <stdint.h>

/* One strict UTF-8 scalar value: overlong forms, surrogates and values past
 * U+10FFFF are malformed. Returns the bytes consumed, or 0. */
static inline size_t btrc_windows_utf8_next(const unsigned char *text, size_t available, uint32_t *value) {
    if (available == 0) return 0;
    unsigned char lead = text[0];
    if (lead < 0x80u) {
        *value = lead;
        return 1;
    }
    size_t length;
    uint32_t scalar;
    uint32_t minimum;
    if ((lead & 0xE0u) == 0xC0u) {
        length = 2;
        scalar = lead & 0x1Fu;
        minimum = 0x80u;
    } else if ((lead & 0xF0u) == 0xE0u) {
        length = 3;
        scalar = lead & 0x0Fu;
        minimum = 0x800u;
    } else if ((lead & 0xF8u) == 0xF0u) {
        length = 4;
        scalar = lead & 0x07u;
        minimum = 0x10000u;
    } else {
        return 0;
    }
    if (length > available) return 0;
    for (size_t index = 1; index < length; index++) {
        unsigned char next = text[index];
        if ((next & 0xC0u) != 0x80u) return 0;
        scalar = (scalar << 6) | (next & 0x3Fu);
    }
    if (scalar < minimum || scalar > 0x10FFFFu
            || (scalar >= 0xD800u && scalar <= 0xDFFFu))
        return 0;
    *value = scalar;
    return length;
}

#endif
