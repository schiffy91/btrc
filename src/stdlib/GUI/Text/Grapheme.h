#ifndef BTRC_GUI_TEXT_GRAPHEME_H
#define BTRC_GUI_TEXT_GRAPHEME_H
#include <stddef.h>
#include <stdint.h>

typedef enum {
    BTRC_GRAPHEME_OK,
    BTRC_GRAPHEME_INVALID,
    BTRC_GRAPHEME_TOO_LARGE,
    BTRC_GRAPHEME_NO_MEMORY
} BtrcGraphemeResult;
typedef struct {
    /* UTF-8 byte positions; contains count+1 entries, including zero and the
     * final byte length. The empty string has a single boundary at zero. */
    uint32_t *byteOffsets;
    size_t count;
} BtrcGraphemes;

BtrcGraphemeResult btrcGraphemeBoundaries(const char *text, size_t bytes, BtrcGraphemes *out);
void btrcGraphemeDestroy(BtrcGraphemes *clusters);
/* Inclusive floor/ceiling, clamping positions past the input to its end. */
uint32_t btrcGraphemeFloor(const BtrcGraphemes *clusters, size_t byteOffset);
uint32_t btrcGraphemeCeil(const BtrcGraphemes *clusters, size_t byteOffset);
#endif
