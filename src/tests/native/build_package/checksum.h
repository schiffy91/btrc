#ifndef BTRC_BUILD_PACKAGE_CHECKSUM_H
#define BTRC_BUILD_PACKAGE_CHECKSUM_H
#include <string.h>
#include <zlib.h>

/* The low 31 bits of zlib's CRC-32 of a text. */
static inline int checksumOf(const char *text) {
    return (int)(crc32(0L, (const Bytef *)text, (uInt)strlen(text)) & 0x7fffffffUL);
}
#endif
